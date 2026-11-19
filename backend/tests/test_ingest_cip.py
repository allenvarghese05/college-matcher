"""NCES CIP 2020 CSV parsing (synthetic file in the NCES layout)."""

from __future__ import annotations

import csv
from pathlib import Path

from ingest.cip import parse_cip_csv

COLS = [
    "CIPFamily",
    "CIPCode",
    "Action",
    "TextChange",
    "CIPTitle",
    "CIPDefinition",
    "CrossReferences",
    "Examples",
]


def _row(code: str, title: str, definition: str = "", action: str = "No substantive changes"):
    return {
        "CIPFamily": f'="{code[:2]}"',
        "CIPCode": f'="{code}"',
        "Action": action,
        "TextChange": "No",
        "CIPTitle": title,
        "CIPDefinition": definition,
        "CrossReferences": "",
        "Examples": "",
    }


def _write(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    return path


def test_parse_cip_csv(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "CIPCode2020.csv",
        [
            _row("01", "AGRICULTURAL/ANIMAL/PLANT/VETERINARY SCIENCE AND RELATED FIELDS."),
            # series with a real definition
            _row("01.09", "Animal Sciences.", "A group of instructional programs that focus on."),
            _row("01.0901", "Animal Sciences, General."),
            # series whose definition only points at its children -> children titles
            _row(
                "47.06",
                "Vehicle Maintenance and Repair Technologies.",
                "Instructional content for this group of programs is defined in codes "
                "47.0603 - 47.0699.",
            ),
            _row("47.0604", "Automobile/Automotive Mechanics Technology/Technician."),
            _row("47.0603", "Autobody/Collision and Repair Technology/Technician."),
            # series with empty definition and no children
            _row("99.99", "Orphan Series.", ""),
            # one-digit family written without zero padding
            _row("9.01", "Communication and Media Studies.", "Programs that focus on media."),
            # deleted rows are ignored
            _row("50.0499", "Old Design Program.", action="Deleted"),
            _row("50.04", "Design and Applied Arts.", ""),
        ],
    )
    defs = parse_cip_csv(path)

    assert "01" not in defs and "0100" not in defs  # families are not series
    assert defs["0109"].title == "Animal Sciences"
    assert defs["0109"].definition == "A group of instructional programs that focus on."
    assert defs["0109"].source == "series"

    d = defs["4706"]
    assert d.source == "children"
    assert d.definition == (
        "Autobody/Collision and Repair Technology/Technician; "
        "Automobile/Automotive Mechanics Technology/Technician."
    )

    assert defs["9999"].definition is None and defs["9999"].source == "none"
    assert defs["0901"].definition == "Programs that focus on media."
    assert defs["5004"].definition is None  # its only child was deleted


def test_parse_cip_csv_strips_excel_wrappers(tmp_path: Path) -> None:
    path = _write(tmp_path / "c.csv", [_row("11.07", "Computer Science.", "Study of computing.")])
    (d,) = parse_cip_csv(path).values()
    assert d.cip4 == "1107"
