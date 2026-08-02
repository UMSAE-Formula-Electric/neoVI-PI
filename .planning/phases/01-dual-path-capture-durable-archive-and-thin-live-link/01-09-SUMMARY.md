---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 09
subsystem: telemetry-capture
tags: [python-ics, hardware-source, capture, cap-01, cap-06, ops-05]

# Dependency graph
requires:
  - phase: 01-03
    provides: "telemetry.logger.config's typed LoggerConfig/ChannelConfig loader (OPS-05) -- channel names, symbolic net-ID names, and capture settings this module resolves"
  - phase: 01-04
    provides: "telemetry.wire.frame_source.RawFrame/FrameSource protocol and telemetry.capture.fanout.CapturedFrame/FanOut -- the two contracts this module's output must satisfy"
provides:
  - "src/telemetry/capture/hardware_source.py -- HardwareFrameSource, the single consolidated python-ics capture implementation for CAP-01's first clause (both configured buses, one device handle, one stream)"
  - "A lazily-imported, injectable SDK seam -- constructing/testing this module never touches ics or hardware, and importing it never touches vspyx"
  - "captured_frames()/frames() for 01-10's logger CLI to feed into FanOut.submit and for the Phase 0 measurement tooling to consume unchanged"
affects: [01-10, 01-11, 01-12, 01-13]

# Tech tracking
tech-stack:
  added: []  # python-ics was already a project dependency; no new package added
  patterns:
    - "SDK object taken as an injectable constructor argument, defaulting to a module-level _default_sdk() factory that imports `ics` lazily -- the same 'never import the real thing at module scope' shape as telemetry.logger.config keeping cantools out of config parsing"
    - "Exception type caught via the injected SDK object's own attribute (self._sdk.RuntimeError), never the bare builtin -- required because ics.RuntimeError does not subclass builtins.RuntimeError; the test fake defines its exception the same way so a regression to the builtin fails in the suite, not in the field"
    - "A single named, explicitly-UNCONFIRMED module constant (TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED) for a fact that could not be established from the installed SDK on this dev machine for the actual deployment target -- carried forward as a labelled assumption per the plan's own instruction, not resolved by guessing"

key-files:
  created:
    - src/telemetry/capture/hardware_source.py
    - tests/test_hardware_source.py
  modified: []

key-decisions:
  - "Constructor takes channels/poll_interval_s/hardware_serial as separate parameters (extracted by the caller from LoggerConfig) rather than the whole LoggerConfig object -- matches FanOut's existing granular-parameter shape and keeps every test in this file free of constructing full LoggerConfig/ArchiveConfig/TelemetryConfig/LinkConfig fixtures just to test channel resolution or device-open logic"
  - "stop_event is a required constructor argument, not a per-call parameter to frames()/captured_frames() -- frames() must satisfy telemetry.wire.frame_source.FrameSource's exact no-argument signature (`def frames(self) -> Iterator[RawFrame]`), so the stop signal has to live on the instance"
  - "The poll loop uses threading.Event.wait(timeout=poll_interval_s) instead of time.sleep(poll_interval_s) -- wait() unblocks immediately when the event is set from another thread, which is what makes 'exits promptly ... without waiting out a full poll interval' actually true rather than aspirational"
  - "Channel resolution happens in __init__, not lazily on first use -- an unresolvable symbolic net-ID name is fatal at construction per the plan, so no partially-configured HardwareFrameSource can ever exist"
  - "Device open (open()) is a separate method from construction and from captured_frames() -- captured_frames() calls it lazily if not already opened, but tests exercise device selection in isolation without needing to drive the poll loop"

requirements-completed: []
# CAP-01, CAP-06, and OPS-05 are all also claimed by 01-10 (CAP-01, OPS-05),
# 01-11/01-12 (OPS-05), and 01-13 (CAP-06). Per this plan's own
# success_criteria and the invoking prompt's explicit instruction, none of
# the three are marked Complete in REQUIREMENTS.md by this plan -- their
# last claimant does that.

