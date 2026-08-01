---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 05
subsystem: telemetry-pipeline
tags: [mcap, archive, crash-recovery, session-lifecycle, durability]

# Dependency graph
requires:
  - phase: 01-04
    provides: ArchiveWriter (mcap.Writer wrapper, use_chunking=False, record-count-or-time fsync cadence), SessionPaths/new_session (UTC-named)/mark_done (writer-closed precondition), archive/record.py's pack_frame/unpack_frame on-disk layout
provides:
  - The one supported crash-recovery read path (telemetry.archive.reader.recover_session), pinned against both failing mcap default reader configurations
  - is_session_complete, the single predicate for "has this session's .done marker been written"
  - Monotonic-counter session naming fallback for a clock that is epoch-garbage at boot (telemetry.archive.session.new_session, naming_source, session.json sidecar)
  - The ARCH-03 physical power-pull test procedure (docs/power-pull-test.md)
affects: [01-06, 01-08, 01-10, 01-11, 01-12, 01-13]

# Tech tracking
tech-stack:
  added: []  # mcap already pinned by 01-02/01-04; this plan is its recovery-path usage
  patterns:
    - "NonSeekingReader(f).iter_messages(log_time_order=False), for-loop accumulation, catch (EndOfFile, struct.error) -- the only mcap 1.4.0 reader configuration that recovers pre-crash data; both 'obvious' alternatives are pinned as failing by their own test"
    - "Session naming source (clock vs counter) recorded on SessionPaths and mirrored into a session.json sidecar alongside the producing config's hash"
    - "Counter state file reseeded from the highest existing counter-named directory when missing/unreadable, never from zero -- a lost state file must not cause a name collision"
    - "Kill-based crash tests spawn a real subprocess (tests/crash_writer_child.py) rather than simulating a kill in-process, so the OS actually tears down the process the way SIGKILL would"

key-files:
  created:
    - src/telemetry/archive/reader.py
    - tests/crash_writer_child.py
    - docs/power-pull-test.md
  modified:
    - src/telemetry/archive/session.py
    - tests/test_archive_crash_recovery.py
    - tests/test_session.py

key-decisions:
  - "recover_session's exception handling catches (mcap.exceptions.EndOfFile, struct.error) as one pair -- struct.error is not an mcap exception type and would silently escape an mcap-only except clause, verified this session by triggering both a clean between-record EOF and a mid-header truncation against real files"
  - "Session naming fallback threshold: a clock reporting a UTC year before 2020 is treated as implausible (the CM4 has no RTC battery and can boot near the Unix epoch) -- an arbitrary but documented sanity floor, no requirement mandates a specific year"
  - "Counter-derived session names use an 8-digit zero-padded 'counter-NNNNNNNN' format so they sort lexically in creation order alongside (and distinguishably from) UTC-named siblings"
  - "crash_writer_child.py detects its own flush-and-fsync completions by observing ArchiveWriter's private _records_since_flush reset to 0, since ArchiveWriter exposes no public event for this and the script exists solely to drive one test -- documented inline as a deliberate, scoped exception rather than a precedent"

patterns-established:
  - "A module whose whole purpose is preventing a regression (reader.py) states in its own module docstring, in the first paragraph, exactly what a later contributor must not do and why"
  - "Kill-based proxy tests state their own scope limit twice: once in the test module's docstring, once again as an inline comment directly above the kill -- so the limit survives even a partial reading of the file"

requirements-completed: [ARCH-02, ARCH-05]

