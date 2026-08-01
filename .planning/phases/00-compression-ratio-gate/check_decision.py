#!/usr/bin/env python3
"""Consistency gate for the Phase 0 compression-ratio go/no-go decision.

Checked in per 00-07-PLAN.md Task 2 so its assertions are readable and
re-runnable by anyone auditing the phase, rather than living as a shell
one-liner in a plan file.

Loads 00-DECISION.md, 00-REPORT.json, 00-THRESHOLD.md, and PROJECT.md, then
asserts:

  1. Every one of the nine required section headings appears in the decision.
  2. The decision cites both 00-REPORT.json and 00-THRESHOLD.md by filename.
  3. The typical bracket's kbps_all_in, rounded to one decimal, appears
     verbatim in the decision text.
  4. The single PROJECT.md Key Decisions line matching the compression-ratio
     gate no longer carries the pending marker and does link 00-DECISION.md.

Exits non-zero with a message naming the specific failure, or prints "ok"
and exits 0.
"""

import json
import sys
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parent
DECISION_PATH = PHASE_DIR / "00-DECISION.md"
REPORT_PATH = PHASE_DIR / "00-REPORT.json"
THRESHOLD_PATH = PHASE_DIR / "00-THRESHOLD.md"
PROJECT_PATH = PHASE_DIR.parent.parent / "PROJECT.md"

REQUIRED_SECTIONS = [
    "Verdict",
    "The bar it was judged against",
    "The measured result",
    "The worst-case bracket",
    "Worst-case IDs",
    "What the ablations say",
    "Critical channels",
    "What this decision rests on",
    "What later phases should build against",
]

COMPRESSION_GATE_ROW_MARKER = "Compression ratio becomes a go/no-go gate before transport work"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    for path in (DECISION_PATH, REPORT_PATH, THRESHOLD_PATH, PROJECT_PATH):
        if not path.exists():
            fail(f"required file missing: {path}")

    decision_text = DECISION_PATH.read_text(encoding="utf-8")
    threshold_text = THRESHOLD_PATH.read_text(encoding="utf-8")
    project_text = PROJECT_PATH.read_text(encoding="utf-8")

    with REPORT_PATH.open(encoding="utf-8") as f:
        report = json.load(f)

    # 1. Every required section heading appears in the decision.
    missing_sections = [s for s in REQUIRED_SECTIONS if s not in decision_text]
    if missing_sections:
        fail(
            "00-DECISION.md is missing required section(s): "
            + ", ".join(missing_sections)
        )

    # 2. The decision cites both source files by filename.
    if "00-REPORT.json" not in decision_text:
        fail("00-DECISION.md does not cite 00-REPORT.json by filename")
    if "00-THRESHOLD.md" not in decision_text:
        fail("00-DECISION.md does not cite 00-THRESHOLD.md by filename")
    # Sanity: the threshold file itself must be non-empty (regression guard,
    # not a decision-content check).
    if not threshold_text.strip():
        fail("00-THRESHOLD.md is empty")

    # 3. The typical bracket's kbps_all_in, rounded to one decimal, appears
    #    verbatim in the decision text.
    try:
        typical_kbps_all_in = report["brackets"]["typical"]["aggregate"]["kbps_all_in"]
    except KeyError as exc:
        fail(f"00-REPORT.json missing expected key: {exc}")
    else:
        rounded = f"{round(typical_kbps_all_in, 1):.1f}"
        if rounded not in decision_text:
            fail(
                "00-DECISION.md does not quote the typical bracket's "
                f"kbps_all_in ({rounded}) verbatim"
            )

    # 4. PROJECT.md's compression-ratio-gate Key Decisions row no longer
    #    reads Pending and links 00-DECISION.md.
    matching_lines = [
        line
        for line in project_text.splitlines()
        if COMPRESSION_GATE_ROW_MARKER in line
    ]
    if len(matching_lines) != 1:
        fail(
            "expected exactly one PROJECT.md Key Decisions row matching "
            f"'{COMPRESSION_GATE_ROW_MARKER}', found {len(matching_lines)}"
        )
    row = matching_lines[0]
    if "Pending" in row:
        fail("PROJECT.md compression-ratio-gate row still contains 'Pending'")
    if "00-DECISION.md" not in row:
        fail("PROJECT.md compression-ratio-gate row does not link 00-DECISION.md")

    print("ok")
    sys.exit(0)


if __name__ == "__main__":
    main()
