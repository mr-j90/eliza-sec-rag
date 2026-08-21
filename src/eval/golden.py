"""The golden set: questions, their labels, and the loader both consumers share.

SPEC §7.1 fixes the shape — 6 single-company, 8 cross-company, 5 temporal, 3 sector, 3
unanswerable — and permits `source_file` + section labels rather than chunk ids, which is what
this uses. Chunk-level labels would be more precise and would also depend on the current
chunker, so a chunking change would silently move the ground truth.

**Labels are derived from the corpus, never from retrieval output.** Each answerable question
records the `probe` term its labels came from, and `eval/build_golden_set.py` regenerates the
file by reading the filings. A test re-derives every label at run time, so a label that cannot
be reproduced from the corpus fails rather than lingering. That is the difference between a
golden set and a fixture: labels written by looking at what the current system returns would
make every downstream metric a measure of how closely a configuration reproduces today's
behaviour.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from src.config import REPO_ROOT

GOLDEN_SET = REPO_ROOT / "eval" / "golden_set.json"

CATEGORIES = {
    "single_company": 6,
    "cross_company": 8,
    "temporal": 5,
    "sector": 3,
    "unanswerable": 3,
}


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    category: str
    question: str
    tickers: list[str] = field(default_factory=list)
    """Companies the question is about. Empty for sector and unanswerable questions."""

    source_files: list[str] = field(default_factory=list)
    """Filings that should be retrieved. Empty for unanswerable questions."""

    sections: list[str] = field(default_factory=list)
    """Item sections expected to carry the answer, where the question implies one."""

    probe: str | None = None
    """The corpus term the labels were derived from. None only for unanswerable questions."""

    absent: list[str] = field(default_factory=list)
    """Companies named that the corpus does not hold — the refusal cases."""

    expect_fiscal_years: list[int] = field(default_factory=list)
    """Inclusive `[from, to]` window a temporal question asks about, **hand-written**.

    Deliberately not derived from `src/query.py`: a label built by our own parser would agree
    with a parser bug, and the metric would score the bug as correct. The harness reports
    whether the parser derived the same window, which turns the coupling into an observation.
    """

    note: str = ""
    """Why these labels are the right answer, for a reader auditing rather than trusting."""

    @property
    def is_unanswerable(self) -> bool:
        return self.category == "unanswerable"


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> tuple[GoldenQuestion, ...]:
    """The golden set. Every field is optional bar `id`/`category`/`question`, so the JSON
    maps straight onto the dataclass — a key mismatch fails here rather than silently
    dropping a label."""
    raw = json.loads((path or GOLDEN_SET).read_text(encoding="utf-8"))
    return tuple(GoldenQuestion(**q) for q in raw["questions"])


def by_category(category: str) -> list[GoldenQuestion]:
    return [q for q in load() if q.category == category]
