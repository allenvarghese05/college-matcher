"""Candidate-pool generation (evals/labels/pool.py, criteria.md "Pooling")."""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.common import persona_from_doc  # noqa: E402
from evals.labels.pool import (  # noqa: E402
    CSV_COLUMNS,
    ProgramInfo,
    RawInstitutions,
    School,
    build_pool,
    generate,
    h2,
    h3,
    h4,
    norm_cip4,
    sat_to_act,
    stratified_sample,
    write_pool,
)

OH = (40.0, -83.0)  # roughly Columbus


def school(uid: int, **kw: object) -> School:
    base: dict[str, object] = dict(
        unitid=uid,
        name=f"School {uid}",
        city="Town",
        state="OH",
        control=1,
        locale=21,
        undergrad_size=5000,
        lat=40.1,
        lon=-83.1,
        admission_rate=0.7,
        net_prices={"net_price_48_75k": 15000},
        programs=[ProgramInfo("5004", "Design and Applied Arts", 41000)],
        tuition_in=10000.0,
        tuition_out=30000.0,
    )
    base.update(kw)
    return School(**base)  # type: ignore[arg-type]


def persona(**hidden: object) -> object:
    h = {"home_state": "OH", "income_bracket": "48-75k", "budget_cap": 22000}
    h.update(hidden)
    return persona_from_doc({"id": "t-oh", "summary": "test", "hidden_profile": h})


def test_norm_cip4_and_concordance() -> None:
    assert norm_cip4("50.04") == "5004"
    assert norm_cip4("5.02") == "0502"
    assert norm_cip4("1419") == "1419"
    assert sat_to_act(1310) == 28
    assert sat_to_act(1305) == 27


def test_h2_out_of_state_public_uses_sticker_gap() -> None:
    p = persona()
    ceiling = 22000 * 1.15
    in_state = h2(school(1), p.hidden)  # type: ignore[attr-defined]
    assert in_state.ok and in_state.oos_estimate is None
    oos = h2(school(2, state="MI"), p.hidden)  # type: ignore[attr-defined]
    assert oos.oos_estimate == 15000 + 20000 and not oos.ok and oos.oos_estimate > ceiling
    private = h2(school(3, state="MI", control=2), p.hidden)  # type: ignore[attr-defined]
    assert private.ok and private.oos_estimate is None
    missing = h2(school(4, state="MI", tuition_out=None), p.hidden)  # type: ignore[attr-defined]
    assert not missing.ok and "tuition missing" in missing.reasons[0]
    no_price = h2(school(5, net_prices={}, avg_net_price=None), p.hidden)  # type: ignore[attr-defined]
    assert not no_price.ok
    avg = h2(school(6, net_prices={}, avg_net_price=12000), p.hidden)  # type: ignore[attr-defined]
    assert avg.ok and avg.net_price == 12000


def test_h2_bracket_default_and_prestige() -> None:
    rich = {"home_state": "OH", "income_bracket": "110k+"}
    pricey = school(1, net_prices={"net_price_110k_plus": 60000})
    assert not h2(pricey, rich).ok
    assert h2(pricey, {**rich, "priorities": ["prestige"]}).ok


def test_h3_distance_and_regions() -> None:
    near, far = school(1), school(2, lat=34.0, lon=-118.0)
    assert h3(near, {"max_distance_miles": 100}, OH).ok
    assert not h3(far, {"max_distance_miles": 100}, OH).ok
    regions = {"home_state": "VT", "regions": ["out_of_state", "pacific"]}
    assert h3(school(3, state="CA"), regions, OH).ok
    assert not h3(school(4, state="VT"), regions, OH).ok
    assert h3(school(5, state="TX"), regions, OH).ok  # out_of_state alone = anywhere but home


def test_h4_admission_plausibility() -> None:
    sel = school(1, admission_rate=0.10, sat_25=1450, sat_75=1550)
    assert not h4(sel, {"sat": 1500}).ok
    assert h4(sel, {"sat": 1560}).ok
    assert h4(sel, {"gpa": 3.9}).ok  # no test, GPA >= 3.85
    far_below = school(2, admission_rate=0.40, sat_25=1300, sat_75=1450)
    assert not h4(far_below, {"sat": 1200}).ok
    assert h4(far_below, {"sat": 1250}).ok
    act_only = school(3, admission_rate=0.40, act_25=30, act_75=34)
    assert not h4(act_only, {"sat": 1200}).ok  # 1200 SAT ~ 24 ACT, > 3 below
    assert not h4(school(4, admission_rate=0.25), {"gpa": 2.8}).ok
    assert not h4(school(5, admission_rate=0.18), {"gpa": 3.3}).ok
    assert h4(school(6, admission_rate=0.18), {"gpa": 3.6}).ok
    assert h4(school(7, admission_rate=0.05, open_admission=True), {}).ok
    assert not h4(school(8, admission_rate=0.10), {}).ok


