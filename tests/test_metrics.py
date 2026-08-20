"""Retrieval metrics, proved on hand-worked examples.

Every expected value below is computed **by hand in the comment**, not by calling the
implementation. A metric tested against its own output agrees with itself and proves nothing —
which is the easiest mistake to make with nDCG in particular.
"""

import math

from src.eval.metrics import dcg, entity_coverage_at_k, mrr_at_k, ndcg_at_k, recall_at_k


def test_recall_is_the_fraction_of_relevant_items_found():
    relevant = {"a.txt", "b.txt", "c.txt", "d.txt"}
    retrieved = ["a.txt", "x.txt", "c.txt", "y.txt"]
    # 2 of 4 relevant files appear -> 0.5
    assert recall_at_k(retrieved, relevant, k=4) == 0.5
    # truncated to k=2: only a.txt -> 1/4
    assert recall_at_k(retrieved, relevant, k=2) == 0.25


def test_recall_is_zero_when_nothing_relevant_is_found_and_one_when_all_is():
    relevant = {"a.txt"}
    assert recall_at_k(["x.txt", "y.txt"], relevant, k=10) == 0.0
    assert recall_at_k(["a.txt"], relevant, k=10) == 1.0


def test_recall_counts_distinct_files_not_repeated_hits():
    """Twenty chunks from one file is one file of coverage, not twenty."""
    relevant = {"a.txt", "b.txt"}
    assert recall_at_k(["a.txt"] * 20, relevant, k=20) == 0.5


def test_mrr_is_the_reciprocal_of_the_first_relevant_rank():
    relevant = {"c.txt"}
    # first relevant at position 3 -> 1/3
    assert mrr_at_k(["a.txt", "b.txt", "c.txt"], relevant, k=10) == 1 / 3
    # first position -> 1.0
    assert mrr_at_k(["c.txt", "a.txt"], relevant, k=10) == 1.0
    # not found within k -> 0.0
    assert mrr_at_k(["a.txt", "b.txt"], relevant, k=2) == 0.0


def test_dcg_discounts_by_log_of_rank():
    # gains [1, 0, 1] -> 1/log2(2) + 0 + 1/log2(4) = 1.0 + 0.5 = 1.5
    assert dcg([1, 0, 1]) == 1.5


def test_ndcg_is_dcg_over_the_ideal_ordering():
    relevant = {"a.txt", "b.txt"}
    retrieved = ["x.txt", "a.txt", "b.txt"]
    # DCG  = 0 + 1/log2(3) + 1/log2(4) = 0.63093 + 0.5      = 1.13093
    # IDCG = 1/log2(2) + 1/log2(3)     = 1.0     + 0.63093  = 1.63093
    expected = (1 / math.log2(3) + 0.5) / (1.0 + 1 / math.log2(3))
    assert abs(ndcg_at_k(retrieved, relevant, k=3) - expected) < 1e-9
    # perfect ordering scores exactly 1
    assert abs(ndcg_at_k(["a.txt", "b.txt"], relevant, k=3) - 1.0) < 1e-9


def test_entity_coverage_is_the_fraction_of_named_companies_reached():
    # two of three named companies appear among the retrieved tickers -> 2/3
    assert entity_coverage_at_k(["AAPL", "AAPL", "TSLA"], ["AAPL", "TSLA", "JPM"], k=10) == 2 / 3
    assert entity_coverage_at_k(["AAPL"], ["AAPL"], k=10) == 1.0
    assert entity_coverage_at_k(["MSFT"], ["AAPL"], k=10) == 0.0


def test_entity_coverage_is_undefined_when_the_question_names_nobody():
    """Sector and unanswerable questions name no company. Returning 0.0 would drag every
    average down and mean nothing; None keeps them out of the aggregate."""
    assert entity_coverage_at_k(["AAPL"], [], k=10) is None
