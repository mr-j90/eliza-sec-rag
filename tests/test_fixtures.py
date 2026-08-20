"""The fixture corpus verifies its own claims.

`fixtures/pathologies.json` names the filings that exercise the hard cases and records a
measured claim about each. This module asserts those claims still hold.

That is not ceremony. Every ticket on the map reasons from these measurements — ticket 03
from BAC's 285,080-char XBRL line, ticket 02 from Meta's zero-space headers, ticket 15 from
Amazon's off-by-one fiscal year. If a claim stops holding, the premise moved and the
reasoning built on it needs rechecking. A silent drift here would be invisible everywhere
else.

Free tier: reads the corpus, needs no Qdrant and no key.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.config import settings

MANIFEST = Path(__file__).parent / "fixtures" / "pathologies.json"

# Exactly the arch doc's §2.3 regex — case-SENSITIVE, deliberately. Its "found in 244/246
# files" figure only reproduces this way; re.IGNORECASE gives 245/246.
COVER_PAGE_ANCHOR = re.compile(r"UNITED\s*STATES\s*SECURITIES AND EXCHANGE COMMISSION")
SEPARATOR = re.compile(r"={20,}")

_FIXTURES = json.loads(MANIFEST.read_text())["fixtures"]
_IDS = [f["file"].replace("_full.txt", "") for f in _FIXTURES]


def _split(name: str) -> tuple[dict[str, str], str]:
    """(header fields, body) for one filing — the same split ingest.py performs."""
    raw = (settings().corpus_dir / name).read_text(encoding="utf-8", errors="replace")
    match = SEPARATOR.search(raw)
    if not match:
        return {}, raw
    fields = {}
    for line in raw[: match.start()].splitlines():
        key, _, value = line.partition(":")
        if value.strip():
            fields[key.strip().lower()] = value.strip()
    return fields, raw[match.end() :]


@pytest.fixture(scope="module")
def corpus_files() -> set[str]:
    return {p.name for p in settings().corpus_dir.glob("*.txt")}


def test_every_fixture_names_its_reason_and_tickets():
    """A fixture with no recorded reason is a file somebody added and nobody can justify."""
    for entry in _FIXTURES:
        assert entry.get("why", "").strip(), f"{entry['file']} has no `why`"
        assert entry.get("tickets"), f"{entry['file']} names no ticket"
        assert entry.get("claims"), f"{entry['file']} makes no verifiable claim"


@pytest.mark.parametrize("entry", _FIXTURES, ids=_IDS)
def test_fixture_is_present_in_the_corpus(entry, corpus_files):
    assert entry["file"] in corpus_files, (
        f"{entry['file']} is named in pathologies.json but absent from "
        f"{settings().corpus_dir}"
    )


@pytest.mark.parametrize("entry", _FIXTURES, ids=_IDS)
def test_fixture_claims_still_hold(entry):
    """Each claim is a measurement some ticket depends on. Assert, don't trust."""
    name = entry["file"]
    claims = entry["claims"]
    fields, body = _split(name)
    lines = body.split("\n")

    if (floor := claims.get("longest_line_at_least")) is not None:
        longest = max((len(line) for line in lines), default=0)
        assert longest >= floor, (
            f"{name}: longest line is {longest:,}, expected >= {floor:,}. "
            "§2.4's no-line-structure finding may no longer hold for this filing."
        )

    if (floor := claims.get("body_chars_at_least")) is not None:
        assert len(body) >= floor, f"{name}: body is {len(body):,} chars, expected >= {floor:,}"

    if (floor := claims.get("pipe_rows_at_least")) is not None:
        rows = sum(1 for line in lines if line.count("|") >= 2)
        assert rows >= floor, (
            f"{name}: {rows:,} pipe-table rows, expected >= {floor:,}. "
            "§2.7's table density is what makes ticket 06 necessary."
        )

    if (pattern := claims.get("matches_regex")) is not None:
        assert re.search(pattern, body), (
            f"{name}: /{pattern}/ no longer matches. The header form or text this fixture "
            "exists to represent has changed."
        )

    if (field := claims.get("header_field_absent")) is not None:
        assert field not in fields, (
            f"{name}: header field {field!r} is present, but this fixture exists because "
            "it is absent (one of §2.2's 54 filings)."
        )

    for field, expected in (claims.get("header_field_equals") or {}).items():
        assert fields.get(field) == expected, (
            f"{name}: header {field!r} is {fields.get(field)!r}, expected {expected!r}"
        )

    if claims.get("lacks_cover_page_anchor"):
        assert not COVER_PAGE_ANCHOR.search(body), (
            f"{name} now contains the cover-page anchor. It is the one filing that forces "
            "ticket 03's fallback — if it parses, the fallback may be untested."
        )

    if claims.get("anchor_found_only_case_insensitively"):
        assert not COVER_PAGE_ANCHOR.search(body), (
            f"{name}: the case-sensitive anchor now matches, so §2.3's 244/246 figure has "
            "changed."
        )
        assert re.search(COVER_PAGE_ANCHOR.pattern, body, re.IGNORECASE), (
            f"{name}: the anchor is not found even case-insensitively, so this needs the "
            "same fallback as NFLX rather than just re.IGNORECASE."
        )


@pytest.mark.parametrize(
    "entry",
    [f for f in _FIXTURES if "url_period_year" in f["claims"]],
    ids=[f["file"].replace("_full.txt", "") for f in _FIXTURES if "url_period_year" in f["claims"]],
)
def test_fiscal_year_off_by_one_cases_are_now_right(entry):
    """Ticket 15's defect, now inverted to pin the fix.

    The original version of this test asserted the bug was **still present**, so it would
    fail the moment ticket 15 landed. It didn't — because it reimplemented the old
    derivation inline (`report period or filing date`) instead of calling the code under
    test. It was pinning the header *data*, which never changed, rather than the
    *behaviour*, which did. A test that cannot observe the fix cannot observe a regression
    either.

    So it now calls `fiscal_period` and asserts three things: the filing-date year is still
    the wrong answer (the trap is real), the URL still carries the right one (the fix has a
    source), and the code returns the right one (the fix works).
    """
    from src.ingest import fiscal_period

    name = entry["file"]
    fields, _ = _split(name)
    wrong = entry["claims"]["filing_date_year"]
    right = entry["claims"]["url_period_year"]

    assert fields.get("filing date", "")[:4] == wrong, (
        f"{name}: filing-date year is no longer {wrong}, so this fixture no longer "
        "represents the off-by-one trap."
    )

    embedded = re.search(r"-(\d{8})[^/]*\.html?", fields.get("url", ""))
    assert embedded, f"{name}: URL carries no parseable period ({fields.get('url')!r})"
    assert embedded.group(1)[:4] == right

    period, year = fiscal_period(fields)
    assert str(year) == right, (
        f"{name}: fiscal_period returned {year}, expected {right}. The filing-date "
        f"fallback ({wrong}) may have crept back in."
    )
    assert period[:4] == right, f"{name}: period_end {period!r} disagrees with year {year}"
