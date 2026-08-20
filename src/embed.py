"""Dense and sparse encoders.

Dense is OpenAI `text-embedding-3-small` (1536d, cosine). Sparse is BM25 via FastEmbed,
which runs **locally** — no API call, no key — which is worth knowing because it means the
sparse half of hybrid retrieval keeps working when the provider does not.

These are embedding calls, not generation, so SPEC §5.2's one-call constraint — which is about
the call that *produces the answer* — does not cover them.
"""

from __future__ import annotations

from functools import lru_cache

from qdrant_client import models

from src.config import SPARSE_MODEL, settings

# The corpus is 20M tokens; batching keeps request sizes sane and is far faster than
# one-at-a-time when entry 4 indexes everything.
BATCH = 128


@lru_cache(maxsize=1)
def _openai():
    import openai

    config = settings()
    return openai.OpenAI(
        api_key=config.openai_api_key or "not-needed",
        base_url=config.openai_base_url,
    )


@lru_cache(maxsize=1)
def _bm25():
    from fastembed import SparseTextEmbedding

    # First use downloads an ONNX model (tens of MB) and caches it.
    return SparseTextEmbedding(model_name=SPARSE_MODEL)


def dense_vectors(texts: list[str]) -> list[list[float]]:
    """Embed a batch. Order is preserved, which the indexer relies on."""
    out: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        batch = texts[start : start + BATCH]
        response = _openai().embeddings.create(
            model=settings().embedding_model, input=batch
        )
        # The API does not promise ordered results, so sort by index rather than assume.
        out.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
    return out


def sparse_vectors(texts: list[str]) -> list[models.SparseVector]:
    """BM25 sparse vectors, computed locally."""
    return [
        models.SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
        for e in _bm25().embed(texts)
    ]


def dense_query(text: str) -> list[float]:
    return dense_vectors([text])[0]


def sparse_query(text: str) -> models.SparseVector:
    """BM25 scores queries differently from documents, hence `query_embed`."""
    embedding = next(iter(_bm25().query_embed(text)))
    return models.SparseVector(
        indices=embedding.indices.tolist(), values=embedding.values.tolist()
    )
