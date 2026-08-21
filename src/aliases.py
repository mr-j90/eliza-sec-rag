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
from difflib import get_close_matches
from functools import lru_cache

from src.ingest import filing_headers

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
    for header in filing_headers():
        company, ticker = header.get("company", ""), header.get("ticker", "")
        if company and ticker:
            names.setdefault(ticker, company)
    return names


@lru_cache(maxsize=1)
def aliases() -> dict[str, str]:
    """`{normalised alias: ticker}`.

    Each company contributes its ticker, its full name, its name without corporate suffixes, and
    every *distinctive* word of that name — so "JPMorgan", "JPMorgan Chase & Co.", "Chase" and
    "JPM" all resolve to `JPM`. A collision goes to the ticker: `V` is Visa, and another
    company's shortened name normalising to `v` must not shadow it.
    """
    companies = by_ticker()

    # **Any** distinctive word of a multi-word name, not just the leading one, and only when it
    # identifies a single issuer — "general" belongs to both General Electric and General Motors.
    #
    # Leading-word-only was the shipped rule and was wrong both ways. Too narrow: "The Walt
    # Disney Company" yielded `walt disney` and `walt` but not **disney**, so the commonest way
    # to name a company with 17 filings here — and the phrasing of the golden set's own temporal
    # question — resolved to nothing and ran unfiltered. Measured 2026-08-20, the same gap hit
    # Lilly, Chase, Hathaway, Sachs and Mobil. Too loose: see `DESCRIPTORS`.
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


# A misspelt name should still find its company. Measured 2026-08-21: "What regulatory risks
# does JP Morgen have" answered "there are no filings for Morgen in this corpus" — a typo
# reported as a corpus gap, which is the refusal contract firing on the wrong thing and the one
# failure mode that makes an honest refusal untrustworthy.
#
# Two guards, because resolving to the *wrong* company is worse than refusing:
#
# - `_TYPO_CUTOFF` on difflib's ratio. Swept against the shipped 145-alias table: 0.85 admits a
#   dropped, doubled or transposed letter ("Nvida", "Teslla", "Goldmann Sachs", "Lockhead
#   Martin") while every out-of-corpus name in the golden set — Shopify, Ferrari, Spotify,
#   Rivian — and every word in `query._NOT_COMPANIES` still matches nothing at all.
# - A length difference of at most one, because a typo changes characters and does not add
#   words. Without it "morgan" scores 0.857 against "jpmorgan", so a Morgan Stanley question
#   would answer as JPMorgan. (Here it resolves exactly to MS first, but only by luck of the
#   corpus holding both.)
# - A floor on both sides, because a short alias cannot absorb a wrong character and stay
#   itself. Measured: "comca" scores 0.889 against "coca", so a four-letter distinctive word
#   would answer a Comcast question as Coca-Cola. Five is the lowest floor that still admits
#   "Amazn" and "Nvida", the shortest typos worth catching.
_TYPO_CUTOFF = 0.85
_TYPO_LENGTH_SLACK = 1
_SHORTEST_FUZZY = 5


def near_miss(alias: str) -> str | None:
    """The ticker for a *misspelt* alias, or None. `alias` must already be normalised."""
    if len(alias) < _SHORTEST_FUZZY:
        return None
    table = aliases()
    candidates = [
        known
        for known in table
        if len(known) >= _SHORTEST_FUZZY
        and abs(len(known) - len(alias)) <= _TYPO_LENGTH_SLACK
    ]
    close = get_close_matches(alias, candidates, n=1, cutoff=_TYPO_CUTOFF)
    return table[close[0]] if close else None


def resolve(text: str) -> str | None:
    """The ticker for a company name or ticker, or None if it isn't in the corpus.

    Exact first, then near-miss, so a spelling the corpus actually uses can never be beaten by
    one that merely resembles it.
    """
    alias = normalise(text)
    return aliases().get(alias) or near_miss(alias)
