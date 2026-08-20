"""Quarterly risk factors are amendments, and are treated as such.

Ticket 08. Form 10-Q's Item 1A carries only *material changes* from the 10-K. Measured on this
corpus, median annual risk-factor section **12,876 tokens** against a quarterly **2,617** — and
at the thin end, a Pfizer quarterly question retrieved **one chunk, 562 tokens**, presented as
a complete risk profile.

Two mechanisms, and they only work together:

1. A 10-Q form filter no longer excludes the covering 10-K's risk-factor baseline.
2. Quarterly risk-factor passages are named in the prompt as amendments — because supplying
   the baseline without labelling it makes a *new* error available: asserting a risk is "new
   this quarter" when it has sat in the 10-K for years.

Free tier where possible; the retrieval assertions need Qdrant and a key and are marked live
by requesting `indexed`.
"""

from __future__ import annotations

from collections import Counter

import pytest

from src.chunks import RISK_FACTOR_SECTIONS, Chunk
from src.index import ensure_indexed
from src.prompt import user_prompt


@pytest.fixture(scope="module")
def indexed():
    """Same gate as `test_retrieve.py` and `test_quotas.py`.

    Requesting it is also what marks these tests `live` — `tests/conftest.py` keys on the
    fixture name, so the tier follows from the dependency rather than from a hand-applied
    marker somebody has to remember.
    """
    from src.config import settings
    from src.index import qdrant_reachable

    if not qdrant_reachable():
        pytest.skip(f"Qdrant not reachable at {settings().qdrant_url} — `docker compose up -d`")
    if not settings().provider_configured:
        pytest.skip("no provider key — dense embeddings need OPENAI_API_KEY")
    return ensure_indexed()


def chunk(form: str, section: str, ticker: str = "TSLA") -> Chunk:
    return Chunk(
        chunk_id=f"{ticker}-{form}-{section[:6]}",
        text="Our business is subject to risks that could adversely affect results.",
        company="Tesla Inc",
        ticker=ticker,
        cik="0001318605",
        form_type=form,
        fiscal_year=2025,
        period_end="2025-09-28",
        filing_date="2025-10-23",
        item_section=section,
        chunk_index=0,
        source_file=f"{ticker}_{form.replace('-', '')}_x.txt",
        token_count=11,
    )


# --- the derived flag --------------------------------------------------------------------


def test_a_quarterly_risk_section_is_flagged_and_an_annual_one_is_not():
    assert chunk("10-Q", "Part II Item 1A — Risk Factors").is_incremental_risk_factors
    assert not chunk("10-K", "Item 1A — Risk Factors").is_incremental_risk_factors


@pytest.mark.parametrize(
    "section",
    ["Item 1 — Financial Statements", "Item 2 — Management's Discussion and Analysis"],
)
def test_other_quarterly_sections_are_not_flagged(section):
    """Only Item 1A is a material-changes section. Flagging a 10-Q's MD&A as an amendment
    would be wrong — quarterly MD&A is a complete discussion of that quarter."""
    assert not chunk("10-Q", section).is_incremental_risk_factors


def test_the_flag_is_derived_rather_than_stored():
    """It follows entirely from `form_type` and `item_section`.

    A payload field would be a second copy that could disagree with the two fields it is
    computed from — and this repo has already been bitten by a stored value drifting from its
    source twice over.
    """
    assert "is_incremental" not in {f.name for f in Chunk.__dataclass_fields__.values()}
    assert isinstance(
        type(chunk("10-Q", "Part II Item 1A — Risk Factors")).is_incremental_risk_factors,
        property,
    )


def test_both_risk_factor_labels_are_recognised():
    """A 10-K files under `Item 1A`; a 10-Q under `Part II Item 1A`. §2.6's collision means
    the labels are distinct, and missing either would silently disable the mechanism."""
    assert RISK_FACTOR_SECTIONS == {
        "Item 1A — Risk Factors",
        "Part II Item 1A — Risk Factors",
    }


# --- the prompt half --------------------------------------------------------------------


def test_the_prompt_names_the_amendment_handles():
    chunks = [
        chunk("10-K", "Item 1A — Risk Factors"),
        chunk("10-Q", "Part II Item 1A — Risk Factors"),
    ]
    rendered = user_prompt("What are Tesla's quarterly risk factors?", chunks)

    assert "Note on C2" in rendered, "the quarterly passage's handle must be named"
    assert "C1" not in rendered.split("Note on")[1].split("\n")[0], (
        "the annual passage must not be labelled an amendment"
    )
    assert "material changes" in rendered
    assert "baseline" in rendered


def test_the_prompt_forbids_calling_an_amendment_a_new_risk():
    """The error the retrieval fix makes newly available.

    With baseline and amendment side by side and nothing distinguishing them, a long-standing
    risk that a quarter merely restated can be reported as newly disclosed.
    """
    rendered = user_prompt(
        "risks", [chunk("10-Q", "Part II Item 1A — Risk Factors")]
    )
    assert "new or newly disclosed" in rendered


def test_no_note_when_nothing_is_incremental():
    """Prose must not collect a caveat it has no use for."""
    rendered = user_prompt("risks", [chunk("10-K", "Item 1A — Risk Factors")])
    assert "Note on" not in rendered


# --- the retrieval half -----------------------------------------------------------------


def test_a_quarterly_scope_still_admits_the_annual_baseline(indexed):
    """The measured failure: this question returned 7 quarterly chunks and no baseline.

    `_form_type_in` sets a 10-Q filter from the word "quarterly", which previously excluded
    the annual risk-factor section outright.
    """
    from src.retrieve import retrieve_for

    results = retrieve_for("What are Tesla's quarterly risk factors?", k=20)
    risk = [r for r in results if r.chunk.item_section in RISK_FACTOR_SECTIONS]
    forms = Counter(r.chunk.form_type for r in risk)

    assert risk, "no risk-factor passages retrieved at all"
    assert forms.get("10-K", 0) > 0, (
        f"a quarterly risk question returned no annual baseline: {dict(forms)}"
    )


def test_the_relaxation_does_not_leak_into_non_risk_questions(indexed):
    """A reader who scoped to quarterly filings and asked about *results* must not be handed
    annual passages. The baseline is admitted for risk factors only."""
    from src.retrieve import retrieve_for

    results = retrieve_for("What were Apple's quarterly results?", k=20)
    annual = [r for r in results if r.chunk.form_type == "10-K"]
    assert not [r for r in annual if r.chunk.item_section not in RISK_FACTOR_SECTIONS], (
        "annual non-risk passages leaked through a 10-Q scope"
    )


def test_the_pfizer_case_is_no_longer_a_single_amendment(indexed):
    """The worst measured instance: 1 chunk, 562 tokens, presented as a full risk profile."""
    from src.retrieve import retrieve_for

    results = retrieve_for(
        "How did Pfizer's risk factors change in its latest quarterly report?", k=20
    )
    risk = [r for r in results if r.chunk.item_section in RISK_FACTOR_SECTIONS]
    tokens = sum(r.chunk.token_count for r in risk)

    assert tokens > 2_000, f"only {tokens} tokens of risk-factor context — was 562"
    assert any(r.chunk.form_type == "10-K" for r in risk), "still no annual baseline"
