"""Labeling tool: key handling, resume, frozen labels.yaml format and round-trip."""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.ablation import load_labels  # noqa: E402
from evals.common import persona_from_doc  # noqa: E402
from evals.labels.label import (  # noqa: E402
    LabelSession,
    finalize,
    label_persona,
    priority_order,
    validate_labels,
)
from evals.labels.pool import CSV_COLUMNS  # noqa: E402


def _persona(pid: str = "t-oh", **hidden: object) -> object:
    h = {"home_state": "OH", "income_bracket": "48-75k", "interests": ["x"]}
    h.update(hidden)
    return persona_from_doc({"id": pid, "summary": "test", "hidden_profile": h})


def _row(uid: int, rate: str = "0.70", sat: str = "") -> dict[str, str]:
    r = dict.fromkeys(CSV_COLUMNS, "")
    r.update(
        unitid=str(uid), name=f"S{uid}", city="C", state="OH", control="public",
        admission_rate=rate, sat_range=sat, net_price="12000",
    )  # fmt: skip
    return r


def _write_pool(d: Path, pid: str, rows: list[dict[str, str]], meta: dict[str, object]) -> None:
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{pid}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    (d / f"{pid}.meta.yaml").write_text(yaml.safe_dump(meta))


def test_session_keys_back_skip_quit() -> None:
    rows = [_row(1), _row(2), _row(3)]
    s = LabelSession(_persona(), rows, {})  # type: ignore[arg-type]
    assert s.apply("2") == "scored" and s.idx == 1
    assert s.apply("b") == "back" and s.idx == 0
    assert s.apply("1") == "scored"
    assert s.apply("s") == "unsure"
    assert s.apply("x") == "ignored"
    assert s.apply("0") == "scored" and s.done
    assert s.scores == {1: 1, 2: "unsure", 3: 0}
    assert s.apply("b") == "back" and s.idx == 2  # back from the end
    assert s.apply("q") == "quit"
    resumed = LabelSession(_persona(), rows, {}, {1: 2})  # type: ignore[arg-type]
    assert resumed.idx == 1


def test_finalize_band_mix_and_target() -> None:
    p = _persona(sat=1200)
    # 3 reaches (rate < 25%, student below median) of 6 acceptable -> trim to <= 1/3
    rows = [_row(1), _row(2, "0.10", "1300-1500"), _row(3, "0.20", "1250-1450"),
            _row(4, "0.22", "1300-1400"), _row(5), _row(6), _row(7)]  # fmt: skip
    scores: dict[int, int | str] = {1: 2, 2: 1, 3: 2, 4: 1, 5: 0, 6: 1, 7: 1}
    e = finalize(p, rows, scores, {"auto_judged": [{"unitid": 99}]}, today=date(2026, 11, 21))  # type: ignore[arg-type]
    assert e["acceptable_unitids"] == [1, 3, 6, 7]  # S1=1 reaches (2, 4) dropped first
    assert "removed reaches [2, 4]" in e["notes"] and "Only 4 acceptable" in e["notes"]
    assert e["judged_unitids"] == [1, 2, 3, 4, 5, 6, 7, 99]
    assert e["labeled_at"] == "2026-11-21"

    many = [_row(i) for i in range(1, 31)]
    sc: dict[int, int | str] = {i: (2 if i <= 12 else 1) for i in range(1, 31)}
    e2 = finalize(_persona(), many, sc, {})  # type: ignore[arg-type]
    assert e2["acceptable_unitids"] == list(range(1, 13)) and "kept S1=2 only" in e2["notes"]


