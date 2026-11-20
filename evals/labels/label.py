"""Terminal labeling tool for the retrieval benchmark (criteria.md pass 2).

Shows the persona (summary, interests, dream, stated wants) and one pooled school at a
time — name, city/state, control/size/locale, matched programs + earnings, net price at
the bracket (+ out-of-state estimate), admission rate, SAT/ACT range, distance — with no
source, rank or score. One keypress per school:

    0 poor fit   1 acceptable   2 strong fit   s unsure (= 0, noted)   b back   q quit + save

After the last row: Enter/f finishes, b goes back. There is no skip: criteria.md judges
every shown school, so "unsure" is recorded as S1 = 0 and listed in ``notes``.

Progress is saved after every key (``evals/labels/progress/<persona>.json``), so it is
resumable. When a persona's last row is scored, the entry is written to
``evals/labels/labels.yaml`` in the frozen format:

* ``acceptable_unitids`` = S1 ≥ 1, after the H4 band-mix check (more than 1/3 reaches
  where the student is below the school's median -> drop the lowest S1 first) and the
  10–25 target (> 25 -> keep S1 = 2 only);
* ``judged_unitids`` = every shown row + every auto-judged (hard-criterion fail)
  system pick from the pool meta;
* ``notes`` (auto notes + your optional one-liner), ``labeled_at``, plus
  ``major_cip4s``, ``pool_size``, ``relaxed``; ``_meta`` carries ``criteria_commit``.

Usage (from ``backend/``)::

    uv run python ../evals/labels/label.py              # next unlabeled persona, priority order
    uv run python ../evals/labels/label.py --persona maya-oh
    uv run python ../evals/labels/label.py --validate   # check labels.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [p for p in (str(_REPO), str(_REPO / "backend")) if p not in sys.path]

import argparse  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
from collections.abc import Callable, Iterator  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import date  # noqa: E402
from typing import Any  # noqa: E402

import yaml  # noqa: E402

from evals.common import (  # noqa: E402
    DEFAULT_LABELS,
    LABELS_DIR,
    PERSONA_DIR,
    Persona,
    git_sha,
    load_persona,
    load_personas,
)
from evals.labels.pool import POOLS_DIR, student_score  # noqa: E402

PROGRESS_DIR = LABELS_DIR / "progress"
TARGET_MIN, TARGET_MAX = 10, 25
REACH_RATE = 0.25
FINISH_KEYS = {"f", "\r", "\n", ""}
UNSURE = "unsure"

# criteria.md "Time budget": voice subset first, then one persona per edge case, then rest.
VOICE_SUBSET = (
    "maya-oh marcus-al aaliyah-ga ethan-vt priya-nj bella-la jose-nm destiny-ms kenji-hi luis-il"
).split()


# ----------------------------------------------------------------- yaml format


class _Dumper(yaml.SafeDumper):
    pass


def _list_repr(dumper: yaml.SafeDumper, data: list[Any]) -> yaml.Node:
    flow = all(isinstance(x, int | float | str) for x in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_Dumper.add_representer(list, _list_repr)


def dump_labels(doc: dict[str, Any]) -> str:
    return yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def load_labels_doc(path: Path) -> dict[str, Any]:
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def validate_labels(doc: dict[str, Any]) -> list[str]:
    """Frozen-format checks (criteria.md "labels.yaml format")."""
    errors: list[str] = []
    if "_meta" not in doc or not (doc["_meta"] or {}).get("criteria_commit"):
        errors.append("_meta.criteria_commit missing")
    for pid, e in doc.items():
        if str(pid).startswith("_"):
            continue
        if not isinstance(e, dict):
            errors.append(f"{pid}: entry is not a mapping")
            continue
        for key in ("acceptable_unitids", "judged_unitids", "notes", "labeled_at"):
            if key not in e:
                errors.append(f"{pid}: missing {key}")
        acc, jud = e.get("acceptable_unitids") or [], e.get("judged_unitids") or []
        if not all(isinstance(x, int) for x in [*acc, *jud]):
            errors.append(f"{pid}: unitids must be ints")
        if not set(acc) <= set(jud):
            errors.append(f"{pid}: acceptable_unitids not a subset of judged_unitids")
        if "notes" in e and not isinstance(e["notes"], str):
            errors.append(f"{pid}: notes must be a string")
        try:
            date.fromisoformat(str(e.get("labeled_at")))
        except ValueError:
            errors.append(f"{pid}: labeled_at is not an ISO date")
    return errors


# ------------------------------------------------------------------ session


@dataclass
class LabelSession:
    persona: Persona
    rows: list[dict[str, str]]
    meta: dict[str, Any]
    scores: dict[int, int | str] = field(default_factory=dict)  # unitid -> 0/1/2 or "unsure"
    idx: int = 0

    def __post_init__(self) -> None:
        # resume at the first row without a score
        while self.idx < len(self.rows) and self.uid(self.idx) in self.scores:
            self.idx += 1

    def uid(self, i: int) -> int:
        return int(self.rows[i]["unitid"])

    @property
    def done(self) -> bool:
        return self.idx >= len(self.rows)

    def apply(self, key: str) -> str:
        """Returns 'scored' | 'unsure' | 'back' | 'quit' | 'ignored'."""
        if key == "q":
            return "quit"
        if key == "b":
            self.idx = max(0, self.idx - 1)
            return "back"
        if self.done:
            return "ignored"
        if key in ("0", "1", "2"):
            self.scores[self.uid(self.idx)] = int(key)
            self.idx += 1
            return "scored"
        if key == "s":
            self.scores[self.uid(self.idx)] = UNSURE
            self.idx += 1
            return "unsure"
        return "ignored"

    def progress(self) -> dict[str, Any]:
        return {"persona": self.persona.id, "scores": {str(k): v for k, v in self.scores.items()}}


def _f(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _median_gap(row: dict[str, str], hidden: dict[str, Any]) -> float | None:
    """Student score minus the school's median (mid of 25th–75th), using the same unit
    rule as H4 (:func:`evals.labels.pool.student_score`)."""
    got = student_score(hidden, bool(row.get("sat_range")), bool(row.get("act_range")))
    if got is None:
        return None
    unit, mine = got
    lo, hi = (float(x) for x in row[f"{unit}_range"].split("-"))
    return mine - (lo + hi) / 2


def finalize(
    persona: Persona,
    rows: list[dict[str, str]],
    scores: dict[int, int | str],
    meta: dict[str, Any],
    note: str = "",
    today: date | None = None,
) -> dict[str, Any]:
    """Build the labels.yaml entry (band-mix check + 10–25 target applied)."""
    by_uid = {int(r["unitid"]): r for r in rows}
    hidden = persona.hidden
    notes: list[str] = []
    graded = {u: (s if isinstance(s, int) else 0) for u, s in scores.items() if u in by_uid}
    acceptable = {u: s for u, s in graded.items() if s >= 1}

    has_stats = any(hidden.get(k) is not None for k in ("gpa", "sat", "act"))
    if has_stats and acceptable:

        def is_reach(u: int) -> bool:
            r = by_uid[u]
            rate = _f(r.get("admission_rate"))
            gap = _median_gap(r, hidden)
            return rate is not None and rate < REACH_RATE and gap is not None and gap < 0

        removed: list[int] = []
        while True:
            reaches = [u for u in acceptable if is_reach(u)]
            if not reaches or len(reaches) <= len(acceptable) / 3:
                break
            drop = min(reaches, key=lambda u: (acceptable[u], u))
            removed.append(drop)
            del acceptable[drop]
        if removed:
            notes.append(f"H4 band-mix: removed reaches {sorted(removed)}.")

    if len(acceptable) > TARGET_MAX:
        strong = {u: s for u, s in acceptable.items() if s == 2}
        if len(strong) > TARGET_MAX:
            notes.append(f"{len(strong)} strong fits (> {TARGET_MAX}); kept all S1=2.")
        else:
            notes.append(f"{len(acceptable)} acceptable (> {TARGET_MAX}); kept S1=2 only.")
        acceptable = strong
    elif len(acceptable) < TARGET_MIN:
        notes.append(f"Only {len(acceptable)} acceptable (< {TARGET_MIN}).")

    unsure = sorted(u for u, s in scores.items() if s == UNSURE and u in by_uid)
    if unsure:
        notes.append(f"Unsure (scored S1=0): {unsure}.")
    if meta.get("relaxed"):
        notes.append(f"H2 relaxed: {meta['relaxed']}.")
    auto = [int(a["unitid"]) for a in meta.get("auto_judged") or []]
    judged = sorted(set(graded) | set(auto))
    if note.strip():
        notes.insert(0, note.strip())
    entry: dict[str, Any] = {
        "acceptable_unitids": sorted(acceptable),
        "notes": " ".join(notes),
        "labeled_at": (today or date.today()).isoformat(),
        "judged_unitids": judged,
        "major_cip4s": [f"{c[:2]}.{c[2:]}" for c in meta.get("major_cip4s") or []],
        "pool_size": meta.get("pool_size"),
        "relaxed": list(meta.get("relaxed") or []),
    }
    return entry


def write_entry(
    labels_path: Path, persona_id: str, entry: dict[str, Any], meta: dict[str, Any]
) -> None:
    doc = load_labels_doc(labels_path)
    head = dict(doc.get("_meta") or {})
    head.setdefault(
        "criteria_commit", meta.get("criteria_commit") or git_sha(LABELS_DIR / "criteria.md")
    )
    head.setdefault("labeler", "project owner")
    head["candidate_tool_version"] = meta.get("candidate_tool_version") or head.get(
        "candidate_tool_version", "unknown"
    )
    out: dict[str, Any] = {"_meta": head}
    for k, v in doc.items():
        if k != "_meta":
            out[k] = v
    out[persona_id] = entry
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    labels_path.write_text(dump_labels(out))


# --------------------------------------------------------------------- UI


def render_header(p: Persona) -> str:
    h = p.hidden

    def j(xs: Any) -> str:
        return ", ".join(str(x).replace("_", " ") for x in xs) if xs else "-"

    lines = [
        f"\033[1m{p.id}\033[0m — {p.summary}",
        f"  interests: {j(h.get('interests'))}",
        f"  dream: {h.get('dream_without_money', '-')}",
        f"  majors: {j(h.get('intended_majors'))} | strengths: {j(h.get('strengths'))}",
        f"  size: {h.get('size_pref', '-')} | setting: {h.get('setting_pref', '-')} | "
        f"regions: {j(h.get('regions'))} | priorities: {j(h.get('priorities'))}",
    ]
    if p.quirks:
        lines.append("  said: " + " / ".join(p.quirks))
    return "\n".join(lines)


def render_row(row: dict[str, str], i: int, n: int, prev: int | str | None) -> str:
    def money(v: str) -> str:
        return f"${int(float(v)):,}" if v else "?"

    size = (
        f"{int(float(row['undergrad_size'])):,} undergrads"
        if row.get("undergrad_size")
        else "size ?"
    )
    oos = (
        f" (out-of-state est {money(row['out_of_state_estimate'])})"
        if row.get("out_of_state_estimate")
        else ""
    )
    dist = f" · {row['distance_miles']} mi" if row.get("distance_miles") else ""
    lines = [
        "",
        f"[{i + 1}/{n}]" + (f"  (current: {prev})" if prev is not None else ""),
        f"  \033[1m{row['name']}\033[0m — {row['city']}, {row['state']}",
        f"  {row['control']} · {size} · {row.get('locale') or 'locale ?'}{dist}",
        f"  net price {money(row.get('net_price', ''))}{oos} · admit "
        f"{row.get('admission_rate') or '?'} · SAT {row.get('sat_range') or '-'} · "
        f"ACT {row.get('act_range') or '-'}",
        f"  programs: {row.get('programs') or '-'}",
        "  [0] poor  [1] acceptable  [2] strong   [s] unsure(=0)  [b]ack  [q]uit+save",
    ]
    return "\n".join(lines)


def read_key() -> str:
    """One keypress (raw mode on a TTY; a line otherwise)."""
    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        return line.strip()[:1] if line else "q"
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return "q" if ch in ("\x03", "\x04") else ch.lower()


def load_pool(persona_id: str, pools_dir: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    csv_path = pools_dir / f"{persona_id}.csv"
    meta_path = pools_dir / f"{persona_id}.meta.yaml"
    if not csv_path.exists():
        raise FileNotFoundError(f"no pool for {persona_id}: run `make pool` first ({csv_path})")
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    meta = (yaml.safe_load(meta_path.read_text()) or {}) if meta_path.exists() else {}
    return rows, meta


def label_persona(
    persona: Persona,
    pools_dir: Path = POOLS_DIR,
    labels_path: Path = DEFAULT_LABELS,
    progress_dir: Path = PROGRESS_DIR,
    keys: Iterator[str] | None = None,
    out: Callable[[str], None] = print,
    ask_note: Callable[[], str] | None = None,
    restart: bool = False,
) -> str:
    """Interactive loop. Returns 'done' (entry written) or 'quit' (progress saved)."""
    rows, meta = load_pool(persona.id, pools_dir)
    prog_path = progress_dir / f"{persona.id}.json"
    saved: dict[int, int | str] = {}
    if prog_path.exists() and not restart:
        in_pool = {int(r["unitid"]) for r in rows}  # ignore scores from an older pool
        saved = {
            int(k): v
            for k, v in json.loads(prog_path.read_text())["scores"].items()
            if int(k) in in_pool
        }
    sess = LabelSession(persona, rows, meta, saved)
    next_key: Callable[[], str] = (lambda: next(keys, "q")) if keys is not None else read_key
    out(render_header(persona))
    out(f"  {len(rows)} schools to judge; {len(sess.scores)} already scored.")
    while True:
        if sess.done:
            out("  all rows scored: [Enter/f] finish and write labels.yaml  [b]ack  [q]uit+save")
            key = next_key()
            if key in FINISH_KEYS:
                break
        else:
            uid = sess.uid(sess.idx)
            out(render_row(rows[sess.idx], sess.idx, len(rows), sess.scores.get(uid)))
            key = next_key()
        action = sess.apply(key)
        progress_dir.mkdir(parents=True, exist_ok=True)
        prog_path.write_text(json.dumps(sess.progress(), indent=1) + "\n")
        if action == "quit":
            out(f"saved progress for {persona.id} ({len(sess.scores)}/{len(rows)}).")
            return "quit"
    note = ask_note() if ask_note else ""
    entry = finalize(persona, rows, sess.scores, meta, note)
    write_entry(labels_path, persona.id, entry, meta)
    out(
        f"{persona.id}: {len(entry['acceptable_unitids'])} acceptable / "
        f"{len(entry['judged_unitids'])} judged -> {labels_path}"
    )
    return "done"


def priority_order(personas: list[Persona]) -> list[Persona]:
    voice = [p for p in personas if p.id in VOICE_SUBSET]
    seen_edges: set[str] = set()
    edge_reps: list[Persona] = []
    for p in personas:
        if p in voice:
            continue
        new = set(p.meta.get("edge_cases") or []) - seen_edges
        if new:
            edge_reps.append(p)
            seen_edges |= new
    rest = [p for p in personas if p not in voice and p not in edge_reps]
    return voice + edge_reps + rest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--persona", default="", help="persona id (default: next unlabeled)")
    ap.add_argument("--pools-dir", type=Path, default=POOLS_DIR)
    ap.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    ap.add_argument("--relabel", action="store_true", help="allow re-labeling a persona")
    ap.add_argument("--validate", action="store_true", help="validate labels.yaml and exit")
    a = ap.parse_args(argv)

    if a.validate:
        errs = validate_labels(load_labels_doc(a.labels))
        for e in errs:
            print(f"ERROR {e}")
        print("labels.yaml OK" if not errs else f"{len(errs)} error(s)")
        return 1 if errs else 0

    done = {k for k in load_labels_doc(a.labels) if not str(k).startswith("_")}
    if a.persona:
        if a.persona in done and not a.relabel:
            print(f"{a.persona} is already labeled (labels are frozen; --relabel to override)")
            return 1
        queue = [load_persona(PERSONA_DIR / f"{a.persona}.yaml")]
    else:
        queue = [
            p
            for p in priority_order(load_personas())
            if p.id not in done and (a.pools_dir / f"{p.id}.csv").exists()
        ]
        if not queue:
            print("nothing to label: every persona with a pool is labeled")
            return 0

    def ask_note() -> str:
        try:
            return input("optional note for this persona (enter to skip): ")
        except EOFError:
            return ""

    for p in queue:
        restart = bool(a.relabel and a.persona)  # --relabel discards that persona's progress
        if label_persona(p, a.pools_dir, a.labels, ask_note=ask_note, restart=restart) == "quit":
            return 0
        if not a.persona:
            print("\nnext persona... (q at any row quits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
