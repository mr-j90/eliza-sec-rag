"""Hybrid retrieval — the seam where fusion is observable.

The live tests need Qdrant and a provider key. They **skip loudly** rather than pass
vacuously when either is missing: a green suite that silently skipped the only tests
proving retrieval works would be worse than a red one.
"""

import statistics

import pytest
from qdrant_client import models

from src.chunks import Chunk
from src.config import settings
from src.index import ensure_indexed
from src.retrieve import (
    PER_FILE_CAP,
    Retrieved,
    build_hybrid_query,
    file_diverse,
    retrieve,
    suppress_near_duplicates,
)


def test_fusion_is_server_side_rrf_over_dense_and_sparse():
    """SPEC §5.4 — one query, two prefetches, rank-based fusion.

    Rank fusion is chosen specifically so cosine similarity (0-1, tight variance) never has
    to be reconciled with BM25 scores (unbounded, corpus-dependent). If someone replaces this
    with score normalisation, this test is what fails.
    """
    query = build_hybrid_query(
        dense=[0.1] * 8,
        sparse=models.SparseVector(indices=[1, 2], values=[0.5, 0.5]),
        limit=20,
    )

    prefetch = query["prefetch"]
    assert len(prefetch) == 2, "hybrid means exactly two prefetches"
    assert {p.using for p in prefetch} == {"dense", "sparse"}

    fusion = query["query"]
    # `RrfQuery`, not `FusionQuery` — the latter takes no ranking constant and Qdrant defaults
    # it to 2, so the value would exist only as a server default. Prior art ran that default
    # while its prose claimed k=60; the constant is now stated where it can be reviewed.
    assert isinstance(fusion, models.RrfQuery)
    assert fusion.rrf.k == settings().rrf_k
    assert query["limit"] == 20


def test_the_ranking_constant_is_explicit_and_not_the_server_default():
    """Qdrant's default is 2, which is not a value anybody chose.

    Verified empirically rather than from docs: `FusionQuery(fusion=Fusion.RRF)` and
    `RrfQuery(rrf=Rrf(k=2))` return an identical id-set and an identical score multiset over
    this collection.
    """
    assert settings().rrf_k != 2, (
        "the ranking constant is back to Qdrant's default — set RAG_RRF_K or DEFAULT_RRF_K"
    )


def test_prefetch_limits_are_wider_than_the_final_limit():
    """Fusion needs candidates to fuse; prefetching k would make RRF a no-op."""
    query = build_hybrid_query(
        dense=[0.1] * 8,
        sparse=models.SparseVector(indices=[1], values=[1.0]),
        limit=10,
    )
    assert all(p.limit > query["limit"] for p in query["prefetch"])


# --- live tests: real Qdrant, real embeddings ---


@pytest.fixture(scope="module")
def indexed():
    from src.config import settings
    from src.index import qdrant_reachable

    if not qdrant_reachable():
        pytest.skip(f"Qdrant not reachable at {settings().qdrant_url} — `docker compose up -d`")
    if not settings().provider_configured:
        pytest.skip("no provider key — dense embeddings need OPENAI_API_KEY")
    return ensure_indexed()


TOPICS = {
    "supply": "What does Apple say about supply chain and manufacturing concentration?",
    "legal": "What legal proceedings and litigation does Apple disclose?",
}


def test_different_questions_retrieve_different_chunks(indexed):
    """The defining property of retrieval, and the one a fixed context could not have.

    Under the fixed context this test was impossible to pass: every question returned the
    same three windows. If it fails now, retrieval is not actually influencing the answer.
    """
    supply = {c.chunk.chunk_id for c in retrieve(TOPICS["supply"], k=10)}
    legal = {c.chunk.chunk_id for c in retrieve(TOPICS["legal"], k=10)}

    assert supply, "supply-chain question retrieved nothing"
    assert legal, "legal question retrieved nothing"
    assert supply != legal, "both questions returned identical chunks — retrieval is inert"


def test_retrieved_passages_are_on_topic(indexed):
    """Not just *different* chunks — the right ones. Different-but-wrong would pass above."""
    legal_text = " ".join(c.chunk.text.lower() for c in retrieve(TOPICS["legal"], k=5))
    assert any(term in legal_text for term in ("legal proceedings", "litigation", "lawsuit")), (
        "top legal results mention none of legal proceedings / litigation / lawsuit"
    )


