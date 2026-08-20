"""Recovering the block boundaries the HTML stripper threw away.

Ticket 03, §2.4. The converter emitted no separator where a block ended, so 216 of 246
filings contain a line over 20,000 characters and Tesla's whole Item 1A is one line of
90,033. Measured before this landed: **88.8% of chunks contained at least one invisible
block join**, and **3.6% fused across an `ITEM` header** — two different sections of a
filing inside one chunk, under one section label.

The omission is itself the signal. Where a boundary was, a sentence-final character now
abuts a capital with no space, or a Title Case heading runs straight into its own body text.

Both rules need guards, and the guards are the whole difficulty — measured on Tesla's 10-K,
**98 of 416** rule-1 candidates are abbreviations (`U.S.`, `I.R.S.`, `U.S.C.`) that must not
split, and the unguarded rule 2 shatters `xAI`, `MyPower` and table headers.

Free tier: no Qdrant, no key.
"""

from __future__ import annotations

import pytest

from src.ingest import _reflow


def blocks(text: str) -> list[str]:
    return [b for b in _reflow(text).split("\n\n") if b.strip()]


# --- rule 1: a sentence-final character abutting a capital ------------------------------


def test_a_sentence_running_into_the_next_is_split():
    got = blocks("We rely on a single supplier.Demand for our products may fall.")
    assert got == ["We rely on a single supplier.", "Demand for our products may fall."]


def test_normal_spaced_prose_is_left_alone():
    """Reflow must add boundaries, never rewrite text that was already fine."""
    text = "We rely on a single supplier. Demand may fall. Margins could compress."
    assert _reflow(text) == text


@pytest.mark.parametrize(
    "abbreviation",
    ["U.S.", "I.R.S.", "U.S.C.", "Inc.", "Corp.", "No.", "e.g.", "i.e.", "Ltd.", "Jr."],
)
def test_abbreviations_do_not_end_a_block(abbreviation):
    """`U.S.` would otherwise become `…in U.` / `S. dollar would…`.

    24% of rule-1 candidates in Tesla's 10-K sit after an abbreviation, so this is the
    difference between reflow working and reflow shredding the text.
    """
    text = f"Our facilities in the {abbreviation} Supply constraints continued."
    assert len(blocks(text)) == 1, f"{abbreviation} was treated as a block boundary"


def test_the_item_header_glue_case_is_split():
    """§2.5 form C, and the reason 3.6% of chunks contained two sections.

    Tesla writes `…into this Annual Report on Form 10-K.ITEM 1A. RISK FACTORS You should…`
    with no separator, so the chunker could not see that a new section had begun.
    """
    text = (
        "is not incorporated by reference into this Annual Report on Form 10-K."
        "ITEM 1A. RISK FACTORS You should carefully consider the risks described below."
    )
    got = blocks(text)
    assert len(got) >= 2
    assert got[1].startswith("ITEM 1A.")


# --- rule 2: a Title Case heading running into its body --------------------------------


def test_a_title_case_heading_running_into_its_body_is_split():
    """The arch doc's own §2.4 example."""
    text = (
        "Risks Related to Government Laws and Regulations"
        "Demand for our products depends on regulatory support."
    )
    got = blocks(text)
    assert got == [
        "Risks Related to Government Laws and Regulations",
        "Demand for our products depends on regulatory support.",
    ]


@pytest.mark.parametrize(
    "text,why",
    [
        (
            "the board did not recommend for or against the xAI Proposal as described.",
            "a two-letter lowercase run is a word like xAI, not a heading boundary",
        ),
        (
            "notes receivable under the legacy MyPower loan program, which ended.",
            "MyPower is a product name",
        ),
        (
            "| Operating Leases |  | FinanceLeases |  | Total |",
            "a pipe in the preceding text means a table row, which ticket 06 owns",
        ),
        (
            "we sell our vehicles directly to consumers and We also lease them.",
            "mid-sentence capitals are not headings when the run-up is not Title Case",
        ),
    ],
)
def test_heading_rule_does_not_fire_on_lookalikes(text, why):
    assert len(blocks(text)) == 1, why


# --- the corpus cases the ticket named -------------------------------------------------


def test_tesla_item_1a_becomes_many_blocks_of_a_workable_size():
    """§2.4's headline case, measured against the real filing.

    Tesla's Item 1A arrives as a single line of ~90,000 characters. The arch doc reported
    81 blocks with a median of 747 chars from the sentence rule alone; both rules together
    on the FY2025 filing give rather more, and the median block stays in the range that
    makes ~600–800-token chunks assemble from whole blocks rather than mid-sentence cuts.
    """
    from src.config import settings
    from src.ingest import _section_map, _section_spans, _strip_boilerplate, parse_header

    raw = (
        settings().corpus_dir / "TSLA_10K_2026-01-29_full.txt"
    ).read_text(encoding="utf-8", errors="replace")
    fields, offset = parse_header(raw)
    body = _strip_boilerplate(raw[offset:])

    item_1a = next(
        body[start:end]
        for label, start, end in _section_spans(body, _section_map("10-K"))
        if "1A" in label
    )
    assert max(len(line) for line in item_1a.split("\n")) > 50_000, (
        "the premise of this test is that Item 1A arrives as one enormous line"
    )

    got = blocks(item_1a)
    assert len(got) > 60, f"expected the section to break into many blocks, got {len(got)}"
    median = sorted(len(b) for b in got)[len(got) // 2]
    assert 200 < median < 3_000, f"median block of {median} chars is not a usable unit"


def test_reflow_never_loses_characters():
    """The one invariant that matters: this inserts separators, it does not edit text.

    A reflow that drops content would be the worst possible bug here — silent, and
    invisible to every retrieval metric.
    """
    from src.config import settings
    from src.ingest import _strip_boilerplate, parse_header

    for name in (
        "TSLA_10K_2026-01-29_full.txt",
        "AAPL_10K_2025-10-31_full.txt",
        "GOOG_10Q_2025Q3_2025-10-30_full.txt",
    ):
        raw = (settings().corpus_dir / name).read_text(encoding="utf-8", errors="replace")
        _, offset = parse_header(raw)
        body = _strip_boilerplate(raw[offset:])
        assert _reflow(body).replace("\n", "") == body.replace("\n", ""), (
            f"{name}: reflow changed the text, not just its line structure"
        )
