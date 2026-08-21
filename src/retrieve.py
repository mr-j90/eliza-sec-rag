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

    The pipeline is fetch-deep, bound, rerank, spread — each step is a constant above with its
    measurement. Fusion fetches `k * CANDIDATE_POOL` candidates because the filings a spread-out
    question needs rank deep in fusion; the rerank input is then cut to `RERANK_CAP` *file-
    diverse* chunks so the cross-encoder still sees a chunk from each deep-ranked filing without
    being handed the whole pool; and the final cut spreads k across filings (`PER_FILE_CAP`).
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

    A 10-Q's Item 1A carries only *material changes* from the 10-K. Measured, a question
    scoped to quarterly filings ("What are Tesla's quarterly risk factors?") retrieved **7
    chunks and 5,372 tokens** of amendments with no baseline at all, and Pfizer's case was **1
    chunk, 562 tokens** — presented as a complete risk profile against an annual section past
    10,000 tokens.

    Note this is a *narrow* trigger, not a general problem: with no form filter the 10-K's
    Item 1A is ~5x larger and so yields ~5x more chunks, and it dominates retrieval naturally.
    The failure only appears when the question's own wording restricts the form. So the filter
    is relaxed for exactly that case rather than the quota design being reworked.

    Widening a scope the user asked for needs justifying: the reader asked about quarterly
    filings and gets some annual passages. It is the right trade because the alternative is an
    answer that is confidently incomplete, and because the annual passages are labelled — the
    prompt says which are baseline and which are amendments (v7), so a "new this quarter"
    claim cannot be made about a long-standing risk.
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
