"""Cross-encoder reranking of the overfetched candidate set.

Fusion ranks a chunk without ever comparing it to the question directly — RRF only sees two
rank lists. A cross-encoder reads the question and the passage **together**, which is why it
is the largest single retrieval-quality gain available, and why it belongs on the candidates
rather than on the final answer.

Runs **locally** via FastEmbed's ONNX runtime — no API call, no key, no per-query cost, same
as the BM25 leg. It is not an LLM call and does not touch the one-call constraint: it scores
candidates before the single generation call, exactly as embedding does.

## The 512-token window, measured

Every reranker FastEmbed exposes truncates at **512 tokens**. That was measured, not read off
a model card — a marker sentence placed at token 300 changes the score, and the same sentence
at token 600 changes it by **exactly 0.0000**, for all of them. `jina-reranker-v1-turbo-en`
advertises 8192 context and still truncates at 512 through this ONNX export, so that headline
must not be repeated in the walkthrough.

Indexed chunks are median **715** tokens and **74.5%** exceed 512, so **26.8% of all indexed
text is invisible to the reranker**. That is accepted deliberately:

- The reranker's job is to **order candidates**, not to read them. The full chunk still
  reaches the generation call untouched.
- Since reflow (§2.4), chunks begin at real block boundaries, so the first 512 tokens are a
  coherent opening carrying the topic — not an arbitrary mid-sentence window. That is what
  makes head-truncation tolerable here, and it was not true before reflow landed.
- The alternative was re-chunking at ~480 tokens, which cuts Item 1A mid-risk-factor: the
  measured median risk factor is 607 tokens, and 17 CFR 229.105(a) makes that the one place
  the chunk unit is defined by a regulator rather than by us.

`jina-reranker-v2-base-multilingual` is **CC-BY-NC-4.0** and therefore unusable commercially —
excluded on licence, not on quality.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from src.config import RERANK_MODEL

__all__ = [
    "FUSION_ONLY",
    "RERANK_MODEL",
    "WITH_RERANK",
    "RerankUnavailable",
    "available",
    "reorder",
    "rerank_scores",
]

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


def available() -> bool:
    try:
        _encoder()
        return True
    except Exception:  # noqa: BLE001 — any load failure means unavailable, and why is logged
        return False


def rerank_scores(question: str, passages: list[str]) -> list[float]:
    """One score per passage. Higher is more relevant; the scale is unbounded logits."""
    if not passages:
        return []
    try:
        return list(_encoder().rerank(question, passages))
    except Exception as error:  # noqa: BLE001
        raise RerankUnavailable(str(error)) from error


def reorder(question: str, results: list, *, on_error: str = "keep") -> tuple[list, bool]:
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
        if on_error == "raise":
            raise
        logger.warning("reranker unavailable, falling back to fusion order: %s", error)
        return results, False

    ranked = sorted(zip(scores, results, strict=True), key=lambda pair: -pair[0])
    return [result for _, result in ranked], True
