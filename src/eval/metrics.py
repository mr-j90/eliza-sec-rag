"""Retrieval metrics over the golden set — SPEC §7.2.

    uv run python -m src.eval.metrics

`Recall@k`, `MRR@10`, `nDCG@10` and `entity_coverage@k`. Relevance is **file-level**, per
SPEC §7.1: a retrieved chunk contributes its `source_file`, and recall counts distinct
files. Twenty chunks from one filing is one filing of coverage.

Two shapes here exist because the naive version would have been misleading:

- **Unanswerable questions are excluded** and counted separately. They have no relevant filings,
  so recall over them is undefined; averaging a zero in would understate every configuration
  equally and say nothing about any of them.
- **`entity_coverage@k` returns None where the question names no company.** Sector questions name
  none by design, and scoring them 0.0 would drag the average down for behaviour that is correct.
"""

from __future__ import annotations

import json
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from src.config import REPO_ROOT
from src.eval.golden import GoldenQuestion, load
from src.query import plan
from src.retrieve import Retrieved, retrieve_for

RESULTS_DIR = REPO_ROOT / "eval" / "results"
RECALL_KS = (5, 10, 20)
RANK_K = 10
# `entity_coverage` is reported at the **retrieval budget**, not at 10, because the model is
# given the entire retrieved set — there is no "top 10" from the answer's point of view.
# Measured 2026-08-19: coverage@10 was 0.50-0.67 on every cross-company question while
# coverage@20 was 1.0, purely because results are ordered company-then-section (SPEC §5.3), so
# the third company sits at ranks 13-18. Reporting only @10 would have understated the very
# effect this metric exists to demonstrate.
COVERAGE_KS = (10, 20)


def _files(retrieved: list[str], k: int) -> list[str]:
    """Distinct source files in rank order, first occurrence wins."""
    seen: list[str] = []
    for name in retrieved[:k]:
        if name not in seen:
            seen.append(name)
    return seen


def normalized_recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """`hits / min(k, |R|)` — recall against what was *attainable*, not against 1.0.

    The only one of the audit's three metric fixes implemented here, because without it the
    headline number is actively misleading rather than merely limited. Relevant-file counts in
    this golden set run from **1 to 36**, so raw `recall@5` has a per-question ceiling between
    **0.139 and 1.000** — on `cc-01` no configuration change can move it by more than 0.139 in
    absolute terms. Averaging raw recall across those questions averages incommensurable
    quantities, and the mean is then dominated by label cardinality rather than by retrieval.

    Reported alongside raw recall rather than replacing it, so the two can be compared and the
    gap between them is itself visible.
    """
    if not relevant:
        return 0.0
    attainable = min(k, len(relevant))
    hits = len(set(_files(retrieved, k)) & relevant)
    return hits / attainable if attainable else 0.0


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    found = set(_files(retrieved, k)) & relevant
    return len(found) / len(relevant)


def mrr_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    for position, name in enumerate(_files(retrieved, k), start=1):
        if name in relevant:
            return 1 / position
    return 0.0


def dcg(gains: list[int]) -> float:
    return sum(g / math.log2(rank + 1) for rank, g in enumerate(gains, start=1))


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    ranked = _files(retrieved, k)
    gains = [1 if name in relevant else 0 for name in ranked]
    ideal = [1] * min(len(relevant), max(len(ranked), 1))
    best = dcg(ideal)
    return dcg(gains) / best if best else 0.0


def entity_coverage_at_k(
    retrieved_tickers: list[str], named: list[str], k: int
) -> float | None:
    """SPEC §7.2's custom metric: how many of the companies asked about were reached.

    None — not 0.0 — when the question names nobody. This is the metric that explains to a
    business audience why per-entity quotas were necessary, and a meaningless zero from every
    sector question would bury the effect it exists to show.
    """
    if not named:
        return None
    reached = set(retrieved_tickers[:k])
    return len([t for t in named if t in reached]) / len(named)


