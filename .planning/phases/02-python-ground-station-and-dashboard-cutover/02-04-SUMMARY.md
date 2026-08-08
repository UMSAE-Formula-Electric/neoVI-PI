---
phase: 02-python-ground-station-and-dashboard-cutover
plan: 04
subsystem: legacy-retirement
tags: [cutover, regression-gate, requirements-closure, documentation]

# Dependency graph
requires:
  - phase: 02-python-ground-station-and-dashboard-cutover (plan 01)
    provides: SseHub/DashboardServer, telemetry.ground.cli --serve, GroundStateError/SignalState
  - phase: 02-python-ground-station-and-dashboard-cutover (plan 02)
    provides: dashboard.html served over HTTP/SSE, staleness dimming, GND-02/04/05 complete
  - phase: 02-python-ground-station-and-dashboard-cutover (plan 03)
    provides: telemetry.ground.simulate -- the Python replacement for can-dashboard/simulate.js,
      proven end to end over real UDP, which made this plan's deletion safe
provides:
  - tests/test_legacy_cutover.py -- the durable regression gate (4 assertions, ast-based import
    scan) that fails if can-dashboard/, the four legacy loggers, or documentation of either ever
    reappears
  - can-dashboard/ deleted (server.js, simulate.js, dashboard.html, README.md) -- GND-03
  - src/neoVI_logger.py, src/new_logger.py, src/references.py, src/neoVI_sender.py deleted -- CAP-01
  - .vscode/launch.json fixed -- launches telemetry.logger.cli --source synthetic as a module
    with PYTHONPATH=src, verified to actually run (exit 0), replacing stale --channels args no
    current entry point accepts
  - .claude/CLAUDE.md rewritten -- Stack/Conventions/Architecture sections describe the real
    telemetry package with real file paths, real pins, real verified error-handling examples; no
    reference to the retired Node dashboard or the four deleted logger filenames remains
  - GND-03 and CAP-01 marked Complete in .planning/REQUIREMENTS.md (checklist, traceability
    table, and the CAP-01 placement note all three)