def test_stratified_sample_is_deterministic_and_proportional() -> None:
    schools = [school(i, control=1 + i % 2, admission_rate=0.1 + (i % 9) / 10) for i in range(200)]
    a = stratified_sample(schools, 60, random.Random("seed:p"))
    b = stratified_sample(schools, 60, random.Random("seed:p"))
    assert len(a) == 60 and [s.unitid for s in a] == [s.unitid for s in b]
    assert {s.control for s in a} == {1, 2}
    assert stratified_sample(schools[:10], 60, random.Random(1)) == schools[:10]


def test_build_pool_auto_judges_failing_system_picks_and_shuffles(tmp_path: Path) -> None:
    p = persona(max_distance_miles=200)
    schools = {i: school(i) for i in range(1, 9)}
    schools[50] = school(50, programs=[ProgramInfo("1101", "Computer Science")])  # fails H1
    schools[51] = school(51, state="MI", lat=42.3, lon=-83.7)  # out-of-state public: fails H2
    pool = build_pool(p, schools, ["50.04"], {1, 50, 51, 999}, OH, seed=7)  # type: ignore[arg-type]
    shown = {int(r["unitid"]) for r in pool.rows}
    assert shown == set(range(1, 9))
    auto = {a["unitid"]: a["reasons"] for a in pool.auto_judged}
    assert set(auto) == {50, 51, 999}
    assert any(r.startswith("H1") for r in auto[50])
    assert any("out-of-state estimate" in r for r in auto[51])
    assert auto[999] == ["not in database"]
    assert pool.pool_size == 8 and pool.relaxed == []
    again = build_pool(p, schools, ["50.04"], {1, 50, 51, 999}, OH, seed=7)  # type: ignore[arg-type]
    assert [r["unitid"] for r in again.rows] == [r["unitid"] for r in pool.rows]
    assert [r["unitid"] for r in pool.rows] != sorted(r["unitid"] for r in pool.rows)

    csv_path, meta_path = write_pool(pool, tmp_path, {"seed": 7})
    with open(csv_path) as f:
        header = next(csv.reader(f))
    assert header == CSV_COLUMNS
    for banned in ("source", "rank", "score", "mode", "system"):
        assert not any(banned in h for h in header)
    meta = yaml.safe_load(meta_path.read_text())
    assert meta["pool_size"] == 8 and len(meta["auto_judged"]) == 3


def test_relaxation_when_too_few_pass() -> None:
    p = persona(budget_cap=2000)  # bella-style unrealistic cap
    schools = {i: school(i, net_prices={"net_price_48_75k": 9000 + i}) for i in range(1, 7)}
    pool = build_pool(p, schools, ["5004"], set(), OH)  # type: ignore[arg-type]
    assert pool.relaxed == ["budget"] and pool.pool_size == 6


def test_raw_institutions_zip_centroid(tmp_path: Path) -> None:
    raw = tmp_path / "inst.csv"
    raw.write_text(
        "UNITID,ZIP,LATITUDE,LONGITUDE,TUITIONFEE_IN,TUITIONFEE_OUT\n"
        "1,43214-1000,40.0,-83.0,11000,30000\n"
        "2,43214,40.2,-83.2,NULL,NULL\n"
        "3,43299,41.0,-84.0,9000,20000\n"
    )
    r = RawInstitutions.load(raw)
    assert r.tuition[1] == (11000.0, 30000.0) and r.tuition[2] == (None, None)
    assert r.home_latlon("43214", "OH") == pytest.approx((40.1, -83.1))
    zip3_mean = ((40 + 40.2 + 41) / 3, (-83 - 83.2 - 84) / 3)
    assert r.home_latlon("43201", "OH") == pytest.approx(zip3_mean)
    assert r.home_latlon("99999", "OH") is not None  # state centroid fallback


@pytest.mark.usefixtures("loaded_db")
async def test_generate_against_fixture_db(tmp_path: Path, db_session: object) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "retrieval.json").write_text(
        json.dumps({"k": 10, "personas": {"t-oh": {"gold": {"hybrid": [100663, 1]}, "e2e": {}}}})
    )
    p = persona_from_doc(
        {
            "id": "t-oh",
            "summary": "test",
            "hidden_profile": {
                "home_state": "AL",
                "income_bracket": "48-75k",
                "budget_cap": 30000,
                "sat": 1300,
            },
        }
    )
    pools = await generate(
        [p],
        {"t-oh": ["09.01", "11.07", "52.02"]},
        [run],
        db_session,  # type: ignore[arg-type]
        RawInstitutions(),
        tmp_path / "pools",
        seed=1,
    )
    assert len(pools) == 1
    pool = pools[0]
    assert (tmp_path / "pools" / "t-oh.csv").exists()
    judged = {int(r["unitid"]) for r in pool.rows} | {a["unitid"] for a in pool.auto_judged}
    assert {100663, 1} <= judged  # every system pick is shown or auto-judged
    # no tuition data -> every out-of-state public fails H2
    assert all(r["state"] == "AL" or r["control"] != "public" for r in pool.rows)
