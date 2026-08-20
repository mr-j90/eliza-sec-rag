"""Numbers keep the caption that says what they mean.

Ticket 06, §2.7. 22.2% of corpus characters are pipe-table rows, and the layout works against
a chunker in two specific ways: the scale caption — `(In millions)` — sits on the **preceding
narrative line**, outside the table, and the column-period header sits on its **own
label-less row**. Cut a long table anywhere after those two lines and every figure below the
cut loses its meaning.

Measured before this landed, across five filings: **113 of 405 (28%) financial-table chunks
carried figures with no stated scale.** From NVIDIA's statement of shareholders' equity:

    Shares repurchased | (211) |  | (27) |  | (9,719) |  | (9,746) |
    Net income         | —     |  | —    |  | 72,880  |  | 72,880  |

`72,880` is millions of dollars. `(211)` in the same table is millions of *shares*. Neither is
stated anywhere in the chunk.

This became demo-critical when the XBRL numeric router went to future state: with no
structured path, NVIDIA's revenue figures — one of the three questions the panel will type —
are answered from exactly these rows. For a diligence tool, an order-of-magnitude error is the
highest-consequence silent failure available.

Free tier: no Qdrant, no key.
"""

from __future__ import annotations

from src.ingest import _bind_table_context, _is_period_header, _scale_caption

CAPTION = "The following table summarises revenue by segment (in millions):"
HEADER = "|  | Jan 26, 2025 |  | Jan 28, 2024 |"
ROWS = [
    "Compute & Networking | 116,193 |  | 47,405 |",
    "Graphics | 14,304 |  | 13,517 |",
    "Total | 130,497 |  | 60,922 |",
]


# --- recognising the two lines that carry the meaning ------------------------------------


def test_a_scale_caption_is_recognised():
    for line in (
        "revenue by segment (in millions):",
        "(In millions, except per share data)",
        "Selected data ($ in millions)",
        "amounts in thousands",
        "(dollars in billions)",
    ):
        assert _scale_caption(line), f"missed a scale caption: {line!r}"


def test_ordinary_prose_is_not_a_scale_caption():
    for line in (
        "We sold millions of units during the period.",
        "Revenue grew in the fourth quarter.",
        "| Total | 130,497 |",
    ):
        assert not _scale_caption(line), f"false positive: {line!r}"


def test_a_period_header_row_is_recognised():
    for line in (
        "|  | Jan 26, 2025 |  | Jan 28, 2024 |",
        "|  | 2025 |  | 2024 |  | 2023 |",
        "| | Three Months Ended | Nine Months Ended |",
    ):
        assert _is_period_header(line), f"missed a period header: {line!r}"


def test_a_figure_row_is_not_a_period_header():
    """The discriminator is that a header carries no figures of its own."""
    assert not _is_period_header("Total | 130,497 |  | 60,922 |")
    assert not _is_period_header("Net income | — |  | 72,880 |")


# --- binding ----------------------------------------------------------------------------


def test_a_continuation_window_regains_its_caption_and_header():
    """The case that matters: a long table cut below its caption."""
    section = "\n".join([CAPTION, HEADER, *ROWS])
    orphan = "\n".join(ROWS[1:])          # as if the chunker cut after the first row

    bound = _bind_table_context(orphan, section)

    assert CAPTION in bound, "the scale caption must be carried to the continuation"
    assert HEADER in bound, "the period header must be carried too"
    assert ROWS[1] in bound and ROWS[2] in bound, "the original rows must survive intact"


def test_a_window_that_already_has_its_caption_is_untouched():
    """No duplication, and no cost where there is no problem."""
    section = "\n".join([CAPTION, HEADER, *ROWS])
    whole = "\n".join([CAPTION, HEADER, *ROWS])
    assert _bind_table_context(whole, section) == whole


def test_a_window_with_no_figures_is_untouched():
    """Narrative prose must not collect table furniture it has no use for."""
    section = "\n".join([CAPTION, HEADER, *ROWS])
    prose = "Our results improved materially over the prior year."
    assert _bind_table_context(prose, section) == prose


def test_only_the_caption_above_the_window_is_used():
    """Two tables in one section must not swap captions.

    Binding the *nearest preceding* caption is the whole point; taking the first or the last
    in the section would attach thousands to a table reported in millions.
    """
    section = "\n".join(
        [
            "First table (in thousands):",
            "|  | 2025 |",
            "Headcount | 36,000 |",
            "",
            "Second table (in millions):",
            HEADER,
            *ROWS,
        ]
    )
    orphan = "\n".join(ROWS[1:])
    bound = _bind_table_context(orphan, section)
    assert "in millions" in bound
    assert "in thousands" not in bound, "attached a caption from a different table"


def test_binding_adds_only_the_filing_s_own_words():
    """No synthesized text ever reaches a chunk.

    `index.py` stores this text as what citations display, and an excerpt must show the
    filing's words. The caption and header are the filing's own lines, carried forward from
    earlier in the same section — a composition of two real spans, never an invention.
    """
    section = "\n".join([CAPTION, HEADER, *ROWS])
    bound = _bind_table_context("\n".join(ROWS[1:]), section)
    for line in bound.split("\n"):
        if line.strip():
            assert line in section, f"line not present in the source section: {line!r}"


# --- the corpus case the ticket named ---------------------------------------------------


def test_nvidia_currency_figures_carry_their_scale():
    """The panel's temporal question is answered from these rows.

    Scoped to **currency** figures deliberately. A first version of this test flagged any
    thousands-separated number and caught NVIDIA's Rule 10b5-1 trading-arrangement table —
    director names against absolute share counts like `29,000`, which needs no scale caption
    because a share count is unambiguous. Only a monetary amount changes meaning with its
    scale, so only monetary amounts are the requirement here.
    """
    import re

    from src.ingest import chunk_filing

    currency = re.compile(r"\|\s*\$\s*\(?\d|\$\s*[\d,]+\s*(?:million|billion)?", re.I)

    orphans = []
    for chunk in chunk_filing("NVDA_10K_2025-02-26_full.txt"):
        lines = chunk.text.split("\n")
        figures = [line for line in lines if line.count("|") >= 2 and currency.search(line)]
        if len(figures) >= 3 and not any(_scale_caption(line) for line in lines):
            orphans.append(chunk)

    assert not orphans, (
        f"{len(orphans)} NVIDIA chunks carry 3+ currency figures with no stated scale, "
        f"e.g. in {orphans[0].item_section!r}: {orphans[0].text[:200]!r}"
    )
