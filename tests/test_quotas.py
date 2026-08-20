"""Entity-quota retrieval — SPEC §5.3, "the single most important retrieval behaviour".

A global top-k returns whichever company writes the most vivid prose: before quotas, the
assessment's own comparative question came back JPMorgan 15, Tesla 3, Apple 1 of 20. These
tests are the fairness bar that replaced it, expressed as checks.

Live tests need Qdrant and a key, and skip loudly rather than pass vacuously.
"""

import collections
import statistics

import pytest

from src.config import settings
from src.index import ensure_indexed, qdrant_reachable
from src.query import plan
from src.retrieve import retrieve_for

PANEL_COMPARATIVE = (
    "What are the primary risk factors facing Apple, Tesla, and JPMorgan, "
    "and how do they compare?"
)


@pytest.fixture(scope="module")
def indexed():
    if not qdrant_reachable():
        pytest.skip(f"Qdrant not reachable at {settings().qdrant_url} — `docker compose up -d`")
    if not settings().provider_configured:
        pytest.skip("no provider key — dense embeddings need OPENAI_API_KEY")
    return ensure_indexed()


def by_ticker(results):
    return collections.Counter(r.chunk.ticker for r in results)


def test_every_named_company_gets_a_fair_share(indexed):
    """The bar is representation, not presence.

    Presence was satisfiable with one Apple passage against fifteen JPMorgan ones, which
    cannot answer the question the panel asked.
    """
    results = retrieve_for(PANEL_COMPARATIVE, k=20)
    counts = by_ticker(results)

    for ticker in ("AAPL", "TSLA", "JPM"):
        assert counts[ticker] >= 4, f"{ticker} got {counts[ticker]} passages of 20: {counts}"

    named = [counts[t] for t in ("AAPL", "TSLA", "JPM")]
    assert min(named) >= max(named) / 4, f"still lopsided: {counts}"


def test_the_budget_is_shared_rather_than_multiplied(indexed):
    """n companies at k/n each, not n x k. Returning 60 passages for three companies would
    blow the context budget while looking like success."""
    results = retrieve_for(PANEL_COMPARATIVE, k=20)
    assert len(results) <= 20, f"asked for 20, got {len(results)}"


def test_quotas_survive_near_duplicate_suppression(indexed):
    """The interaction flagged when this intent was carved.

    Suppression over a merged result set can eat one company's entire quota, and the failure
    looks exactly like the imbalance quotas exist to fix — so it is checked directly rather
    than inferred from the counts above.
    """
    counts = by_ticker(retrieve_for(PANEL_COMPARATIVE, k=20))
    assert all(counts[t] > 0 for t in ("AAPL", "TSLA", "JPM")), (
        f"a company lost its whole quota to suppression: {counts}"
    )


def test_a_single_company_question_stays_on_that_company(indexed):
    """Before filters, an Apple-only question pulled passages from five companies."""
    counts = by_ticker(retrieve_for("What legal proceedings does Apple disclose?", k=20))
    assert counts["AAPL"] >= 15, f"Apple-only question drifted: {counts}"


def test_a_sector_question_is_not_made_worse(indexed):
    """Sector breadth already worked with no filters at all — this must not regress."""
    counts = by_ticker(
        retrieve_for(
            "What regulatory risks do the major pharmaceutical companies face, "
            "and how are they addressing them?",
            k=20,
        )
    )
    assert len(counts) >= 4, f"sector question narrowed to {len(counts)} companies: {counts}"


def test_a_time_scoped_question_is_restricted_to_those_years(indexed):
    question = "How has NVIDIA's revenue and growth outlook changed over the last two years?"
    wanted = plan(question).fiscal_years
    assert wanted is not None

    for result in retrieve_for(question, k=20):
        assert wanted[0] <= result.chunk.fiscal_year <= wanted[1], (
            f"{result.chunk.chunk_id} is FY{result.chunk.fiscal_year}, outside {wanted}"
        )


def test_a_form_scoped_question_is_restricted_to_that_form(indexed):
    for result in retrieve_for("What did Apple report in its most recent quarter?", k=20):
        assert result.chunk.form_type == "10-Q", f"got a {result.chunk.form_type}"


def test_quota_retrieval_stays_inside_the_latency_budget(indexed):
    """n companies means n filtered searches. The budget is 2s, and the query embedding must
    be computed once rather than per company."""
    import time

    timings = []
    for _ in range(3):
        started = time.perf_counter()
        retrieve_for(PANEL_COMPARATIVE, k=20)
        timings.append((time.perf_counter() - started) * 1000)
    p50 = statistics.median(timings)
    assert p50 < 2000, f"quota retrieval p50 {p50:.0f} ms exceeds the 2s budget"