def test_the_contextual_prefix_is_embedded_not_just_stored(indexed):
    """A term that exists *only* in the prefix must still retrieve the chunk.

    SPEC §4's claim is that the synthesized header goes to the embedder, so a chunk that never
    names its company is still reachable by company. The ticker is the clean probe: `AAPL`
    appears in 1 of 78 chunk bodies and `FY2025` in none, so a hit whose body lacks the term
    can only have matched through the embedded prefix.

    Asking for a *prefix-free result* directly does not work on this filing — Apple names
    itself in 59 of 78 chunks — which is why the probe is the ticker rather than the name.
    """
    results = retrieve("AAPL", k=5)
    assert results, "the ticker retrieved nothing — the prefix cannot have been embedded"

    matched_via_prefix = [r for r in results if "AAPL" not in r.chunk.text]
    assert matched_via_prefix, (
        "every AAPL hit already contained AAPL in its body, so this proves nothing"
    )


def test_stored_text_is_display_clean(indexed):
    """The prefix must not leak into what a citation shows a user."""
    for result in retrieve("Apple risk factors", k=10):
        prefix_head = f"{result.chunk.company} ({result.chunk.ticker})"
        assert not result.chunk.text.startswith(prefix_head), (
            f"stored text carries the synthesized prefix: {result.chunk.text[:120]!r}"
        )


def test_retrieval_latency_is_measured_and_within_budget(indexed):
    """The lower bound matters: the fixed-context version's 0.0 ms was a dict lookup."""
    timings = []
    for question in list(TOPICS.values()) * 3:
        import time

        started = time.perf_counter()
        retrieve(question, k=10)
        timings.append((time.perf_counter() - started) * 1000)

    p50 = statistics.median(timings)
    assert p50 > 0, "a zero reading means nothing was measured"
    assert p50 < 2000, f"retrieval p50 {p50:.0f} ms exceeds the 2s budget"


# --- near-duplicate suppression ---


def retrieved(text: str, score: float = 1.0) -> Retrieved:
    return Retrieved(chunk=chunk_from(text), score=score)


def chunk_from(text: str) -> Chunk:
    return Chunk(
        chunk_id=f"X-{hash(text) & 0xffff:04x}",
        text=text,
        company="Apple Inc",
        ticker="AAPL",
        cik="0000320193",
        form_type="10-Q",
        fiscal_year=2025,
        period_end="",
        filing_date="2025-05-02",
        item_section="Part II Item 1A — Risk Factors",
        chunk_index=0,
        source_file="x.txt",
        token_count=50,
    )


QUARTER_ONE = (
    "The Company's business is subject to global and regional economic conditions, "
    "including inflation and interest rates, which could materially adversely affect "
    "demand for the Company's products and services during fiscal 2025."
)
# The same risk factor next quarter: a couple of numbers changed, everything else verbatim.
QUARTER_TWO = QUARTER_ONE.replace("fiscal 2025", "fiscal 2026")
DIFFERENT = (
    "The Company is party to litigation including antitrust claims brought by developers "
    "regarding App Store terms, the outcome of which cannot be predicted with certainty."
)


def test_a_passage_repeated_across_quarters_is_suppressed():
    kept = suppress_near_duplicates([retrieved(QUARTER_ONE), retrieved(QUARTER_TWO)])
    assert len(kept) == 1
    assert kept[0].chunk.text == QUARTER_ONE, "the higher-ranked passage must survive"


def test_passages_on_the_same_topic_are_not_treated_as_duplicates():
    """Suppression must remove repetition, not variety — over-aggressive is its own failure."""
    kept = suppress_near_duplicates([retrieved(QUARTER_ONE), retrieved(DIFFERENT)])
    assert len(kept) == 2


def test_suppression_never_empties_the_result_set():
    kept = suppress_near_duplicates([retrieved(QUARTER_ONE)] * 5)
    assert len(kept) == 1, "identical passages collapse to one, not to none"


def test_live_results_contain_no_near_duplicates(indexed):
    results = retrieve("What risks does Apple disclose about economic conditions?", k=20)
    assert results
    assert len(suppress_near_duplicates(results)) == len(results), (
        "retrieve() returned near-duplicates; suppression is not being applied"
    )


# --- file-diversity selection (2026-08-21) ---


def in_file(source_file: str, score: float = 1.0) -> Retrieved:
    """A Retrieved carrying only the field file_diverse cares about: its source_file."""
    chunk = chunk_from(f"chunk from {source_file} @ {score}")
    return Retrieved(
        chunk=Chunk(**{**chunk.__dict__, "source_file": source_file}), score=score
    )