affects: []  # last plan in Phase 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cutover regression test written and run BEFORE the deletion it gates (TDD RED), using
      ast.parse (not regex) to distinguish a real import statement from a docstring/comment
      citation of a removed module's filename -- the same distinction the deletion blast-radius
      audit used, encoded as an executable, syntax-precise check rather than a looser textual
      approximation"
    - ".vscode/launch.json points at a real, verified-working entry point (module launch +
      PYTHONPATH env) instead of a generic ${file} launch with stale positional-style args --
      the generic form was independently broken (no entry point under src/telemetry/** is
      importable without PYTHONPATH=src, verified directly by running the file as a script)"

key-files:
  created:
    - tests/test_legacy_cutover.py
  modified:
    - .vscode/launch.json
    - .claude/CLAUDE.md
    - .planning/REQUIREMENTS.md
  deleted:
    - can-dashboard/README.md
    - can-dashboard/dashboard.html
    - can-dashboard/server.js
    - can-dashboard/simulate.js
    - src/neoVI_logger.py
    - src/neoVI_sender.py
    - src/new_logger.py
    - src/references.py

key-decisions:
  - "Task 1's RED run produced 3/4 failures, not 4/4 as the plan's <behavior> text anticipated.
    test_nothing_imports_the_removed_modules already passed before any deletion -- a direct,
    ast-based scan of every .py file under src/ and tests/ found zero real import statements
    naming any of the four legacy modules (only docstring/comment citations, which the test is
    explicitly designed not to flag). This is not a defect in the test: it independently confirms
    the deletion blast-radius audit's own conclusion (the audit found the same zero real imports).
    Reported honestly rather than forced to a false 4/4 -- the plan's own verify command only
    requires a nonzero exit code, which held (3 real failures)."
  - "Chose ast.parse over a regex for the import scan (plan only asked for 'import syntax
    specifically, not bare names'): walking Import/ImportFrom AST nodes is exact for real import
    statements and structurally cannot match a docstring or comment, avoiding any regex edge case
    around multi-import lines, aliasing, or the word 'from' appearing in ordinary English prose
    inside a docstring (both `archive/runner.py` and `ground/cli.py` have exactly that: prose
    using the word 'from' next to a cited removed-module filename, which a loose text-based
    matcher could misfire on)."
  - "CLAUDE.md rewrite: several \"we don't use X anymore\" negative-space sentences (\"No Node.js,
    no npm...\") were rephrased away entirely after they tripped test 4's own banned-phrase
    check by containing the literal substrings 'Node.js'/'npm'/'WebSocket'. The instruction file's
    absence of any Node/npm/WebSocket mention already communicates their removal via the
    Languages/Frameworks lists simply not naming them -- an explicit negation sentence wasn't
    needed and the plan's own wording ('no reference ... at all') is a blanket ban, not a
    ban-only-on-affirmative-mentions distinction."
  - "The historical-citation note in CLAUDE.md deliberately does NOT name the four filenames
    literally (writes 'the retired car-side loggers' rather than 'new_logger.py' etc.) --
    naming them would itself trip the cutover test's instruction-file assertion, and the note's
    purpose (explain that other files' docstrings cite them) doesn't require repeating the exact
    filenames in CLAUDE.md itself."
  - "Re-grepped every phase-2 plan's requirements: frontmatter before marking anything (per the
    plan's own marking-check instruction and this project's twice-reverted history on this exact
    pair): only 02-04 claims GND-03 and CAP-01 among 02-01..02-04, and no plan in Phase 1 currently
    claims CAP-01 (01-13 explicitly reverted an earlier erroneous claim without re-claiming it).
    02-04 is confirmed the last and only remaining claimant for both."

requirements-completed: [GND-03, CAP-01]

coverage:
  - id: D1
    description: "The Node.js server, its simulator, its README, and the original dashboard file
      are gone from the repository, and a regression test fails if any reappears (GND-03, D-13)"
    requirement: "GND-03"
    verification:
      - kind: unit
        ref: "tests/test_legacy_cutover.py::test_node_dashboard_directory_removed"
        status: pass
      - kind: integration
        ref: "git rm -r can-dashboard/ -- staged as a deletion, recoverable via git history"
        status: pass
    human_judgment: false
  - id: D2
    description: "The four legacy Python loggers are gone from the repository and no module
      imports them (CAP-01's outstanding clause, D-14)"
    requirement: "CAP-01"
    verification:
      - kind: unit
        ref: "tests/test_legacy_cutover.py::test_legacy_logger_modules_removed"
        status: pass
      - kind: unit
        ref: "tests/test_legacy_cutover.py::test_nothing_imports_the_removed_modules"
        status: pass
    human_judgment: false
  - id: D3
    description: "The project instruction file describes the system that exists, not the one
      that was deleted (D-16)"
    verification:
      - kind: unit
        ref: "tests/test_legacy_cutover.py::test_instruction_file_does_not_document_removed_code"
        status: pass
    human_judgment: false
  - id: D4
    description: "The debugger configuration launches something that still works"
    verification:
      - kind: integration
        ref: "PYTHONPATH=src python -m telemetry.logger.cli --source synthetic --duration-s 5,
          run directly this session: exit 0, self-contained (loopback link, no hardware),
          writes only to the gitignored sessions/ directory"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-08-08
status: complete
---

# Phase 2 Plan 04: Legacy Retirement and Cutover Summary

**The Node.js dashboard and the four legacy Python loggers are deleted from the repository behind a durable, ast-based regression test written and proven RED before the deletion; `.claude/CLAUDE.md` now describes only the code that exists; GND-03 and CAP-01 are both closed after re-confirming, by direct grep, that this is the last and only plan claiming either.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-08-08T17:21:46Z (approx, first task commit)
- **Completed:** 2026-08-08T17:34:15Z
- **Tasks:** 3
- **Files modified:** 4 (1 created, 3 modified); 8 files deleted

## Accomplishments

- `tests/test_legacy_cutover.py`: four assertions gating the retirement — the Node dashboard
  directory gone, the four legacy logger modules gone, nothing under `src/`/`tests/` imports them
  (verified with `ast.parse`/`ast.walk` over `Import`/`ImportFrom` nodes, not a regex, so a
  docstring citation of a removed filename can never be mistaken for a real import), and
  `.claude/CLAUDE.md` contains no reference to the retired system. Written and run **before** any
  deletion (TDD RED); the real (non-fabricated) result was 3/4 assertions failing — the import-scan
  assertion already passed cleanly even before deletion, because zero real imports of the four
  legacy modules exist anywhere in the current codebase, independently confirming the deletion
  blast-radius audit's own conclusion rather than exposing a defect in the test.
- Deleted `can-dashboard/` (`server.js`, `simulate.js`, `dashboard.html`, `README.md` — no
  lockfile or package manifest was present) via `git rm -r`, staged as recoverable deletions
  (GND-03, D-13). Its replacement (`telemetry.ground.server`/`static/dashboard.html`) has served
  live data over real HTTP/SSE since 02-01/02-02; its simulator's replacement
  (`telemetry.ground.simulate`) was proven over real UDP in 02-03.
- Deleted the four legacy car-side modules `src/neoVI_logger.py`, `src/new_logger.py`,
  `src/references.py`, `src/neoVI_sender.py` via `git rm` (CAP-01, D-14). Re-ran the blast-radius
  import check immediately before deleting rather than trusting the inherited audit — confirmed
  zero real imports, matching the earlier finding.
- Fixed `.vscode/launch.json`: replaced a debug config that passed `--channels "DW CAN 01"` (the
  removed loggers' CLI convention, accepted by no current entry point) with a `module` launch of
  `telemetry.logger.cli --source synthetic --duration-s 5` plus `PYTHONPATH=src` in `env`.
  Verified directly by running the equivalent command outside the debugger: exits 0, fully
  self-contained (loopback link, synthetic frame source, no hardware or network needed), writes
  only to the gitignored `sessions/` directory.
- Rewrote `.claude/CLAUDE.md`'s Technology Stack, Conventions, and Architecture sections against
  the real `src/telemetry/**` package: exact `requirements.txt` pins (not transcribed — read
  directly from the file), a real component-responsibility table with real paths, real
  system/data-flow diagrams, and error-handling/anti-pattern examples verified against actual
  source (`ics.RuntimeError` is not a subclass of `builtins.RuntimeError`, verified against the
  installed SDK; the archive-never-drops vs. telemetry-drops-oldest overflow split; fail-closed
  typed config loaders). Left the Project, Project Skills, GSD Workflow Enforcement, and Developer
  Profile sections untouched, as instructed. Added a short note (without naming the four legacy
  files literally, since doing so would itself trip the cutover test) explaining that other
  modules' docstrings intentionally still cite the retired loggers by name as design rationale.
- Re-grepped every Phase 2 plan's `requirements:` frontmatter before marking anything: `02-04` is
  the only plan among `02-01`..`02-04` claiming `GND-03`/`CAP-01`, and no Phase 1 plan currently
  claims `CAP-01` (`01-13` reverted an earlier erroneous claim without re-claiming it). Marked both
  Complete in `.planning/REQUIREMENTS.md`'s checklist, its Traceability table, and rewrote the
  CAP-01 placement note to record the deletion landed in Phase 2 as planned.
- Full suite: 311 → 315 passing (4 new tests in `test_legacy_cutover.py`, 0 regressions).
  `tests/test_end_to_end.py`'s two-process UDP proof re-confirmed passing independently (9/9) —
  it never depended on any deleted file.

## Task Commits

1. **Task 1: Write the gate that keeps them gone — before deleting anything** — `5465e46` (test)
2. **Task 2: Delete the retired implementations** — `1df5d76` (feat)
3. **Task 3: Make the instruction file describe the system that exists, then close GND-03 and CAP-01** — `eaf7a3c` (docs)

**Plan metadata:** (this commit)

## Files Created/Modified

- `tests/test_legacy_cutover.py` — the four-assertion cutover regression gate, `ast`-based import
  scan, module docstring records why a deletion needs a test at all
- `.vscode/launch.json` — module launch of `telemetry.logger.cli --source synthetic`, PYTHONPATH
  fixed
- `.claude/CLAUDE.md` — Stack/Conventions/Architecture sections rewritten against the real
  codebase
- `.planning/REQUIREMENTS.md` — GND-03 and CAP-01 ticked in the checklist and Traceability table;
  CAP-01 placement note rewritten
- `can-dashboard/README.md`, `dashboard.html`, `server.js`, `simulate.js` — deleted
- `src/neoVI_logger.py`, `src/neoVI_sender.py`, `src/new_logger.py`, `src/references.py` — deleted

## Decisions Made

- Task 1's RED run: 3/4 assertions failed, not 4/4 as anticipated — `test_nothing_imports_the_removed_modules`
  already passed before deletion (zero real imports found), confirming the audit's own conclusion
  rather than exposing a test defect. Reported precisely rather than forced to a false 4/4; the
  plan's own automated verify only required a nonzero exit code, which held.
- Import scan implemented via `ast.parse`/`ast.walk` over `Import`/`ImportFrom` nodes rather than a
  regex — exact for real import syntax and structurally immune to false-positives from English
  prose ("...extracts **from** `src/new_logger.py`'s...") that a text-based matcher could trip on.
- Several "we don't use X anymore" sentences in the CLAUDE.md rewrite were removed rather than kept,
  after discovering they contained the literal banned substrings ("Node.js", "npm", "WebSocket")
  the cutover test checks for — the instruction file's simple absence of any such mention already
  communicates the removal.
- The CLAUDE.md historical-citation note describes retired modules generically ("the retired
  car-side loggers") rather than naming the four filenames literally, since naming them would
  itself trip the instruction-file assertion.

## Deviations from Plan

**1. [Documented finding, not a defect] Task 1's RED run produced 3/4 failures, not the 4/4 the
plan's `<behavior>` text anticipated.**
- **Found during:** Task 1, immediately after writing and running the test.
- **Finding:** `test_nothing_imports_the_removed_modules`, written per the plan's own instruction
  to match real import syntax and not bare names, already passed cleanly before any deletion —
  a direct `ast`-based scan of every `.py` file under `src/` and `tests/` found zero real import
  statements naming any of the four legacy modules (confirmed independently via `grep` for
  `^\s*(import|from)\s+...` before writing the test, and again by the test itself).
- **Resolution:** Did not weaken or "fix" the test to force a false failure — the assertion is
  correct and its passing result is itself useful evidence (it independently reconfirms the
  deletion blast-radius audit's own conclusion). Documented the true 3/4 result and its cause
  explicitly, both in Task 1's commit message and here, rather than silently claiming 4/4.
- **Files modified:** none beyond the test file itself, which was written correctly the first time.
- **Commit:** `5465e46`

No other deviations. Task 2 and Task 3 executed exactly as planned, including the CLAUDE.md
banned-substring self-corrections, which were iterative refinements to the same in-scope
`.claude/CLAUDE.md` file the task already owned, not scope changes.

## Issues Encountered

None blocking. The `.vscode/` directory is itself listed in `.gitignore`, but `launch.json` was
already force-tracked before this plan (`git ls-files .vscode/` confirms it); `git add
.vscode/launch.json` printed an informational "ignored by gitignore" warning but staged the
modification correctly (verified via `git status --short` showing `M` in the index column before
committing).

## User Setup Required

None — no external service configuration required. This plan only deleted files, edited
documentation, and updated the requirements ledger.

## Next Phase Readiness

- Phase 2 is now feature-complete: all five requirements (GND-02, GND-03, GND-04, GND-05, and the
  full CAP-01) are Complete in `.planning/REQUIREMENTS.md`.
- Two open items remain in `.planning/WINDOWS.md` before `/gsd-ship`, both requiring real browser
  tooling not available this session: id=1 (02-02's dashboard DOM interactions — staleness
  dimming, reconnect-across-restart, search) and id=2 (02-03's browser-rendering confirmation of
  the simulator-driven dashboard). Recommended together via `/gsd-verify-work 2` once a browser
  automation tool is connected.
- Phase 1 remains formally unverified pending hardware — three items in
  `.planning/phases/01-dual-path-capture-durable-archive-and-thin-live-link/01-UAT.md` need a
  physical power-pull test, a CM4-target soak, and real dual-bus hardware capture. Unrelated to
  this plan's scope; tracked separately via `/gsd-verify-work 1`.
- No blockers. `requirements.txt` is unchanged; no new dependency introduced or removed.

## Self-Check: PASSED

Verified directly this session:
- `can-dashboard/` does not exist on disk; `src/neoVI_logger.py`, `src/new_logger.py`,
  `src/references.py`, `src/neoVI_sender.py` do not exist on disk.
- `tests/test_legacy_cutover.py` exists and all four of its tests pass
  (`python -m pytest -x -q tests/test_legacy_cutover.py` → `4 passed`).
- All three cited task commits (`5465e46`, `1df5d76`, `eaf7a3c`) are present in
  `git log --oneline --all`.
- Full suite passes: `python -m pytest -x -q` → `315 passed`.
- `tests/test_end_to_end.py` independently reconfirmed: `9 passed`.

---
*Phase: 02-python-ground-station-and-dashboard-cutover*
*Completed: 2026-08-08*
