"""FastAPI surface — SPEC §8.

`POST /ask` is the seam the answer path is verified through, and the only place an answer is
produced. `GET /health` reports which model would answer and whether the index is reachable,
so the frontend can label the UI from the backend rather than keeping a second, driftable
copy of the same fact.

The provider and the retriever are injected so the shape-and-one-call tests run offline against
substitutes; live retrieval behaviour is exercised in `tests/test_retrieve.py`.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from src import index, prompt
from src.coverage import Coverage, coverage_of
from src.verify import CitationCheck, verify_citations
from src.config import settings
from src.llm import LLM, ProviderNotConfigured, build_llm
from src.query import QueryPlan, fiscal_year_range, plan
from src.retrieve import Retrieved, retrieval_description, retrieve_for

app = FastAPI(title="SEC Filings RAG", version="0.2.0")


class Retriever(Protocol):
    def __call__(self, question: str, k: int = ...) -> list[Retrieved]: ...


def get_llm() -> LLM:
    """The provider, as a dependency so tests can substitute and count it."""
    return build_llm()


def get_retriever() -> Retriever:
    return retrieve_for


def get_index_size() -> int:
    """Points in the collection — 0 when the index is empty *or* unreachable.

    Injected for the same reason the provider and retriever are: it is what tells an empty
    index apart from a query whose filters excluded everything, and the two need opposite
    responses. `index.count()` already returns 0 for an unreachable Qdrant, and both cases
    mean the same thing to a caller: there is nothing to answer from and the operator has to
    act.
    """
    return index.count()


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


def _meta(
    query_plan: QueryPlan,
    *,
    n_chunks: int,
    coverage: Coverage,
    check: CitationCheck,
    latency: dict[str, float],
    generated: bool,
    top_score: float | None = None,
) -> dict[str, Any]:
    """`retrieval_meta`, in one place so the answering and no-match paths cannot drift.

    `entities_detected` is SPEC §8's field: tickers in the order the question named them.
    `unresolved_mentions` are capitalised names that look like companies but are not in this
    corpus — heuristic, and only ever used to explain a refusal.

    `generated=False` omits `generation_model`, because nothing generated that answer. The
    field is what the UI labels an answer with, and labelling a refusal with a model that was
    never called would be the same class of lie the citation contract exists to prevent.
    """
    meta: dict[str, Any] = {
        "entities_detected": query_plan.companies,
        "unresolved_mentions": query_plan.unresolved_mentions,
        "fiscal_years": list(query_plan.fiscal_years) if query_plan.fiscal_years else None,
        "form_type": query_plan.form_type,
        "n_chunks": n_chunks,
        "coverage": coverage.as_dict(),
        "citation_check": check.as_dict(),
        "prompt_version": prompt.PROMPT_VERSION,
        "retrieval": retrieval_description(),
        "latency_ms": latency,
    }
    if generated:
        meta["generation_model"] = settings().generation_model
    if top_score is not None:
        meta["top_score"] = round(top_score, 4)
    return meta


@app.post("/ask")
def ask(
    request: AskRequest,
    llm: Annotated[LLM, Depends(get_llm)],
    retriever: Annotated[Retriever, Depends(get_retriever)],
    index_size: Annotated[int, Depends(get_index_size)],
) -> dict[str, Any]:
    started = time.perf_counter()

    # Rule-based, no model call — SPEC §5.2. Computed here as well as inside the retriever so
    # the response can report what was understood; `plan` is pure and cached, so this costs
    # nothing and keeps the retriever swappable in tests.
    query_plan = plan(request.question)
    results = retriever(request.question, k=request.top_k)
    retrieved_at = time.perf_counter()

    if not results:
        # Two failures used to share one message, and it named the wrong one: an empty result
        # with a populated index means the question's own scope excluded everything, and telling
        # that reader to rebuild the index sends them after a problem they do not have.
        if index_size == 0:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Nothing was retrieved and the index is empty or unreachable — build it "
                    "with `uv run python -m src.index` and check Qdrant is up."
                ),
            )
        return _no_matches(query_plan, started, retrieved_at)

    chunks = [result.chunk for result in results]

    # Computed once, used twice — see `src/coverage.py`.
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

    cited = prompt.citations(chunks)
    # Checked, not trusted. A handle that resolves to nothing is a false claim of groundedness,
    # which is worse than no citation — and the count the UI shows should be a verified one.
    check = verify_citations(answer, [c.id for c in cited])

    return {
        "answer": answer,
        "citations": [asdict(citation) for citation in cited],
        "retrieval_meta": _meta(
            query_plan,
            n_chunks=len(chunks),
            coverage=coverage,
            check=check,
            generated=True,
            top_score=results[0].score,
            latency={
                "retrieval": round((retrieved_at - started) * 1000, 1),
                "generation": round((finished - retrieved_at) * 1000, 1),
                "total": round((finished - started) * 1000, 1),
            },
        ),
    }


def _no_matches(
    query_plan: QueryPlan,
    started: float,
    retrieved_at: float,
) -> dict[str, Any]:
    """A 200 with a refusal, not a 5xx — the request was well-formed and answered honestly.

    Deliberately **no LLM call**: with zero passages there is nothing to ground an answer in,
    so a generated one could only come from the model's own knowledge of these companies,
    which is what rule 1 of the system prompt forbids. `retrieval_meta` keeps the same shape
    the answering path returns, so the UI renders this like any other answer — `n_chunks: 0`
    and an empty citation list are the honest values, not missing ones.
    """
    answer = prompt.no_matches_answer(
        companies=query_plan.companies,
        fiscal_years=query_plan.fiscal_years,
        form_type=query_plan.form_type,
        corpus_years=fiscal_year_range(),
    )
    return {
        "answer": answer,
        "citations": [],
        "retrieval_meta": {
            **_meta(
                query_plan,
                n_chunks=0,
                coverage=coverage_of([], named=query_plan.companies),
                # Vacuously verified, and true: no handle was written, so none can be fabricated.
                check=verify_citations(answer, []),
                generated=False,
                latency={
                    "retrieval": round((retrieved_at - started) * 1000, 1),
                    "generation": 0.0,
                    "total": round((retrieved_at - started) * 1000, 1),
                },
            ),
            "no_matches": True,
        },
    }


@app.exception_handler(ProviderNotConfigured)
def provider_not_configured(_request: Any, exc: ProviderNotConfigured):
    """503 with the reason, never a plausible-looking answer."""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=503, content={"detail": str(exc)})