coverage:
  - id: D1
    description: "Each configured channel's symbolic net-ID constant name resolves against the injected SDK object to the integer it exposes; an unresolvable name raises ChannelResolutionError at construction, naming the channel and the constant, with no partially-constructed source returned"
    requirement: "OPS-05"
    verification:
      - kind: unit
        ref: "tests/test_hardware_source.py::test_channel_resolves_to_sdk_integer"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_unresolvable_channel_name_raises_named_error_at_construction"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_net_id_to_channel_map_covers_exactly_configured_channels"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_shipped_config_channels_resolve_against_real_ics"
        status: pass
    human_judgment: false
  - id: D2
    description: "Device open fails fast (no retry, no blocking wait) when no devices are found; selects by configured serial when several devices are present, naming the configured serial and listing what was seen when no match exists; selects the first device when no serial is configured"
    requirement: "CAP-06"
    verification:
      - kind: unit
        ref: "tests/test_hardware_source.py::test_open_with_no_devices_raises_named_error_no_retry_or_block"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_open_selects_matching_serial_among_several_devices"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_open_with_configured_serial_matching_none_names_serial_and_lists_available"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_open_with_no_configured_serial_selects_first_of_several"
        status: pass
    human_judgment: false
  - id: D3
    description: "No module under telemetry imports vspyx, directly or transitively -- proven both statically (AST scan of every src/telemetry/*.py file) and at runtime (vspyx absent from sys.modules after importing hardware_source)"
    requirement: "CAP-01"
    verification:
      - kind: unit
        ref: "tests/test_hardware_source.py::test_hardware_source_module_does_not_import_vspyx"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_no_module_under_telemetry_imports_vspyx"
        status: pass
    human_judgment: false
  - id: D4
    description: "captured_frames() constructs one CapturedFrame per surviving SDK message with the arbitration id masked to 29 bits, the extended flag read from StatusBitField & SPY_STATUS_XTD_FRAME, the payload sliced to the reported byte count, and the timestamp converted via the named (UNCONFIRMED) constant; frames() yields the same stream as RawFrames"
    requirement: "CAP-01"
    verification:
      - kind: unit
        ref: "tests/test_hardware_source.py::test_captured_frames_yields_frame_with_masked_id_extended_flag_payload_and_timestamp"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_captured_frames_extended_flag_clear_when_bit_not_set"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_frames_yields_raw_frames_matching_captured_frames"
        status: pass
    human_judgment: false
  - id: D5
    description: "Messages on a net ID not among the configured channels are excluded and counted rather than silently dropped; both configured channels stream from one HardwareFrameSource instance in one interleaved stream -- CAP-01's first clause at the source layer"
    requirement: "CAP-01"
    verification:
      - kind: unit
        ref: "tests/test_hardware_source.py::test_excluded_messages_are_counted_not_yielded"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_dual_bus_interleaved_messages_both_channels_in_one_stream"
        status: pass
    human_judgment: false
  - id: D6
    description: "A non-zero hardware error count from the SDK increments a named counter and logs the poll iteration and count; a poll exception is caught by the SDK's own RuntimeError type (never the builtin), logged critical with iteration context, counted, and re-raised after the stop event is set; the loop exits promptly when the stop event is set without waiting out a full poll interval"
    requirement: "CAP-06"
    verification:
      - kind: unit
        ref: "tests/test_hardware_source.py::test_hardware_error_count_increments_and_logs_iteration_and_count"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_poll_exception_caught_by_sdk_type_logged_critical_counted_reraised_and_stop_event_set"
        status: pass
      - kind: unit
        ref: "tests/test_hardware_source.py::test_loop_exits_promptly_when_stop_event_set_without_waiting_full_interval"
        status: pass
    human_judgment: false
  - id: D7
    description: "Dual-bus capture against real hardware, extended-ID flag correctness on real DBC-marked-extended messages, and archive timestamps advancing at real wall-clock rate (settling the UNCONFIRMED timestamp constant) -- 01-VALIDATION.md lists this as manual-only; not exercisable without the neoVI PI attached"
    requirement: "CAP-01 / CAP-06"
    verification: []
    human_judgment: true

