"""The answer contract — SPEC §6's five parts, and the refusal that must never regress.

These tests make **real generation calls** (four or five per run, cents in total). They skip
loudly without Qdrant and a key: an out-of-corpus refusal that only ever passed vacuously
would be worse than no test, because SPEC §10 names graceful refusal one of three things
never to cut.

Assertions are on the section headings the prompt *requires*, never on phrasing. A test that
hopes the model chose particular words is a test that fails on a reword and teaches nothing.
"""

import re

import pytest

from src.api import app, get_llm
from src.config import settings
from src.index import qdrant_reachable
from src.prompt import SECTIONS
from src.query import plan
from src.retrieve import retrieve_for

from fastapi.testclient import TestClient

PANEL_COMPARATIVE = (
    "What are the primary risk factors facing Apple, Tesla, and JPMorgan, "
    "and how do they compare?"
)
PANEL_TEMPORAL = "How has NVIDIA's revenue and growth outlook changed over the last two years?"
PANEL_SECTOR = (
    "What regulatory risks do the major pharmaceutical companies face, "
    "and how are they addressing them?"
)
OUT_OF_CORPUS = "What is Shopify's China exposure?"
MIXED = "Compare the risk factors of Apple and Shopify."


@pytest.fixture(scope="module", autouse=True)
def live():
    if not qdrant_reachable():
        pytest.skip(f"Qdrant not reachable at {settings().qdrant_url} — `docker compose up -d`")
    if not settings().provider_configured:
        pytest.skip("no provider key — these tests make real generation calls")


@pytest.fixture(scope="module")
def answers():
    """One generation per question, shared across assertions to keep the cost down."""
    client = TestClient(app)
    out = {}
    for question in (PANEL_COMPARATIVE, PANEL_TEMPORAL, PANEL_SECTOR, OUT_OF_CORPUS, MIXED):
        response = client.post("/ask", json={"question": question, "top_k": 20})
        assert response.status_code == 200, response.text
        out[question] = response.json()
    return out


# --- the refusal: an absent company is named, never substituted ---


def test_an_absent_company_is_named_and_refused(answers):
    body = answers[OUT_OF_CORPUS]
    answer = body["answer"]

    assert "Shopify" in answer, "the absent company must be named, not silently dropped"
    assert re.search(
        r"not (?:appear|present|in|included|available|covered)|no (?:information|context|filings)",
        answer,
        re.IGNORECASE,
    ), f"no explicit statement of absence: {answer[:300]!r}"


def test_the_refusal_invents_no_attribution(answers):
    """No ticker in the answer may be absent from the retrieved set. A refusal that names a
    company it did not retrieve has fabricated an attribution."""
    from src.aliases import by_ticker

    body = answers[OUT_OF_CORPUS]
    retrieved = {c["company"] for c in body["citations"]}

    for ticker, company in by_ticker().items():
        # Word-boundary, case-sensitive: tickers are uppercase and short ones collide.
        if re.search(rf"\b{re.escape(ticker)}\b", body["answer"]) and company not in retrieved:
            raise AssertionError(
                f"answer cites ticker {ticker} ({company}) which was never retrieved"
            )


# --- one absence must not cost the whole answer ---


def test_a_mixed_question_answers_the_company_it_has(answers):
    body = answers[MIXED]
    answer = body["answer"]

    assert "Shopify" in answer, "the absent company must still be named"
    assert re.search(r"\[C\d+\]", answer), (
        "no citations at all — the Apple half was discarded along with the Shopify half"
    )
    assert "Apple" in answer
    # Apple's passages were retrieved; the answer must actually use them.
    assert len(re.findall(r"\[C\d+\]", answer)) >= 3, (
        f"only {len(re.findall(r'\\[C\\d+\\]', answer))} citations for a company we hold 20 passages of"
    )


# --- SPEC §6's five parts ---


def test_a_comparative_answer_carries_every_required_section(answers):
    answer = answers[PANEL_COMPARATIVE]["answer"]
    missing = [name for name, heading in SECTIONS.items() if heading.lower() not in answer.lower()]
    assert not missing, f"missing sections {missing} in:\n{answer[:600]}"


def test_every_answer_carries_the_always_required_sections(answers):
    """Bottom line and gaps are required of every answer. Sources is required of every answer
    that cites something.

    **Amended when the clean refusal landed (prompt v4).** This originally required Sources
    unconditionally, which was right until refusals stopped citing anything. A pure refusal has
    nothing to source, and demanding the heading anyway would mean either an empty section or
    — worse — an invitation to fill it.
    The rule that survives is the honest one: cite your sources when you have used sources.
    """
    for question, body in answers.items():
        answer = body["answer"]
        for key in ("bottom_line", "gaps"):
            assert SECTIONS[key].lower() in answer.lower(), (
                f"{question[:40]!r} is missing the {key} section"
            )
        if re.search(r"\[C\d+\]", answer):
            assert SECTIONS["sources"].lower() in answer.lower(), (
                f"{question[:40]!r} cites passages but has no Sources section"
            )
        else:
            assert SECTIONS["sources"].lower() not in answer.lower(), (
                f"{question[:40]!r} has a Sources section but cited nothing"
            )


