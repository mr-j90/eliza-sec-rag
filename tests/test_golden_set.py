"""The golden set's integrity — including that its labels can be re-derived from the corpus.

The point of these tests is not that the file parses. It is that the labels are **auditable**:
a golden set whose ground truth cannot be reproduced from the corpus is a fixture, and every
metric computed over it measures how closely a configuration reproduces whatever produced the
labels.
"""

import re

from src.aliases import by_ticker, resolve
from src.config import settings
from src.eval.golden import CATEGORIES, GoldenQuestion, load


def questions() -> tuple[GoldenQuestion, ...]:
    return load()


def test_the_set_matches_the_shape_spec_fixes():
    """SPEC §7.1's counts, exactly: 6 single-company, 8 cross-company, 5 temporal, 3 sector,
    3 unanswerable. The three unanswerable ones are the point, not padding."""
    counts: dict[str, int] = {}
    for question in questions():
        counts[question.category] = counts.get(question.category, 0) + 1
    assert counts == CATEGORIES, f"expected {CATEGORIES}, got {counts}"


def test_ids_are_unique_and_questions_are_real():
    ids = [q.id for q in questions()]
    assert len(ids) == len(set(ids)), "duplicate question ids"
    for question in questions():
        assert len(question.question) > 20, f"{question.id} is not a question: {question.question!r}"
        # Not all of them are interrogative — "Compare X and Y." is how people actually ask,
        # and requiring a question mark would have rejected valid prompts. The assertion that
        # earns its place is that the text is complete rather than truncated.
        assert question.question[-1] in "?.", f"{question.id} looks truncated: {question.question!r}"
        assert question.note, f"{question.id} has no note explaining its labels"


def test_every_labelled_filing_exists_and_every_ticker_is_in_the_corpus():
    corpus = {p.name for p in settings().corpus_dir.glob("*.txt")}
    known = set(by_ticker())
    for question in questions():
        for name in question.source_files:
            assert name in corpus, f"{question.id} labels a filing that does not exist: {name}"
        for ticker in question.tickers:
            assert ticker in known, f"{question.id} names a ticker not in the corpus: {ticker}"


def test_every_answerable_question_has_labels():
    for question in questions():
        if question.is_unanswerable:
            assert not question.source_files, f"{question.id} is unanswerable but has labels"
            assert question.absent, f"{question.id} is unanswerable but names no absent company"
        else:
            assert question.source_files, f"{question.id} has no labelled sources"
            assert question.probe, f"{question.id} has no probe, so its labels cannot be audited"


def test_every_label_can_be_re_derived_from_the_corpus():
    """The signal that matters. Each labelled filing must genuinely contain the probe.

    This is what separates a golden set from a fixture: run it and the ground truth either
    reproduces from the filings or it doesn't. A label that cannot be re-derived is a label
    somebody wrote by looking at output.
    """
    failures = []
    for question in questions():
        if question.is_unanswerable:
            continue
        pattern = re.compile(re.escape(question.probe or ""), re.IGNORECASE)
        for name in question.source_files:
            text = (settings().corpus_dir / name).read_text(encoding="utf-8", errors="replace")
            if not pattern.search(text):
                failures.append((question.id, name, question.probe))
    assert not failures, f"labels that do not contain their probe: {failures[:5]}"


def test_labels_restricted_to_named_tickers_stay_restricted():
    """A question naming companies must not label another company's filing."""
    for question in questions():
        if not question.tickers:
            continue
        for name in question.source_files:
            ticker = name.split("_")[0]
            assert ticker in question.tickers, (
                f"{question.id} names {question.tickers} but labels a {ticker} filing"
            )


def test_the_unanswerable_questions_are_genuinely_unanswerable():
    """A trick question whose subject is actually in the corpus would score a correct answer
    as a failure — which would make the refusal metric worse than useless."""
    for question in questions():
        if not question.is_unanswerable:
            continue
        for company in question.absent:
            assert resolve(company) is None, (
                f"{question.id} claims {company} is absent, but it resolves to {resolve(company)}"
            )
        assert not question.tickers, f"{question.id} is unanswerable but names corpus tickers"


def test_no_label_covers_so_much_of_the_corpus_that_it_measures_nothing():
    """A probe matching half the corpus makes recall structurally tiny.

    Measured while building: "allowance for credit losses" matched 111 of 246 filings and
    "data center" 89. Both were narrowed. This keeps that from creeping back.
    """
    total = len(list(settings().corpus_dir.glob("*.txt")))
    oversized = [
        (q.id, len(q.source_files))
        for q in questions()
        if len(q.source_files) > total * 0.25
    ]
    assert not oversized, f"labels covering >25% of the corpus: {oversized}"


def test_the_set_is_loaded_through_one_typed_loader():
    """Two parsers of one file diverge. The metrics harness and the ablation share this."""
    for question in questions():
        assert isinstance(question, GoldenQuestion)
        assert isinstance(question.source_files, list)
        assert isinstance(question.tickers, list)
