"""FastAPI surface — SPEC §8.

`POST /ask` is the seam the answer path is verified through, and the only place an answer is
produced. `GET /health` reports which model would answer and whether the index is reachable,
so the frontend can label the UI from the backend rather than keeping a second, driftable
copy of the same fact.

Both the provider and the retriever are injected as dependencies. That is not ceremony: it
lets the shape-and-one-call tests run offline against substitutes, while the live retrieval
behaviour is exercised where it belongs, in `tests/test_retrieve.py`.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from src import index, prompt
from src.coverage import coverage_of
from src.config import settings
from src.llm import LLM, ProviderNotConfigured, build_llm
from src.query import plan
from src.retrieve import Retrieved, retrieval_description, retrieve_for

app = FastAPI(title="SEC Filings RAG", version="0.2.0")


class Retriever(Protocol):
    def __call__(self, question: str, k: int = ...) -> list[Retrieved]: ...


def get_llm() -> LLM:
    """The provider, as a dependency so tests can substitute and count it."""
    return build_llm()


def get_retriever() -> Retriever:
    return retrieve_for


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=20, ge=1, le=100)

    @field_validator("question")
    @classmethod
    def not_only_whitespace(cls, value: str) -> str:
        """`min_length` cannot see whitespace, so three spaces would otherwise reach the
        provider and spend a generation call on a non-question."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        return stripped


@app.get("/health")
def health() -> dict[str, Any]:
    config = settings()
    return {
        "status": "ok",
        "generation_model": config.generation_model,
        "embedding_model": config.embedding_model,
        "provider_configured": config.provider_configured,
        "index": {
            "url": config.qdrant_url,
            "collection": config.collection,
            "reachable": index.qdrant_reachable(),
            "chunks": index.count(),
        },
    }


@app.post("/ask")
def ask(
    request: AskRequest,
    llm: Annotated[LLM, Depends(get_llm)],
    retriever: Annotated[Retriever, Depends(get_retriever)],
) -> dict[str, Any]:
    started = time.perf_counter()

    # Rule-based, no model call — SPEC §5.2. Computed here as well as inside the retriever so
    # the response can report what was understood; `plan` is pure and cached, so this costs
    # nothing and keeps the retriever swappable in tests.
    query_plan = plan(request.question)
    results = retriever(request.question, k=request.top_k)
    retrieved_at = time.perf_counter()

    if not results:
        raise HTTPException(
            status_code=503,
            detail=(
                "Nothing was retrieved. The index may be empty — build it with "
                "`uv run python -m src.index`."
            ),
        )

    chunks = [result.chunk for result in results]

    # Computed once and used twice: given to the model so its prose can hedge in proportion to
    # the evidence, and returned in `retrieval_meta` so the UI renders an authoritative copy
    # the model cannot garble. The rendered copy is the one to trust.
    coverage = coverage_of(chunks, named=query_plan.companies)

    # The one LLM call. Everything above this line is deterministic — SPEC §5.2.
    answer = llm.complete(
        system=prompt.SYSTEM,
        user=prompt.user_prompt(
            request.question,
            chunks,
            # Named but absent from this corpus. Telling the model is what makes rule 3
            # reliable rather than dependent on it noticing.
            absent=query_plan.unresolved_mentions,
            # Distinguishes "named companies, none present" (a refusal) from "named no company
            # at all" (a sector question, which must still be answered).
            named_present=query_plan.companies,
            coverage=coverage.sentence(),
        ),
    )
    finished = time.perf_counter()

    return {
        "answer": answer,
        "citations": [asdict(citation) for citation in prompt.citations(chunks)],
        "retrieval_meta": {
            # SPEC §8's field, populated at last. Tickers in the order the question named
            # them; `unresolved_mentions` are capitalised names that look like companies but
            # are not in this corpus — heuristic, and only ever used to explain a refusal.
            "entities_detected": query_plan.companies,
            "unresolved_mentions": query_plan.unresolved_mentions,
            "fiscal_years": list(query_plan.fiscal_years) if query_plan.fiscal_years else None,
            "form_type": query_plan.form_type,
            "n_chunks": len(chunks),
            "coverage": coverage.as_dict(),
            "generation_model": settings().generation_model,
            "prompt_version": prompt.PROMPT_VERSION,
            "retrieval": retrieval_description(),
            "top_score": round(results[0].score, 4),
            "latency_ms": {
                "retrieval": round((retrieved_at - started) * 1000, 1),
                "generation": round((finished - retrieved_at) * 1000, 1),
                "total": round((finished - started) * 1000, 1),
            },
        },
    }


@app.exception_handler(ProviderNotConfigured)
def provider_not_configured(_request: Any, exc: ProviderNotConfigured):
    """503 with the reason, never a plausible-looking answer."""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=503, content={"detail": str(exc)})
