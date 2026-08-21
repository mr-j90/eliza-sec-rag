"""Hybrid retrieval — the seam where fusion is observable.

SPEC §5.4: dense and sparse are fused by **Reciprocal Rank Fusion, server-side, in one Qdrant
query**. Rank-based fusion is the point: it never has to reconcile cosine similarity (0-1,
tight variance) against BM25 scores (unbounded, corpus-dependent), which is where naive hybrid
implementations break quietly — they keep returning results, just worse ones.

The pipeline is fetch-deep → bound → rerank → spread; each step is a constant below, stated
with the measurement that set it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from qdrant_client import models

from src.chunks import RISK_FACTOR_SECTIONS, Chunk
from src.config import settings
from src.embed import dense_query, sparse_query
from src.index import client
from src.query import QueryPlan, plan
from src.rerank import FUSION_ONLY, WITH_RERANK, reorder

# Each branch fetches more candidates than the final limit, because fusion needs something
# to fuse: prefetching exactly k would leave RRF nothing to reorder.
PREFETCH_LIMIT = 80


# Whether the most recent search actually reranked. Reported through `retrieval_description`
# so `retrieval_meta` never names a step that silently did not run — the model download can
# fail on a first offline run, and fusion order is a graceful degradation rather than a wrong
# answer.
_LAST_RERANKED = False


def retrieval_description() -> str:
    return WITH_RERANK if _LAST_RERANKED else FUSION_ONLY


@dataclass(frozen=True)
class Retrieved:
    chunk: Chunk
    score: float


def _fusion_query() -> models.FusionQuery | models.RrfQuery:
    """The fusion step, with its constant stated rather than inherited.

    `FusionQuery(fusion=Fusion.RRF)` accepts no ranking constant and Qdrant defaults it to
    **2** — confirmed by comparing against `RrfQuery(rrf=Rrf(k=2))`, which returns an identical
    id-set and score multiset. `RrfQuery` is the newer form and does take `k`, so the constant
    is set explicitly here: a value that only exists as a server default is a value nobody can
    defend in a review.

    `RAG_FUSION=dbsf` selects distribution-based score fusion, which uses score *magnitude*
    rather than rank. It can beat RRF when one leg is confidently right — plausible on a corpus
    this identifier-dense — and Qdrant appears to be the only mainstream store shipping it.
    """
    config = settings()
    if config.fusion == "dbsf":
        return models.FusionQuery(fusion=models.Fusion.DBSF)
    return models.RrfQuery(rrf=models.Rrf(k=config.rrf_k))


def build_hybrid_query(
    *,
    dense: list[float],
    sparse: models.SparseVector,
    limit: int,
    query_filter: models.Filter | None = None,
) -> dict[str, Any]:
    """The Qdrant request, as data, so a test can assert on its shape.

    Separated from execution on purpose: "fusion happens server-side over two branches" is a
    contract with Qdrant, and asserting it through an HTTP response would mean inferring it
    from results rather than checking it.
    """
    return {
        "prefetch": [
            models.Prefetch(
                query=dense, using="dense", limit=max(PREFETCH_LIMIT, limit * 2), filter=query_filter
            ),
            models.Prefetch(
                query=sparse, using="sparse", limit=max(PREFETCH_LIMIT, limit * 2), filter=query_filter
            ),
        ],
        "query": _fusion_query(),
        "limit": limit,
        "query_filter": query_filter,
    }


def _to_chunk(payload: dict[str, Any]) -> Chunk:
    """Payload back to `Chunk`. `index.py` writes every field via `asdict`, so this is the
    exact inverse — a stale collection missing a field fails loudly here rather than
    defaulting it to something that reads as real."""
    return Chunk(**payload)


SHINGLE = 5
NEAR_DUPLICATE = 0.8

# How the candidate pool is built and cut — measured 2026-08-21 (see `_search`). Relevance is
# file-level (SPEC §7.1), and the failure this addresses was file-level: on questions whose
# answer is spread across many filings — Pfizer/Merck patent expiration, the pharma sector —
# the relevant filings were in the index but ranked past the old `k*3` cutoff, or lost their
# slots to several chunks of the same filing. Three constants, each a distinct lever:
#
# - CANDIDATE_POOL: fuse this many candidates (× the final limit) before selecting. The old ×3
#   left Pfizer's filings, ranked 30-100 in fusion, outside the pool entirely; ×10 brings all
#   15/15 in. Fusion at this depth is a cheap Qdrant operation — it is the reranker, not the
#   fetch, that costs (measured ~1.2s at 100 candidates), which is why the rerank input is
#   bounded next rather than the fetch.
# - RERANK_CAP: rerank at most this many, chosen file-diverse from the deep pool, so a filing
#   ranked deep in fusion still reaches the cross-encoder without paying to rerank everything.
# - PER_FILE_CAP: at most this many chunks per filing in the final cut, so k slots span ~k/2
#   filings instead of being spent on the most vivid one. cap=2 (not 1) is deliberate — with
#   many filings it behaves like one-per-file, but a company with few filings may still
#   contribute a second passage rather than being padded out by a rival's boilerplate.
CANDIDATE_POOL = 10
RERANK_CAP = 60
PER_FILE_CAP = 2


def _shingles(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < SHINGLE:
        return {" ".join(words)}
    return {" ".join(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def suppress_near_duplicates(
    results: list[Retrieved], threshold: float = NEAR_DUPLICATE
) -> list[Retrieved]:
    """Drop passages that repeat a higher-ranked one almost verbatim.

    SPEC §5.5 asks for this because filings repeat language across quarters: a 10-Q's risk
    factors are frequently the previous quarter's with a few numbers changed. Ten
    near-identical passages crowd out the ten distinct ones that would have made the answer
    better, and they inflate the citation list with sources that say the same thing.

    Jaccard similarity over word 5-shingles, which catches near-identical text without
    treating two passages on the same *topic* as duplicates. The higher-ranked passage always
    survives, so suppression can only ever remove a worse result.
    """
    kept: list[Retrieved] = []
    kept_shingles: list[set[str]] = []

    for result in results:
        shingles = _shingles(result.chunk.text)
        duplicate = False
        for existing in kept_shingles:
            union = shingles | existing
            if union and len(shingles & existing) / len(union) >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(result)
            kept_shingles.append(shingles)
    return kept


def file_diverse(results: list[Retrieved], limit: int, cap: int = PER_FILE_CAP) -> list[Retrieved]:
    """Fill `limit` slots from `results` (kept in their given order), at most `cap` per filing.

    Relevance is file-level, so a slot spent on a filing already represented buys no recall and
    little for the reader — a comparison or a trend answer wants breadth across filings, not the
    same 10-K quoted five times. Walked in passes so the slots still fill when distinct filings
    are fewer than `limit`: pass one takes each filing's best chunk, pass two the second-best,
    and so on up to `cap`. With filings to spare this yields one per filing; with few filings it
    degrades gracefully to `cap` chunks each rather than returning short.
    """
    counts: dict[str, int] = {}
    out: list[Retrieved] = []
    for pass_cap in range(1, cap + 1):
        for result in results:
            if len(out) >= limit:
                return out
            source = result.chunk.source_file
            if counts.get(source, 0) < pass_cap and result not in out:
                out.append(result)
                counts[source] = counts.get(source, 0) + 1
    return out


def retrieve(
    question: str, k: int = 20, *, query_filter: models.Filter | None = None
) -> list[Retrieved]:
    """Question in, ranked passages out. No LLM involved — SPEC §5.2."""
    return _search(
        question,
        k,
        query_filter=query_filter,
        dense=dense_query(question),
        sparse=sparse_query(question),
    )


def _search(
    question: str,
    k: int,
    *,
    query_filter: models.Filter | None,
    dense: list[float],
    sparse: models.SparseVector,
) -> list[Retrieved]:
    """One filtered hybrid search. Takes pre-computed vectors so a quota run embeds once.

    Fetch-deep, bound, rerank, spread — see the constants above for why each is where it is.
    """
    query = build_hybrid_query(
        dense=dense, sparse=sparse, limit=k * CANDIDATE_POOL, query_filter=query_filter
    )
    response = client().query_points(collection_name=settings().collection, **query)
    candidates = [
        Retrieved(chunk=_to_chunk(point.payload or {}), score=point.score or 0.0)
        for point in response.points
    ]
    deduped = suppress_near_duplicates(candidates)
    # Bound what the reranker sees, but keep it file-diverse: a plain prefix of the deep pool
    # would be all the top filing's chunks and would drop exactly the deep-ranked filings this
    # fetch depth exists to surface. Reranking cost is ~linear in input (measured), so this is
    # what keeps latency near the shallow-pool version.
    for_rerank = file_diverse(deduped, RERANK_CAP)
    ranked, reranked = (
        reorder(question, for_rerank) if settings().rerank_enabled else (for_rerank, False)
    )
    global _LAST_RERANKED
    _LAST_RERANKED = reranked
    # Spread the k slots across filings rather than taking the top-k, which clusters into the
    # few filings that phrase the topic most strongly. `retrieve_for` re-orders the merge by
    # company-then-section afterwards, so the score order here only decides *which* chunks win a
    # slot, not their final position.
    return file_diverse(ranked, k)


# SPEC §5.3: each detected company gets `k/n`, with a floor so a four-company question does
# not reduce every company to a fragment.
QUOTA_FLOOR = 6


def _scope_filter(
    plan: QueryPlan, *, ticker: str | None = None
) -> models.Filter | None:
    """Time and form scope, plus one company when running that company's quota."""
    conditions: list[models.FieldCondition] = []
    if ticker:
        conditions.append(
            models.FieldCondition(key="ticker", match=models.MatchValue(value=ticker))
        )
    if plan.fiscal_years:
        low, high = plan.fiscal_years
        conditions.append(
            models.FieldCondition(key="fiscal_year", range=models.Range(gte=low, lte=high))
        )
    if plan.form_type:
        conditions.append(_form_scope(plan.form_type))
    return models.Filter(must=conditions) if conditions else None


