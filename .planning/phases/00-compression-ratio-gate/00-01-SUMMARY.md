---
phase: 00-compression-ratio-gate
plan: 01
subsystem: testing
tags: [pytest, cantools, dbc, telemetry-package-skeleton]

# Dependency graph
requires: []
provides:
  - "pytest test framework, runnable via `python -m pytest tests/ -x`"
  - "src/telemetry/{wire,synth,measure} package skeleton (D-07 rebuild layout root)"
  - "tests/conftest.py session-scoped dbc/dbc_path/repo_root fixtures"
  - "Executable DBC ground-truth assertions (tests/test_dbc_ground_truth.py) that later plans in this phase build against instead of RESEARCH.md prose"
  - ".gitignore allowlist for .planning/**/*.csv (closes RESEARCH.md Pitfall 2)"
affects: ["00-02", "00-03", "00-04", "00-05", "00-06", "00-07"]

# Tech tracking
tech-stack:
  added: ["cantools==42.0.3", "pytest==9.1.1"]
  patterns:
    - "Session-scoped pytest fixtures over module-level globals for shared DBC state (tests/conftest.py)"
    - "Read DBC-derived counts at runtime in tests; never hardcode as a src/ constant"

key-files:
  created:
    - requirements-dev.txt
    - pytest.ini
    - src/telemetry/__init__.py
    - src/telemetry/wire/__init__.py
    - src/telemetry/synth/__init__.py
    - src/telemetry/measure/__init__.py
    - tests/__init__.py
    - tests/conftest.py
    - tests/test_dbc_ground_truth.py
  modified:
    - .gitignore

key-decisions:
  - "Package legitimacy checkpoint (Task 1) was approved in a prior session and recorded in STATE.md Decisions — honored as already-satisfied rather than re-asked."
  - "Corrected two RESEARCH.md DBC Ground Truth figures against direct cantools measurement: cycle-time-bearing message count is 19, not 23 (RESEARCH.md's 23 was a raw grep count of the string 'GenMsgCycleTime', which double-counts the BA_DEF_/BA_DEF_DEF_ attribute-definition lines and misses that cantools treats an explicit GenMsgCycleTime of 0 as non-periodic/None); the third multiplexed message is M175_Diag_Data_Message, not INV_Diag_Buffer (which exists in the DBC but has no multiplexer signals at all)."

patterns-established:
  - "Ground-truth-by-measurement: any DBC-derived fact used by test assertions is measured live via cantools during test authoring, not copied from research prose, and the test comments record the discrepancy when one is found."

requirements-completed: [GATE-01]

coverage:
  - id: D1
    description: "pytest test framework runs green for the first time in this repository"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "python -m pytest tests/ -x"
        status: pass
    human_judgment: false
  - id: D2
    description: "src/telemetry/{wire,synth,measure} package skeleton (D-07) exists with tier-documented docstrings"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "PYTHONPATH=src python -c \"import telemetry, telemetry.wire, telemetry.synth, telemetry.measure\""
        status: pass
    human_judgment: false
  - id: D3
    description: "DBC ground-truth facts (message count, cycle-time count, multiplexed set, mux-value coverage, A5 nested-mux probe, rolling-counter names, extended-ID handling, id_index key uniqueness/bound) are asserted by executable tests"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_dbc_ground_truth.py (8 tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: ".gitignore no longer silently excludes .planning/**/*.csv report artifacts"
    verification:
      - kind: unit
        ref: "grep -c '^!\\.planning/\\*\\*/\\*\\.csv$' .gitignore"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-07-31
status: complete
---

# Phase 0 Plan 1: Toolchain Bootstrap & DBC Ground Truth Summary

**pytest + cantools installed and pinned, `src/telemetry/` D-07 package skeleton created, and RESEARCH.md's DBC assumptions replaced with 8 executable ground-truth tests — two of which caught RESEARCH.md itself being wrong.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-31T23:07:35Z
- **Completed:** 2026-07-31T23:12:47Z
- **Tasks:** 3 (1 checkpoint, 2 auto)
- **Files modified:** 10 (9 created, 1 modified)

## Accomplishments
- First test framework in this repository: `python -m pytest tests/ -x` runs green
- `src/telemetry/{wire,synth,measure}` package skeleton stood up per D-07, each tier's docstring stating what Phase 1/4 may vs. may not import
- Session-scoped `dbc`/`dbc_path`/`repo_root` fixtures in `tests/conftest.py`, hard-failing (not degraded-mode) on an unreadable DBC per RESEARCH.md's Security Domain guidance
- 8 executable assertions in `tests/test_dbc_ground_truth.py` covering every fact in RESEARCH.md's "DBC Ground Truth" section, including the A5 nested-multiplex probe (previously checked only by regex)
- `.gitignore` Pitfall 2 closed: `!.planning/**/*.csv` allowlist added, proven by a probe file appearing in `git status --porcelain`

## Task Commits

Each task was committed atomically:

1. **Task 1: Package legitimacy review — cantools and pytest** - no commit (checkpoint produces no artifacts; approved in a prior session, recorded in STATE.md Decisions)
2. **Task 2: Toolchain bootstrap — manifest, pytest config, package skeleton, gitignore allowlist** - `5a64e40` (feat)
3. **Task 3: DBC ground-truth probe** - `9736ceb` (test)

**Plan metadata:** pending (this commit)

## Files Created/Modified
- `requirements-dev.txt` - Pins `cantools==42.0.3` and `pytest==9.1.1`, Phase-0-scoped
- `pytest.ini` - `pythonpath = src`, `testpaths = tests`, `addopts = -ra`
- `src/telemetry/__init__.py` - First package in the repo; states its role as the D-07 rebuild layout root
- `src/telemetry/wire/__init__.py` - Car-side telemetry library docstring (Phase 1/4 import boundary)
- `src/telemetry/synth/__init__.py` - Phase-0-only synthetic generation docstring
- `src/telemetry/measure/__init__.py` - Phase-0-only measurement/report docstring
- `tests/__init__.py` - First test package
- `tests/conftest.py` - `dbc_path`, `dbc`, `repo_root` session-scoped fixtures; explicit re-raise with resolved path on load failure
- `tests/test_dbc_ground_truth.py` - 8 tests asserting DBC ground truth, all counts read at runtime
- `.gitignore` - Added `!.planning/**/*.csv` allowlist line immediately after the `*.csv` rule

## Decisions Made
- Honored the already-recorded package-legitimacy approval from STATE.md rather than re-running Task 1's checkpoint — no new approval was granted in this session, an existing one was read.
- Wrote Task 3's assertions against directly-measured cantools output rather than RESEARCH.md's stated figures, since two of RESEARCH.md's DBC Ground Truth numbers turned out to be wrong (see Deviations below). The whole point of this test file is to be the source of truth going forward, so encoding a known-wrong number into it would have been self-defeating.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected the cycle-time-bearing message count from RESEARCH.md's 23 to the measured 19**
- **Found during:** Task 3 (writing `test_cycle_time_bearing_message_count`)
- **Issue:** RESEARCH.md's "DBC Ground Truth" table states 23 messages carry `GenMsgCycleTime`. Direct measurement in this session found `grep -c 'BA_ "GenMsgCycleTime"'` returns 21 (RESEARCH.md's 23 additionally counted the `BA_DEF_`/`BA_DEF_DEF_` attribute-definition lines, which are not per-message assignments). Of those 21 per-message assignments, two (`BO_ 194`, `BO_ 193`) set an explicit value of `0`; cantools' `message.cycle_time` property treats an explicit `0` as "not periodic" and returns `None`, not `0`. The true count of messages with a non-`None` `cycle_time`, as read by the exact API the plan's later plans will use, is 19.
- **Fix:** `tests/test_dbc_ground_truth.py::test_cycle_time_bearing_message_count` asserts 19, with an inline comment explaining the discrepancy and why 19 (not 21, not 23) is correct.
- **Files modified:** `tests/test_dbc_ground_truth.py`
- **Verification:** `python -m pytest tests/test_dbc_ground_truth.py::test_cycle_time_bearing_message_count -q` passes; hand-verified via `sum(1 for m in db.messages if m.cycle_time is not None)` in an interactive check against every one of the 21 `BA_` lines individually.
- **Committed in:** `9736ceb` (Task 3 commit)

