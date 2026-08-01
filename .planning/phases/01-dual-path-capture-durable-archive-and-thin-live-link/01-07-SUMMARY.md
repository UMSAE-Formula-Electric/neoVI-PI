---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 07
subsystem: telemetry-pipeline
tags: [fanout, capture, backpressure, discard-accounting, error-context, threading]

# Dependency graph
requires:
  - phase: 01-04
    provides: "FanOut/CapturedFrame/FanOutCounters (the capture divergence point), the two-queue overflow-policy scaffold verified end to end by the tracer"
  - phase: 01-06
    provides: "FanOutCounters.archive_write_failure (the durability-side counterpart to archive_overflow), ArchiveRunner as FanOut's real archive-side consumer"
provides:
  - "tests/test_fanout.py filled in from its Wave-0 placeholder: 14 tests covering CAP-01 (dual-bus), CAP-03 (archive never-drop), CAP-04 (structural non-blocking), CAP-05 (exact discard/filter accounting), and CAP-06 (rate-limited, frame-context error accounting)"
  - "FanOutCounters gains frames_submitted, archive_enqueued, telemetry_enqueued, telemetry_filtered_count, telemetry_unknown_id_count, telemetry_payload_too_long_count, telemetry_unexpected_error_count, and telemetry_error_log_suppressed_count -- every discard/filter/error reason now has its own exact counter"
  - "FanOut(..., dictionary=) -- an optional CAP-06 telemetry-path precheck (dictionary membership + CAN DLC payload length) that runs before a frame reaches the telemetry deque, with per-frame-id log rate limiting"
  - "A static, AST-based test proving telemetry.capture.fanout imports nothing from telemetry.archive or telemetry.link -- CAP-04's structural guarantee pinned against regression, not just asserted by behavior"
affects: [01-09, 01-10, 01-13]

# Tech tracking
tech-stack:
  added: []  # no new dependencies; reuses telemetry.wire.dictionary/encoder's existing exception types
  patterns:
    - "CAP-06 telemetry-path precheck reuses telemetry.wire.dictionary.UnknownFrameId and telemetry.wire.encoder.PayloadTooLong/MAX_PAYLOAD_BYTES directly rather than defining a parallel exception family -- it validates the same two conditions Encoder.encode() would raise on, without running the encoder itself (encoding still happens downstream, unchanged)"
    - "Per-frame-id log rate limiting: a private set on FanOut (_logged_error_frame_keys) gates full-detail logging to the first occurrence per (frame_id, is_extended); every suppressed repeat still increments telemetry_error_log_suppressed_count so nothing is silently lost"
    - "dictionary: Optional[IdDictionary] = None keeps FanOut's constructor backward compatible with every already-committed call site (01-04's tracer, 01-06's archive tests) that never passes one -- absence just skips the unknown-id half of the precheck; the payload-length half needs no dictionary and always runs"

key-files:
  created: []
  modified:
    - src/telemetry/capture/fanout.py
    - tests/test_fanout.py

key-decisions:
  - "FanOut's telemetry-path CAP-06 precheck is deliberately NOT the real CFR encode -- it validates dictionary membership and CAN DLC payload length only (the two conditions Encoder.encode() would raise PayloadTooLong/UnknownFrameId on), reusing those exact exception types rather than inventing new ones. This keeps 01-CONTEXT.md's 'allowlist... applied here, before the encoder' true: the actual Encoder still runs downstream, unchanged, and FanOut never imports telemetry.wire.encoder's stateful Encoder class -- only its two lightweight, stateless error-condition primitives (MAX_PAYLOAD_BYTES, PayloadTooLong)."
  - "dictionary is an optional keyword parameter (default None) rather than required, specifically to avoid touching test_end_to_end.py or test_archive_writer.py (both out of this plan's files_modified) -- both already-committed call sites construct FanOut without it and their behavior is provably unchanged (full suite re-verified green)."
  - "Rate limiting keys on (frame_id, is_extended) only, not on error type -- a frame id that first fails with one error type and later a different one is still treated as 'already seen' and its second failure is suppressed-but-counted. This matches the plan's literal wording ('the first occurrence per frame id is logged in full') and keeps the bookkeeping to one set rather than a cross product of (frame_id, error_type)."
  - "Both tasks followed a real RED/GREEN cycle: each task's test additions were run against the fanout.py state that existed before that task's implementation (verified failing for the new behavior specifically, not the whole file), then the implementation was added and the same run re-verified green, before either commit."

