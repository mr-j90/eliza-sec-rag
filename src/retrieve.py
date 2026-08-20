"""Hybrid retrieval — the seam where fusion is observable.

SPEC §5.4: dense and sparse are fused by **Reciprocal Rank Fusion, server-side, in one
Qdrant query**. Rank-based fusion is the point: it never has to reconcile cosine similarity
(0-1, tight variance) against BM25 scores (unbounded, corpus-dependent). Normalising those
two scales against each other is fragile and is where naive hybrid implementations break
quietly — they keep returning results, just worse ones.

`k=60` is the Cormack et al. default and is left at the default deliberately rather than
tuned against a 25-question golden set. Qdrant owns that constant server-side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from qdrant_client import models

from src.chunks import Chunk
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
        "query": models.FusionQuery(fusion=models.Fusion.RRF),
        "limit": limit,
        "query_filter": query_filter,
    }


def _to_chunk(payload: dict[str, Any]) -> Chunk:
    return Chunk(
        chunk_id=payload["chunk_id"],
        text=payload["text"],
        company=payload["company"],
        ticker=payload["ticker"],
        cik=payload["cik"],
        form_type=payload["form_type"],
        fiscal_year=payload["fiscal_year"],
        period_end=payload.get("period_end", ""),
        filing_date=payload.get("filing_date", ""),
        item_section=payload["item_section"],
        chunk_index=payload["chunk_index"],
        source_file=payload["source_file"],
        token_count=payload["token_count"],
    )


SHINGLE = 5
NEAR_DUPLICATE = 0.8
# Suppression removes results, so ask for more than we need and trim afterwards. Without this,
# a question whose top hits are all the same boilerplate would come back short.
OVERFETCH = 3


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
    """One filtered hybrid search. Takes pre-computed vectors so a quota run embeds once."""
    query = build_hybrid_query(
        dense=dense, sparse=sparse, limit=k * OVERFETCH, query_filter=query_filter
    )
    response = client().query_points(collection_name=settings().collection, **query)
    candidates = [
        Retrieved(chunk=_to_chunk(point.payload or {}), score=point.score or 0.0)
        for point in response.points
    ]
    # Rerank the overfetched, de-duplicated candidates and *then* cut to k. Placed here
    # rather than on the final merged set for two reasons: this is where there is genuinely
    # something to choose between (3k candidates for k slots), and `retrieve_for` orders its
    # output by company-then-section deliberately — reordering that by score would break the
    # grouping that makes a comparison readable.
    deduped = suppress_near_duplicates(candidates)
    ranked, reranked = reorder(question, deduped)
    global _LAST_RERANKED
    _LAST_RERANKED = reranked
    return ranked[:k]


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
        conditions.append(
            models.FieldCondition(
                key="form_type", match=models.MatchValue(value=plan.form_type)
            )
        )
    return models.Filter(must=conditions) if conditions else None


def retrieve_for(question: str, k: int = 20) -> list[Retrieved]:
    """Retrieve for a question, honouring the companies, period and form it asked about.

    **Why quotas rather than one global search.** A comparative question against a global
    top-k returns whichever company writes the most vivid prose — measured before this
    existed, "Apple, Tesla and JPMorgan" came back JPMorgan 15, Tesla 3, Apple 1 of 20, which
    satisfies "every company is represented" and cannot answer the question. Per-company
    budgets guarantee representation instead of hoping for it.

    Three properties worth stating because each was a way to get this wrong:

    - **The budget is shared, not multiplied.** *n* companies get `k/n` each, so three
      companies still return ~k passages rather than 3k and blow the context budget.
    - **The query is embedded once.** The dense vector is identical across the per-company
      searches, and that round trip is what dominates retrieval latency.
    - **Suppression runs per company, before the merge.** Over a merged set it can delete a
      company's entire quota, and that failure looks exactly like the imbalance quotas exist
      to fix.
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