**2. [Rule 1 - Bug] Corrected the third multiplexed message name from RESEARCH.md's `INV_Diag_Buffer` to the measured `M175_Diag_Data_Message`**
- **Found during:** Task 3 (writing `test_multiplexed_message_names`)
- **Issue:** RESEARCH.md names the three multiplexed messages as `CAR_ERROR_STATE`, `CAN_ENERGY_METER_TEMPERATURE`, and `INV_Diag_Buffer` (with 6 mux values). Direct measurement found `INV_Diag_Buffer` exists in the DBC but `is_multiplexed()` is `False` — none of its 5 signals declare `is_multiplexer` or `multiplexer_ids`. The message that actually matches RESEARCH.md's description (a diagnostic buffer with mux values 0-5, 19 signals split across 3 record groups) is `M175_Diag_Data_Message`.
- **Fix:** `tests/test_dbc_ground_truth.py::test_multiplexed_message_names` asserts the corrected set `{"CAR_ERROR_STATE", "CAN_ENERGY_METER_TEMPERATURE", "M175_Diag_Data_Message"}`, with an inline comment explaining the discrepancy.
- **Files modified:** `tests/test_dbc_ground_truth.py`
- **Verification:** `python -m pytest tests/test_dbc_ground_truth.py::test_multiplexed_message_names -q` passes; hand-verified by inspecting every signal of both `INV_Diag_Buffer` and `M175_Diag_Data_Message` interactively.
- **Committed in:** `9736ceb` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — correcting factually wrong reference values inherited from RESEARCH.md into the plan's `<behavior>` block)
**Impact on plan:** Both corrections are exactly what this task exists to catch — a DBC fact that was checked in research by a method (grep / regex / prose recollection) less authoritative than loading the file with `cantools` directly. GATE-02's classifier work in later plans now has correct multiplexed-message and cycle-time populations to build against instead of inheriting the same two errors. No scope creep — no new files, no new dependencies, only corrected assertion values within the one file this task creates.

## Issues Encountered
None beyond the two deviations above — Python 3.12.10 was already confirmed on PATH at session start (native Windows CPython, per STATE.md's recorded decision), so Task 2's precondition was met without incident.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plans 00-02 through 00-06 (encoder/decoder core, classifier, synthetic generator, measurement/report tooling) can now rely on a working `pytest` suite, the `src/telemetry/` package layout, and a corrected, executable DBC ground-truth baseline instead of RESEARCH.md prose.
- No blockers. The two corrected figures (19 cycle-time-bearing messages, `M175_Diag_Data_Message` as the third multiplexed message) should be treated as authoritative by any later plan that references RESEARCH.md's DBC Ground Truth table — this SUMMARY and the test file itself are now the source of truth for those two facts.

---
*Phase: 00-compression-ratio-gate*
*Completed: 2026-07-31*

## Self-Check: PASSED

All 9 created files found on disk; both task commits (`5a64e40`, `9736ceb`) found in git history.