def test_label_persona_round_trip(tmp_path: Path) -> None:
    pools, labels, progress = tmp_path / "pools", tmp_path / "labels.yaml", tmp_path / "prog"
    meta = {
        "major_cip4s": ["5004", "1419"],
        "pool_size": 47,
        "relaxed": [],
        "auto_judged": [{"unitid": 900, "reasons": ["H1"]}],
        "criteria_commit": "abc123",
        "candidate_tool_version": "def456",
    }
    _write_pool(pools, "t-oh", [_row(10), _row(11), _row(12)], meta)
    out: list[str] = []
    # quit after one row: progress saved, no labels yet
    r = label_persona(_persona(), pools, labels, progress, iter(["2", "q"]), out.append)  # type: ignore[arg-type]
    assert r == "quit" and not labels.exists() and (progress / "t-oh.json").exists()
    # resume: the remaining two rows
    r = label_persona(
        _persona(),
        pools,
        labels,
        progress,
        iter(["0", "s", "b", "s", "f"]),
        out.append,
        lambda: "my note",  # type: ignore[arg-type]
    )
    assert r == "done"
    doc = yaml.safe_load(labels.read_text())
    assert doc["_meta"]["criteria_commit"] == "abc123"
    assert doc["_meta"]["candidate_tool_version"] == "def456"
    e = doc["t-oh"]
    assert e["acceptable_unitids"] == [10]
    assert e["judged_unitids"] == [10, 11, 12, 900]  # every shown row is judged
    assert e["major_cip4s"] == ["50.04", "14.19"] and e["pool_size"] == 47
    assert e["notes"].startswith("my note") and "Unsure (scored S1=0): [12]" in e["notes"]
    assert validate_labels(doc) == []
    parsed = load_labels(labels)  # the scorer reads it back
    assert parsed["t-oh"].acceptable == {10} and parsed["t-oh"].judged == {10, 11, 12, 900}
    assert "acceptable_unitids: [10]" in labels.read_text()  # flow-style lists

    # a second persona keeps the first entry and _meta
    _write_pool(pools, "u-oh", [_row(20)], meta)
    label_persona(_persona("u-oh"), pools, labels, progress, iter(["1", "f"]), out.append)  # type: ignore[arg-type]
    doc = yaml.safe_load(labels.read_text())
    assert set(doc) == {"_meta", "t-oh", "u-oh"} and list(doc)[0] == "_meta"


def test_validate_labels_catches_format_errors() -> None:
    bad = {
        "p": {"acceptable_unitids": [1, 2], "judged_unitids": [1], "labeled_at": "nope"},
    }
    errs = validate_labels(bad)
    assert any("criteria_commit" in e for e in errs)
    assert any("missing notes" in e for e in errs)
    assert any("subset" in e for e in errs)
    assert any("ISO date" in e for e in errs)


def test_priority_order_voice_first() -> None:
    a = persona_from_doc({"id": "zz-ia", "meta": {"edge_cases": ["cs"]}})
    b = persona_from_doc({"id": "maya-oh", "meta": {"edge_cases": []}})
    c = persona_from_doc({"id": "aa-co", "meta": {"edge_cases": []}})
    d = persona_from_doc({"id": "bb-ny", "meta": {"edge_cases": ["cs"]}})
    assert [p.id for p in priority_order([a, b, c, d])] == ["maya-oh", "zz-ia", "aa-co", "bb-ny"]


def test_relabel_restart_discards_progress(tmp_path: Path) -> None:
    pools, labels, progress = tmp_path / "pools", tmp_path / "labels.yaml", tmp_path / "prog"
    _write_pool(pools, "t-oh", [_row(10), _row(11)], {"criteria_commit": "c"})
    p = _persona()
    label_persona(p, pools, labels, progress, iter(["2", "q"]), print)  # type: ignore[arg-type]
    out: list[str] = []
    keys = iter(["0", "0", "f"])
    label_persona(p, pools, labels, progress, keys, out.append, restart=True)  # type: ignore[arg-type]
    assert "0 already scored" in "\n".join(out)
    assert yaml.safe_load(labels.read_text())["t-oh"]["acceptable_unitids"] == []


def test_band_mix_uses_students_own_test_when_school_reports_it() -> None:
    # ACT-25 student at a <25% school reporting SAT 1300-1450 AND ACT 22-26: in ACT units
    # (criteria H4) the student is above the median (24), so it is not a reach. Concording
    # to SAT (25 -> 1210 vs median 1375) would wrongly call it one and trim it.
    p = _persona(act=25)
    rows = [_row(1, "0.20", "1300-1450"), _row(2)]  # 1 reach of 2 would exceed 1/3
    rows[0]["act_range"] = "22-26"
    e = finalize(p, rows, {1: 1, 2: 1}, {})  # type: ignore[arg-type]
    assert e["acceptable_unitids"] == [1, 2] and "band-mix" not in e["notes"]
    sat_only = [_row(1, "0.20", "1300-1450"), _row(2)]  # concorded: 1210 < 1375 -> reach
    e2 = finalize(p, sat_only, {1: 1, 2: 1}, {})  # type: ignore[arg-type]
    assert e2["acceptable_unitids"] == [2] and "band-mix" in e2["notes"]