coverage:
  - id: D1
    description: "recover_session() recovers every complete record from a footer-less crashed archive, a clean truncation, and a mid-record-cut truncation -- dropping only the truly incomplete record and never emitting a partial one"
    requirement: "ARCH-02"
    verification:
      - kind: unit
        ref: "tests/test_archive_crash_recovery.py#test_recovers_all_records_from_a_footerless_file"
        status: pass
      - kind: unit
        ref: "tests/test_archive_crash_recovery.py#test_recovers_a_clean_prefix_from_a_file_truncated_to_half_its_size"
        status: pass
      - kind: unit
        ref: "tests/test_archive_crash_recovery.py#test_drops_only_the_record_cut_mid_body"
        status: pass
      - kind: unit
        ref: "tests/test_archive_crash_recovery.py#test_recovers_a_complete_session_and_reports_it_not_truncated"
        status: pass
    human_judgment: false
  - id: D2
    description: "Both default mcap reader configurations (make_reader(), NonSeekingReader's own log_time_order=True default) are pinned as failing on a footer-less file, so a later simplification of recover_session cannot pass review unnoticed"
    requirement: "ARCH-02"
    verification:
      - kind: unit
        ref: "tests/test_archive_crash_recovery.py#test_default_mcap_readers_fail_on_a_footerless_file"
        status: pass
    human_judgment: false
  - id: D3
    description: "A writer process killed mid-session (real subprocess, real SIGKILL-equivalent) still yields at least every fsync-confirmed record on recovery, and the session is found with no .done marker"
    requirement: "ARCH-02"
    verification:
      - kind: integration
        ref: "tests/test_archive_crash_recovery.py#test_killed_writer_recovers_at_least_every_fsync_confirmed_record"
        status: pass
    human_judgment: false
  - id: D4
    description: "is_session_complete() reports true only when the .done marker is present"
    verification:
      - kind: unit
        ref: "tests/test_archive_crash_recovery.py#test_is_session_complete_true_with_marker"
        status: pass
      - kind: unit
        ref: "tests/test_archive_crash_recovery.py#test_is_session_complete_false_without_marker"
        status: pass
    human_judgment: false
  - id: D5
    description: "Session naming falls back from UTC to a monotonic, zero-padded counter when the clock reports a pre-2020 (epoch-garbage) time, recording which branch produced the name; a lost counter state file reseeds from the highest existing counter directory rather than colliding"
    requirement: "OPS-04"
    verification:
      - kind: unit
        ref: "tests/test_session.py#test_new_session_with_a_working_clock_uses_utc_naming"
        status: pass
      - kind: unit
        ref: "tests/test_session.py#test_new_session_with_epoch_garbage_clock_falls_back_to_counter"
        status: pass
      - kind: unit
        ref: "tests/test_session.py#test_two_consecutive_counter_sessions_sort_in_creation_order_and_do_not_collide"
        status: pass
      - kind: unit
        ref: "tests/test_session.py#test_counter_session_after_state_file_deleted_does_not_collide"
        status: pass
      - kind: unit
        ref: "tests/test_session.py#test_two_sessions_each_get_their_own_directory"
        status: pass
    human_judgment: false
  - id: D6
    description: "The .done marker is provably created strictly after ArchiveWriter.close() returns (spied ordering), and mark_done raises with no partial marker left behind when handed an unclosed writer"
    requirement: "ARCH-05"
    verification:
      - kind: unit
        ref: "tests/test_session.py#test_done_marker_ordering"
        status: pass
      - kind: unit
        ref: "tests/test_session.py#test_mark_done_raises_if_writer_not_closed"
        status: pass
    human_judgment: false
  - id: D7
    description: "docs/power-pull-test.md gives a repeatable physical procedure for the ARCH-03 bench proof, requiring at least three repetitions and stating the SIGKILL proxy's page-cache limitation"
    requirement: "ARCH-03"
    verification:
      - kind: other
        ref: "python -c \"...headings check...\" against docs/power-pull-test.md"
        status: pass
    human_judgment: true
    rationale: "ARCH-03's real proof is a physical bench procedure run on the CM4 with real power interruption; this plan's own success_criteria states the requirement itself stays open until that bench run is recorded, so it cannot auto-pass from a document-shape check alone."

# Metrics
duration: 55min
completed: 2026-08-01
status: complete
---

# Phase 1 Plan 5: Crash Recovery, Session Naming Fallback, and the ARCH-03 Procedure Summary

**A pinned, non-negotiable `NonSeekingReader(log_time_order=False)` crash-recovery reader; a monotonic-counter session-naming fallback for a CM4 with no RTC battery; and the written physical power-pull test procedure ARCH-03 requires.**

## Performance

- **Duration:** 55 min (approx.)
- **Completed:** 2026-08-01T20:08:00Z
- **Tasks:** 3
- **Files modified:** 6 (4 created, 2 modified — `src/telemetry/archive/session.py` and the two Wave-0 placeholder test files it filled in)