requirements-completed: [CAP-04]
# CAP-01 also claimed by 01-09/01-10/01-12 -- not marked here (per this plan's own success_criteria).
# CAP-03 also claimed by 01-13 -- not marked here.
# CAP-05/CAP-06 also claimed by 01-09/01-10/01-13 -- not marked here.
# CAP-04 appears in no later plan's requirements frontmatter (only 01-04's, already-passed prerequisite,
# and this plan's) -- 01-07 is the last claimant, so it is marked complete here. Note: REQUIREMENTS.md's
# checkbox for CAP-04 (and CAP-03) was already [x] before this plan ran, apparently set prematurely by
# 01-04's own requirements-completed list; that pre-existing state was not altered by this plan's changes
# (out of this plan's scope per the Scope Boundary rule) beyond confirming CAP-04's completion is now
# also correctly the last-claimant plan's own assertion.

coverage:
  - id: D1
    description: "A telemetry deque of depth four holding twenty submitted allowlisted frames discards exactly sixteen (drop-oldest), while fewer-than-depth submissions discard zero, and a non-allowlisted frame is counted as filtered rather than discarded"
    requirement: "CAP-05"
    verification:
      - kind: unit
        ref: "tests/test_fanout.py#test_discard_counting"
        status: pass
      - kind: unit
        ref: "tests/test_fanout.py#test_discard_counting_fewer_than_depth_is_zero"
        status: pass
      - kind: unit
        ref: "tests/test_fanout.py#test_filtered_frame_never_reaches_deque_and_is_not_counted_as_a_discard"
        status: pass
    human_judgment: false
  - id: D2
    description: "The archive queue accepts exactly its configured capacity with no discards, and submitting one frame beyond capacity sets the stop event, sets the overflow flag, emits a critical log record naming the frame's channel/id/timestamp, and never grows the queue past capacity on subsequent submits"
    requirement: "CAP-03"
    verification:
      - kind: unit
        ref: "tests/test_fanout.py#test_archive_accepts_exactly_capacity_frames_in_order_no_discards"
        status: pass
      - kind: unit
        ref: "tests/test_fanout.py#test_archive_overflow_is_fatal_logs_full_context_stops_and_stays_stopped"
        status: pass
    human_judgment: false
  - id: D3
    description: "A telemetry consumer that never drains has no effect on archive delivery count or the producer's per-submit call time across a burst several times the telemetry depth; submit() never raises queue.Full even under sustained telemetry overflow; and the module statically imports nothing from telemetry.archive or telemetry.link"
    requirement: "CAP-04"
    verification:
      - kind: unit
        ref: "tests/test_fanout.py#test_stalled_telemetry_consumer_does_not_affect_archive_delivery_or_submit_time"
        status: pass
      - kind: unit
        ref: "tests/test_fanout.py#test_submit_never_raises_under_sustained_telemetry_overflow"
        status: pass
      - kind: unit
        ref: "tests/test_fanout.py#test_fanout_module_imports_nothing_from_archive_or_link"
        status: pass
    human_judgment: false
  - id: D4
    description: "Both queues' high-water marks equal the deepest occupancy actually reached and never decrease when the queues later drain"
    requirement: "CAP-05"
    verification:
      - kind: unit
        ref: "tests/test_fanout.py#test_high_water_marks_track_deepest_occupancy_and_never_decrease"
        status: pass
    human_judgment: false
  - id: D5
    description: "One FanOut instance, driven by a real SyntheticFrameSource stream, carries frames tagged with both configured channel names into the single archive queue in submission order, with per-channel counts matching what the source produced"
    requirement: "CAP-01"
    verification:
      - kind: unit
        ref: "tests/test_fanout.py#test_dual_bus_capture"
        status: pass
    human_judgment: false
  - id: D6
    description: "A frame whose id is absent from the dictionary, and separately an over-length payload, are each counted on a specific FanOutCounters field, logged at warning severity with channel/id/timestamp, do not propagate an unhandled exception, and never cost the archive path the frame"
    requirement: "CAP-06"
    verification:
      - kind: unit
        ref: "tests/test_fanout.py#test_unknown_id_counted_and_logged_archive_still_receives_the_frame"
        status: pass
      - kind: unit
        ref: "tests/test_fanout.py#test_over_length_payload_counted_and_logged_no_unhandled_exception"
        status: pass
    human_judgment: false
  - id: D7
    description: "An unexpected exception from the telemetry-side precheck is caught, counted, and logged rather than propagating out of submit() or being silently swallowed"
    requirement: "CAP-06"
    verification:
      - kind: unit
        ref: "tests/test_fanout.py#test_unexpected_telemetry_error_is_caught_counted_logged_not_swallowed"
        status: pass
    human_judgment: false
  - id: D8
    description: "Repeated errors for the same frame id are logged in full only on first occurrence; every subsequent occurrence is counted (telemetry_error_log_suppressed_count) without re-logging"
    requirement: "CAP-06"
    verification:
      - kind: unit
        ref: "tests/test_fanout.py#test_repeated_unknown_id_errors_are_rate_limited_but_still_counted"
        status: pass
    human_judgment: false

