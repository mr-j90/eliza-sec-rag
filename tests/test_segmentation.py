"""How much of a filing lands inside a correctly-named item.

Ticket 02. The verdict was **keep the existing segmenter** — measured across all 246 filings
it puts a median **98%** of a 10-K body and **96%** of a 10-Q inside a named item, well past
the 78% §2.5 reports for the TOC-anchored aligner it recommends building. Rewriting it would
have been a regression risk for no measured gain.

What the measurement did find is a single-character omission that cost 11 filings their
entire segmentation, and a residue of filings that genuinely carry no body item headers at
all.

Free tier: reads the corpus, needs no Qdrant and no key.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.ingest import (
    UNLABELLED,
    _section_map,
    _section_spans,
    _strip_boilerplate,
    parse_header,
)


def sections(name: str) -> list[tuple[str, int, int]]:
    raw = (settings().corpus_dir / name).read_text(encoding="utf-8", errors="replace")
    fields, offset = parse_header(raw)
    body = _strip_boilerplate(raw[offset:])
    form = (fields.get("filing type", "").split("(")[0] or "").strip()
    return [s for s in _section_spans(body, _section_map(form)) if s[0] != UNLABELLED]


def coverage(name: str) -> float:
    raw = (settings().corpus_dir / name).read_text(encoding="utf-8", errors="replace")
    _, offset = parse_header(raw)
    body = _strip_boilerplate(raw[offset:])
    named = sections(name)
    return sum(end - start for _, start, end in named) / max(1, len(body))


# --- the omission that cost 11 filings ---------------------------------------------------


@pytest.mark.parametrize(
    "name,why",
    [
        (
            "CMCSA_10K_2026-02-03_full.txt",
            "Comcast writes `Item 1A: Risk Factors` — a colon, not a period",
        ),
        (
            "DIS_10Q_2025Q2_2025-08-06_full.txt",
            "Disney's Part II headers use the same colon form; all 10 of its 10-Qs did",
        ),
        (
            "COST_10K_2025-10-08_full.txt",
            "Costco uses a dash between the number and the title",
        ),
    ],
)
def test_the_colon_and_dash_header_forms_are_segmented(name, why):
    """§2.5 lists a colon/dash form; the pattern only ever allowed `\\.?`.

    Each of these produced **zero** named sections before the separator class was widened —
    every character of the filing fell back to `UNLABELLED`, so `item_section` was useless on
    it and every citation from it displayed no section. Eleven filings in total.
    """
    found = sections(name)
    assert found, f"no sections detected: {why}"
    assert coverage(name) > 0.5, (
        f"{name}: only {coverage(name) * 100:.0f}% of the body is inside a named item"
    )


# --- the coverage the verdict rests on ---------------------------------------------------


def test_corpus_wide_coverage_holds():
    """The number the walkthrough quotes, asserted so it cannot quietly regress.

    Widening a header pattern is exactly the kind of change that could pull in false
    positives and wreck the filings that already worked, so the guard is on the median rather
    than on any one filing.
    """
    per_form: dict[str, list[float]] = {"10-K": [], "10-Q": []}
    zero = []

    for path in sorted(settings().corpus_dir.glob("*.txt")):
        raw = path.read_text(encoding="utf-8", errors="replace")
        fields, offset = parse_header(raw)
        body = _strip_boilerplate(raw[offset:])
        form = (fields.get("filing type", "").split("(")[0] or "").strip()
        named = [s for s in _section_spans(body, _section_map(form)) if s[0] != UNLABELLED]
        if not named:
            zero.append(path.name)
        key = "10-Q" if "10-Q" in form.upper() else "10-K"
        per_form[key].append(sum(e - s for _, s, e in named) / max(1, len(body)))

    for form, floor in (("10-K", 0.95), ("10-Q", 0.93)):
        values = sorted(per_form[form])
        median = values[len(values) // 2]
        assert median >= floor, f"{form} median coverage fell to {median * 100:.0f}%"

    # 15 filings genuinely carry no body item headers — JNJ (12) structures its 10-Qs by
    # `NOTE 11 — LEGAL PROCEEDINGS` rather than by item, plus INTC, MCD and MS. Their content
    # is still chunked and retrievable under `UNLABELLED`; only the section label is missing.
    # The bound is a ceiling, so a regression that loses more filings fails here.
    assert len(zero) <= 15, f"{len(zero)} filings segment to nothing: {sorted(zero)}"


def test_content_is_never_dropped_even_when_no_item_is_detected():
    """The coverage guarantee, on the filings where detection fails entirely.

    A section label is best-effort metadata; losing the text is not. JNJ's 10-Qs detect no
    items at all and must still be fully chunked, or twelve filings would silently vanish
    from the index.
    """
    from src.ingest import chunk_filing

    chunks = chunk_filing("JNJ_10Q_2022Q2_2022-04-29_full.txt")
    assert chunks, "a filing with no detectable items produced no chunks at all"
    assert all(c.item_section == UNLABELLED for c in chunks)
    assert sum(c.token_count for c in chunks) > 10_000, "most of the filing is missing"


# --- the false positives §2.5 warns about ------------------------------------------------


def test_a_reg_sk_citation_is_not_treated_as_a_header():
    """Intel's only bare-regex item match is an `Item 601(a)` Reg S-K citation (§2.5).

    Treating it as a header would put a section boundary in the exhibit index and drag the
    label across everything above it.
    """
    for label, _, _ in sections("INTC_10K_2026-01-23_full.txt"):
        assert "601" not in label


@pytest.mark.parametrize(
    "name",
    [
        "AMZN_10K_2026-02-06_full.txt",
        "AAPL_10K_2025-10-31_full.txt",
        "TSLA_10K_2026-01-29_full.txt",
        "META_10K_2026-01-29_full.txt",
        "GOOG_10Q_2025Q3_2025-10-30_full.txt",
    ],
)
def test_each_header_form_still_segments(name):
    """One filing per §2.5 header form — pipe, glued-behind-page-furniture, ALL CAPS,
    zero-space, and zero-space-with-caps. A mean would hide any one of them failing."""
    assert coverage(name) > 0.5, f"{name}: {coverage(name) * 100:.0f}% inside a named item"


def test_ten_q_part_two_items_are_keyed_separately_from_part_one():
    """§2.6 measures the collision in 125 of 157 10-Qs.

    A key on `item` alone would merge Apple's *Financial Statements* with its *Legal
    Proceedings*, because both are "Item 1". Ticket 08's baseline anchoring depends on these
    being distinguishable.
    """
    labels = [label for label, _, _ in sections("AAPL_10Q_2025Q2_2025-08-01_full.txt")]
    part_one = [l for l in labels if l.startswith("Item 1 ")]
    part_two = [l for l in labels if l.startswith("Part II")]
    assert part_one, f"no Part I Item 1 found in {labels}"
    assert part_two, f"no Part II item found in {labels}"
    assert len(set(labels)) == len(labels), f"duplicate section labels: {labels}"


def test_a_quoted_cross_reference_several_words_in_is_not_a_header():
    """The regression the widened separator introduced, and the guard that fixed it.

    AMD writes `see “Part I, Item 1A—Risk Factors” and the “Financial Condition” section`.
    Allowing a dash after the item number made that match, and because the opening quote sits
    eight characters before `Item` rather than immediately before it, the old guard — which
    checked only the preceding character — let it through. Item 1A's boundary jumped from 16.3%
    of the body to 2.3%, cutting Item 1 Business from 19 chunks to **1**.

    §2.5 measures 30.7% of all `Item N` mentions as cross-references, so this guard carries
    most of the weight in keeping segmentation honest.
    """
    from collections import Counter

    from src.ingest import chunk_filing

    sections_seen = Counter(c.item_section for c in chunk_filing("AMD_10K_2026-02-04_full.txt"))
    assert sections_seen["Item 1 — Business"] > 10, (
        "Item 1 Business collapsed — a quoted cross-reference is being read as a header: "
        f"{dict(sections_seen)}"
    )


def test_the_quote_walk_stops_at_a_closing_quote():
    """A real header following a quoted phrase must still be found.

    Walking back for an opening quote without stopping at a closing one would reject any
    header that happens to sit within 48 characters of a quotation — and filings quote
    themselves constantly.
    """
    from src.ingest import _inside_a_quotation

    body = 'as described under “risk factors” above.ITEM 1A. RISK FACTORS'
    assert not _inside_a_quotation(body, body.index("ITEM 1A."))

    quoted = 'see “Part I, Item 1A—Risk Factors” and'
    assert _inside_a_quotation(quoted, quoted.index("Item 1A"))