@dataclass
class QuestionResult:
    id: str
    category: str
    recall: dict[int, float] = field(default_factory=dict)
    # `hits / min(k, |R|)` — see `normalized_recall_at_k`. Carried alongside raw recall so the
    # gap between "what we got" and "what the labels allowed" is visible per question.
    normalized_recall: dict[int, float] = field(default_factory=dict)
    mrr: float = 0.0
    ndcg: float = 0.0
    entity_coverage: dict[int, float | None] = field(default_factory=dict)
    n_relevant: int = 0
    n_files_retrieved: int = 0
    parser_window_agrees: bool | None = None
    suspect: str = ""
    """Set when a number looks wrong, naming what is suspected."""


def score_question(
    question: GoldenQuestion, results: list[Retrieved]
) -> QuestionResult:
    files = [r.chunk.source_file for r in results]
    tickers = [r.chunk.ticker for r in results]
    relevant = set(question.source_files)

    out = QuestionResult(
        id=question.id,
        category=question.category,
        n_relevant=len(relevant),
        n_files_retrieved=len(set(files)),
        recall={k: recall_at_k(files, relevant, k) for k in RECALL_KS},
        normalized_recall={k: normalized_recall_at_k(files, relevant, k) for k in RECALL_KS},
        mrr=mrr_at_k(files, relevant, RANK_K),
        ndcg=ndcg_at_k(files, relevant, RANK_K),
        entity_coverage={
            k: entity_coverage_at_k(tickers, question.tickers, k) for k in COVERAGE_KS
        },
    )

    # Report whether our own parser agrees with the hand-written window, rather than using the
    # parser to build the label. A label derived from the parser would agree with a parser bug.
    if question.expect_fiscal_years:
        derived = plan(question.question).fiscal_years
        out.parser_window_agrees = derived == tuple(question.expect_fiscal_years)

    if out.recall[RANK_K] == 0.0:
        # A zero must be explained, not published bare. Distinguishing "retrieval
        # missed" from "the label is unreachable at this k" is the useful part.
        if out.n_files_retrieved and len(relevant) > out.n_files_retrieved * 2:
            out.suspect = (
                f"label spans {len(relevant)} filings but only {out.n_files_retrieved} distinct "
                f"files fit in k={RANK_K}; suspect label breadth rather than retrieval"
            )
        else:
            out.suspect = "retrieval returned no labelled filing; suspect retrieval or the probe"
    return out


def _config_label() -> str:
    """What actually ran, so two result files cannot be confused for each other."""
    from src.config import settings

    base = "hybrid+quotas+prefix"
    return f"{base}+rerank" if settings().rerank_enabled else base


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 4) if values else None


def aggregate(scored: list[QuestionResult]) -> dict:
    def over(rows: list[QuestionResult]) -> dict:
        coverage = {
            k: [r.entity_coverage[k] for r in rows if r.entity_coverage.get(k) is not None]
            for k in COVERAGE_KS
        }
        return {
            "n": len(rows),
            **{f"recall@{k}": _mean([r.recall[k] for r in rows]) for k in RECALL_KS},
            **{
                f"normalized_recall@{k}": _mean([r.normalized_recall[k] for r in rows])
                for k in RECALL_KS
            },
            f"mrr@{RANK_K}": _mean([r.mrr for r in rows]),
            f"ndcg@{RANK_K}": _mean([r.ndcg for r in rows]),
            **{f"entity_coverage@{k}": _mean(coverage[k]) for k in COVERAGE_KS},
            "entity_coverage_n": len(coverage[COVERAGE_KS[-1]]),
        }

    categories = sorted({r.category for r in scored})
    return {
        "overall": over(scored),
        "by_category": {c: over([r for r in scored if r.category == c]) for c in categories},
    }


