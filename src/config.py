"""Runtime configuration.

Values come from the process environment, with a `.env` file at the repo root as
a fallback for local runs. Ambient environment always wins — `load_dotenv` is not
allowed to override it — so a value exported in CI or a shell is never silently
replaced by a stale file.

`.env` is gitignored and must stay that way. Nothing in this repo commits a
secret; the file exists so a local process gets the key deterministically instead
of depending on which shell profile happened to load.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# override=False: a real environment variable beats the file, every time.
load_dotenv(REPO_ROOT / ".env", override=False)

# The backend owns generation, so this is the single source of truth for which model
# answers and the frontend names none. That split is what makes the one-call constraint
# checkable by grep rather than by trust: no provider SDK is imported browser-side at all.
DEFAULT_GENERATION_MODEL = "gpt-4.1"

# SPEC §2: dense embeddings are text-embedding-3-small, 1536d, cosine.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DENSE_DIM = 1536

# SPEC §2: BM25 sparse vectors via FastEmbed, in the *same* collection as dense.
SPARSE_MODEL = "Qdrant/bm25"

# Cross-encoder reranker, run locally through FastEmbed like the BM25 leg — no API, no key.
# apache-2.0, 0.08 GB, fastest of four candidates at 328 ms for 20 passages. Chosen on latency
# and licence, not window: see `src/rerank.py` for the measured 512-token truncation.
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

# The RRF ranking constant, set **explicitly** rather than inherited from Qdrant's default of 2
# — see `retrieve.build_hybrid_query`. `RAG_RRF_K` overrides it, which ran the 2/10/60/100 sweep
# in docs/EVALUATION.md was run.
DEFAULT_RRF_K = 60

COLLECTION = "filings"

# The host port our own compose service binds. Deliberately not 6333: another project on
# this machine has run a Qdrant there, and colliding fails silently — a client connects
# happily and creates its collection inside a stranger's instance.
DEFAULT_QDRANT_URL = "http://127.0.0.1:6533"

# A default index run covers this one filing; `--all` covers all 246.
SEED_FILING = "AAPL_10K_2025-10-31_full.txt"


@dataclass(frozen=True)
class Settings:
    generation_model: str
    embedding_model: str
    qdrant_url: str
    collection: str
    corpus_dir: Path
    openai_api_key: str | None
    openai_base_url: str | None
    # `RAG_RERANK=0` turns the cross-encoder off. It exists so "does reranking help?" is a
    # measurement rather than an assertion — §7's ablation needs the row it cannot otherwise
    # produce, and the answer turned out to be interesting (see docs/EVALUATION.md).
    rerank_enabled: bool
    rrf_k: int

    @property
    def provider_configured(self) -> bool:
        """A base URL alone is enough — a local OpenAI-compatible server ignores
        the key even though the SDK insists on some value."""
        return bool(self.openai_api_key or self.openai_base_url)


def _env(name: str) -> str | None:
    return (os.environ.get(name) or "").strip() or None


@lru_cache(maxsize=1)
def settings() -> Settings:
    corpus = _env("RAG_CORPUS_DIR")
    return Settings(
        generation_model=_env("RAG_GENERATION_MODEL") or DEFAULT_GENERATION_MODEL,
        embedding_model=_env("RAG_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL,
        qdrant_url=_env("QDRANT_URL") or DEFAULT_QDRANT_URL,
        collection=_env("RAG_COLLECTION") or COLLECTION,
        corpus_dir=Path(corpus) if corpus else REPO_ROOT / "edgar_corpus",
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_base_url=_env("OPENAI_BASE_URL"),
        rerank_enabled=(_env("RAG_RERANK") or "1") not in {"0", "false", "no"},
        rrf_k=int(_env("RAG_RRF_K") or DEFAULT_RRF_K),
    )
