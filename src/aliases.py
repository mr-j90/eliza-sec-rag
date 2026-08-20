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

    Each company contributes its ticker, its full name, and its name without corporate
    suffixes — so "JPMorgan", "JPMorgan Chase & Co." and "JPM" all resolve to `JPM`.

    A collision is resolved in favour of the ticker: `V` is Visa's ticker, and if some other
    company's shortened name normalised to `v` it must not shadow it.
    """
    companies = by_ticker()

    # People say "JPMorgan", not "JPMorgan Chase & Co." — SPEC §5.2 names that exact case. So
    # the leading word of a multi-word name becomes an alias too, but **only when it identifies
    # one company**: "general" belongs to both General Electric and General Motors, and a
    # dictionary that guessed between them would silently retrieve the wrong issuer.
    leading: dict[str, set[str]] = {}
    for ticker, company in companies.items():
        words = normalise(company).split()
        if len(words) > 1:
            leading.setdefault(words[0], set()).add(ticker)

    table: dict[str, str] = {}
    for ticker, company in companies.items():
        for alias in (normalise(company), normalise(ticker)):
            if alias:
                table.setdefault(alias, ticker)

    for word, owners in leading.items():
        if len(owners) == 1:
            table.setdefault(word, next(iter(owners)))

    # The ticker itself wins outright, overwriting any name-derived collision.
    for ticker in companies:
        table[normalise(ticker)] = ticker
    return table


def resolve(text: str) -> str | None:
    """The ticker for a company name or ticker, or None if it isn't in the corpus."""
    return aliases().get(normalise(text))