def run(
    retriever: Callable[[str, int], list[Retrieved]] = retrieve_for,
    *,
    k: int = 20,
    label: str | None = None,
) -> dict:
    """Score every answerable golden question. Returns the results document."""
    questions = load()
    answerable = [q for q in questions if not q.is_unanswerable]
    unanswerable = [q for q in questions if q.is_unanswerable]

    scored = [score_question(q, retriever(q.question, k)) for q in answerable]

    return {
        "config": label or _config_label(),
        "k": k,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_scored": len(scored),
        "n_unanswerable": len(unanswerable),
        "unanswerable_ids": [q.id for q in unanswerable],
        "note": (
            "Relevance is file-level (SPEC §7.1). Unanswerable questions are excluded from "
            "retrieval metrics — they have no relevant filings, so recall over them is "
            "undefined. entity_coverage is averaged only over questions that name a company, "
            "and is reported at both 10 and the retrieval budget: results are ordered "
            "company-then-section (SPEC §5.3), so a third named company sits at ranks 13-18 "
            "and any prefix metric below the budget reflects that ordering rather than "
            "retrieval. The model receives the whole retrieved set, so the budget figure is "
            "the one that corresponds to observable behaviour."
        ),
        **aggregate(scored),
        "per_question": [
            {
                "id": r.id,
                "category": r.category,
                **{f"recall@{k_}": round(v, 4) for k_, v in r.recall.items()},
                **{
                    f"normalized_recall@{k_}": round(v, 4)
                    for k_, v in r.normalized_recall.items()
                },
                f"mrr@{RANK_K}": round(r.mrr, 4),
                f"ndcg@{RANK_K}": round(r.ndcg, 4),
                **{
                    f"entity_coverage@{k}": (
                        round(r.entity_coverage[k], 4)
                        if r.entity_coverage.get(k) is not None
                        else None
                    )
                    for k in COVERAGE_KS
                },
                "n_relevant": r.n_relevant,
                "n_files_retrieved": r.n_files_retrieved,
                "parser_window_agrees": r.parser_window_agrees,
                "suspect": r.suspect,
            }
            for r in scored
        ],
    }


def _run_filename(document: dict) -> str:
    """`2026-08-20T115103Z--hybrid-quotas-prefix-rerank.json`.

    Timestamp first so a directory listing sorts chronologically, config second so two runs are
    distinguishable at a glance. Both are already in the document; this only makes them findable
    without opening every file.
    """
    stamp = str(document.get("generated_at", "")).replace(":", "").replace("-", "")[:15]
    config = re.sub(r"[^a-z0-9]+", "-", str(document.get("config", "run")).lower()).strip("-")
    return f"{stamp or 'unknown'}--{config}.json"


def main(argv: list[str]) -> int:
    document = run()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # One file per run, never overwritten. Comparing configurations is the whole point of this
    # harness — docs/EVALUATION.md's tables are all before/after — and a single overwritten file
    # makes that impossible without copying results out by hand between runs, which is what was
    # happening. `latest.json` is kept as a stable path for anything that wants the newest.
    (RESULTS_DIR / _run_filename(document)).write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    (RESULTS_DIR / "latest.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )

    overall = document["overall"]
    print(f"config: {document['config']}  k={document['k']}", flush=True)
    print(
        f"  scored {document['n_scored']} answerable "
        f"({document['n_unanswerable']} unanswerable excluded)",
        flush=True,
    )
    for key in (f"normalized_recall@{k}" for k in RECALL_KS):
        print(f"  {key:24s} {overall[key]}", flush=True)
    for key in (f"recall@{k}" for k in RECALL_KS):
        print(f"  {key:24s} {overall[key]}", flush=True)
    print(f"  mrr@{RANK_K:<21d} {overall[f'mrr@{RANK_K}']}", flush=True)
    print(f"  ndcg@{RANK_K:<20d} {overall[f'ndcg@{RANK_K}']}", flush=True)
    for k in COVERAGE_KS:
        suffix = " <- the budget the model actually sees" if k == COVERAGE_KS[-1] else ""
        print(f"  entity_coverage@{k:<9d} {overall[f'entity_coverage@{k}']}{suffix}", flush=True)
    print(
        f"  (coverage over {overall['entity_coverage_n']} questions naming a company)",
        flush=True,
    )
    suspects = [q for q in document["per_question"] if q["suspect"]]
    if suspects:
        print(f"\n  {len(suspects)} question(s) scored 0 recall@{RANK_K}:", flush=True)
        for q in suspects:
            print(f"    {q['id']}: {q['suspect']}", flush=True)
    print(f"\nwrote {RESULTS_DIR / _run_filename(document)} (and latest.json)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
