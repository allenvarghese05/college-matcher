"""College Scorecard transform layer: raw CSV rows -> typed, frozen records.

Pure stdlib (csv, json, dataclasses, argparse). The raw files are treated as
untrusted data: they are parsed with ``csv`` only and nothing in them is
evaluated. See docs/SPEC.md §5 for the column list and inclusion rule.

Inclusion rule (SPEC D6): ``CURROPER == 1`` AND ``STABBR`` in the 50 states +
DC AND at least one ``CREDLEV == 3`` (bachelor's) row in the field-of-study
file. On the 2026-11 release this gives 2,343 schools.

Missing-value markers
---------------------
``NA``, ``NULL``, ``PS`` / ``PrivacySuppressed`` and blank all parse to None.
``PS`` means privacy-suppressed (cohort too small to publish); program records
keep that distinction in ``earnings_suppressed`` / ``debt_suppressed`` so the
UI can say "suppressed" instead of "not reported".

CIPCODE format (checked on the 2026-10-15 field-of-study release)
-----------------------------------------------------------------
All 223,587 rows hold CIPCODE as a 4-character, zero-padded digit string with
no dot (e.g. ``0109``, ``1107``, ``5203``). The leading zero survives because
we read every cell as text. ``normalize_cip4`` still accepts the other shapes
seen in older releases or after a spreadsheet round-trip:

* ``"11.07"`` / ``"1.1"`` (dotted, 2-digit series + subseries; a 1-digit
  subseries is a float that lost its trailing zero, so ``"1.1"`` -> ``"0110"``)
* ``"110"`` (integer that lost its leading zero) -> ``"0110"``
* ``"110701"`` / ``"11.0701"`` (6-digit CIP) -> first four digits ``"1107"``

CIPDESC always ends with a period (``"Animal Sciences."``); it is stripped.

Usage::

    python -m ingest.scorecard --raw data/raw/scorecard --out data/processed
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

csv.field_size_limit(sys.maxsize)

INSTITUTION_FILE = "Most-Recent-Cohorts-Institution.csv"
FIELD_OF_STUDY_FILE = "Most-Recent-Cohorts-Field-of-Study.csv"

STATES_50_DC = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE "
    "NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
BACHELORS = 3
CONTROL_PUBLIC = 1

_MISSING = frozenset({"", "NA", "NULL", "PS", "PRIVACYSUPPRESSED"})
_SUPPRESSED = frozenset({"PS", "PRIVACYSUPPRESSED"})

# (record field suffix, Scorecard bracket digit)
NET_PRICE_BRACKETS = (
    ("0_30k", "1"),
    ("30_48k", "2"),
    ("48_75k", "3"),
    ("75_110k", "4"),
    ("110k_plus", "5"),
)


# --------------------------------------------------------------------------- parsing


def parse_num(s: str | None) -> float | None:
    """Parse a Scorecard cell. NA / NULL / PS / PrivacySuppressed / blank -> None."""
    if s is None:
        return None
    s = s.strip()
    if s.upper() in _MISSING:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    if x != x or x in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return x


def is_suppressed(s: str | None) -> bool:
    """True when the cell is a privacy-suppression marker (PS / PrivacySuppressed)."""
    return s is not None and s.strip().upper() in _SUPPRESSED


def parse_int(s: str | None) -> int | None:
    x = parse_num(s)
    return None if x is None else int(round(x))


def parse_str(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.strip()
    return None if s.upper() in _MISSING else s


def normalize_cip4(raw: str | None) -> str | None:
    """Normalise a CIPCODE cell to a 4-digit string ("1107"). None if unparseable."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if "." in s:
        series, _, sub = s.partition(".")
        if not (series.isdigit() and sub.isdigit()) or len(series) > 2:
            return None
        series = series.zfill(2)
        if len(sub) == 1:
            sub = sub + "0"  # "1.1" is 01.10 after float coercion
        code = series + sub[:2]
    else:
        if not s.isdigit():
            return None
        if len(s) <= 4:
            code = s.zfill(4)
        elif len(s) == 6:
            code = s[:4]
        else:
            return None
    return code if code != "0000" else None


def normalize_url(raw: str | None) -> str | None:
    s = parse_str(raw)
    if s is None:
        return None
    lower = s.lower()
    if lower.startswith(("http://", "https://")):
        return s
    return "https://" + s.lstrip("/")


def _open_admission(raw: str | None) -> bool | None:
    v = parse_int(raw)
    return {1: True, 2: False}.get(v) if v is not None else None


def _sat_composite(row: dict[str, str], pct: str) -> int | None:
    vr = parse_num(row.get(f"SATVR{pct}"))
    mt = parse_num(row.get(f"SATMT{pct}"))
    if vr is None or mt is None:
        return None
    return int(round(vr + mt))


