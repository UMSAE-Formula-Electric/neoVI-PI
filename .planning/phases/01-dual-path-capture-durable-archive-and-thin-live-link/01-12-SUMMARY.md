---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 12
subsystem: testing
tags: [mcap, frame-source, compression-gate, dbc, cantools]

# Dependency graph
requires:
  - phase: 01-dual-path-capture-durable-archive-and-thin-live-link (01-05)
    provides: telemetry.archive.reader.recover_session, the one supported crash-tolerant read path
  - phase: 01-dual-path-capture-durable-archive-and-thin-live-link (01-10)
    provides: the FanOut/telemetry pipeline this plan's real-log reader is a sibling frame source to
provides:
  - ArchiveReplaySource, the third FrameSource implementation (D-08), replaying a captured session
    archive byte-identically through the recovery path
  - measure/cli.py's --frame-source archive real-traffic input path for the compression gate
affects: [00-compression-ratio-gate re-check, Phase 5 (soak/dropped-frame reporting), any future
  archive-consuming tool]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FrameSource implementations mirror SyntheticFrameSource's shape: captured_frames() as the
      primary generator, frames() as a thin RawFrame-only delegate for protocol compatibility"
    - "Read archives only through archive/reader.py's recovery path, never by opening the .mcap
      directly -- keeps the on-disk layout defined in exactly one place and handles a crashed
      session by construction rather than by exception"

key-files:
  created:
    - src/telemetry/capture/replay_source.py
    - tests/test_replay_source.py
  modified:
    - src/telemetry/measure/cli.py

key-decisions:
  - "A --frame-source archive run reports one 'measured' bracket key instead of the three modelled
    entropy brackets (best/typical/worst) -- there is no entropy model to bracket a real capture
    under, and 'measured' is deliberately not one of BRACKET_NAMES so a report reader can never
    mistake it for a fourth modelled bracket."
  - "duration_s and achieved_bus_fps for an archive run come from the archive's own recorded
    timestamps (ArchiveReplaySource.measured_frame_rates_hz()), never from gate.json's modelled
    duration/rate -- a real capture's duration and rate are facts of the log, not an assumption to
    read from config or override from the command line."
  - "input_provenance and known_limitation meta text are fully replaced (not appended to) for an
    archive run, per T-01-30 -- a report that measured captured traffic must never carry the
    synthetic-stream caveat that belongs to a modelled report. Pinned by a test that checks the
    verbatim synthetic-only phrases are absent, not by banning the word 'synthetic' outright (the
    real-log limitation text still legitimately names the synthetic model for comparison)."
  - "The pre-registered thresholds block, classify_database output, and assign_rates-derived
    per-ID name/sender/bus enrichment are computed identically for both frame sources -- only the
    bracket key, duration_s, achieved_bus_fps, and the two provenance/limitation strings differ."

requirements-completed: [ARCH-01, CAP-01, OPS-05]

coverage:
  - id: D1
    description: "ArchiveReplaySource round-trips a captured session archive byte-identically, in
      order, with channel tags recovered from the archive topic"
    requirement: ARCH-01
    verification:
      - kind: unit
        ref: "tests/test_replay_source.py#test_frames_round_trip_byte_identically_in_order"
        status: pass
      - kind: unit
        ref: "tests/test_replay_source.py#test_captured_frames_tag_channel_recovered_from_topic"
        status: pass
    human_judgment: false
  - id: D2
    description: "A channel filter narrows which frames ArchiveReplaySource yields without altering
      any yielded frame"
    verification:
      - kind: unit
        ref: "tests/test_replay_source.py#test_channel_filter_narrows_without_altering_yielded_frames"
        status: pass
    human_judgment: false
  - id: D3
    description: "A crashed (footer-less) session replays its complete records through the recovery
      path rather than a reader that assumes a whole file"
    requirement: ARCH-01
    verification:
      - kind: unit
        ref: "tests/test_replay_source.py#test_crashed_session_replays_its_complete_records"
        status: pass
    human_judgment: false
  - id: D4
    description: "ArchiveReplaySource satisfies the FrameSource protocol structurally and feeds
      Encoder.encode without modification"
    verification:
      - kind: unit
        ref: "tests/test_replay_source.py#test_satisfies_frame_source_protocol_structurally"
        status: pass
      - kind: unit
        ref: "tests/test_replay_source.py#test_frames_feed_encoder_encode_without_modification"
        status: pass
    human_judgment: false
  - id: D5
    description: "measured_frame_rates_hz() reports per-channel fps from the archive's own
      timestamps, summing exactly to frame count / archive time span"
    verification:
      - kind: unit
        ref: "tests/test_replay_source.py#test_measured_frame_rates_come_from_archive_timestamps"
        status: pass
      - kind: unit
        ref: "tests/test_replay_source.py#test_measured_frame_rates_empty_archive_reports_zero"
        status: pass
    human_judgment: false
  - id: D6
    description: "The compression gate CLI runs against a real archive with --frame-source archive,
      producing a single 'measured'-bracket report with correct frame counts"
    requirement: CAP-01
    verification:
      - kind: unit
        ref: "tests/test_replay_source.py#test_archive_frame_source_produces_a_measured_bracket_report"
        status: pass
    human_judgment: false
  - id: D7
    description: "An archive-run report's provenance names the archive path and session, and does
      not carry the synthetic-stream caveat (T-01-30)"
    requirement: OPS-05
    verification:
      - kind: unit
        ref: "tests/test_replay_source.py#test_archive_report_provenance_names_archive_and_session_not_synthetic"
        status: pass
    human_judgment: false
  - id: D8
    description: "An archive-run report's achieved-fps figures come from the archive's own
      timestamps, and duration_s_source records archive_measured"
    verification:
      - kind: unit
        ref: "tests/test_replay_source.py#test_archive_report_achieved_fps_from_archive_timestamps"
        status: pass
    human_judgment: false
  - id: D9
    description: "The default (no --frame-source flag) synthetic path is unchanged: three modelled
      brackets, and the existing 00-06 smoke test still passes unmodified"
    verification:
      - kind: unit
        ref: "tests/test_replay_source.py#test_default_synthetic_path_unchanged_by_a_missing_frame_source_flag"
        status: pass
      - kind: unit
        ref: "tests/test_measure_cli_smoke.py (all 7 tests, unmodified)"
        status: pass
    human_judgment: false
  - id: D10
    description: "Selecting --frame-source archive without --archive-path exits non-zero naming the
      missing argument"
    verification:
      - kind: unit
        ref: "tests/test_replay_source.py#test_archive_frame_source_without_archive_path_exits_nonzero"
        status: pass
    human_judgment: false
  - id: D11
    description: "Phase 0's published 00-REPORT.json (config/gate.json's committed path) still
      reproduces byte-for-byte: typical 305.13072 kbit/s, worst 344.51352 kbit/s"
    verification:
      - kind: manual_procedural
        ref: "python -m telemetry.measure.cli --gate-config .planning/phases/00-compression-ratio-gate/config/gate.json --out-dir <tmp>, diffed against the committed 00-REPORT.json"
        status: pass
    human_judgment: false

