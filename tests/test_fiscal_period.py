"""The period a filing reports on, and the year that labels it.

Ticket 15. The defect: `fiscal_year` was `int((period_end or filing_date)[:4])`, and 54
filings carry no `Report Period` header, so they fell back to the **filing date** — which
for a 10-K lands one to three months *after* the year being reported. 37 filings were
labelled a year too high.

Two consequences, and the second was the worse one:

1. Citations displayed the wrong year, directly above an excerpt that often stated the
   right one.
2. `query.py`'s `LATEST_FISCAL_YEAR` derives from the same header fields, so it read
   **2026** when the newest period end in the corpus is **2025**. Every relative temporal
   question ("the last two years") was anchored a year too high, which is why the panel's
   NVIDIA question filtered to [2025, 2026] and matched only one year of data.

Free tier: reads the corpus, needs no Qdrant and no key.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.ingest import fiscal_period, parse_header


def _header(name: str) -> dict[str, str]:
    raw = (settings().corpus_dir / name).read_text(encoding="utf-8", errors="replace")
    fields, _ = parse_header(raw)
    return fields


# (filing, expected period_end, expected fiscal_year, why this case exists)
CASES = [
    (
        "NVDA_10Q_2025Q4_2025-11-19_full.txt",
        "2025-10-26",
        2025,
        "Report Period present — used verbatim, no inference",
    ),
    (
        "AMZN_10K_2026-02-06_full.txt",
        "2025-12-31",
        2025,
        "No Report Period. Filed Feb 2026 for FY2025 — the off-by-one this ticket fixes",
    ),
    (
        "ABBV_10K_2025-02-14_full.txt",
        "2024-12-31",
        2024,
        "Same defect on a different year boundary, so the fix is not tuned to one filing",
    ),
    (
        "ADBE_10K_2026-01-15_full.txt",
        "2025-11-28",
        2025,
        "Off-calendar (November FY end) AND no Report Period — both paths at once",
    ),
    (
        "DE_10K_2025-12-18_full.txt",
        "2025-11-02",
        2025,
        "URL is `de-20251102x10k.htm` — the date is not flush against `.htm`, which the "
        "first version of the regex required",
    ),
    (
        "AAPL_10K_2025-10-31_full.txt",
        "2025-09-27",
        2025,
        "Off-calendar September filer where the filing-date year happened to be right — "
        "must stay right, not get decremented",
    ),
]


@pytest.mark.parametrize(
    "name,period_end,fiscal_year,why",
    CASES,
    ids=[c[0].replace("_full.txt", "") for c in CASES],
)
def test_period_and_year_are_derived_from_the_period_not_the_filing_date(
    name, period_end, fiscal_year, why
):
    got_period, got_year = fiscal_period(_header(name))
    assert got_period == period_end, why
    assert got_year == fiscal_year, why


def test_the_one_filing_with_no_recoverable_period_falls_back_to_the_filing_month():
    """`GE_10K_2015-02-27` — the only filing with neither a Report Period nor a date in
    its URL (`gecc10k2014.htm`).

    A 10-K filed in Jan–Apr reports on the previous calendar year, so the fallback
    decrements. It is a heuristic and applies to exactly one file in this corpus; the
    empty `period_end` is what marks the derivation as inferred rather than read.
    """
    period, year = fiscal_period(_header("GE_10K_2015-02-27_full.txt"))
    assert period == "", "no period end is recoverable, so none should be asserted"
    assert year == 2014, "filed 2015-02-27, reports on FY2014 — and the URL says `10k2014`"


def test_no_filing_claims_a_year_beyond_the_corpus():
    """The bug's signature was a corpus that appeared to contain 2026 filings.

    Nothing in this snapshot has a period ending in 2026, so nothing should be labelled
    2026. This is the assertion that would have caught the original defect.
    """
    offenders = {}
    for path in settings().corpus_dir.glob("*.txt"):
        fields, _ = parse_header(path.read_text(encoding="utf-8", errors="replace"))
        _, year = fiscal_period(fields)
        if year > 2025:
            offenders[path.name] = year
    assert not offenders, f"filings labelled beyond the corpus: {offenders}"


def test_latest_fiscal_year_matches_the_newest_period_end():
    """`query.py` anchors every relative time expression to this.

    It used to derive years from `Report Period or Filing Date` — its own copy of the
    buggy logic — and read 2026. Both must now agree, which is the point of having one
    derivation rather than two.
    """
    from src.query import LATEST_FISCAL_YEAR

    years = []
    for path in settings().corpus_dir.glob("*.txt"):
        fields, _ = parse_header(path.read_text(encoding="utf-8", errors="replace"))
        years.append(fiscal_period(fields)[1])

    assert LATEST_FISCAL_YEAR == max(years) == 2025