# --------------------------------------------------------------------------- records


@dataclass(frozen=True, slots=True)
class InstitutionRecord:
    unitid: int
    name: str
    city: str | None
    state: str
    zip: str | None
    lat: float | None
    lon: float | None
    control: int  # 1 public, 2 private nonprofit, 3 private for-profit
    locale: int | None
    undergrad_size: int | None
    admission_rate: float | None
    open_admission: bool | None
    sat_25: int | None  # composite SATVR25 + SATMT25
    sat_75: int | None
    act_25: int | None
    act_75: int | None
    net_price_0_30k: int | None
    net_price_30_48k: int | None
    net_price_48_75k: int | None
    net_price_75_110k: int | None
    net_price_110k_plus: int | None
    avg_net_price: int | None
    completion_rate: float | None
    median_earnings_10yr: int | None
    median_debt: int | None
    url: str | None
    # Published tuition + fees (TUITIONFEE_IN / TUITIONFEE_OUT). For publics the
    # difference is the out-of-state surcharge added to the (in-state) net price.
    tuition_in_state: int | None = None
    tuition_out_of_state: int | None = None


@dataclass(frozen=True, slots=True)
class ProgramRecord:
    unitid: int
    cip4: str
    cip_title: str
    credential_level: int
    median_earnings: int | None  # EARN_MDN_4YR
    earnings_suppressed: bool
    median_debt: int | None  # DEBT_ALL_STGP_EVAL_MDN
    debt_suppressed: bool
    graduates: int | None  # IPEDSCOUNT1 + IPEDSCOUNT2


def institution_from_row(row: dict[str, str]) -> InstitutionRecord:
    """Build an InstitutionRecord from one institution-file row (dict of str)."""
    control = parse_int(row.get("CONTROL"))
    if control not in (1, 2, 3):
        raise ValueError(f"UNITID {row.get('UNITID')!r}: bad CONTROL {row.get('CONTROL')!r}")
    sector = "PUB" if control == CONTROL_PUBLIC else "PRIV"
    net = {
        f"net_price_{suffix}": parse_int(row.get(f"NPT4{digit}_{sector}"))
        for suffix, digit in NET_PRICE_BRACKETS
    }
    return InstitutionRecord(
        unitid=int(row["UNITID"].strip()),
        name=(row.get("INSTNM") or "").strip(),
        city=parse_str(row.get("CITY")),
        state=(row.get("STABBR") or "").strip(),
        zip=parse_str(row.get("ZIP")),
        lat=parse_num(row.get("LATITUDE")),
        lon=parse_num(row.get("LONGITUDE")),
        control=control,
        locale=parse_int(row.get("LOCALE")),
        undergrad_size=parse_int(row.get("UGDS")),
        admission_rate=parse_num(row.get("ADM_RATE")),
        open_admission=_open_admission(row.get("OPENADMP")),
        sat_25=_sat_composite(row, "25"),
        sat_75=_sat_composite(row, "75"),
        act_25=parse_int(row.get("ACTCM25")),
        act_75=parse_int(row.get("ACTCM75")),
        **net,
        avg_net_price=parse_int(row.get(f"NPT4_{sector}")),
        completion_rate=parse_num(row.get("C150_4")),
        median_earnings_10yr=parse_int(row.get("MD_EARN_WNE_P10")),
        median_debt=parse_int(row.get("GRAD_DEBT_MDN")),
        url=normalize_url(row.get("INSTURL")),
        tuition_in_state=parse_int(row.get("TUITIONFEE_IN")),
        tuition_out_of_state=parse_int(row.get("TUITIONFEE_OUT")),
    )


def program_from_row(row: dict[str, str]) -> ProgramRecord:
    """Build a ProgramRecord from one field-of-study row (dict of str)."""
    cip4 = normalize_cip4(row.get("CIPCODE"))
    if cip4 is None:
        raise ValueError(f"UNITID {row.get('UNITID')!r}: bad CIPCODE {row.get('CIPCODE')!r}")
    title = (row.get("CIPDESC") or "").strip().rstrip(".").strip()
    c1 = parse_num(row.get("IPEDSCOUNT1"))
    c2 = parse_num(row.get("IPEDSCOUNT2"))
    graduates = None if c1 is None and c2 is None else int(round((c1 or 0) + (c2 or 0)))
    earn_raw = row.get("EARN_MDN_4YR")
    debt_raw = row.get("DEBT_ALL_STGP_EVAL_MDN")
    return ProgramRecord(
        unitid=int(row["UNITID"].strip()),
        cip4=cip4,
        cip_title=title,
        credential_level=int(row["CREDLEV"].strip()),
        median_earnings=parse_int(earn_raw),
        earnings_suppressed=is_suppressed(earn_raw),
        median_debt=parse_int(debt_raw),
        debt_suppressed=is_suppressed(debt_raw),
        graduates=graduates,
    )


