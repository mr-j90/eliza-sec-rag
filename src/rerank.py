"""Cross-encoder reranking of the overfetched candidate set.

Fusion ranks a chunk without ever comparing it to the question directly — RRF only sees two
rank lists. A cross-encoder reads the question and the passage **together**, which is why it
is the largest single retrieval-quality gain available, and why it belongs on the candidates
rather than on the final answer.

Runs **locally** via FastEmbed's ONNX runtime — no API call, no key, no per-query cost, same
as the BM25 leg. It is not an LLM call and does not touch the one-call constraint: it scores
candidates before the single generation call, exactly as embedding does.

**The 512-token window is measured, not read off a model card.** A marker sentence at token
300 changes the score; the same sentence at token 600 changes it by exactly 0.0000 — for every
reranker FastEmbed exposes, `jina-reranker-v1-turbo-en` included despite its advertised 8192.
Indexed chunks are median **715** tokens and 74.5% exceed 512, so **26.8% of indexed text is
invisible to the reranker**. Accepted deliberately: the reranker orders candidates rather than
reading them (the full chunk still reaches the generation call), and since reflow those first
512 tokens are a coherent opening rather than an arbitrary window. Re-chunking at ~480 tokens
was the alternative, and it cuts Item 1A mid-risk-factor — measured median risk factor 607
tokens, and 17 CFR 229.105(a) makes that the one place a regulator defines the unit.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from src.config import RERANK_MODEL

logger = logging.getLogger(__name__)

# How the retrieval path describes itself in `retrieval_meta`, so a reader can tell whether
# reranking actually ran rather than having to trust that it did.
FUSION_ONLY = "hybrid dense+sparse, server-side RRF"
WITH_RERANK = f"{FUSION_ONLY} + cross-encoder rerank ({RERANK_MODEL})"


class RerankUnavailable(RuntimeError):
    """The model could not be loaded — usually a first run with no network."""


@lru_cache(maxsize=1)
def _encoder():
    """Loaded once per process. ~0.08 GB on disk, ~6 s on a cold first load."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=RERANK_MODEL)


def rerank_scores(question: str, passages: list[str]) -> list[float]:
    """One score per passage. Higher is more relevant; the scale is unbounded logits."""
    if not passages:
        return []
    try:
        return list(_encoder().rerank(question, passages))
    except Exception as error:  # noqa: BLE001
        raise RerankUnavailable(str(error)) from error


def reorder(question: str, results: list) -> tuple[list, bool]:
    """Reorder candidates by cross-encoder score. Returns `(results, reranked)`.

    Degrades to fusion order rather than failing the request, because a ranking that is merely
    *less good* is not a wrong answer — unlike a fabricated one, which is why the provider path
    refuses instead of degrading. The difference is reported: `retrieval_meta.retrieval` names
    reranking only when it actually ran, so the UI never claims a step that did not happen.

    The fusion score on each result is deliberately **left alone**. `retrieval_meta.top_score`
    has always been the fusion score and stays comparable across versions; cross-encoder logits
    are unbounded and would silently change what that number means.
    """
    if len(results) < 2:
        return results, False
    try:
        scores = rerank_scores(question, [r.chunk.text for r in results])
    except RerankUnavailable as error:
        logger.warning("reranker unavailable, falling back to fusion order: %s", error)
        return results, False

    ranked = sorted(zip(scores, results, strict=True), key=lambda pair: -pair[0])
    return [result for _, result in ranked], True