def _form_scope(form_type: str) -> models.Filter | models.FieldCondition:
    """The form filter — which lets the 10-K risk-factor baseline through a 10-Q scope.

    A 10-Q's Item 1A is an amendment, not a risk profile (`Chunk.is_incremental_risk_factors`).
    Measured: "What are Tesla's quarterly risk factors?" retrieved **7 chunks, 5,372 tokens** of
    amendments with no baseline; Pfizer's case was **1 chunk, 562 tokens** against an annual
    section past 10,000.

    A *narrow* trigger, not a general problem — unfiltered, the 10-K's Item 1A is ~5x larger and
    dominates retrieval anyway, so only a question whose own wording restricts the form is
    affected. Widening a scope the reader asked for is the right trade here because the
    alternative is a confidently incomplete answer, and because prompt v7 labels which passages
    are baseline and which are amendments.
    """
    scoped = models.FieldCondition(
        key="form_type", match=models.MatchValue(value=form_type)
    )
    if form_type.upper() != "10-Q":
        return scoped
    return models.Filter(
        should=[
            scoped,
            # The annual baseline for the amendments a 10-Q files.
            models.Filter(
                must=[
                    models.FieldCondition(
                        key="form_type", match=models.MatchValue(value="10-K")
                    ),
                    models.FieldCondition(
                        key="item_section",
                        match=models.MatchAny(any=sorted(RISK_FACTOR_SECTIONS)),
                    ),
                ]
            ),
        ]
    )


