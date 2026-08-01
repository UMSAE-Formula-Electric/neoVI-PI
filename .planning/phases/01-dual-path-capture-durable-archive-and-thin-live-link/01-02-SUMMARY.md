---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 02
subsystem: testing
tags: [pip, pytest, mcap, cobs, crccheck, python-ics, requirements, provisioning]

# Dependency graph
requires:
  - phase: 01-dual-path-capture-durable-archive-and-thin-live-link
    provides: "01-01's cleared package-legitimacy verdict for mcap, cobs, crccheck, python-ics"
provides:
  - "requirements.txt: the single authoritative, exact-pinned, clean-machine-installable manifest for OPS-06"
  - "pytest.ini's registered slow marker, letting the quick loop exclude the soak test"
  - ".gitignore rules keeping session archives (sessions/, *.mcap) out of git"
  - "Eleven placeholder test files, one per named Wave 0 gap in 01-VALIDATION.md, each collected and skipping with a reason naming its filling plan"
affects: ["01-03", "01-04", "01-05", "01-06", "01-07", "01-08", "01-09", "01-10", "01-12", "01-13"]

# Tech tracking
tech-stack:
  added: [cobs==1.2.2, crccheck==1.3.1, lz4==4.4.5, mcap==1.4.0, "python-ics==1!26.3.9", zstandard==0.25.0]
  patterns:
    - "requirements.txt is the single authoritative pinned manifest; requirements-dev.txt is retained byte-identical as a Phase 0 provenance record, not extended or converted to a -r include"
    - "Wave 0 placeholder test files skip at module level with a reason naming the responsible plan, so pytest -ra output is a live outstanding-work list rather than a silent gap"

key-files:
  created:
    - requirements.txt
    - tests/test_fanout.py
    - tests/test_archive_writer.py
    - tests/test_archive_crash_recovery.py
    - tests/test_session.py
    - tests/test_framing.py
    - tests/test_link.py
    - tests/test_end_to_end.py
    - tests/test_soak.py
    - tests/test_hardware_source.py
    - tests/test_replay_source.py
    - tests/test_logger_cli_smoke.py
  modified:
    - requirements-dev.txt
    - pytest.ini
    - .gitignore

key-decisions:
  - "python-ics pinned as python-ics==1!26.3.9 (PEP 440 epoch 1), correcting 01-RESEARCH.md's illustrative install line which drops the epoch"
  - "lz4 and zstandard pinned explicitly as mcap's transitive dependencies, even though Phase 1's writer disables chunk compression, per 01-RESEARCH.md's Standard Stack note that mcap imports them unconditionally"
  - "pytest included in requirements.txt as a provisioning dependency, not an optional extra, since the test suite is how every phase requirement is proven"

patterns-established:
  - "Pin verification asserts installed version equals the pin, not the reverse — every entry in requirements.txt was checked against importlib.metadata before being written"

requirements-completed: [OPS-06]

coverage:
  - id: D1
    description: "requirements.txt holds eight exact pins (cantools, cobs, crccheck, lz4, mcap, python-ics, pytest, zstandard), each matching the version actually installed"
    requirement: "OPS-06"
    verification:
      - kind: unit
        ref: "Task 1 <automated> verify: packaging.requirements parse + importlib.metadata cross-check"
        status: pass
    human_judgment: false
  - id: D2
    description: "pytest.ini registers a slow marker so tests/test_soak.py can be excluded from the quick loop"
    requirement: "OPS-06"
    verification:
      - kind: unit
        ref: "python -m pytest -q (127 passed, 11 skipped, no unregistered-marker warning)"
        status: pass
    human_judgment: false
  - id: D3
    description: ".gitignore excludes sessions/ and *.mcap so captured session archives never enter git"
    verification:
      - kind: other
        ref: "git status --short confirms only intended files staged; .gitignore diff reviewed"
        status: pass
    human_judgment: false
  - id: D4
    description: "Eleven placeholder test files exist under tests/, one per 01-VALIDATION.md Wave 0 gap, each collected and skipping with a reason naming its filling plan"
    verification:
      - kind: unit
        ref: "Task 2 <automated> verify: python -m pytest -q + pathlib existence check for all eleven filenames"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-08-01
status: complete
---

# Phase 01 Plan 02: Wave 0 Provisioning Summary

**Pinned OPS-06 runtime manifest (eight exact pins including the corrected `python-ics==1!26.3.9` epoch), a registered `slow` pytest marker, session-archive `.gitignore` rules, and eleven Wave 0 placeholder test files that keep the suite green while naming their filling plan.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-08-01T19:33:18Z
- **Tasks:** 2/2 completed
- **Files modified:** 15 (1 created + 3 modified in Task 1; 11 created in Task 2)

