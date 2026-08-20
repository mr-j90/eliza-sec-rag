"""The company/ticker alias dictionary.

**Built from the `Company:`/`Ticker:` header lines, not from `manifest.json`** — CLAUDE.md
correction 1: the manifest has no company names at all, only `file_count`, `filing_types` and
a flat `files` array. SPEC §5.2 says to build it from the manifest; the manifest cannot.

Reading 54 header blocks is cheap (a few hundred bytes per file), so this is derived from the
corpus at startup rather than hand-maintained. A hand-written list is a list that goes stale
the first time the corpus changes.

Entity *extraction* — matching these against a question — lives in `query.py`. This module
only owns the vocabulary.
"""

from __future__ import annotations

import re
from functools import lru_cache

from src.config import settings

# Corporate suffixes carry no identifying information and get in the way of matching a question
# that says "Apple" against a filing that says "Apple Inc". Stripped from the *alias*, never
# from the stored company name, which stays exactly as the filing wrote it.
_SUFFIXES = re.compile(
    r"[\s,]*\b("
    r"inc|incorporated|corp|corporation|company|co|plc|llc|lp|ltd|limited|holdings|"
    r"group|the|and|&"
    r")\b\.?",
    re.IGNORECASE,
)

_HEADER_BYTES = 400

# Two characters or fewer is a ticker's business, not a name fragment's: `co`, `at` and `jp`
# are not company names, and a two-letter alias colliding with a real ticker would shadow it.
_SHORTEST_ALIAS = 2

# Words that appear in these 54 legal names as descriptors rather than identifiers. A
# single-word alias is only useful if it *identifies* one company, and these do not — measured
# 2026-08-20 against the shipped table, where promoting the leading word unconditionally had
# already put four wrong-issuer resolutions in front of a reader: "General Motors" → GE,
# "United States" → UPS, "American companies" → AXP, "bank regulations" → BAC. Each retrieved
# the wrong company's filings and said nothing about it, which is the failure this system is
# built to avoid. A word here still resolves inside a longer span, so "Bank of America" and
# "American Express" are unaffected.
DESCRIPTORS = frozenset({
    "advanced", "america", "american", "bank", "business", "com", "communications",
    "devices", "electric", "express", "general", "global", "group", "holdings", "home",
    "industries", "international", "machines", "micro", "motors", "national", "of",
    "parcel", "platforms", "scientific", "service", "services", "stores", "systems",
    "technologies", "united", "wholesale",
})

# Names people use that no rule can derive from the legal name in the filing header: a former
# name ("Raytheon" is now RTX Corporation), a contraction ("Amex", "J&J"), or a brand that is
# not the registrant ("Coke"). Hand-written, and the module docstring is right that a
# hand-written list goes stale — so this one is **filtered against the corpus** below and an
# entry for a company we do not hold is silently dropped rather than resolving to nothing.
_COLLOQUIAL = {
    "coke": "KO",
    "amex": "AXP",
    "p g": "PG",          # P&G — `normalise` drops the ampersand
    "j j": "JNJ",         # J&J
    "raytheon": "RTX",
    "google": "GOOG",
    "facebook": "META",
    "exxonmobil": "XOM",  # written as one word about as often as two
    "jp morgan": "JPM",
    "unitedhealthcare": "UNH",
}


def normalise(text: str) -> str:
    """Lower-case, strip corporate suffixes and punctuation, collapse whitespace."""
    without_suffixes = _SUFFIXES.sub(" ", text.lower())
    return re.sub(r"[^a-z0-9 ]+", " ", without_suffixes).strip()


@lru_cache(maxsize=1)
def by_ticker() -> dict[str, str]:
    """`{"AAPL": "Apple Inc", ...}` — the company name exactly as the filings write it."""
    names: dict[str, str] = {}
    for path in sorted(settings().corpus_dir.glob("*.txt")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            head = handle.read(_HEADER_BYTES)
        company = re.search(r"^Company:\s*(.+)$", head, re.MULTILINE)
        ticker = re.search(r"^Ticker:\s*(.+)$", head, re.MULTILINE)
        if company and ticker:
            names.setdefault(ticker.group(1).strip(), company.group(1).strip())
    return names


@lru_cache(maxsize=1)
def aliases() -> dict[str, str]:
    """`{normalised alias: ticker}`.

    Each company contributes its ticker, its full name, its name without corporate suffixes,
    and every *distinctive* word of that name — so "JPMorgan", "JPMorgan Chase & Co.", "Chase"
    and "JPM" all resolve to `JPM`. "Distinctive" is doing real work: see `DESCRIPTORS`.

    A collision is resolved in favour of the ticker: `V` is Visa's ticker, and if some other
    company's shortened name normalised to `v` it must not shadow it.
    """
    companies = by_ticker()

    # People say "JPMorgan", not "JPMorgan Chase & Co." — SPEC §5.2 names that exact case. So
    # **any** distinctive word of a multi-word name becomes an alias, not just the leading one,
    # and only when it identifies a single issuer: "general" belongs to both General Electric
    # and General Motors, and a dictionary that guessed between them would silently retrieve
    # the wrong issuer.
    #
    # Leading-word-only was the shipped rule and it was wrong in both directions. Too narrow:
    # "The Walt Disney Company" yielded `walt disney` and `walt` but not **disney**, so the
    # commonest way to name a company with 17 filings here — and the phrasing of the golden
    # set's own temporal question — resolved to nothing and ran as an unfiltered search.
    # Measured 2026-08-20, the same gap hit Lilly, Chase, Hathaway, Sachs and Mobil. Too
    # loose: see `DESCRIPTORS`.
    distinctive: dict[str, set[str]] = {}
    for ticker, company in companies.items():
        words = normalise(company).split()
        if len(words) > 1:
            for word in words:
                if word not in DESCRIPTORS and len(word) > _SHORTEST_ALIAS:
                    distinctive.setdefault(word, set()).add(ticker)

    table: dict[str, str] = {}
    for ticker, company in companies.items():
        for alias in (normalise(company), normalise(ticker)):
            if alias:
                table.setdefault(alias, ticker)

    for word, owners in distinctive.items():
        if len(owners) == 1:
            table.setdefault(word, next(iter(owners)))

    # Dropped when the corpus does not hold the company, so the list cannot claim coverage
    # this index does not have.
    for alias, ticker in _COLLOQUIAL.items():
        if ticker in companies:
            table.setdefault(alias, ticker)

    # The ticker itself wins outright, overwriting any name-derived collision.
    for ticker in companies:
        table[normalise(ticker)] = ticker
    return table


def resolve(text: str) -> str | None:
    """The ticker for a company name or ticker, or None if it isn't in the corpus."""
    return aliases().get(normalise(text))
