"""Smoke test: proves the toolchain runs and the corpus sits where SPEC.md assumes."""

from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "edgar_corpus"


def test_corpus_is_present():
    assert CORPUS.is_dir(), f"corpus missing at {CORPUS}"
    # 246 filings is a measured fact recorded in CLAUDE.md; a change should be noticed.
    assert len(list(CORPUS.glob("*.txt"))) == 246