# Metrics
duration: 30min
completed: 2026-08-01
status: complete
---

# Phase 1 Plan 9: The Single Consolidated python-ics Capture Implementation Summary

**`HardwareFrameSource` — CAP-01's first clause built on `python-ics` through a lazily-imported, injectable SDK seam: config-driven channel resolution that fails fast on an unresolvable name, fail-fast device selection with CAP-06 error context, and a poll loop whose extended-ID flag and poll-return-shape are established live against the installed SDK while its timestamp conversion is carried forward as a named, explicitly UNCONFIRMED constant rather than guessed.**

## Performance

- **Duration:** ~30 min (includes the prior paused session's context-gathering and live SDK investigation, preserved in `.continue-here.md`/`HANDOFF.json`, plus this session's implementation)
- **Completed:** 2026-08-01
- **Tasks:** 2
- **Files modified:** 2 (both created — `tests/test_hardware_source.py` replaces 01-02's placeholder skip)

## Accomplishments

- `src/telemetry/capture/hardware_source.py` created: `HardwareFrameSource` takes the SDK module as an injectable constructor argument defaulting to a lazily-imported real `ics` (imported only inside `_default_sdk()`, never at module scope), so constructing, testing, or merely importing this module never touches `ics` or hardware.
- Channel resolution is config-driven and fails fast: each configured channel's symbolic net-ID constant name is resolved against the SDK object in `__init__`; an unresolvable name raises `ChannelResolutionError` naming the channel and the constant, and no partially-constructed source is returned. This deliberately does not reproduce `src/new_logger.py::resolve_net_ids`'s warn-and-continue-unfiltered behavior (T-01-22).
- `open()` selects the device by configured serial (or first-found with none configured), fails fast with `DeviceNotFoundError` when no devices are found or the configured serial matches none, and logs the configured serial plus every device actually seen at critical severity before raising (CAP-06) — a bench diagnosis never requires re-running under a debugger.
- `captured_frames()` polls at the configured interval via `threading.Event.wait(timeout=...)` rather than `time.sleep()`, so a stop event set by another thread mid-sleep is noticed immediately rather than after a full poll interval elapses. It filters by the resolved net-ID set (excluded messages are counted, not silently dropped), constructs one `CapturedFrame` per surviving message, and yields a stream carrying both configured channels from one device handle — CAP-01's first clause at the source layer. `frames()` is a thin delegate yielding the `RawFrame` half, satisfying `telemetry.wire.frame_source.FrameSource` unchanged.
- Hardware error counts reported by the SDK increment a named counter and log the poll iteration and count; a poll exception is caught via the injected SDK object's own `RuntimeError` attribute — never the bare builtin, since `ics.RuntimeError` does not subclass `builtins.RuntimeError` — logged at critical severity with iteration context, counted, and re-raised after the stop event is set (CAP-06). The test fake's exception class mirrors this same non-builtin inheritance, so a regression to `except RuntimeError:` would fail the test suite rather than silently fail on real hardware.
- 18 tests in `tests/test_hardware_source.py`, all driven entirely through an injected fake SDK (except one explicitly-marked test that resolves the shipped `config/logger.json` against the real `ics` module without ever calling `find_devices()` — proving a config typo is caught by the suite, not at first boot on the car). Full suite: `python -m pytest -q -m "not slow"` — 249 passed, 3 skipped (all three remaining skips are placeholders explicitly owned by 01-10/01-12/01-13).

## Task Commits

1. **Task 1: SDK seam, config-driven channel resolution, fail-fast device open** — `9079b5d` (feat)
2. **Task 2: Poll loop, frame construction, hardware error accounting** — `0dff482` (feat)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified

- `src/telemetry/capture/hardware_source.py` — `HardwareFrameSource`, `ChannelResolutionError`, `DeviceNotFoundError`, `HardwareSourceCounters`, `TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED`
- `tests/test_hardware_source.py` — replaces 01-02's placeholder skip; 18 tests against a fake SDK covering channel resolution, device open, vspyx isolation, frame construction, error accounting, and prompt stop-event handling

## The Three SDK Facts (Task 2's Required Investigation)

All three were established live against the installed `python-ics 1!26.3.9` — never assumed from memory or from `src/new_logger.py`'s existing usage — as the plan's Task 2 `<action>` requires. Two are settled facts; one is deliberately carried forward as a labelled, unresolved assumption rather than guessed.

1. **Extended-identifier flag — ESTABLISHED.** `StatusBitField & ics.SPY_STATUS_XTD_FRAME` (`0x4`), not `ics.SPY_STATUS_EXTENDED` (`0x80000000`). Established by inspecting the installed module's own constants live: `SPY_STATUS_XTD_FRAME` sits in the coherent low-order per-frame flag family (`GLOBAL_ERR=0x1, TX_MSG=0x2, XTD_FRAME=0x4, REMOTE_FRAME=0x8, CRC_ERROR=0x10`), while `SPY_STATUS_EXTENDED` sits in a separate high-bit tier that even overloads `0x20000000` for both `SPY_STATUS_CANFD` and `SPY_STATUS_INIT_MESSAGE` — ruling it out as a reliable simple per-frame flag. Corroborated by `src/new_logger.py`'s existing working TX code, which already sets `msg.StatusBitField = ics.SPY_STATUS_XTD_FRAME` to mark an outgoing frame extended on the exact same field.
2. **Poll return shape — ESTABLISHED.** `ics.get_messages(device)` returns `(tuple_of_SpyMessage, error_count)`. Confirmed verbatim from the installed module's own docstring (`ics.get_messages.__doc__`, captured live this session), matching `src/new_logger.py`'s existing `msgs, error_count = ics.get_messages(device)` usage exactly.
3. **Timestamp unit/epoch — NOT ESTABLISHED. Deliberately left unconfirmed, per the plan's own instruction not to guess.** `SpyMessage.TimeSystem`'s own docstring (captured live via `help(ics.SpyMessage)`) states it is sourced from the Windows-only `timeGetTime()` multimedia API — milliseconds, from an arbitrary system-uptime-relative epoch. The deployment target is Linux (the CM4), so this Windows-specific docstring text may not describe what the same attribute reports on the real hardware. `src/new_logger.py`'s existing `f'{ts:.6f}'` CSV formatting is not authoritative counter-evidence — an integer millisecond count formatted with six decimals just shows trailing zeros. Implemented behind one named module constant, `TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED = 1000` (assumes milliseconds, the SDK-documented value), with an extensive UNCONFIRMED comment at its definition site. **This is a hardware bring-up item**, not a closed question — settle it on the first bench session with the neoVI PI attached and record the result against `01-VALIDATION.md`'s manual-only dual-bus capture check (Task 2's `<verify>` `human-check`: archive timestamps must advance at the real wall-clock rate).

A fourth fact — not an SDK behavior but an exception-hierarchy landmine — was also verified live and is load-bearing throughout this module: **`ics.RuntimeError` does not subclass `builtins.RuntimeError`** (`issubclass(ics.RuntimeError, RuntimeError)` is `False`; its MRO is `(ics.ics.RuntimeError, Exception, BaseException, object)`). Every SDK exception in this module is caught via `self._sdk.RuntimeError`, never a bare `except RuntimeError:`.

## Decisions Made

- **Constructor takes granular parameters (`channels`, `poll_interval_s`, `hardware_serial`), not the whole `LoggerConfig` object.** Matches `FanOut`'s existing shape and keeps every test free of constructing full `LoggerConfig`/`ArchiveConfig`/`TelemetryConfig`/`LinkConfig` fixtures just to exercise channel resolution or device-open logic in isolation. `01-10`'s logger CLI extracts these from its loaded `LoggerConfig` at the call site.
- **`stop_event` is a required constructor argument, not a per-call parameter.** `frames()` must satisfy `FrameSource`'s exact no-argument signature (`def frames(self) -> Iterator[RawFrame]`), so the stop signal has to live on the instance rather than be threaded through each call.
- **`threading.Event.wait(timeout=...)` instead of `time.sleep()`** in the poll loop — `wait()` unblocks immediately when the event is set from another thread, which is what makes "exits promptly ... without waiting out a full poll interval" true rather than aspirational. Verified by `test_loop_exits_promptly_when_stop_event_set_without_waiting_full_interval`, which uses a 5-second poll interval and asserts the generator returns in well under a second once the stop event is set from another thread.
- **Channel resolution happens in `__init__`, not lazily.** An unresolvable symbolic net-ID name is fatal at construction per the plan; no partially-configured `HardwareFrameSource` can exist.
- **`open()` is a separate method, called lazily by `captured_frames()` if not already invoked.** Tests exercise device selection in isolation (calling `open()` directly) without needing to drive the poll loop.

## Deviations from Plan

None — plan executed exactly as written. Both blocking constraints from `.continue-here.md` (catch `ics.RuntimeError` via the injected SDK object, never the bare builtin; label the timestamp constant UNCONFIRMED rather than guessing) are implemented and tested. `src/new_logger.py`, `src/neoVI_logger.py`, `src/references.py`, and `src/neoVI_sender.py` were not touched, modified, or deleted (CAP-01's removal clause is deferred to Phase 2 per user decision).

## Issues Encountered

None. The prior session's live SDK investigation (preserved in `.continue-here.md`/`HANDOFF.json`) resolved two of the three required facts with confidence and correctly identified the third as unresolvable without real hardware — this session implemented directly from that record with no further investigation needed.

## User Setup Required

None — no external service configuration required. python-ics was already an installed project dependency.

## Next Phase Readiness

- `HardwareFrameSource` is ready for `01-10`'s logger CLI to construct from a loaded `LoggerConfig`, call `.open()`, and feed `.captured_frames()` into `FanOut.submit()` — no further change needed in this module for that integration.
- `.frames()` is ready for the Phase 0 measurement tooling to consume unchanged, satisfying `FrameSource` with no adaptation.
- **Open hardware bring-up item:** `TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED` must be settled against real hardware. Task 2's `<verify>` `human-check` (dual-bus capture with the neoVI PI attached, checking both channel tags, the extended-ID flag against DBC-marked-extended messages, and archive timestamps advancing at the real wall-clock rate) is the place to record the result, per `01-VALIDATION.md`'s manual-only listing. If the true unit turns out to differ from the documented Windows `timeGetTime()` milliseconds assumption, only this one named constant needs to change.
- CAP-01, CAP-06, and OPS-05 are **not** marked complete in `REQUIREMENTS.md` by this plan — `01-10` (CAP-01, OPS-05), `01-11`/`01-12` (OPS-05), and `01-13` (CAP-06) also claim them and are their last claimants.
- `.planning/phases/01-dual-path-capture-durable-archive-and-thin-live-link/.continue-here.md` is now stale and is deleted as part of this plan's completion.
- No blockers.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-01*

## Self-Check: PASSED

`src/telemetry/capture/hardware_source.py` and `tests/test_hardware_source.py` were verified present on disk. Commits `9079b5d` (Task 1) and `0dff482` (Task 2) were verified present in `git log --oneline --all`. `python -m pytest tests/test_hardware_source.py -x -q --tb=short` (18 passed) and `python -m pytest -q -m "not slow"` (249 passed, 3 skipped — all remaining skips are placeholders explicitly owned by 01-10/01-12/01-13) were both re-confirmed green before this summary was finalized.