## Accomplishments

- Created `requirements.txt` as the single authoritative, exact-pinned manifest for both runtime and test dependencies, with every pin verified against the version actually installed in the project interpreter rather than transcribed from prose
- Corrected the `python-ics` epoch: pinned as `python-ics==1!26.3.9`, not the epoch-dropping `26.3.9` that `01-RESEARCH.md`'s illustrative install line uses
- Reconciled `requirements-dev.txt` with the new manifest — kept its two Phase 0 pins byte-identical, only updated its header comment to point at `requirements.txt` as authoritative
- Registered the `slow` marker in `pytest.ini`, unblocking a future `-m "not slow"` quick loop
- Added `sessions/` and `*.mcap` to `.gitignore` so on-car run artifacts never enter the repository
- Scaffolded eleven placeholder test files, each a module docstring plus a `pytest.skip(..., allow_module_level=True)`, matching every ❌ Wave 0 entry in `01-VALIDATION.md` except `tests/test_logger_config.py` (owned by 01-03) and the `conftest.py` addition (also 01-03)

## Task Commits

1. **Task 1: Pinned runtime manifest, slow marker, and archive git-ignore rules** - `5e2eb33` (feat)
2. **Task 2: Placeholder test files for every Wave 0 validation gap** - `c5690cd` (test)

**Plan metadata:** pending (docs: complete plan, committed after this SUMMARY)

## Files Created/Modified

- `requirements.txt` - New authoritative manifest: eight exact pins (cantools, cobs, crccheck, lz4, mcap, python-ics, pytest, zstandard)
- `requirements-dev.txt` - Header comment updated to point at requirements.txt as authoritative; two Phase 0 pins unchanged
- `pytest.ini` - Added `markers` section registering `slow`
- `.gitignore` - Added `sessions/` and `*.mcap` under a comment explaining captured archives are run artifacts
- `tests/test_fanout.py` - Placeholder for 01-07 (CAP-01/03/04/05/06)
- `tests/test_archive_writer.py` - Placeholder for 01-06 (ARCH-01/04)
- `tests/test_archive_crash_recovery.py` - Placeholder for 01-05 (ARCH-02/03), notes its own SIGKILL-proxy scope limit
- `tests/test_session.py` - Placeholder for 01-05 (ARCH-05, OPS-04)
- `tests/test_framing.py` - Placeholder for 01-08 (LINK-01/02)
- `tests/test_link.py` - Placeholder for 01-08 (LINK-03/04)
- `tests/test_end_to_end.py` - Placeholder for 01-04 tracer, extended by 01-11 (GND-01)
- `tests/test_soak.py` - Placeholder for 01-13, will carry `@pytest.mark.slow` (CAP-02)
- `tests/test_hardware_source.py` - Placeholder for 01-09 (CAP-01/06)
- `tests/test_replay_source.py` - Placeholder for 01-12 (ARCH-01, Phase 0 D-14 real-traffic re-check)
- `tests/test_logger_cli_smoke.py` - Placeholder for 01-10 (CAP-01, OPS-04/05)

## Decisions Made

- **`python-ics` pinned with PEP 440 epoch 1** (`python-ics==1!26.3.9`), correcting `01-RESEARCH.md`'s epoch-dropping illustrative line, per the plan's explicit instruction and 01-01-SUMMARY.md's carried-forward note.
- **`lz4` and `zstandard` pinned explicitly** as `mcap`'s transitive dependencies even though the Phase 1 writer disables chunk compression — `01-RESEARCH.md` records `mcap` imports them unconditionally at module load.
- **`pytest` included in `requirements.txt`** as a provisioning dependency rather than a dev-only extra, since the test suite is how every phase requirement gets proven.
- **`requirements-dev.txt` left with its two pins untouched** and not converted to a `-r requirements.txt` include, preserving the exact byte-identical pins that 01-03's `test_requirements_pinned` will cross-check for drift.

## Deviations from Plan

None - plan executed exactly as written. All three pinning facts (epoch, transitive deps, pytest inclusion) and the reconciliation approach for `requirements-dev.txt` were followed as specified.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `requirements.txt` is clean-machine-provisionable and every pin is proven to match the installed interpreter (OPS-06 satisfied for this plan's scope).
- `python -m pytest -q -m "not slow"` is now a valid invocation once `01-13` adds `@pytest.mark.slow` to `tests/test_soak.py`.
- Every downstream plan (01-04 through 01-13, plus 01-03) that needs a named test file to attach its `<automated>` verify to now has one waiting, collected and skipping honestly rather than missing.
- No blockers. 138 tests collected (127 passing, 11 skipped with named-plan reasons), full suite green.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-01*
