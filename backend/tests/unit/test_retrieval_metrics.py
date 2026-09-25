import pytest

from app.evaluation.retrieval_metrics import (
    hit_rate_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

RETRIEVED = ["c9", "c2", "c7", "c1", "c5"]
RELEVANT = {"c2", "c1"}


def test_recall_and_precision():
    assert recall_at_k(RETRIEVED, RELEVANT, 3) == 0.5
    assert recall_at_k(RETRIEVED, RELEVANT, 5) == 1.0
    assert precision_at_k(RETRIEVED, RELEVANT, 5) == pytest.approx(0.4)


def test_hit_rate_and_mrr():
    assert hit_rate_at_k(RETRIEVED, RELEVANT, 1) == 0.0
    assert hit_rate_at_k(RETRIEVED, RELEVANT, 2) == 1.0
    assert reciprocal_rank(RETRIEVED, RELEVANT) == 0.5


def test_ndcg_perfect_and_partial():
    assert ndcg_at_k(["c2", "c1", "x"], RELEVANT, 3) == pytest.approx(1.0)
    assert 0 < ndcg_at_k(RETRIEVED, RELEVANT, 5) < 1