def test_file_diverse_spreads_slots_across_filings():
    """With filings to spare, each slot goes to a distinct filing — the recall fix.

    Ten candidates from three filings must not spend all ten slots on filing A; a file-level
    label counts filings, and a comparison the reader trusts wants breadth."""
    ranked = [in_file("a.txt")] * 5 + [in_file("b.txt")] * 3 + [in_file("c.txt")] * 2
    picked = file_diverse(ranked, limit=3, cap=PER_FILE_CAP)
    assert {r.chunk.source_file for r in picked} == {"a.txt", "b.txt", "c.txt"}


def test_file_diverse_respects_the_per_file_cap_before_a_second_pass():
    """Pass one takes one chunk per filing; only then may a filing take a second (up to cap)."""
    ranked = [in_file("a.txt", 3), in_file("a.txt", 2), in_file("b.txt", 1)]
    picked = file_diverse(ranked, limit=3, cap=2)
    files = [r.chunk.source_file for r in picked]
    assert files == ["a.txt", "b.txt", "a.txt"], (
        "b.txt must win the second slot over a.txt's second chunk"
    )


def test_file_diverse_degrades_to_cap_rather_than_returning_short():
    """One filing, three candidates, cap=2: fill two slots, not one and not three."""
    ranked = [in_file("a.txt", 3), in_file("a.txt", 2), in_file("a.txt", 1)]
    assert len(file_diverse(ranked, limit=5, cap=2)) == 2


def test_file_diverse_never_exceeds_the_limit():
    ranked = [in_file(f"{i}.txt") for i in range(50)]
    assert len(file_diverse(ranked, limit=20, cap=PER_FILE_CAP)) == 20


# --- corpus-scale checks ---


def test_the_index_holds_every_filing_and_every_company(indexed):
    """Deterministic point ids mean a collision overwrites silently, so the count
    is compared against what the chunker produces rather than assumed to match."""
    from src.config import settings as _settings
    from src.index import client, count
    from src.ingest import chunk_filing

    expected = sum(
        len(chunk_filing(p.name)) for p in sorted(_settings().corpus_dir.glob("*.txt"))
    )
    stored = count()
    assert stored == expected, f"index holds {stored:,}, chunker produces {expected:,}"

    tickers = set()
    offset = None
    while True:
        points, offset = client().scroll(
            collection_name=_settings().collection,
            limit=4096,
            offset=offset,
            with_payload=["ticker"],
            with_vectors=False,
        )
        tickers.update(p.payload["ticker"] for p in points if p.payload)
        if offset is None:
            break
    assert len(tickers) == 54, f"expected 54 tickers in the index, found {len(tickers)}"


def test_a_cross_company_question_reaches_more_than_one_company(indexed):
    """Deliberately weak: guaranteeing *every* named company is entity quotas, the
    next entry. But a comparative question returning a single company means retrieval is
    ignoring two thirds of the question, and that must not pass silently."""
    results = retrieve(
        "What are the primary risk factors facing Apple, Tesla, and JPMorgan, "
        "and how do they compare?",
        k=20,
    )
    companies = {r.chunk.ticker for r in results}
    assert len(companies) > 1, f"a three-company question retrieved only {companies}"


def test_report_period_is_used_when_the_filing_carries_it():
    """Getting the period wrong misdates citations, which is a quiet way to
    mislead a reader.

    **Amended by ticket 15.** This test used to assert that the 54 filings without a
    `Report Period:` line have no period end and take the **filing-date year** — which is
    the defect, not the requirement. A 10-K is filed one to three months after the period it
    reports on, so that fallback labelled 37 of 246 filings a year too high and pushed
    `LATEST_FISCAL_YEAR` to 2026 for a corpus ending in 2025.

    The period end is recoverable for 53 of those 54 from the `URL:` field, so it is now
    read rather than abandoned. Note this test needs no Qdrant and no key — it only calls
    `chunk_filing` — so it no longer requests `indexed` and runs in the free tier.
    """
    from src.ingest import chunk_filing

    with_period = chunk_filing("AAPL_10K_2024Q3_2024-11-01_full.txt")[0]
    assert with_period.period_end, "Report Period was present but not captured"
    assert with_period.fiscal_year == int(with_period.period_end[:4])

    # No `Report Period:` line at all — the period end comes from the URL, `aapl-20250927`.
    without = chunk_filing("AAPL_10K_2025-10-31_full.txt")[0]
    assert without.period_end == "2025-09-27", (
        "the period end is in the URL field and must be used rather than discarded"
    )
    assert without.fiscal_year == 2025

    # And the case that proves the point: filed in the year *after* the period it covers.
    # The filing-date fallback would say 2026.
    off_by_one = chunk_filing("AMZN_10K_2026-02-06_full.txt")[0]
    assert off_by_one.period_end == "2025-12-31"
    assert off_by_one.fiscal_year == 2025, "filed Feb 2026, reports on FY2025"