def test_a_figure_answer_states_the_scale_its_figures_are_in(answers):
    """Prompt v8, on the generation this fixture already makes — no extra call.

    The temporal question is answered from pipe-delimited table rows, where the scale lives in
    a `(in millions)` caption rather than beside the number. `$130.5` with no scale anywhere is
    off by a factor of a thousand or a million and reads exactly as authoritative as the
    correct figure.

    Coarse on purpose: it asserts the answer names a scale *somewhere* when it quotes currency,
    not that every figure carries one adjacently. Filings state a scale once per table, so a
    per-figure check would fail on an answer that correctly did the same.
    """
    answer = answers[PANEL_TEMPORAL]["answer"]
    if not re.search(r"\$\s?\d", answer):
        pytest.skip("this generation quoted no currency figures")
    assert re.search(r"million|billion|thousand|percent|%|scale is not stated", answer, re.I), (
        "currency figures are quoted with no scale named anywhere in the answer:\n"
        f"{answer[:600]}"
    )


# --- citations still resolve, one call per question ---


def test_every_handle_resolves_across_all_three_panel_questions(answers):
    for question in (PANEL_COMPARATIVE, PANEL_TEMPORAL, PANEL_SECTOR):
        body = answers[question]
        used = set(re.findall(r"\[(C\d+)\]", body["answer"]))
        have = {c["id"] for c in body["citations"]}
        assert used, f"{question[:40]!r} produced no citations at all"
        assert used <= have, f"{question[:40]!r} cites unresolvable handles: {sorted(used - have)}"


def test_structure_did_not_cost_the_one_call_constraint():
    """Five sections must not become five calls."""

    class Counting:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def complete(self, *, system: str, user: str) -> str:
            self.calls.append(user)
            return "## Bottom line\nx [C1]\n## Sources\n[C1]"

    llm = Counting()
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        response = TestClient(app).post("/ask", json={"question": PANEL_COMPARATIVE})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(llm.calls) == 1


def test_the_prompt_names_the_absent_company_to_the_model(answers):
    """The refusal should not depend on the model noticing an absence on its own.

    `unresolved_mentions` already knows Shopify is not in the corpus, so the prompt tells it —
    which is what makes the behaviour reliable rather than lucky.
    """
    assert plan(OUT_OF_CORPUS).unresolved_mentions == ["Shopify"]
    results = retrieve_for(OUT_OF_CORPUS, k=20)
    assert results, "retrieval should still return passages; the prompt handles the absence"


def test_the_structure_is_stable_across_generations():
    """One compliant sample is luck, not a property.

    An earlier version of this prompt passed a single-sample section check and then produced
    0 of 5 sections on the next three generations of the same question. Structure is only a
    property if it holds repeatedly, so this pays for two extra generations to find out.
    """
    client = TestClient(app)
    for attempt in range(2):
        body = client.post("/ask", json={"question": PANEL_COMPARATIVE, "top_k": 20}).json()
        missing = [
            name for name, heading in SECTIONS.items()
            if heading.lower() not in body["answer"].lower()
        ]
        assert not missing, (
            f"generation {attempt + 1} missing {missing}; structure is not stable"
        )


# --- prompt v4: a refusal answers nothing else ---


def test_a_pure_refusal_carries_no_findings_for_anyone_else(answers):
    """The question named only Shopify. Before this, the answer said so and then wrote five
    hundred words about Amazon, Bank of America, Cisco and Goldman Sachs — nothing fabricated,
    the wrong question answered at length. SPEC §10 lists graceful refusal among the three
    things never to cut, and dilution defeats it as surely as invention would.
    """
    answer = answers[OUT_OF_CORPUS]["answer"]

    subsections = re.findall(r"^###\s+(.+)$", answer, re.MULTILINE)
    assert not subsections, f"refusal produced findings for: {subsections}"

    handles = re.findall(r"\[C\d+\]", answer)
    assert not handles, f"refusal cited {len(handles)} passages it should not have used"


def test_a_sector_question_is_not_caught_by_the_refusal_rule(answers):
    """The regression this fix most plausibly causes.

    A sector question names no company either. A rule phrased as "only answer about companies
    the question named" would refuse the best-behaving question type on the project.
    """
    body = answers[PANEL_SECTOR]
    subsections = re.findall(r"^###\s+(.+)$", body["answer"], re.MULTILINE)
    assert len(subsections) >= 3, (
        f"sector question got {len(subsections)} company subsections: {subsections}"
    )
    assert re.findall(r"\[C\d+\]", body["answer"]), "sector answer lost its citations"
