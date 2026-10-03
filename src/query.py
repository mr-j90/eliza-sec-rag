"""Rule-based query understanding. **No LLM, by construction.**

SPEC §5.2 requires everything before the answer to be deterministic: entity extraction, time
scope and form hints are rules over text, so the system provably makes exactly one model call.
An LLM query-rewriter would probably improve recall and is deliberately excluded.

Nothing here imports a provider or touches the network, and `tests/test_ask.py` asserts it —
if this module ever needs a service, the one-call story has broken upstream of the answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from src.aliases import DESCRIPTORS, aliases, by_ticker, near_miss, normalise
from src.ingest import filing_headers, fiscal_period


@lru_cache(maxsize=1)
def fiscal_year_range() -> tuple[int, int]:
    """`(earliest, newest)` fiscal year in the corpus, read from filing headers.

    Relative time expressions anchor to the **newest** of these, not to `date.today()`. The
    corpus is a fixed snapshot (SPEC §9 lists that as an honest limitation), so "the last two
    years" means the last two years of available filings. Anchored to the clock, this question
    would quietly return nothing the year after the snapshot stops being current — the worst
    kind of failure, because the answer would still look confident.

    The earliest is returned alongside it so an answer can say what the corpus actually covers
    when a question asks for a period outside it.

    The derivation is `ingest.fiscal_period` over `ingest.filing_headers`, deliberately shared
    rather than reimplemented. This function used to read `Report Period or Filing Date` itself
    — its own copy of the bug ticket 15 fixed — and returned **2026** for a corpus whose newest
    period ends in 2025, anchoring every relative temporal question a year too high.
    """
    years = [fiscal_period(header)[1] for header in filing_headers()]
    return (min(years), max(years)) if years else (0, 0)


LATEST_FISCAL_YEAR = fiscal_year_range()[1]
"""The year relative expressions anchor to."""


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

# Every word is a candidate, not just capitalised runs. Measured 2026-10-01: "what did apple
# say about tariffs" resolved to nothing and ran as a sector question, because the extractor
# read only capitalised runs — a reader who types in lowercase got an answer about twenty
# companies to a question about one. Capitalisation is still the only signal for an *unknown*
# company (see `_companies_in`). Possessives are stripped so "NVIDIA's" resolves as NVIDIA.
_TOKEN = re.compile(r"[A-Za-z0-9][\w&.\-'’]*")
_POSSESSIVE = re.compile(r"['’]s$")

# Short tickers collide with ordinary words, so they only resolve as a standalone uppercase
# token: `V` is Visa and `T` is AT&T, but a question about a T-bill is not about AT&T.
_SHORT_TICKER_CHARS = 2

# Aliases that are also ordinary words in filing prose. Written in lowercase they are taken as
# the word: "cost of revenue" is not Costco and an "H-1B visa" is not Visa. Capitalised, or as
# the ticker (COST, TGT), they still resolve.
# ponytail: hand-kept list, add to it from a wrong-issuer report; swap for a word-frequency
# check only if it keeps growing.
_AMBIGUOUS_LOWERCASE = {"cost", "target", "cat", "ups", "chase", "gamble", "visa"}

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


def _match_at(
    tokens: list[str], index: int, table: dict[str, str], known_tickers: dict[str, str]
) -> tuple[int, str] | None:
    """The longest span starting at `index` that names a company, as `(end, ticker)`.

    Exact aliases across **every** span length first, near-misses only once all of them have
    failed. Ordering matters: run longest-first with fuzzy matching inline and a typo'd long
    span would outrank a shorter span the corpus spells exactly.

    A misspelling has to be matched here rather than at `_record_unresolved`, because the run
    is already broken up by then — "JP Morgen" loses "JP" to the short-token rule below and
    leaves only "Morgen", which resembles nothing.

    Exact matching is case-insensitive; fuzzy matching is only tried on capitalised spans. A
    lowercase near-miss is far more often a common word than a typo'd proper noun — "goods"
    scores 0.889 against "goog", so "consumer goods" would answer as Alphabet.
    """
    spans = [(end, " ".join(tokens[index:end])) for end in range(len(tokens), index, -1)]

    for end, span in spans:
        # A bare short ticker only counts written exactly as the ticker: `V` is Visa and `T`
        # is AT&T, but a T-bill question is not an AT&T question.
        if len(span) <= _SHORT_TICKER_CHARS:
            if span in known_tickers:
                return end, span
            continue
        alias = normalise(span)
        ticker = table.get(alias)
        if ticker and (span[0].isupper() or alias not in _AMBIGUOUS_LOWERCASE):
            return end, ticker

    for end, span in spans:
        alias = normalise(span)
        # Never fuzzy-match a short span, a lowercase span, or ordinary filing vocabulary — a
        # two-character near-miss is a different ticker, not a typo.
        if (
            len(span) <= _SHORT_TICKER_CHARS
            or alias in _NOT_COMPANIES
            or not all(t[0].isupper() for t in tokens[index:end])
        ):
            continue
        ticker = near_miss(alias)
        if ticker:
            return end, ticker
    return None


def _companies_in(question: str) -> tuple[list[str], list[str]]:
    """(tickers in mention order, capitalised names that did not resolve).

    Every token is a candidate start, scanned for the **longest sub-span that resolves** —
    so "Compare JPMorgan" finds JPMorgan rather than reading as an unknown company, and
    "what did apple say" finds Apple. Only a run of *capitalised* words that fails to
    resolve is recorded as unresolved: for a company this corpus does not hold,
    capitalisation is the one deterministic signal there is, and a lowercase "colgate" is
    indistinguishable from any other word. That question falls through to an unfiltered
    search and the system prompt's rule against substituting companies.
    """
    table = aliases()
    known_tickers = by_ticker()
    tokens = [_POSSESSIVE.sub("", token).rstrip(".") for token in _TOKEN.findall(question)]

    found: list[str] = []
    unresolved: list[str] = []
    pending: list[str] = []  # consecutive unmatched capitalised, non-vocabulary words
    index = 0

    while index < len(tokens):
        matched = _match_at(tokens, index, table, known_tickers)

        if matched is not None:
            index, ticker = matched
            if ticker not in found:
                found.append(ticker)
            _record_unresolved(pending, unresolved)
            pending = []
            continue

        word = tokens[index]
        if (
            word[0].isupper()
            and normalise(word) not in _NOT_COMPANIES
            and len(word) > _SHORT_TICKER_CHARS
        ):
            pending.append(word)
        else:
            # Lowercase words, digits, and ordinary filing or question vocabulary end a run.
            _record_unresolved(pending, unresolved)
            pending = []
        index += 1

    _record_unresolved(pending, unresolved)
    return found, unresolved


def _record_unresolved(words: list[str], into: list[str]) -> None:
    """A capitalised name we do not hold, recorded so an answer can name what it cannot speak
    about (see `QueryPlan.unresolved_mentions`).

    A **single** word that `aliases` refuses to promote is dropped: "Bank", "Technologies",
    "International" identify no company, and reporting one as absent puts a line in the answer
    saying this corpus holds no filings for "Technologies". Only when it stands alone, though —
    "General Motors" is two words and must still be named.
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
