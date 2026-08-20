"""The rendered prompt template cannot drift from the prompt.

Ticket 11. The brief asks for "your final prompt template" as its own deliverable, and the
prompt lives in `src/prompt.py` as code — a reader would otherwise have to assemble `SYSTEM`
plus `user_prompt` in their head to see what the model receives.

So `docs/PROMPT_TEMPLATE.md` is **generated**, and this file is what keeps it honest. A
hand-maintained prompt document drifts within a day, and a drifted one is worse than none: it
describes a system that no longer exists while looking authoritative. That failure has already
happened twice in this repo — `frontend/README.md` still described a pre-RAG chat app that no
longer existed, and `prompt.py`'s own docstring claimed v2 while the code ran v4.

Free tier: no Qdrant, no key.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.prompt import PROMPT_VERSION, SECTIONS, SYSTEM, render_template

TEMPLATE = Path(__file__).parent.parent / "docs" / "PROMPT_TEMPLATE.md"
PROMPT_LOG = Path(__file__).parent.parent / "PROMPT_LOG.md"


def test_the_committed_template_matches_the_live_prompt():
    """If this fails, regenerate — do not edit the markdown.

        uv run python -m src.prompt > docs/PROMPT_TEMPLATE.md

    Then add a `PROMPT_LOG.md` entry saying what changed and why, which is the deliverable the
    brief actually asks for.
    """
    assert TEMPLATE.is_file(), f"{TEMPLATE} is missing — regenerate it"
    committed = TEMPLATE.read_text()
    assert committed.strip() == render_template().strip(), (
        "docs/PROMPT_TEMPLATE.md is stale. Regenerate with "
        "`uv run python -m src.prompt > docs/PROMPT_TEMPLATE.md` and log the change."
    )


def test_the_template_shows_both_the_answering_and_refusing_forms():
    """A template that only shows the happy path hides the behaviour most worth reviewing."""
    rendered = render_template()
    assert "## User message — answering" in rendered
    assert "## User message — refusing" in rendered
    assert "Do not write a Findings section" in rendered, (
        "the refusal variant's actual instruction should be visible, not described"
    )


def test_the_template_carries_the_live_version_and_every_required_section():
    rendered = render_template()
    assert PROMPT_VERSION in rendered.split("\n", 1)[0], "the heading should name the version"
    for heading in SECTIONS.values():
        assert heading in rendered, f"the format block should show {heading!r}"
    assert SYSTEM in rendered, "the system message must appear verbatim, not paraphrased"


def test_the_grounding_rules_say_what_to_do_with_a_table_figure():
    """v8. Both halves, because the second one is the rule.

    Financial tables are ~46% of the index and arrive as pipe-delimited rows, so a figure's
    scale sits in a caption rather than beside it. "State the units" alone would invite the
    model to supply units it was not given — a missing scale becoming a confident wrong one.
    Asserted on substance rather than phrasing, like the rest of this file.
    """
    assert "|" in SYSTEM and "table" in SYSTEM.lower(), (
        "nothing tells the model a pipe-delimited row is a financial table"
    )
    assert re.search(r"in millions|in thousands", SYSTEM), (
        "the scale caption's own wording should be shown, not described"
    )
    assert re.search(r"no scale|not stated", SYSTEM) and "assume" in SYSTEM, (
        "the guard is missing: an unstated scale must be reported, never assumed"
    )


def test_the_log_has_an_entry_for_the_live_version():
    """The version the system reports must be explained somewhere a reader can find.

    This is the check that would have caught `prompt.py`'s docstring describing v2 while
    `PROMPT_VERSION` was v4 — a discrepancy ticket 01 found by reading, not by testing.
    """
    log = PROMPT_LOG.read_text()
    assert re.search(rf"^## {re.escape(PROMPT_VERSION)}\b", log, re.MULTILINE), (
        f"PROMPT_LOG.md has no `## {PROMPT_VERSION}` entry, but the system reports "
        f"prompt_version={PROMPT_VERSION}"
    )


def test_every_logged_version_is_reachable_and_none_are_skipped():
    """`v1, v2, ... vN` with no gaps, and N is what the code reports.

    A gap means an iteration was made and not written down — which is the one thing this
    deliverable exists to prevent.
    """
    log = PROMPT_LOG.read_text()
    versions = {int(m) for m in re.findall(r"^## v(\d+)\b", log, re.MULTILINE)}
    assert versions, "no version headings found in PROMPT_LOG.md"

    live = int(PROMPT_VERSION.lstrip("v"))
    assert versions == set(range(1, live + 1)), (
        f"logged versions {sorted(versions)} should be exactly 1..{live} with no gaps"
    )


def test_no_change_entries_are_marked_as_such():
    """Some entries record a change in *context* rather than in the prompt — a new reranker,
    reflowed passages, bound table captions. They are worth logging because the prompt's
    behaviour changed, and they must not read as prompt edits."""
    log = PROMPT_LOG.read_text()
    observations = re.findall(r"^## v\d+ — observed[^\n]*", log, re.MULTILINE)
    assert observations, "expected at least one no-prompt-change observation entry"
    for heading in observations:
        assert "no prompt change" in heading, (
            f"an observation entry should say so in its heading: {heading!r}"
        )
