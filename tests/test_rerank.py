"""Cross-encoder reranking of the candidate set.

Ticket 04. The decision these tests pin is that **every reranker FastEmbed exposes truncates
at 512 tokens** — measured, not read off a model card: a marker sentence at token 300 moves
the score, and the same sentence at token 600 moves it by exactly 0.0000, for all four
candidates including `jina-reranker-v1-turbo-en`, whose card advertises 8192.

Chunks are median 715 tokens and 74.5% exceed 512, so 26.8% of indexed text does not influence
ranking. Accepted, because the reranker orders candidates rather than reading them, and because
since reflow a chunk's first 512 tokens are a coherent opening rather than an arbitrary window.

**These tests stub the encoder.** The real model is a 0.08 GB download, and `make test` is
meant to need no network — the live tier exercises the real one through `retrieve`.
"""

from __future__ import annotations

import pytest

from src.chunks import Chunk
from src.retrieve import Retrieved


def chunk(text: str, name: str = "X.txt") -> Chunk:
    return Chunk(
        chunk_id=f"c-{name}-{abs(hash(text)) % 9999}",
        text=text,
        company="Apple Inc",
        ticker="AAPL",
        cik="0000320193",
        form_type="10-K",
        fiscal_year=2025,
        period_end="2025-09-27",
        filing_date="2025-10-31",
        item_section="Item 1A — Risk Factors",
        chunk_index=0,
        source_file=name,
        token_count=len(text.split()),
    )


def results(*texts: str) -> list[Retrieved]:
    # Descending fusion scores, so any reordering is unambiguously the reranker's work.
    return [Retrieved(chunk=chunk(t), score=1.0 - i / 10) for i, t in enumerate(texts)]


# --- reordering --------------------------------------------------------------------------


def test_candidates_are_reordered_by_cross_encoder_score(monkeypatch):
    import src.rerank as rr

    monkeypatch.setattr(rr, "rerank_scores", lambda q, ps: [0.1, 9.9, 0.5])
    ranked, reranked = rr.reorder("q", results("first", "second", "third"))

    assert reranked is True
    assert [r.chunk.text for r in ranked] == ["second", "third", "first"]


def test_the_fusion_score_is_left_untouched(monkeypatch):
    """`retrieval_meta.top_score` has always been the fusion score.

    Cross-encoder outputs are unbounded logits — overwriting `.score` with one would silently
    change what that number means across versions, while looking like the same field.
    """
    import src.rerank as rr

    monkeypatch.setattr(rr, "rerank_scores", lambda q, ps: [0.1, 9.9])
    ranked, _ = rr.reorder("q", results("a", "b"))

    assert {r.score for r in ranked} == {1.0, 0.9}, "fusion scores were rewritten"
    assert all(0.0 <= r.score <= 1.0 for r in ranked)


@pytest.mark.parametrize("count", [0, 1])
def test_nothing_to_reorder_is_not_reported_as_reranked(count, monkeypatch):
    """A single candidate has no ordering to improve, so claiming it was reranked would be
    a claim about work that did not happen."""
    import src.rerank as rr

    monkeypatch.setattr(
        rr, "rerank_scores", lambda q, ps: pytest.fail("should not have been called")
    )
    ranked, reranked = rr.reorder("q", results(*["x"] * count))
    assert reranked is False
    assert len(ranked) == count


# --- degradation ------------------------------------------------------------------------


def test_an_unavailable_model_degrades_to_fusion_order(monkeypatch):
    """A worse *ordering* is not a wrong answer, unlike a fabricated one.

    The provider path refuses rather than degrading, because a canned answer that reads as
    real is dangerous. Ranking is different in kind: fusion order is still a real ranking of
    real passages. What must not happen is claiming the step ran.
    """
    import src.rerank as rr

    def boom(question, passages):
        raise rr.RerankUnavailable("no network on first run")

    monkeypatch.setattr(rr, "rerank_scores", boom)
    ranked, reranked = rr.reorder("q", results("a", "b", "c"))

    assert reranked is False
    assert [r.chunk.text for r in ranked] == ["a", "b", "c"], "fusion order must survive"


def test_the_retrieval_descriptor_names_reranking_only_when_it_ran(monkeypatch):
    """`retrieval_meta.retrieval` is rendered in the UI, so it must not advertise a step that
    silently did not happen."""
    import src.rerank as rr
    import src.retrieve as rt

    assert rr.RERANK_MODEL in rr.WITH_RERANK, "the descriptor should name the model"
    assert "rerank" not in rr.FUSION_ONLY

    monkeypatch.setattr(rt, "_LAST_RERANKED", True)
    assert "rerank" in rt.retrieval_description()

    monkeypatch.setattr(rt, "_LAST_RERANKED", False)
    assert rt.retrieval_description() == rr.FUSION_ONLY


# --- the licence trap the arch doc warned about -------------------------------------------


def test_the_configured_model_is_not_the_non_commercial_one():
    """`jina-reranker-v2-base-multilingual` is CC-BY-NC-4.0.

    It is the strongest multilingual option FastEmbed offers and it cannot be used in a
    commercial product. Pinned as a test because a future "let's try the better model" is
    exactly how a licence violation gets shipped.
    """
    from src.config import RERANK_MODEL

    assert "jina-reranker-v2" not in RERANK_MODEL, (
        "jina-reranker-v2-base-multilingual is CC-BY-NC-4.0 — not usable commercially"
    )


def test_reranking_is_not_a_generation_call():
    """The one-call constraint covers the call that *produces the answer*.

    Reranking, like embedding, is retrieval work done beforehand. Asserted by grep because
    that is how the constraint is defended in the walkthrough: no provider SDK in the
    reranking path at all.
    """
    from pathlib import Path

    source = (Path(__file__).parent.parent / "src" / "rerank.py").read_text()
    assert "openai" not in source.lower()
    assert "chat.completions" not in source
