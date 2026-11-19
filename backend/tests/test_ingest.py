"""Tests for the Scorecard transform layer. No raw data or database needed."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:  # works with or without a conftest / pyproject pythonpath
    sys.path.insert(0, str(BACKEND))

from ingest.scorecard import (  # noqa: E402
    STATES_50_DC,
    InstitutionRecord,
    ProgramRecord,
    institution_from_row,
    is_suppressed,
    normalize_cip4,
    normalize_url,
    parse_num,
    program_from_row,
)

FIXTURES = BACKEND.parent / "data" / "fixtures"


# --------------------------------------------------------------------------- helpers


def inst_row(**overrides: str) -> dict[str, str]:
    row = {
        "UNITID": "100654", "INSTNM": "Alabama A & M University", "CITY": "Normal",
        "STABBR": "AL", "ZIP": "35762", "LATITUDE": "34.783368", "LONGITUDE": "-86.568502",
        "LOCALE": "12", "INSTURL": "www.aamu.edu/", "CONTROL": "1", "UGDS": "6124",
        "ADM_RATE": "0.5795", "OPENADMP": "2",
        "SATVR25": "420", "SATVR75": "530", "SATMT25": "390", "SATMT75": "510",
        "ACTCM25": "14", "ACTCM75": "19",
        "NPT4_PUB": "18255", "NPT4_PRIV": "NA",
        "C150_4": "0.2771", "MD_EARN_WNE_P10": "41266", "GRAD_DEBT_MDN": "27204",
        "CURROPER": "1",
    }
    for i in range(1, 6):
        row[f"NPT4{i}_PUB"] = str(10000 + i)
        row[f"NPT4{i}_PRIV"] = str(30000 + i)
    row.update(overrides)
    return row


def prog_row(**overrides: str) -> dict[str, str]:
    row = {
        "UNITID": "100654", "CIPCODE": "0109", "CIPDESC": "Animal Sciences.",
        "CREDLEV": "3", "IPEDSCOUNT1": "18", "IPEDSCOUNT2": "12",
        "EARN_MDN_4YR": "PS", "DEBT_ALL_STGP_EVAL_MDN": "27000",
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------- parse_num


@pytest.mark.parametrize("raw", ["NA", "NULL", "PS", "PrivacySuppressed", "", "   ", None,
                                 "na", "privacysuppressed", "abc", "nan"])
def test_parse_num_missing(raw):
    assert parse_num(raw) is None


@pytest.mark.parametrize("raw,expected", [("0.5795", 0.5795), ("27000", 27000.0),
                                          (" 12 ", 12.0), ("-3.5", -3.5), ("0", 0.0)])
def test_parse_num_values(raw, expected):
    assert parse_num(raw) == expected


@pytest.mark.parametrize("raw,expected", [("PS", True), ("PrivacySuppressed", True),
                                          (" ps ", True), ("NA", False), ("NULL", False),
                                          ("", False), (None, False), ("123", False)])
def test_is_suppressed(raw, expected):
    assert is_suppressed(raw) is expected


# --------------------------------------------------------------------------- institution


def test_sat_composite_both_present():
    rec = institution_from_row(inst_row())
    assert (rec.sat_25, rec.sat_75) == (420 + 390, 530 + 510)


def test_sat_composite_requires_both_sections():
    rec = institution_from_row(inst_row(SATMT25="NA", SATVR75="PS"))
    assert rec.sat_25 is None
    assert rec.sat_75 is None


def test_act_range():
    rec = institution_from_row(inst_row())
    assert (rec.act_25, rec.act_75) == (14, 19)
    assert institution_from_row(inst_row(ACTCM25="NA")).act_25 is None


def test_net_price_public_uses_pub_columns():
    rec = institution_from_row(inst_row(CONTROL="1"))
    assert [rec.net_price_0_30k, rec.net_price_30_48k, rec.net_price_48_75k,
            rec.net_price_75_110k, rec.net_price_110k_plus] == [10001, 10002, 10003, 10004, 10005]
    assert rec.avg_net_price == 18255


@pytest.mark.parametrize("control", ["2", "3"])
def test_net_price_private_uses_priv_columns(control):
    rec = institution_from_row(inst_row(CONTROL=control, NPT4_PUB="NA", NPT4_PRIV="41000"))
    assert [rec.net_price_0_30k, rec.net_price_30_48k, rec.net_price_48_75k,
            rec.net_price_75_110k, rec.net_price_110k_plus] == [30001, 30002, 30003, 30004, 30005]
    assert rec.avg_net_price == 41000


def test_net_price_does_not_fall_back_across_sectors():
    rec = institution_from_row(inst_row(CONTROL="2", NPT41_PRIV="NA", NPT4_PRIV="NA"))
    assert rec.net_price_0_30k is None
    assert rec.avg_net_price is None


@pytest.mark.parametrize("raw,expected", [("1", True), ("2", False), ("NA", None),
                                          ("", None), ("3", None)])
def test_open_admission_mapping(raw, expected):
    assert institution_from_row(inst_row(OPENADMP=raw)).open_admission is expected


@pytest.mark.parametrize("raw,expected", [
    ("www.aamu.edu/", "https://www.aamu.edu/"),
    ("https://www.uab.edu/", "https://www.uab.edu/"),
    ("http://example.edu", "http://example.edu"),
    ("HTTPS://X.EDU", "HTTPS://X.EDU"),
    ("NA", None), ("", None),
])
def test_url_normalisation(raw, expected):
    assert normalize_url(raw) == expected


def test_institution_types():
    rec = institution_from_row(inst_row())
    assert rec.unitid == 100654 and rec.control == 1 and rec.locale == 12
    assert rec.undergrad_size == 6124 and rec.admission_rate == pytest.approx(0.5795)
    assert rec.zip == "35762" and rec.state == "AL"
    assert rec.median_earnings_10yr == 41266 and rec.median_debt == 27204
    assert rec.completion_rate == pytest.approx(0.2771)
    assert institution_from_row(inst_row(MD_EARN_WNE_P10="PS")).median_earnings_10yr is None


def test_bad_control_rejected():
    with pytest.raises(ValueError):
        institution_from_row(inst_row(CONTROL="NA"))


def test_records_are_frozen():
    rec = institution_from_row(inst_row())
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.name = "x"  # type: ignore[misc]


# --------------------------------------------------------------------------- CIP / programs


@pytest.mark.parametrize("raw,expected", [
    ("1107", "1107"), ("0109", "0109"), (" 5203 ", "5203"),
    ("11.07", "1107"), ("1.01", "0101"), ("1.1", "0110"), ("01.10", "0110"),
    ("110", "0110"), ("109", "0109"),
    ("110701", "1107"), ("11.0701", "1107"),
    ("", None), ("NA", None), ("abcd", None), ("12345", None), ("0000", None),
])
def test_normalize_cip4(raw, expected):
    assert normalize_cip4(raw) == expected


def test_program_suppressed_earnings():
    p = program_from_row(prog_row())
    assert p.cip4 == "0109" and p.cip_title == "Animal Sciences"
    assert p.median_earnings is None and p.earnings_suppressed is True
    assert p.median_debt == 27000 and p.debt_suppressed is False
    assert p.graduates == 30 and p.credential_level == 3


def test_program_na_is_missing_not_suppressed():
    p = program_from_row(prog_row(EARN_MDN_4YR="NA", DEBT_ALL_STGP_EVAL_MDN="PrivacySuppressed"))
    assert p.median_earnings is None and p.earnings_suppressed is False
    assert p.median_debt is None and p.debt_suppressed is True


def test_program_graduates():
    assert program_from_row(prog_row(IPEDSCOUNT2="NA")).graduates == 18
    assert program_from_row(prog_row(IPEDSCOUNT1="NA", IPEDSCOUNT2="NA")).graduates is None


def test_program_earnings_value():
    p = program_from_row(prog_row(EARN_MDN_4YR="61234", CIPCODE="11.07",
                                  CIPDESC="Computer Science."))
    assert p.median_earnings == 61234 and p.earnings_suppressed is False
    assert p.cip4 == "1107" and p.cip_title == "Computer Science"


# --------------------------------------------------------------------------- fixtures


def _load(name: str) -> list[dict]:
    path = FIXTURES / name
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture(scope="module")
def sample_insts() -> list[dict]:
    return _load("institutions_sample.jsonl")


@pytest.fixture(scope="module")
def sample_progs() -> list[dict]:
    return _load("programs_sample.jsonl")


def test_fixture_schema(sample_insts, sample_progs):
    inst_fields = [f.name for f in dataclasses.fields(InstitutionRecord)]
    prog_fields = [f.name for f in dataclasses.fields(ProgramRecord)]
    assert all(list(r) == inst_fields for r in sample_insts)
    assert all(list(r) == prog_fields for r in sample_progs)
    # round-trips into the frozen dataclasses
    InstitutionRecord(**sample_insts[0])
    ProgramRecord(**sample_progs[0])


def test_fixture_scope_and_size(sample_insts, sample_progs):
    assert 150 <= len(sample_insts) <= 260
    uids = [r["unitid"] for r in sample_insts]
    assert len(uids) == len(set(uids))
    assert all(r["state"] in STATES_50_DC for r in sample_insts)
    assert {r["control"] for r in sample_insts} == {1, 2, 3}
    inst_set = set(uids)
    assert all(p["unitid"] in inst_set for p in sample_progs)
    assert inst_set == {p["unitid"] for p in sample_progs}  # every school has >= 1 bachelor's
    keys = [(p["unitid"], p["cip4"]) for p in sample_progs]
    assert len(keys) == len(set(keys))


def test_fixture_diversity(sample_insts, sample_progs):
    assert sum(r["open_admission"] is True for r in sample_insts) >= 10
    assert sum((r["admission_rate"] or 1) < 0.15 for r in sample_insts) >= 10
    assert sum(r["sat_25"] is not None for r in sample_insts) >= 20
    assert sum(r["sat_25"] is None for r in sample_insts) >= 20
    assert any(p["earnings_suppressed"] for p in sample_progs)
    assert any(p["median_earnings"] is not None for p in sample_progs)
    assert len({r["state"] for r in sample_insts}) >= 40


def _in(v, lo, hi) -> bool:
    return v is None or lo <= v <= hi


def test_fixture_institution_ranges(sample_insts):
    for r in sample_insts:
        assert r["name"] and len(r["state"]) == 2
        assert _in(r["lat"], 18, 72) and _in(r["lon"], -180, -60)
        assert _in(r["admission_rate"], 0, 1) and _in(r["completion_rate"], 0, 1)
        assert _in(r["sat_25"], 400, 1600) and _in(r["sat_75"], 400, 1600)
        assert _in(r["act_25"], 1, 36) and _in(r["act_75"], 1, 36)
        if r["sat_25"] is not None and r["sat_75"] is not None:
            assert r["sat_25"] <= r["sat_75"]
        if r["act_25"] is not None and r["act_75"] is not None:
            assert r["act_25"] <= r["act_75"]
        for k in ("net_price_0_30k", "net_price_30_48k", "net_price_48_75k",
                  "net_price_75_110k", "net_price_110k_plus", "avg_net_price"):
            assert _in(r[k], 0, 150_000), (r["unitid"], k, r[k])
        assert _in(r["median_earnings_10yr"], 5_000, 500_000)
        assert _in(r["median_debt"], 0, 200_000)
        assert _in(r["undergrad_size"], 0, 500_000)
        assert r["url"] is None or r["url"].startswith(("https://", "http://"))
        assert r["open_admission"] in (True, False, None)


def test_fixture_program_ranges(sample_progs):
    for p in sample_progs:
        assert len(p["cip4"]) == 4 and p["cip4"].isdigit()
        assert p["cip_title"] and not p["cip_title"].endswith(".")
        assert p["credential_level"] == 3
        assert _in(p["median_earnings"], 5_000, 500_000)
        assert _in(p["median_debt"], 0, 200_000)
        assert _in(p["graduates"], 0, 100_000)
        if p["earnings_suppressed"]:
            assert p["median_earnings"] is None
        if p["debt_suppressed"]:
            assert p["median_debt"] is None