## Accomplishments

- `telemetry.archive.reader.recover_session` is the one supported way to read back a session archive, built on the exact, empirically-reverified reader configuration `01-RESEARCH.md` Pattern 2 identified: `NonSeekingReader(f).iter_messages(log_time_order=False)`, iterated in a `for` loop that accumulates results before either `mcap.exceptions.EndOfFile` or a bare `struct.error` can fire. Re-verified directly against real files this session (not carried forward from memory) before writing a single line of `reader.py`: a 50-record footer-less file recovers all 50 through this path, 0 through `NonSeekingReader`'s own `log_time_order=True` default, and raises `RecordLengthLimitExceeded` through `mcap.reader.make_reader()`.
- `test_default_mcap_readers_fail_on_a_footerless_file` pins both failing library behaviors against a real file, so a later "simplification" back to either default cannot pass review unnoticed — exactly the regression `reader.py`'s own module docstring warns against.
- Four damage scenarios (no `finish()` call, truncated to half size, cut 3 bytes into the last record's body, and a normally-closed complete session) each recover the exact expected record count, verified against real files built through the real `ArchiveWriter`, not synthetic byte buffers.
- A kill-based proxy test (`tests/crash_writer_child.py`, spawned as a real subprocess and killed with `proc.kill()`) confirms recovery finds at least every fsync-confirmed record and that the killed session carries no `.done` marker — its scope limit (write-cadence, not fsync, correctness) is stated in both the test module's docstring and inline immediately above the kill, per the plan's explicit double-statement requirement.
- `telemetry.archive.session.new_session` now falls back from UTC naming to a persisted, zero-padded monotonic counter when the clock reports a pre-2020 year — the CM4 has no RTC battery and can boot near the Unix epoch. Which branch produced a session's name is recorded on `SessionPaths.naming_source` and mirrored into a new `session.json` sidecar alongside the producing config's hash. A lost or unreadable counter state file reseeds from the highest existing counter-named directory rather than restarting at zero, so it can never collide with and silently overwrite a prior run (T-01-15).
- `mark_done`'s close-then-marker ordering is now verified with a spy (not merely assumed), its not-closed raise path is confirmed to leave no partial marker file behind, and the Linux/Windows directory-fsync branch split is asserted on both sides via mocked `os` calls rather than only on whichever platform happens to run the suite.
- `docs/power-pull-test.md` gives a repeatable, self-contained bench procedure for the real ARCH-03 proof: states the SIGKILL proxy's page-cache limitation directly, requires at least three repetitions at different cut points, and defines explicit pass criteria and a recording location — ARCH-03 stays open until that procedure is actually run on real hardware.

## Task Commits

1. **Task 1: The one supported crash-recovery read path** - `40724e5` (feat)
2. **Task 2: Session naming fallback, per-run directories, and .done ordering** - `fabcf20` (feat)
3. **Task 3: The ARCH-03 physical power-pull procedure** - `9a935fe` (docs)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified

- `src/telemetry/archive/reader.py` — `recover_session()`, `RecoveredSession`, `is_session_complete()`; the one supported crash-recovery entry point
- `tests/crash_writer_child.py` — standalone subprocess helper driving the kill-based proxy test; prints `SESSION_DIR:`/`FSYNC:` confirmation lines, never calls `mark_done`
- `tests/test_archive_crash_recovery.py` — filled in from its Wave-0 placeholder: four damage-scenario tests, the library-behavior pin, the kill-based proxy test, `is_session_complete` tests
- `src/telemetry/archive/session.py` — extended with the monotonic-counter naming fallback, `session.json` sidecar, injectable clock
- `tests/test_session.py` — filled in from its Wave-0 placeholder: naming-fallback tests, collision/reseed tests, `.done` ordering spy, not-closed raise test, platform-branch tests
- `docs/power-pull-test.md` — the ARCH-03 physical procedure

## Decisions Made

- **Crash simulation for unit-level scenarios:** `_write_uncommitted_session` writes real frames through the real `ArchiveWriter` with `flush_every_records=1` (so every record reaches the OS immediately), then closes the underlying file object directly (`writer._f.close()`) rather than calling `ArchiveWriter.close()` — this produces a genuinely footer-less file without needing a real process kill for the byte-manipulation scenarios (truncate-to-half, cut-3-bytes), which is the fast, deterministic complement to the real-subprocess kill test.
- **Sanity floor for clock plausibility: year 2020.** No requirement mandates a specific value; 2020 is comfortably after any plausible Unix-epoch-adjacent boot-time garbage and comfortably before any plausible real session, documented as a Claude's Discretion choice in `session.py`'s module docstring.
- **`crash_writer_child.py` reaches into `ArchiveWriter._records_since_flush`** to detect flush completions, documented inline as a deliberate, narrowly-scoped exception (the script exists to drive exactly one test and `ArchiveWriter` offers no public event for this) rather than a precedent for production code to follow.

## Deviations from Plan

None - plan executed exactly as written. All four `<critical_constraints>` were followed precisely: the exact `NonSeekingReader(f).iter_messages(log_time_order=False)` call with both exception types caught; the SIGKILL scope-limit statement appears both in `tests/test_archive_crash_recovery.py`'s module docstring and as an inline comment directly above the kill; `docs/power-pull-test.md` is written for someone who was not in this planning session, with explicit repetition counts and marker-check instructions; session naming records which branch (`naming_source`) produced each name, tested for both the clock and counter paths.

## Issues Encountered

None. Every reader-behavior claim in `01-RESEARCH.md` Pattern 2 (make_reader's `RecordLengthLimitExceeded`, the default reader's zero-of-fifty recovery, the working `log_time_order=False` configuration, and the `EndOfFile`/`struct.error` split between clean-boundary and mid-header truncation) was re-verified directly against real files built in this session before being relied upon in `reader.py` or its tests, per ground-truth discipline — no figure was carried forward from memory or from RESEARCH.md prose without a fresh check.

## User Setup Required

None - no external service configuration required. `docs/power-pull-test.md` itself requires a human to run it on the bench with real hardware before ARCH-03 can be considered closed — that is the point of the document, not a setup step for this plan.

## Next Phase Readiness

- ARCH-02 and ARCH-05 are fully closed: crash recovery is proven against real damaged files plus a real killed subprocess, and `.done` marker ordering is proven with a spy rather than assumed.
- **ARCH-03 remains open by design.** The written procedure exists and is complete, but per this plan's own `<success_criteria>` the requirement itself stays open until the bench run is actually performed on real hardware and recorded — not marked complete in `REQUIREMENTS.md` by this plan.
- **OPS-04 is not marked complete by this plan** despite this plan's own directory-per-session/naming-collision work: `01-10-PLAN.md` also claims OPS-04 and has not yet run, so this plan is not the last claimant. (Note: `OPS-04`'s checkbox in `REQUIREMENTS.md` was already `[x]` before this plan ran, apparently set prematurely by `01-04`'s execution while `01-10` still claims the same ID — a pre-existing inconsistency from before this plan, left as-is rather than "fixed" outside this plan's scope.)
- `telemetry.archive.reader.recover_session`/`is_session_complete` are ready for `01-12`'s replay source (which the plan's own `key_links` names as the intended caller) and for Phase 8's SYNC-02.
- `session.json`'s `config_hash` field is wired to accept a value but no caller yet passes `LoggerConfig.config_hash` into `new_session` — that wiring belongs to whichever plan first builds the real logger entry point (`01-10`), consistent with `new_session`'s existing tracer-era callers (`01-04`'s end-to-end test, this plan's own tests) that all still call it with just `root_dir`.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-01*

## Self-Check: PASSED

All 6 created/modified source and doc files (`src/telemetry/archive/reader.py`, `tests/crash_writer_child.py`, `docs/power-pull-test.md`, `src/telemetry/archive/session.py`, `tests/test_archive_crash_recovery.py`, `tests/test_session.py`) and this SUMMARY.md were verified present on disk. All four commits (`40724e5`, `fabcf20`, `9a935fe`, `1c80329`) were verified present in `git log --oneline --all`. `python -m pytest tests/test_archive_crash_recovery.py tests/test_session.py -x -q --tb=short` (18 passed) and `python -m pytest -q -m "not slow"` (175 passed, 8 Wave-0 placeholder skips, 0 failures) were both re-confirmed green before this summary was finalized.
