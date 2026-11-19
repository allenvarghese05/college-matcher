"""NCES CIP 2020 CSV parsing (synthetic file in the NCES layout)."""

from __future__ import annotations

import csv
from pathlib import Path

from ingest.cip import MAX_WORDS, parse_cip_csv

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
SAME = "No substantive changes"


def _row(code: str, title: str, definition: str = "", action: str = SAME) -> dict[str, str]:
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


def _parse(tmp_path: Path, rows: list[dict[str, str]]):
    return parse_cip_csv(_write(tmp_path / "CIPCode2020.csv", rows))


def test_series_with_real_definition_wins(tmp_path: Path) -> None:
    defs = _parse(
        tmp_path,
        [
            _row("01", "AGRICULTURAL SCIENCES."),
            _row("01.09", "Animal Sciences.", "A group of programs about animals."),
            _row("01.0901", "Animal Sciences, General.", "Child text."),
        ],
    )
    assert "01" not in defs  # families are not series
    d = defs["0109"]
    assert (d.title, d.definition, d.source) == (
        "Animal Sciences",
        "A group of programs about animals.",
        "series",
    )


def test_single_child_pointer_uses_child_definition(tmp_path: Path) -> None:
    defs = _parse(
        tmp_path,
        [
            _row("11.07", "Computer Science.", "Instructional content is defined in code 11.0701."),
            _row("11.0701", "Computer Science.", "A program that focuses on computer theory"),
        ],
    )
    d = defs["1107"]
    assert d.source == "child"
    assert d.definition == "A program that focuses on computer theory."


def test_multi_child_pointer_builds_items_general_first(tmp_path: Path) -> None:
    defs = _parse(
        tmp_path,
        [
            _row(
                "47.06",
                "Vehicle Maintenance and Repair Technologies.",
                "Instructional content for this group of programs is defined in codes "
                "47.0603 - 47.0699.",
            ),
            _row("47.0604", "Automobile Mechanics.", "Prepares people to fix cars."),
            _row("47.0603", "Autobody Repair.", "Prepares people to repair bodywork."),
            _row("47.0699", "Vehicle Repair, Other.", ""),
            _row("47.0601", "Vehicle Repair, General.", "General vehicle repair."),
        ],
    )
    d = defs["4706"]
    assert d.source == "children"
    assert d.definition == (
        "Vehicle Repair, General: General vehicle repair. "
        "Autobody Repair: Prepares people to repair bodywork. "
        "Automobile Mechanics: Prepares people to fix cars. "
        "Vehicle Repair, Other."
    )


def test_multi_child_truncated_to_word_budget(tmp_path: Path) -> None:
    long_def = " ".join(["word"] * 150)
    rows = [_row("52.02", "Business.", "Instructional content is defined in codes 52.0201-99.")]
    rows += [_row(f"52.02{i:02d}", f"Child {i}.", long_def) for i in range(1, 8)]
    d = _parse(tmp_path, rows)["5202"]
    n = len((d.definition or "").split())
    assert 0 < n <= MAX_WORDS
    assert d.definition is not None and d.definition.startswith("Child 1: word")


def test_moved_to_kept_moved_from_and_deleted_dropped(tmp_path: Path) -> None:
    defs = _parse(
        tmp_path,
        [
            # whole series moved in 2020 (01.80 in the real file): KEEP
            _row(
                "01.80",
                "Veterinary Medicine.",
                "Instructional content is defined in code 01.8001.",
                action="Moved to",
            ),
            _row(
                "01.8001",
                "Veterinary Medicine.",
                "A program that prepares veterinarians.",
                action="Moved to",
            ),
            # retired code pointing at its new home: DROP
            _row(
                "01.0309",
                "Viticulture and Enology.",
                "Moved from 01.0309 to 01.1004",
                action="Moved from 01.0309 to 01.1004",
            ),
            _row("01.03", "Agricultural Production.", "Instructional content is defined in codes"),
            _row("01.0301", "Agricultural Production, General.", "Farming."),
            _row("50.04", "Design and Applied Arts.", ""),
            _row("50.0499", "Old Design Program.", "Gone.", action="Deleted"),
        ],
    )
    assert defs["0180"].definition == "A program that prepares veterinarians."
    assert defs["0103"].definition == "Farming."  # the moved-from child is not mixed in
    assert defs["0103"].source == "child"
    assert defs["5004"].definition is None and defs["5004"].source == "none"


def test_unpadded_and_excel_wrapped_codes(tmp_path: Path) -> None:
    defs = _parse(tmp_path, [_row("9.01", "Communication.", "Programs that focus on media.")])
    assert defs["0901"].definition == "Programs that focus on media."
