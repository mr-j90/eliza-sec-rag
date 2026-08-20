"""Rule-based query understanding. **No LLM, by construction.**

SPEC §5.2 requires that everything before the answer be deterministic: entity extraction,
time scope and form hints are rules over text, so the system provably makes exactly one
model call. An LLM query-rewriter would probably improve recall and is deliberately excluded
— it belongs in the roadmap, and an interviewer will check the constraint.

Nothing in this module imports a provider or touches the network. That is the property, not
an implementation detail: if this ever needs a service, the one-call story has broken
upstream of the answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from src.aliases import DESCRIPTORS, aliases, by_ticker, normalise
from src.config import settings
from src.ingest import fiscal_period, parse_header


@lru_cache(maxsize=1)
def fiscal_year_range() -> tuple[int, int]:
    """`(earliest, newest)` fiscal year in the corpus, read from filing headers.

    Relative time expressions anchor to the **newest** of these, not to `date.today()`. The corpus is a
    fixed snapshot (SPEC §9 lists that as an honest limitation), so "the last two years"
    means the last two years of available filings. Anchored to the clock, this question
    would quietly return nothing the year after the snapshot stops being current — the
    worst kind of failure, because the answer would still look confident.

    The earliest is returned alongside it so an answer can say what the corpus actually
    covers when a question asks for a period outside it — one scan, one derivation.

    The derivation is `ingest.fiscal_period`, deliberately shared rather than reimplemented.
    This function used to read `Report Period or Filing Date` itself — its own copy of the
    bug ticket 15 fixed — and returned **2026** for a corpus whose newest period ends in
    2025. Every relative temporal question was anchored a year too high, so "the last two
    years" asked for [2025, 2026] and matched only one year of filings. Two derivations of
    one number is what allowed that to go unnoticed.
    """
    years: list[int] = []
    for path in settings().corpus_dir.glob("*.txt"):
        with path.open(encoding="utf-8", errors="replace") as handle:
            # Enough to clear the header block and its `=` separator; the URL line that
            # `fiscal_period` falls back to lives inside it.
            head = handle.read(4000)
        fields, _ = parse_header(head)
        if fields:
            years.append(fiscal_period(fields)[1])
    return (min(years), max(years)) if years else (0, 0)


LATEST_FISCAL_YEAR = fiscal_year_range()[1]
"""The year relative expressions anchor to. Both ends come from one derivation, for the reason
the docstring above gives: the bug it describes was two functions computing the same number."""


@dataclass(frozen=True)
class QueryPlan:
    """What the question asked for, in retrievable terms."""

    companies: list[str]
    """Tickers, in the order the question named them."""

    unresolved_mentions: list[str]
    """Capitalised names that look like companies but are not in the corpus.

    Deliberately *not* called "absent companies": this is a heuristic and it will
    occasionally include something that is not a company at all. It exists so an answer can
    say **which** name it cannot speak about, and it must never be used to suppress an
    answer — only to explain one.
    """

    fiscal_years: tuple[int, int] | None
    """Inclusive `(from, to)` range, or None for no time filter."""

    form_type: str | None
    """`10-K`, `10-Q`, or None for no form filter."""


# Capitalised words that appear in filing questions and are not companies. Without this, the
# same rule that finds "Shopify" also finds "Risk", "Item" and "China".
_NOT_COMPANIES = {
    "risk", "risks", "factors", "item", "items", "part", "form", "annual", "quarterly",
    "report", "reports", "filing", "filings", "management", "discussion", "analysis",
    "legal", "proceedings", "business", "financial", "statements", "compare", "compared",
    "china", "india", "japan", "korea", "taiwan", "vietnam", "europe", "america",
    "american", "united", "states", "federal", "reserve", "congress", "sec", "gaap",
    "act", "section", "chips", "basel", "cecl", "covid", "ai", "esg",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    # Question and sentence openers. A capitalised run always starts with one of these when
    # the question does, and without them "What" and "Compare" read as unknown companies.
    "what", "how", "which", "why", "when", "where", "who", "whose", "whom",
    "compare", "comparing", "summarise", "summarize", "describe", "explain", "list",
    "tell", "does", "do", "did", "is", "are", "was", "were", "has", "have", "had",
    "please", "give", "show", "over", "since", "about", "their", "they", "them",
    "this", "that", "these", "those", "recent", "primary", "major", "each", "both",
}

# Sequences of capitalised words, so "General Electric" is considered before "General".
#
# A run may cross the lowercase connectives that sit inside legal names — "Bank of America",
# "Procter and Gamble". Without that, `Bank of America` was never tested as a span at all: the
# runs were "Bank" and "America" separately, and the only reason it ever resolved was the
# leading-word rule mapping bare "bank" → BAC, which resolved "bank regulations" the same way.
# Fixing the alias table without this would have taken a company with 4 filings here down to
# ticker-only.
_WORD = r"[A-Z][a-zA-Z0-9&.\-]*"
_CAPITALISED = re.compile(
    rf"\b({_WORD}(?:\s+(?:of|and|the|de|&)\s+{_WORD}|\s+{_WORD})*)\b"
)

# Short tickers collide with ordinary words, so they only resolve as a standalone uppercase
# token: `V` is Visa and `T` is AT&T, but a question about a T-bill is not about AT&T.
_SHORT_TICKER_CHARS = 2

# A run may *contain* these (see `_CAPITALISED`), but once a span has failed to resolve they
# are what it should be split on: "Spotify and Rivian" is two absent companies to name, not one
# phrase. Shorter connectives are already caught by the `_SHORT_TICKER_CHARS` branch below.
_CONNECTIVES = {"and", "the"}

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_LAST_N_YEARS = re.compile(
    r"\b(?:last|past|previous|recent)\s+"
    r"(two|three|four|five|2|3|4|5|few|several|couple(?:\s+of)?)\s+"
    r"(?:fiscal\s+)?years?\b",
    re.IGNORECASE,
)
_SINCE_YEAR = re.compile(r"\bsince\s+((?:19|20)\d{2})\b", re.IGNORECASE)
_WORD_NUMBERS = {
    "two": 2, "2": 2, "couple": 2, "couple of": 2,
    "three": 3, "3": 3, "few": 3, "several": 3,
    "four": 4, "4": 4, "five": 5, "5": 5,
}

_QUARTERLY = re.compile(r"\b(10-?Q|quarter|quarterly|q[1-4])\b", re.IGNORECASE)
_ANNUAL = re.compile(r"\b(10-?K|annual|full[- ]year|fiscal\s+year\s+end)\b", re.IGNORECASE)


def _companies_in(question: str) -> tuple[list[str], list[str]]:
    """(tickers in mention order, capitalised names that did not resolve).

    Capitalised runs glue sentence-initial words onto company names — "Compare JPMorgan and
    Apple" yields the run "Compare JPMorgan" — so each run is scanned for the **longest
    sub-span that resolves**, left to right, rather than tested whole. Without that,
    "Compare JPMorgan" resolves to nothing and reads as an unknown company.
    """
    table = aliases()
    known_tickers = by_ticker()

    found: list[str] = []
    unresolved: list[str] = []

    for match in _CAPITALISED.finditer(question):
        # Strip a trailing possessive so "NVIDIA's" resolves as NVIDIA.
        tokens = re.sub(r"['’]s\b", "", match.group(1)).split()
        index = 0
        pending: list[str] = []  # consecutive unmatched, non-vocabulary words

        while index < len(tokens):
            matched_to = None
            for end in range(len(tokens), index, -1):
                span = " ".join(tokens[index:end])

                # A bare short ticker only counts written exactly as the ticker: `V` is
                # Visa and `T` is AT&T, but a T-bill question is not an AT&T question.
                if len(span) <= _SHORT_TICKER_CHARS:
                    if span in known_tickers:
                        matched_to, ticker = end, span
                        break
                    continue

                ticker = table.get(normalise(span))
                if ticker:
                    matched_to = end
                    break

            if matched_to is not None:
                if ticker not in found:
                    found.append(ticker)
                if pending:
                    _record_unresolved(pending, unresolved)
                    pending = []
                index = matched_to
                continue

            word = tokens[index]
            if (
                normalise(word) in _NOT_COMPANIES
                or word.lower() in _CONNECTIVES
                or len(word) <= _SHORT_TICKER_CHARS
            ):
                # Ordinary filing or question vocabulary breaks the run.
                if pending:
                    _record_unresolved(pending, unresolved)
                    pending = []
            else:
                pending.append(word)
            index += 1

        if pending:
            _record_unresolved(pending, unresolved)

    return found, unresolved


def _record_unresolved(words: list[str], into: list[str]) -> None:
    """A capitalised name we do not hold — recorded so an answer can name what it cannot
    speak about. Heuristic on purpose, and never used to suppress an answer.

    A **single** word that `aliases` refuses to promote to an alias is dropped: "Bank",
    "Technologies", "International" identify no company, and reporting one as absent puts a
    line in the answer saying this corpus holds no filings for "Technologies". Only when it
    stands alone — "General Motors" is two words and must still be named, because naming what
    it cannot speak about is the whole point of this list.
    """
    if len(words) == 1 and normalise(words[0]) in DESCRIPTORS:
        return
    phrase = " ".join(words)
    if phrase and phrase not in into:
        into.append(phrase)


def _fiscal_years_in(question: str) -> tuple[int, int] | None:
    since = _SINCE_YEAR.search(question)
    if since:
        return (int(since.group(1)), LATEST_FISCAL_YEAR)

    relative = _LAST_N_YEARS.search(question)
    if relative:
        span = _WORD_NUMBERS.get(relative.group(1).lower().replace("  ", " "), 2)
        # Inclusive of the newest year, so "the last two years" is 2025-2026 rather than
        # 2024-2026.
        return (LATEST_FISCAL_YEAR - span + 1, LATEST_FISCAL_YEAR)

    years = sorted({int(m.group(0)) for m in _YEAR.finditer(question)})
    if years:
        # An explicit year outside the corpus is honoured rather than widened: an empty
        # result the reader can understand beats a silent answer about a different period.
        return (years[0], years[-1])
    return None


def _form_type_in(question: str) -> str | None:
    quarterly = bool(_QUARTERLY.search(question))
    annual = bool(_ANNUAL.search(question))
    if quarterly and not annual:
        return "10-Q"
    if annual and not quarterly:
        return "10-K"
    # Both or neither: no filter. A question mentioning both wants both.
    return None


def plan(question: str) -> QueryPlan:
    """Everything the retriever needs, derived from the question text alone."""
    companies, unresolved = _companies_in(question)
    return QueryPlan(
        companies=companies,
        unresolved_mentions=unresolved,
        fiscal_years=_fiscal_years_in(question),
        form_type=_form_type_in(question),
    )