# Metrics
duration: 40min
completed: 2026-08-01
status: complete
---

# Phase 1 Plan 7: Fan-Out Overflow Policies, Discard Accounting, and Frame-Context Errors Summary

**FanOutCounters now carries exact accounting for every discard/filter/error reason (CAP-05/CAP-06), a CAP-06 telemetry-path precheck catches unencodable frames before they reach the deque with per-frame-id rate-limited logging, and a static AST-based test pins CAP-04's no-import-from-archive-or-link guarantee against regression.**

## Performance

- **Duration:** 40 min (approx.)
- **Started:** 2026-08-01T19:55:00Z (approx., immediately following 01-06's completion)
- **Completed:** 2026-08-01T20:35:00Z
- **Tasks:** 2
- **Files modified:** 2 (both existing: `src/telemetry/capture/fanout.py`, `tests/test_fanout.py`)

## Accomplishments

- `tests/test_fanout.py` replaced its 01-02 Wave-0 placeholder skip with 14 real tests, including the two nodes `01-VALIDATION.md` names explicitly: `test_discard_counting` (CAP-05) and `test_dual_bus_capture` (CAP-01).
- `FanOutCounters` grew from 5 fields to 13: `frames_submitted`/`archive_enqueued`/`telemetry_enqueued` (throughput), `telemetry_filtered_count` (allowlist rejection, kept strictly separate from `telemetry_discard_count`'s overflow drops per CAP-05's own wording), and four CAP-06 fields (`telemetry_unknown_id_count`, `telemetry_payload_too_long_count`, `telemetry_unexpected_error_count`, `telemetry_error_log_suppressed_count`).
- `FanOut.submit()` gained a telemetry-path precheck (`_passes_telemetry_precheck`) that runs strictly after the archive enqueue has already happened unconditionally, so a frame the live path cannot carry still reaches the archive. It catches `UnknownFrameId` (dictionary lookup, only run if a `dictionary=` was supplied at construction) and `PayloadTooLong` (CAN DLC check, always run) by their specific types, reusing `telemetry.wire.dictionary`/`telemetry.wire.encoder`'s existing exception types rather than inventing a parallel family, plus a last-resort `except Exception` that counts and logs — deliberately unlike `src/new_logger.py`'s bare `except Exception: debug(...)` swallow, per critical constraint 4.
- Per-frame-id log rate limiting: `_record_telemetry_error` logs the first occurrence for a given `(frame_id, is_extended)` at full detail (channel, id, is_extended, timestamp, exception message) and silently increments `telemetry_error_log_suppressed_count` for every repeat — proven directly with `caplog` against a 50-submission burst that produces exactly one warning record and 49 suppressed counts.
- `test_fanout_module_imports_nothing_from_archive_or_link` parses `fanout.py`'s own source with `ast` and asserts no `import`/`from` statement resolves to `telemetry.archive` or `telemetry.link` — CAP-04's "the telemetry consumer holds no handle that could block capture or the archive path" is now a fact a future edit cannot silently break without failing a test, not merely a claim proven by today's behavior.
- `test_dual_bus_capture` builds a two-message subset of the real DBC through `SyntheticFrameSource` (real, DBC-valid payloads, not invented bytes), interleaves the resulting frames across `config/logger.json`'s two configured channel names, submits them all through one `FanOut` instance, and confirms the archive queue receives every frame in submission order with the exact per-channel split the source produced — CAP-01's "one implementation carries both buses" clause, explicitly documented in the test's own docstring as NOT proving the duplicate legacy implementation has been removed (deferred to Phase 2 per `01-CONTEXT.md`).
- Both tasks followed a genuine RED/GREEN cycle: Task 1's tests were run against the untouched 01-04 `fanout.py` and failed on the new `telemetry_filtered_count` field before Task 1's implementation was added; Task 2's tests were run against Task 1's already-green `fanout.py` and failed with `TypeError: unexpected keyword argument 'dictionary'` before Task 2's implementation was added. Each RED was re-verified GREEN, and the full non-slow suite (197 then 202 tests) was re-confirmed green, before either task's commit.

## Task Commits

1. **Task 1: Divergent overflow policies, exact discard accounting, and high-water marks** - `a3b78d4` (feat)
2. **Task 2: Dual-bus capture in one stream, and errors that carry frame context** - `c86d90b` (feat)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified

- `src/telemetry/capture/fanout.py` — `FanOutCounters` gains 8 new fields (throughput accounting, filter/discard distinction, CAP-06 error accounting); `FanOut.submit()` gains a telemetry-path precheck ordered strictly after the unconditional archive enqueue; `FanOut.__init__` gains an optional `dictionary: Optional[IdDictionary] = None` keyword parameter (backward compatible with every existing call site)
- `tests/test_fanout.py` — filled in from its Wave-0 placeholder: 14 tests across both tasks (discard/filter accounting, archive never-drop, CAP-04 structural proofs including the static import-direction check, high-water marks, dual-bus capture, and the three CAP-06 error-context tests plus rate-limiting)

## Decisions Made

- **CAP-06's telemetry-path precheck reuses `telemetry.wire.dictionary.UnknownFrameId` and `telemetry.wire.encoder.PayloadTooLong`/`MAX_PAYLOAD_BYTES` directly** rather than defining a parallel exception family for `fanout.py`. This validates the same two conditions `Encoder.encode()` would raise on, without constructing or calling the stateful `Encoder` itself — the actual CFR encoding still runs downstream, unchanged, keeping `01-CONTEXT.md`'s "allowlist... applied here, before the encoder" literally true.
- **`dictionary` is an optional keyword parameter (`Optional[IdDictionary] = None`)**, not a required constructor argument, specifically so this plan's changes stay confined to its own two `files_modified` — `tests/test_end_to_end.py` (01-04) and `tests/test_archive_writer.py` (01-06) both construct `FanOut` without it and remain untouched; their behavior was re-verified unchanged (full suite still green). When absent, only the unknown-id half of the precheck is skipped; the payload-length check needs no dictionary and always runs.
- **Rate limiting keys on `(frame_id, is_extended)` alone, not on `(frame_id, is_extended, error_type)`** — matches the plan's literal "first occurrence per frame id" wording with a single bookkeeping set rather than a cross product.
- **Archive overflow's critical log record gained `timestamp_us`** alongside the channel/frame_id/is_extended fields the tracer already logged — needed for `test_archive_overflow_is_fatal_logs_full_context_stops_and_stays_stopped`'s frame-context assertion and consistent with CAP-06's "channel, id, and timestamp" requirement text, which the plan's own critical constraints apply to every logged frame-related error in this file, not only the CAP-06 telemetry-path ones.

## Deviations from Plan

None — plan executed exactly as written. All five `<critical_constraints>` were followed precisely: the two overflow policies (drop-oldest telemetry, fatal-never-drop archive) were kept exactly as the tracer wrote them, untouched; CAP-04 was made structural via both a behavioral stalled-consumer proof and a new static AST-based import-direction test; CAP-05/CAP-06 assert exact counts with frame context rather than absence of crashes; `src/new_logger.py`'s bare `except Exception: debug(...)` swallow and silent-continue-on-unknown-input anti-patterns were explicitly not reproduced (the catch-all in `_passes_telemetry_precheck` always counts and logs); and CAP-01's removal clause was not claimed — `test_dual_bus_capture`'s own docstring states this explicitly.

## Issues Encountered

One self-caught test bug, fixed before either commit: `test_archive_overflow_is_fatal_logs_full_context_stops_and_stays_stopped` initially asserted `"0x2AB" in joined.upper()`, but `joined.upper()` turns the log message's `0x2AB` (produced by the `0x%X` format spec) into `0X2AB` — the assertion's own uppercasing broke the match it was trying to make. Fixed to assert `"0x2AB" in joined` directly (no case transform needed, since `%X` already uppercases the hex digits and the `0x` prefix is always lowercase). Caught immediately by the first post-implementation test run, not a runtime defect in `fanout.py` itself.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `FanOutCounters` is ready for `01-10`'s logger CLI to report at shutdown (all 13 fields) and for `01-13`'s soak test to assert against, per this plan's own `key_links`.
- `FanOut(..., dictionary=)` is ready for `01-09`'s hardware capture source to construct with a real `IdDictionary`, activating the unknown-id half of the CAP-06 precheck in production for the first time (this plan's tests exercise it via a deliberately empty or exploding fake dictionary, not the real DBC-built one, since no message in the real DBC/allowlist pairing can naturally trigger "unknown id" — see `Decisions Made`).
- `CAP-01` (also claimed by `01-09`/`01-10`/`01-12`), `CAP-03` (also claimed by `01-13`), and `CAP-05`/`CAP-06` (also claimed by `01-09`/`01-10`/`01-13`) are deliberately NOT marked complete in `REQUIREMENTS.md` by this plan — only the last plan to claim each ID does. `CAP-04` appears in no later plan's `requirements` frontmatter (only `01-04`'s and this plan's), so it is marked complete here; its `REQUIREMENTS.md` checkbox was already `[x]` before this plan ran (apparently set by `01-04`'s own `requirements-completed` list, ahead of the "last claimant" convention this phase later adopted) — this plan's own claim is now also correctly the last-claimant assertion for that ID, and the pre-existing checkbox state was not otherwise altered, per the Scope Boundary rule.
- No blockers. `tests/test_hardware_source.py` (01-09), `tests/test_framing.py`/`tests/test_link.py` (01-08), `tests/test_logger_cli_smoke.py` (01-10), `tests/test_replay_source.py` (01-12), and `tests/test_soak.py` (01-13) remain their own plans' Wave-0 placeholders, unchanged by this plan.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-01*

## Self-Check: PASSED

Both modified files (`src/telemetry/capture/fanout.py`, `tests/test_fanout.py`) and this SUMMARY.md were verified present on disk. Both task commits (`a3b78d4`, `c86d90b`) were verified present in `git log --oneline --all`. `python -m pytest tests/test_fanout.py -x -q --tb=short` (14 passed) and `python -m pytest -q -m "not slow"` (202 passed, 6 Wave-0 placeholder skips, 0 failures) were both re-confirmed green before this summary was finalized.
