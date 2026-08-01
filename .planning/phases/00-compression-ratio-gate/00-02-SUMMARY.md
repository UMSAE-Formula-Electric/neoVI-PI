---
phase: 00-compression-ratio-gate
plan: 02
subsystem: testing
tags: [cantools, struct, encoder-decoder, cfr, round-trip, ablation]

# Dependency graph
requires:
  - phase: 00-01
    provides: "pytest framework, src/telemetry/{wire,synth,measure} package skeleton, tests/conftest.py dbc fixture, DBC ground-truth facts"
provides:
  - "src/telemetry/wire/{frame_source,dictionary,encoder,decoder}.py — the D-05 CFR encoder/decoder core, hardened against malformed input"
  - "src/telemetry/synth/generator.py — SyntheticFrameSource, D-08's Phase 0 FrameSource implementation"
  - "src/telemetry/measure/{report,cli}.py — measure_stream/build_report/write_report_json and the `python -m telemetry.measure.cli` entry point"
  - "tests/test_wire_roundtrip.py — 21 tests: byte-identical round-trip proof across all four D-10 ablation modes crossed with a standard-ID and extended-ID subject, plus named-exception coverage for every malformed-input path"
affects: ["00-03", "00-04", "00-05", "00-06", "00-07"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-ID state isolation (last_payload, next_seq dicts keyed on id_index) — a discontinuity in one CAN ID's traffic never corrupts another's decode"
    - "Explicit field-count/length assertion immediately before every struct.pack/unpack call, raising a named exception with the offending value rather than letting struct.error surface"
    - "Frozen EncoderOptions dataclass shared by Encoder and Decoder — ablation is a caller contract, not a wire negotiation (Phase 4 scope)"

key-files:
  created:
    - src/telemetry/wire/frame_source.py
    - src/telemetry/wire/dictionary.py
    - src/telemetry/wire/encoder.py
    - src/telemetry/wire/decoder.py
    - src/telemetry/synth/generator.py
    - src/telemetry/measure/report.py
    - src/telemetry/measure/cli.py
    - tests/test_wire_roundtrip.py
  modified: []

key-decisions:
  - "Task 2 required no changes to encoder.py or decoder.py. Task 1's tracer slice had already implemented every guard Task 2's <behavior> block specifies (length checks before struct.pack/unpack, all four named exceptions, keyframe-on-DLC-change, per-ID sequence isolation) — confirmed by writing all 21 behavior assertions first and observing the full set pass against the untouched Task 1 implementation. This plan's contribution is the parametrized proof, not new production code."
  - "Verified INV_Diag_Buffer (frame_id 0xAA5) is genuinely extended-ID via direct cantools measurement (message.is_extended_frame == True) before using it as the extended-ID ablation subject, per the continuation brief's anti-pattern warning not to trust RESEARCH.md prose uncritically. It is unaffected by RESEARCH.md's separate multiplexed-message error (00-01-SUMMARY.md), which concerns a different property of the same message."
  - "Re-verified the four tracer-checkpoint ablation anchors (8.129 / 7.129 / 14.000 / 11.129 bytes/frame for full / sequence_byte=False / payload_delta=False / use_dictionary=False) by direct measure_stream invocation after Task 2's commit — all four unchanged, as expected since no encoder/decoder logic was touched."

patterns-established:
  - "Ablation-and-subject parametrization: pytest.mark.parametrize stacked over EncoderOptions modes and message subjects (standard-ID, extended-ID), each ablation×subject pair proven independently reversible before its bytes/frame number is trusted — the pattern plan 00-06's full ablation report table will consume."

requirements-completed: [GATE-01]

coverage:
  - id: D1
    description: "All four D-10 EncoderOptions ablation modes (full, sequence_byte=False, payload_delta=False, use_dictionary=False) round-trip byte-identical, each proven against both a standard-ID (M192_Command_Message) and extended-ID (INV_Diag_Buffer) subject"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_wire_roundtrip.py::test_ablation_roundtrip_byte_identical (8 parametrized cases)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Malformed input raises a named exception carrying the offending value: PayloadTooLong, BatchWindowExceeded, UnknownFrameId, and DecodeError (short buffer, delta with no stored predecessor, trim_count implying DLC > 8)"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_wire_roundtrip.py::test_payload_too_long_raises, test_batch_window_exceeded_raises, test_unknown_frame_id_raises, test_decode_buffer_too_short_raises, test_decode_delta_with_no_previous_payload_raises, test_decode_trim_count_implies_dlc_above_8_raises"
        status: pass
    human_judgment: false
  - id: D3
    description: "A DLC change forces a keyframe (never a delta) and round-trips; identical repeated payloads collapse to exactly the header size; the per-ID sequence byte wraps 255->0 and advances independently per CAN ID"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "tests/test_wire_roundtrip.py::test_dlc_change_forces_keyframe_and_roundtrips, test_identical_payload_produces_header_size_delta, test_sequence_byte_wraps_at_256, test_sequence_byte_independent_per_id"
        status: pass
    human_judgment: false
  - id: D4
    description: "decoder.py contains no bare except Exception: pass and no bare except: — every malformed-input path raises a named exception"
    requirement: "GATE-01"
    verification:
      - kind: unit
        ref: "grep -n except src/telemetry/wire/decoder.py (only docstring prose references the anti-pattern, zero live except clauses of that shape)"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-08-01
status: complete
---

# Phase 0 Plan 2: Compression-Ratio Spine (Tracer + Hardening) Summary

**The full DBC-to-CFR-report spine for one CAN ID, proven byte-identical across all four D-10 ablation modes for both a standard-ID and extended-ID message, with every malformed-input path raising a named exception instead of producing silently wrong bytes.**

## Performance

- **Duration:** ~20 min (Task 2 only; Task 1 completed and approved in a prior session)
- **Started:** 2026-08-01 (Task 2 resume)
- **Completed:** 2026-08-01
- **Tasks:** 2 (1 tracer, 1 auto/tdd)
- **Files modified:** 1 (tests/test_wire_roundtrip.py); 8 files created in Task 1

## Accomplishments
- One command (`PYTHONPATH=src python -m telemetry.measure.cli --only-message M192_Command_Message`) runs the whole spine — DBC load, ID dictionary, synthetic frame source, CFR encoder, matching decoder, aggregation, JSON report — and produces a real, round-trip-proven bytes/frame number (Task 1)
- The CFR byte layout matches `.planning/research/ARCHITECTURE.md` Pattern 3 field for field: `"<BBBHB"`, 6-byte header, `FLAG_KEYFRAME`/`FLAG_EXTENDED_ID` bits, per-ID sequence, uint16 `delta_t_us`, `trim_count`, payload (Task 1)
- All four `EncoderOptions` ablation modes are now proven reversible over both a standard-ID and extended-ID subject — 8 new parametrized round-trip cases (Task 2)
- Every malformed-input path named in the plan's `<behavior>` block raises a distinct, value-naming exception: `PayloadTooLong`, `BatchWindowExceeded`, `UnknownFrameId`, and three distinct `DecodeError` triggers (Task 2)
- DLC-change-forces-keyframe, identical-payload-collapses-to-header-size, and per-ID sequence wrap/independence are now explicitly asserted, not just implied by the general round-trip loop (Task 2)
- `tests/test_wire_roundtrip.py` grew from 2 tests to 21 tests; the full suite (`python -m pytest -q`) is 29 tests, all passing, no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end bytes/frame for one CAN ID — the whole spine, one path** - `5588bfd` (feat) — tracer checkpoint reached, verified, and approved in a prior session
2. **Task 2: Harden the spine — input validation and the four ablation modes** - `463a72e` (test)

**Plan metadata:** pending (this commit)

## Files Created/Modified
- `src/telemetry/wire/frame_source.py` - `RawFrame` NamedTuple and `FrameSource` Protocol (Task 1, unchanged)
- `src/telemetry/wire/dictionary.py` - `IdDictionary`, `build_id_dictionary`, `load_dbc`, `UnknownFrameId`, `DbcLoadError` (Task 1, unchanged)
- `src/telemetry/wire/encoder.py` - `Encoder`, `EncoderOptions`, `CfrError`/`BatchWindowExceeded`/`PayloadTooLong`, `CFR_HEADER_STRUCT` (Task 1, unchanged — already hardened)
- `src/telemetry/wire/decoder.py` - `Decoder`, `DecodeError` (Task 1, unchanged — already hardened)
- `src/telemetry/synth/generator.py` - `SyntheticFrameSource` (Task 1, unchanged)
- `src/telemetry/measure/report.py` - `PerIdStats`, `StreamMeasurement`, `measure_stream`, `build_report`, `write_report_json` (Task 1, unchanged)
- `src/telemetry/measure/cli.py` - `main` argparse entry point (Task 1, unchanged)
- `tests/test_wire_roundtrip.py` - Extended from 2 to 21 tests: 8 ablation×subject round-trip cases, 6 named-exception cases, 4 mechanic-specific assertions (DLC-change keyframe, identical-payload collapse, sequence wrap, sequence independence), 1 extended-ID flag check, plus the 2 original Task 1 tests unchanged (Task 2)

## Decisions Made
- Task 2 required zero changes to `encoder.py`/`decoder.py`. Writing all 21 `<behavior>`-block assertions and running them against the untouched Task 1 implementation showed every guard already present — see "TDD Gate Compliance" below.
- Verified `INV_Diag_Buffer` is genuinely extended-ID (`is_extended_frame == True`, frame_id `0xAA5`) via direct `cantools` measurement before using it as the extended-ID ablation subject, rather than trusting RESEARCH.md prose per the continuation brief's anti-pattern warning. This message's extended-ID status is independent of, and unaffected by, the separate multiplexed-message correction recorded in `00-01-SUMMARY.md`.
- Re-verified the four tracer-checkpoint ablation anchors (8.129 / 7.129 / 14.000 / 11.129 bytes/frame) unchanged after Task 2's commit, since no encoder/decoder byte-producing logic was modified.

## Deviations from Plan

None (Rule 1-4) - no bugs, missing functionality, blocking issues, or architectural changes were found. The plan's `<behavior>` block was satisfied by Task 1's implementation without modification; see "TDD Gate Compliance" for the process note this produces.

## TDD Gate Compliance

Task 2 is marked `tdd="true"` and its `<action>` instructs writing the failing assertions first, then adding guards to make them pass (RED then GREEN). In this execution, writing and running all 21 assertions produced 21 passes with zero implementation changes — Task 1's tracer slice had already implemented every guard the plan's `<behavior>` block specifies (explicit length checks before both `struct.pack` and `struct.unpack`, all four named exceptions with value-naming messages, keyframe-forcing on DLC change, and per-ID state isolation for the sequence byte). There was no RED phase to observe and no corresponding `feat(...)` commit, because there was no production-code gap to close.

This was verified deliberately rather than assumed: each of the six exception-raising tests targets a specific code path (payload length check, batch window check, dictionary lookup, header-length check, delta-with-no-predecessor check, trim_count-implies-oversized-DLC check) and uses `pytest.raises(..., match=...)` against the actual exception message text already present in Task 1's code, not a generic exception type. A vacuously-passing test (e.g., matching on empty string, or catching a broader exception) was not used anywhere in this file.

Git log for this plan: `5588bfd` (feat, Task 1) → `463a72e` (test, Task 2). No intervening `feat` commit for Task 2 is expected or missing under the above explanation.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The D-05 encoder/decoder core is now proven reversible under all four D-10 ablation modes for both a standard-ID and extended-ID subject — plan 00-06's ablation report table can trust every number it will report from this core.
- Plans 00-03 through 00-05 (entropy brackets, classifier, horizontal expansion to all CAN IDs) build directly on `src/telemetry/wire/` and `src/telemetry/synth/generator.py` as-is; no changes to their public exports occurred in this plan.
- No blockers.

---
*Phase: 00-compression-ratio-gate*
*Completed: 2026-08-01*

## Self-Check: PASSED

All 8 files created/touched by this plan found on disk; both task commits (`5588bfd`, `463a72e`) found in git history.
