from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

from app.retrieval.metrics import judged_precision_at_k, ndcg_at_k, recall_at_k, unjudged_at_k

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


# ------------------------------------------------------------------ judged precision


def test_judged_precision() -> None:
    # top-3 = [1, 2, 9]; judged {1, 2, 3}; acceptable {1}: 1 hit / 2 judged
    assert judged_precision_at_k([1, 2, 9, 3], {1}, {1, 2, 3}, 3) == pytest.approx(0.5)
    assert judged_precision_at_k([1, 3], {1, 3}, {1, 3}, 10) == 1.0


def test_judged_precision_none_when_nothing_judged() -> None:
    assert judged_precision_at_k([7, 8, 9], {1}, {1, 2}, 3) is None
    assert judged_precision_at_k([], {1}, {1}, 3) is None


def test_judged_precision_acceptable_counts_as_judged() -> None:
    # malformed labels (acceptable not in judged) can't exceed 1.0
    assert judged_precision_at_k([1, 2], {1, 2}, set(), 2) == 1.0


def test_unjudged_at_k() -> None:
    assert unjudged_at_k([1, 2, 9, 8], {1, 2}, 3) == 1
    assert unjudged_at_k([1, 1, 9], {1}, 2) == 1  # dedupe before the cut
    assert unjudged_at_k([], {1}, 10) == 0


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
    cs_lab = labels["synthetic-cs-tx"]
    assert all(isinstance(u, int) for u in cs_lab.acceptable | cs_lab.judged)
    assert cs_lab.acceptable <= cs_lab.judged and len(cs_lab.judged) == 8


def test_ablation_labels_require_judged(tmp_path: Path) -> None:
    ab = load_ablation()
    f = tmp_path / "labels.yaml"
    f.write_text("p1:\n  acceptable_unitids: [1, 2]\n")
    with pytest.raises(ValueError, match="judged_unitids"):
        ab.load_labels(f)


def test_ablation_strips_meta(tmp_path: Path) -> None:
    ab = load_ablation()
    f = tmp_path / "p.yaml"
    f.write_text(
        "id: p\nhidden_profile:\n  home_state: OH\n  meta: {x: 1}\nmeta:\n  articulateness: terse\n"
    )
    [p] = ab.load_personas(str(f))
    assert p.id == "p" and p.profile.home_state.value == "OH"


def test_ablation_ignores_unknown_hidden_fields() -> None:
    ab = load_ablation()
    p = ab.profile_from_hidden({"home_state": "OH", "favourite_colour": "blue"})
    assert p.home_state.value == "OH"


def test_format_table() -> None:
    ab = load_ablation()
    table = ab.format_table(
        [
            ab.ModeResult("hybrid", 0.5, 0.25, 3, judged_precision=0.75, unjudged=4),
            ab.ModeResult("sql_only", 0.1, 0.1, 3, judged_precision=None, unjudged=30),
            ab.ModeResult("x", None, None, 0, "not implemented"),
        ]
    )
    lines = table.splitlines()
    assert lines[0] == "| mode | recall@10 | nDCG@10 | judged-P@10 | unjudged@10 | n |"
    assert "| hybrid | 0.500 | 0.250 | 0.750 | 4 | 3 |" in lines
    assert "| sql_only | 0.100 | 0.100 | n/a | 30 | 3 |" in lines
    assert "not implemented" in lines[-1]