# Metrics
duration: ~55min
completed: 2026-08-01
status: complete
---

# Phase 1 Plan 12: Real-log FrameSource and the compression gate's real-traffic input path Summary

**ArchiveReplaySource (the D-08 real-log FrameSource) plus `measure/cli.py --frame-source archive`, discharging the instrument half of `00-DECISION.md`'s worst-case-bracket re-check condition**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-08-01
- **Completed:** 2026-08-01
- **Tasks:** 2
- **Files modified:** 3 (1 created: `replay_source.py`; 1 created: `test_replay_source.py`; 1 modified: `cli.py`)

## Accomplishments
- Built `ArchiveReplaySource` — the real-log `FrameSource` implementation `telemetry.wire.frame_source`'s own module docstring named as the deferred Phase 1 piece — reading through `archive/reader.py`'s crash-tolerant recovery path so a session that lost power on the car replays too, not just a cleanly closed one
- Widened `measure/cli.py` with `--frame-source {synthetic,archive}` / `--archive-path`, additive to the existing default: the compression gate can now be re-run against a real captured session archive with one command and no code change
- Proved the default synthetic path is untouched: Phase 0's committed `00-REPORT.json` reproduces byte-for-byte (typical 305.13072 kbit/s, worst 344.51352 kbit/s, best bracket also matched) against `config/gate.json`

## Task Commits

Each task was committed atomically:

1. **Task 1: ArchiveReplaySource — a captured session as a frame source** - `c17b5f6` (test)
2. **Task 2: A real-log input path for the compression gate** - `478ee0e` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/telemetry/capture/replay_source.py` - `ArchiveReplaySource`: `captured_frames()`/`frames()`/`measured_frame_rates_hz()`, reading through `recover_session`
- `src/telemetry/measure/cli.py` - `--frame-source`/`--archive-path` flags, the archive-mode measurement branch, and the replaced provenance/limitation text for archive runs
- `tests/test_replay_source.py` - Task 1 (round trip, channel tagging, filter, crash replay, protocol conformance, encoder compatibility, measured rates) and Task 2 (CLI real-log path, provenance, achieved fps, default-path regression, missing-archive-path error)

## Decisions Made
- Single `"measured"` bracket key for archive runs, deliberately outside `BRACKET_NAMES`, so a report reader can never mistake a real capture's numbers for a fourth modelled bracket
- `duration_s`/`achieved_bus_fps` for an archive run are computed from the archive's own timestamps unconditionally (ignoring `--duration-s`/config), since a real capture's duration and rate are facts of the log, not an assumption
- `input_provenance`/`known_limitation` are fully replaced, not appended to, for an archive run (T-01-30) — pinned by asserting the exact synthetic-only phrases are absent, since the real-log limitation text legitimately still names the synthetic model for comparison
- Kept `classify_database`/`assign_rates`-derived per-ID name/sender/bus enrichment identical for both frame sources (informational context only) rather than touching `report.py`, which is out of this plan's file scope

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The instrument half of `00-DECISION.md`'s Phase 1 condition is discharged: `python -m telemetry.measure.cli --frame-source archive --archive-path <session.mcap>` is ready to run against a real bench or track session capture the moment one exists
- Running it against real captured bus traffic — the re-check itself — remains outstanding and needs the car; this plan does not and cannot close that
- ARCH-01, CAP-01, and OPS-05 are closed by this plan (the last plan in Phase 1 to claim each ID per their frontmatter `requirements` fields — verified against every other Phase 1 PLAN.md, including 01-13's `[CAP-02, CAP-03, CAP-05, CAP-06]`, before marking)

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-01*

## Self-Check: PASSED

- FOUND: `src/telemetry/capture/replay_source.py`
- FOUND: `tests/test_replay_source.py`
- FOUND: `.planning/phases/01-dual-path-capture-durable-archive-and-thin-live-link/01-12-SUMMARY.md`
- FOUND commit: `c17b5f6` (Task 1)
- FOUND commit: `478ee0e` (Task 2)