def retrieve_for(question: str, k: int = 20) -> list[Retrieved]:
    """Retrieve for a question, honouring the companies, period and form it asked about.

    **Why quotas rather than one global search.** Measured before this existed, "Apple, Tesla
    and JPMorgan" against a global top-k came back JPMorgan 15, Tesla 3, Apple 1 of 20 — every
    company represented, and the question unanswerable.

    Three properties, each a way this was got wrong: the budget is **shared** (`k/n` each, so
    three companies return ~k passages, not 3k); the query is **embedded once** (that round trip
    dominates retrieval latency); and near-duplicate suppression runs **per company, before the
    merge**, because over a merged set it can delete a company's whole quota — which looks
    exactly like the imbalance quotas exist to fix.
    """
    query_plan = plan(question)

    # One embedding for every branch. No LLM call anywhere in here.
    dense = dense_query(question)
    sparse = sparse_query(question)

    if not query_plan.companies:
        # No company named: one unfiltered search at full k, still scoped by period and form.
        return _search(
            question,
            k,
            query_filter=_scope_filter(query_plan),
            dense=dense,
            sparse=sparse,
        )

    budget = max(k // len(query_plan.companies), QUOTA_FLOOR)
    merged: list[Retrieved] = []
    for ticker in query_plan.companies:
        merged.extend(
            _search(
                question,
                budget,
                query_filter=_scope_filter(query_plan, ticker=ticker),
                dense=dense,
                sparse=sparse,
            )
        )

    # Order by company, then section, then period — SPEC §5.3. Grouping a comparison by
    # company is what makes it readable; interleaving companies by score does not.
    merged.sort(
        key=lambda r: (
            query_plan.companies.index(r.chunk.ticker)
            if r.chunk.ticker in query_plan.companies
            else len(query_plan.companies),
            r.chunk.item_section,
            r.chunk.fiscal_year,
        )
    )
    return merged[:k]