# --------------------------------------------------------------------------- iteration


def _rows(path: str | Path) -> Iterator[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        yield from csv.DictReader(f)


def iter_institutions(
    path: str | Path, in_scope_unitids: Iterable[int] | None
) -> Iterator[InstitutionRecord]:
    """Yield InstitutionRecords for rows whose UNITID is in ``in_scope_unitids``.

    Pass ``None`` to yield every row (not recommended: out-of-scope rows may
    have unusual values).
    """
    scope = None if in_scope_unitids is None else set(in_scope_unitids)
    for row in _rows(path):
        if scope is not None and parse_int(row.get("UNITID")) not in scope:
            continue
        yield institution_from_row(row)


@dataclass(slots=True)
class SkipCounter:
    """Mutable tally of rows ``iter_programs`` dropped because UNITID didn't parse.

    The field-of-study file has rows whose UNITID is literally ``NA`` (5,573 on
    the 2026-10-15 release); they can't be joined to a school, so they are
    skipped and counted rather than crashing ``program_from_row``.
    """

    no_unitid: int = 0


def iter_programs(
    path: str | Path,
    credential_level: int | None = BACHELORS,
    in_scope_unitids: Iterable[int] | None = None,
    skipped: SkipCounter | None = None,
) -> Iterator[ProgramRecord]:
    """Yield ProgramRecords at ``credential_level`` (None = all levels),
    optionally restricted to ``in_scope_unitids``.

    Rows at the wanted level whose UNITID doesn't parse are skipped and, if
    ``skipped`` is given, counted in ``skipped.no_unitid``.
    """
    scope = None if in_scope_unitids is None else set(in_scope_unitids)
    want = None if credential_level is None else str(credential_level)
    for row in _rows(path):
        if want is not None and (row.get("CREDLEV") or "").strip() != want:
            continue
        uid = parse_int(row.get("UNITID"))
        if uid is None:
            if skipped is not None:
                skipped.no_unitid += 1
            continue
        if scope is not None and uid not in scope:
            continue
        yield program_from_row(row)


def compute_scope(inst_path: str | Path, fos_path: str | Path) -> set[int]:
    """UNITIDs in scope: CURROPER=1, 50 states + DC, >= 1 bachelor's (CREDLEV=3) row."""
    with_bachelors: set[int] = set()
    for row in _rows(fos_path):
        if (row.get("CREDLEV") or "").strip() == str(BACHELORS):
            uid = parse_int(row.get("UNITID"))
            if uid is not None:
                with_bachelors.add(uid)
    scope: set[int] = set()
    for row in _rows(inst_path):
        uid = parse_int(row.get("UNITID"))
        if (
            uid in with_bachelors
            and parse_int(row.get("CURROPER")) == 1
            and (row.get("STABBR") or "").strip() in STATES_50_DC
        ):
            scope.add(uid)
    return scope


# --------------------------------------------------------------------------- output


def to_json(rec: InstitutionRecord | ProgramRecord) -> str:
    return json.dumps(asdict(rec), separators=(",", ":"))


def write_jsonl(path: Path, records: Iterable[InstitutionRecord | ProgramRecord]) -> int:
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(to_json(rec) + "\n")
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", required=True, type=Path, help="dir with the Scorecard CSVs")
    ap.add_argument("--out", required=True, type=Path, help="output dir for *.jsonl")
    args = ap.parse_args(argv)

    inst_path = args.raw / INSTITUTION_FILE
    fos_path = args.raw / FIELD_OF_STUDY_FILE
    args.out.mkdir(parents=True, exist_ok=True)

    scope = compute_scope(inst_path, fos_path)
    n_inst = write_jsonl(args.out / "institutions.jsonl", iter_institutions(inst_path, scope))

    n_prog = n_earn = n_debt = 0
    skipped = SkipCounter()
    with (args.out / "programs.jsonl").open("w", encoding="utf-8") as f:
        for p in iter_programs(fos_path, BACHELORS, scope, skipped):
            f.write(to_json(p) + "\n")
            n_prog += 1
            n_earn += p.median_earnings is not None
            n_debt += p.median_debt is not None

    print(f"in-scope schools:        {len(scope):,}")
    print(f"institutions written:    {n_inst:,}")
    print(f"bachelor's programs:     {n_prog:,}")
    print(f"  with median earnings:  {n_earn:,} ({n_earn / max(n_prog, 1):.1%})")
    print(f"  with median debt:      {n_debt:,} ({n_debt / max(n_prog, 1):.1%})")
    print(f"rows skipped (no UNITID): {skipped.no_unitid:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
