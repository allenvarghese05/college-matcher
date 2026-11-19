from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

from app.retrieval.metrics import ndcg_at_k, recall_at_k

REPO = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "data"


def load_ablation():
    spec = importlib.util.spec_from_file_location("evals_ablation", REPO / "evals" / "ablation.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["evals_ablation"] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ recall


def test_recall_perfect_and_zero() -> None:
    assert recall_at_k([1, 2, 3], {1, 2, 3}, 3) == 1.0
    assert recall_at_k([4, 5, 6], {1, 2, 3}, 3) == 0.0


def test_recall_partial() -> None:
    assert recall_at_k([1, 9, 2, 8], {1, 2, 3, 4}, 4) == pytest.approx(0.5)


def test_recall_denominator_capped_at_k() -> None:
    # 20 acceptable schools, a perfect top-10 is recall 1.0
    assert recall_at_k(list(range(10)), set(range(20)), 10) == 1.0


def test_recall_only_top_k_counts() -> None:
    assert recall_at_k([7, 8, 9, 1], {1}, 3) == 0.0
    assert recall_at_k([8, 9, 1], {1}, 3) == 1.0


def test_recall_dedupes_and_handles_empty() -> None:
    # duplicates collapse before the cut: [1, 1, 2] -> [1, 2]
    assert recall_at_k([1, 1, 2], {1, 2}, 2) == 1.0
    assert recall_at_k([1, 2], set(), 10) == 0.0
    assert recall_at_k([], {1}, 10) == 0.0
    assert recall_at_k([1], {1}, 0) == 0.0


# ------------------------------------------------------------------ ndcg


def test_ndcg_perfect() -> None:
    assert ndcg_at_k([1, 2, 3, 4], {1, 2}, 4) == pytest.approx(1.0)


def test_ndcg_position_matters() -> None:
    first = ndcg_at_k([1, 9, 9], {1}, 3)
    third = ndcg_at_k([8, 9, 1], {1}, 3)
    assert first == pytest.approx(1.0)
    assert third == pytest.approx(1 / math.log2(4))
    assert first > third


def test_ndcg_known_value() -> None:
    # hits at ranks 1 and 3, two relevant: DCG = 1 + 1/log2(4); IDCG = 1 + 1/log2(3)
    expected = (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert ndcg_at_k([1, 9, 2], {1, 2}, 3) == pytest.approx(expected)


def test_ndcg_empty_and_none() -> None:
    assert ndcg_at_k([1, 2], set(), 5) == 0.0
    assert ndcg_at_k([7, 8], {1}, 5) == 0.0


def test_ndcg_more_relevant_than_k() -> None:
    assert ndcg_at_k([1, 2], {1, 2, 3, 4, 5}, 2) == pytest.approx(1.0)


# ------------------------------------------------------------------ ablation helpers


def test_ablation_loads_personas_and_labels() -> None:
    ab = load_ablation()
    personas = ab.load_personas(str(DATA / "personas" / "*.yaml"))
    assert [p.id for p in personas] == ["synthetic-cs-tx", "synthetic-nurse-oh"]
    cs = personas[0].profile
    assert cs.home_state.value == "TX" and cs.home_state.confidence == 1.0
    assert cs.interests.value and "computer programming" in cs.interests.value
    labels = ab.load_labels(DATA / "labels.yaml")
    assert set(labels) == {"synthetic-cs-tx", "synthetic-nurse-oh"}
    assert all(isinstance(u, int) for s in labels.values() for u in s)


def test_ablation_ignores_unknown_hidden_fields() -> None:
    ab = load_ablation()
    p = ab.profile_from_hidden({"home_state": "OH", "favourite_colour": "blue"})
    assert p.home_state.value == "OH"


def test_format_table() -> None:
    ab = load_ablation()
    table = ab.format_table(
        [
            ab.ModeResult("hybrid", 0.5, 0.25, 3),
            ab.ModeResult("x", None, None, 0, "not implemented"),
        ]
    )
    lines = table.splitlines()
    assert lines[0] == "| mode | recall@10 | nDCG@10 | n |"
    assert "| hybrid | 0.500 | 0.250 | 3 |" in lines
    assert "not implemented" in lines[-1]
