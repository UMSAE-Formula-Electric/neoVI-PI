---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 11
subsystem: telemetry-pipeline
tags: [ground-station, dbc-decode, udp, cli, link-health, subprocess, two-process]

# Dependency graph
requires:
  - phase: 01-04
    provides: "telemetry.ground.deframe.Deframer with its per-failure-mode DeframeCounters -- the byte-stream-to-RawFrame half this plan's consumer loop sits on top of"
  - phase: 01-08
    provides: "telemetry.link.udp.UdpLink (LINK-03) and framing's proven resync/discard-and-count guarantees (LINK-01/LINK-02) under real corruption -- what this plan's real UDP run and link-health line depend on"
  - phase: 01-10
    provides: "telemetry.logger.cli, the car-side counterpart process this plan's two-process test spawns and points at the ground station"
provides:
  - "telemetry.ground.cli -- python -m telemetry.ground.cli, the headless GND-01 ground-station entry point: receive, deframe, DBC-decode, emit newline-delimited JSON signal records to stdout, and a periodic link-health line to stderr"
  - "telemetry.ground.cli.run_consumer_loop -- the reusable receive-decode-emit core, importable and testable directly against a LoopbackLink with no CLI or subprocess involved"
  - "tests/test_end_to_end.py's Task 1 in-process suite (5 tests) proving GND-01's decode/undecodable/corrupt-batch/silent-link/link-health behaviors directly"
  - "tests/test_end_to_end.py's Task 2 two-process test -- the phase's own success-criterion-4 proof at the process level: two real OS subprocesses connected over one real loopback UDP socket, no radio, no vehicle hardware, no second machine"
affects: [01-12, 01-13]

# Tech tracking
tech-stack:
  added: []  # no new dependencies; assembles telemetry.ground.deframe, telemetry.link.udp, and cantools directly
  patterns:
    - "run_consumer_loop is a plain blocking function (not a thread class like ArchiveRunner/TelemetryPipeline) -- main() is the only production caller and it owns the process's one thread; tests drive the same function on a background thread they own, so the exact same code path is exercised in-process and via subprocess"
    - "Per-message-id log-once-with-suppression-counted for a DBC decode failure, mirroring FanOutCounters.telemetry_error_log_suppressed_count and TelemetryPipelineCounters' equivalent -- the third instance of the same T-01-18 rate-limiting shape in this codebase, not a new one"
    - "The udp link config block's local/remote fields are read with a deliberate role reversal on the ground side: this station binds (remote_host, remote_port) -- the address config/logger.json documents as where the car sends -- rather than (local_host, local_port), so the single shared checked-in file serves both ends when they run on two different machines"
    - "--duration-s on both CLIs (not just the car's) makes the two-process test deterministic without relying on platform-specific SIGTERM/SIGINT delivery -- Windows subprocess.terminate() calls TerminateProcess and never reaches a child's own signal handlers, so a bounded internal watchdog is the only cross-platform way to end a subprocess-based test cleanly"

key-files:
  created:
    - src/telemetry/ground/cli.py
  modified:
    - tests/test_end_to_end.py

key-decisions:
  - "Emitted records carry a 'topic' field (f\"/can/{message.name}\"), not a 'channel' field, and no channel/bus information is invented on the wire. The CFR/batch protocol (telemetry.wire.encoder, telemetry.wire.batcher) carries no per-frame channel field by design -- CapturedFrame.channel (which physical bus a frame was captured on) is dropped the moment a frame becomes a RawFrame headed for the encoder, one layer before anything crosses the wire. Inventing a channel label on the ground side would require importing config/gate.json's bus_assignment.by_ecu model (a Phase 0 modelling artifact, itself confirmed:false) into the ground station's own runtime -- a real architectural coupling this plan's files_modified scope (ground/cli.py, test file only) does not license. The two-process test computes channel coverage independently instead, using the same already-established telemetry.synth.rates.assign_rates mapping, as a test-side check rather than a wire-format claim."
  - "DBC decode failure (T-01-28, UndecodableFrame) is structurally unreachable through telemetry.ground.cli.main()'s own wiring, since the dictionary and the DBC used for decode are always built from the same loaded database -- every id_index the Deframer can recover necessarily resolves to a message the same db describes. Task 1's in-process test for this behavior therefore constructs a deliberately mismatched pair (the CFR dictionary built from the full DBC, but a stripped cantools.database.can.Database missing one message passed to the decode step) to exercise the real-world case this guards: a stale ground DBC after a car-side DBC update mid-deployment. This is documented directly in the test's own docstring, not left implicit."
  - "The two-process test raises telemetry.queue_depth to 10,000 in the car's own temp config, specifically for this test. --source synthetic's frame generator (telemetry.synth.generator.SyntheticFrameSource.frames()) yields an entire duration's worth of events with no real-time pacing at all -- confirmed directly that a 3s run against the shipped queue_depth=1000 measured telemetry_discard_count=288 (~14% of the allowlisted stream dropped by the deque's drop-oldest policy), which was flaky enough to occasionally drop every occurrence of the rarest allowlisted message (Battery_Volt_1_Overall_Param_Std, the only allowlisted message on bus2/SENSOR) and fail the two-bus coverage assertion. This is a synthetic-source test-determinism fix scoped to this one test's config file, not a change to config/logger.json's shipped default -- a real hardware run paces frames at the bus's own real rate and never approaches this queue depth."
  - "Both CLIs' subprocess lifetime in the two-process test is bounded by their own --duration-s (a new flag added to ground/cli.py, mirroring the car CLI's existing one), not by sending a termination signal from the test. Verified this session: Python's subprocess.Popen.terminate() on Windows calls TerminateProcess, which does not invoke the child's own Python signal handlers -- a signal-based shutdown protocol would work on the Linux deployment target but not on this Windows dev box, and would be nondeterministic in cross-platform CI. A bounded internal watchdog (threading.Timer, identical pattern to telemetry.logger.cli's existing one) works identically on both platforms."

requirements-completed: [GND-01, LINK-02, LINK-04]
# OPS-05 is also claimed by 01-12-PLAN.md's own requirements frontmatter
# (not yet run) and is therefore NOT marked complete here, per this plan's
# invoking prompt's explicit instruction and 01-08-SUMMARY.md's own note
# that LINK-02/LINK-04 (but not LINK-01/LINK-03, already closed by 01-08)
# wait for this plan. 01-12/01-13-PLAN.md frontmatter was read directly
# this session to confirm neither claims GND-01, LINK-02, or LINK-04 --
# this plan is their last claimant.

coverage:
  - id: D1
    description: "The ground consumer's own receive-decode-emit loop, driven in-process against a real LoopbackLink, turns a framed batch into a decoded signal record carrying the message name, the signal name, its value, and its unit taken from the DBC -- compared against the DBC-encoded source values, not opaque bytes"
    requirement: "GND-01"
    verification:
      - kind: unit
        ref: "tests/test_end_to_end.py#test_ground_consumer_decodes_batch_to_named_signal_values"
        status: pass
    human_judgment: false
  - id: D2
    description: "A recovered frame whose message the DBC does not describe is counted as an undecodable record and logged once with its id (repeats suppressed, not re-logged) -- and the loop keeps decoding the next good record in the same batch regardless"
    requirement: "GND-01"
    verification:
      - kind: unit
        ref: "tests/test_end_to_end.py#test_ground_consumer_counts_undecodable_message_and_continues"
        status: pass
    human_judgment: false
  - id: D3
    description: "A corrupt batch fed into the loop increments the deframer's own corruption counters and yields no decoded output at all, and the loop itself survives to prove it -- not merely recovers afterward"
    requirement: "LINK-02"
    verification:
      - kind: unit
        ref: "tests/test_end_to_end.py#test_ground_consumer_discards_corrupt_batch_and_keeps_running"
        status: pass
    human_judgment: false
  - id: D4
    description: "The loop exits on the stop event within a bounded time even when the link is completely silent, so a terminated session cannot hang the process"
    verification:
      - kind: unit
        ref: "tests/test_end_to_end.py#test_ground_consumer_loop_exits_promptly_on_stop_event_with_silent_link"
        status: pass
    human_judgment: false
  - id: D5
    description: "A periodic link-health line reports batches received, batches discarded by each failure class, records decoded, and records that failed to decode -- the counters Phase 6's link-health indicator (VIEW-06) will read"
    verification:
      - kind: unit
        ref: "tests/test_end_to_end.py#test_ground_consumer_link_health_reports_batches_and_records"
        status: pass
    human_judgment: false
  - id: D6
    description: "A frame captured by the car-side logger CLI, run as a real OS subprocess, arrives at a separate ground-station CLI subprocess decoded against the DBC -- having crossed batching, CRC-16, COBS framing, and a real loopback UDP socket -- with messages from both configured channels (MAIN/bus1 and SENSOR/bus2) present among the decoded records"
    requirement: "GND-01"
    verification:
      - kind: integration
        ref: "tests/test_end_to_end.py#test_two_process_capture_to_pit_run_over_udp_no_radio_present"
        status: pass
    human_judgment: false
  - id: D7
    description: "The car process's archive path is unaffected by anything happening on the live/UDP path: it exits zero, leaves exactly one complete session directory with a .done marker, and reports zero archive-path drops -- while the ground process's own final link-health line reports zero batches discarded on this clean loopback run"
    requirement: "LINK-02"
    verification:
      - kind: integration
        ref: "tests/test_end_to_end.py#test_two_process_capture_to_pit_run_over_udp_no_radio_present"
        status: pass
    human_judgment: false
  - id: D8
    description: "No radio hardware, no vehicle hardware, and no second machine are involved anywhere in the two-process proof -- two Python processes, one loopback network interface, with the ground station's real bound port discovered from its own reported listening line, never hardcoded"
    requirement: "LINK-04"
    verification:
      - kind: integration
        ref: "tests/test_end_to_end.py#test_two_process_capture_to_pit_run_over_udp_no_radio_present"
        status: pass
    human_judgment: false

# Metrics
duration: 90min
completed: 2026-08-02
status: complete
---

# Phase 1 Plan 11: The Headless Ground Station -- Deframe, DBC-Decode, and the Real Two-Process Proof Summary

**`python -m telemetry.ground.cli` is the headless GND-01 consumer -- receive, deframe, DBC-decode, and emit newline-delimited JSON signal records to stdout with a periodic link-health line to stderr -- proved both in-process against a `LoopbackLink` and, for real, as two separate OS subprocesses talking over one loopback UDP socket with no radio hardware anywhere in the chain.**

## Performance

- **Duration:** ~90 min
- **Started:** 2026-08-02 (approx., immediately following 01-10's completion)
- **Completed:** 2026-08-02
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- `src/telemetry/ground/cli.py`'s `run_consumer_loop` is the ground station's reusable receive-decode-emit core: it feeds every arriving link payload through a `Deframer`, DBC-decodes each recovered `RawFrame` via `cantools`, and calls back once per decoded signal with its topic, message id/name, signal name, value, unit, and frame timestamp. `main()` is a thin CLI wrapper around the same function -- no separate code path exists for "tested" versus "run for real."
- Every failure this plan's own layer can produce is caught by its specific type, counted, and logged at most once per message id with the repeat count preserved (mirroring `FanOutCounters`/`TelemetryPipelineCounters`' existing T-01-18 rate-limiting shape, now a third instance of the same pattern): an id the DBC does not describe or a payload the DBC itself rejects (`UndecodableFrame`, T-01-28), and an unexpected link-layer `OSError` beyond what `UdpLink.recv()` already contains (T-01-29). None of these can reach or kill the loop (T-01-01) -- framing/CFR failures remain `Deframer`'s own responsibility, never re-caught here.
- The `udp` link config block is read with a deliberate role reversal on the ground side, documented directly in the module's own docstring: this station binds `(remote_host, remote_port)` -- the address `config/logger.json` documents as where the car sends -- rather than `(local_host, local_port)`, which is the car's own outbound source address. This is what lets the one checked-in file serve both ends (car onboard box, pit laptop) without a second config file in real deployment.
- A periodic link-health line to stderr reports batches received, batches discarded by each failure class, records decoded, records that failed to decode, and an unexpected-link-error count -- named as Phase 6's link-health indicator (VIEW-06) will consume them.
- Task 1's five in-process tests drive `run_consumer_loop` directly against a real `LoopbackLink`, proving: decoded values equal the DBC-encoded source values (not opaque bytes); an undescribed message id is counted and logged exactly once even when it repeats in the same batch, and does not stop decoding of the next good record; a corrupt batch yields nothing while the loop itself keeps running (proven, not just recovered-from-afterward); the loop exits within roughly one `recv` timeout of the stop event even on a completely silent link; and the periodic health line reports every documented field.
- Task 2's two-process test is the phase's own success-criterion-4 proof at the *process* level, not merely in-process: `python -m telemetry.logger.cli` and `python -m telemetry.ground.cli` run as two real, separate OS subprocesses connected over one real loopback UDP socket. The ground process's real bound port (an OS-assigned ephemeral port, `remote_port=0` in its own temp config) is discovered by reading its own stderr readiness line -- never hardcoded, never assumed -- before the car process is started. Decoded records on the ground process's stdout are asserted against the configured allowlist and checked to span both configured channels (MAIN/bus1 and SENSOR/bus2), the car's archive path is confirmed unaffected (zero drops, session marked `.done`), and the ground process's own final link-health line confirms zero batches discarded on this clean run.
- Both subprocesses are bounded by their own `--duration-s` (a new flag added to `ground/cli.py`, mirroring the car CLI's existing one) rather than a termination signal from the test -- verified this session that `subprocess.Popen.terminate()` on this Windows dev box calls `TerminateProcess`, which never reaches a child's own Python signal handlers, so a signal-based shutdown protocol would not have been portable to this platform. The test additionally wraps both subprocesses in a hard-timeout `finally` block, so a hang fails the test rather than the suite.

## Task Commits

1. **Task 1: The headless ground-station consumer** - `a50f4d5` (feat)
2. **Task 2: Two-process capture-to-pit run over UDP with no radio present** - `1243476` (test)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified

- `src/telemetry/ground/cli.py` -- `main()`, `run_consumer_loop`, `GroundConsumerCounters`, `UndecodableFrame`; the headless ground-station entry point
- `tests/test_end_to_end.py` -- extended with Task 1's five in-process tests and Task 2's two-process subprocess test

## Decisions Made

- **Emitted records carry a `topic` field, not a `channel` field.** The wire protocol (CFR + batch header) carries no per-frame channel information by design -- `CapturedFrame.channel` is dropped the moment a frame becomes a `RawFrame` headed for the encoder, one layer before anything crosses the wire. Inventing a channel label would require importing Phase 0's `bus_assignment.by_ecu` model (itself `confirmed: false`) into the ground station's own runtime, a coupling this plan's scope does not license. The two-process test's own two-bus coverage check computes this independently, via the same mapping `telemetry.synth.rates.assign_rates` already uses, as a test-side check rather than a wire-format claim.
- **The DBC-decode-failure test constructs a deliberately mismatched dictionary/DBC pair**, since `main()`'s own wiring (dictionary and DBC always built from the same loaded database) makes an "id the DBC does not describe" structurally unreachable through the CLI's real code path. The test exercises the real-world case this guards instead: a stale ground DBC after a car-side DBC update mid-deployment.
- **`telemetry.queue_depth` is raised to 10,000 in the two-process test's own car config**, not in the shipped `config/logger.json`. `--source synthetic`'s frame generator yields an entire duration's worth of events with no real-time pacing, and the shipped `queue_depth=1000` measurably dropped ~14% of the allowlisted stream in a 3s run -- flaky enough to occasionally drop every occurrence of the one allowlisted bus2 message. A real hardware run paces frames at the bus's own rate and never approaches this depth.
- **`--duration-s` added to `ground/cli.py`** so the two-process test can bound both subprocesses' lifetimes deterministically, without relying on platform-specific signal delivery (verified `Popen.terminate()` does not reach a child's signal handlers on Windows).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Raised `telemetry.queue_depth` in the two-process test's own car config to prevent synthetic-burst deque overflow from making the two-bus coverage assertion flaky**
- **Found during:** Task 2, first full-suite run of the two-process test (passed standalone three times in isolation, then failed once inside the full `pytest -m "not slow"` run)
- **Issue:** `--source synthetic`'s frame generator (`telemetry.synth.generator.SyntheticFrameSource.frames()`) yields an entire duration's worth of events with no real-time pacing at all -- confirmed directly via a manual diagnostic run that a 3s run against the shipped `queue_depth=1000` measured `telemetry_discard_count=288` (~14% of the ~2,035-frame allowlisted stream dropped by the telemetry deque's drop-oldest policy). `Battery_Volt_1_Overall_Param_Std` -- the only allowlisted message resolving to bus2/SENSOR via `telemetry.synth.rates.assign_rates` -- occurs only ~39 times in that stream, small enough that the drop-oldest policy could plausibly evict every occurrence, which is exactly what happened on the failing run (test asserted `{'MAIN'}` instead of `{'MAIN', 'SENSOR'}`).
- **Fix:** The two-process test's `_write_config` helper gained a `telemetry_queue_depth` parameter; the car's own temp config in this one test is written with `telemetry.queue_depth=10_000`, comfortably above the total possible burst volume for a 3s synthetic run. Confirmed via the same manual diagnostic that this eliminates all drops (`telemetry_discard_count=0`). The test now also asserts `car_summary["telemetry_discard_count"] == 0` directly, so a regression of this fix fails loudly rather than silently re-introducing the flake. `config/logger.json`'s shipped default (1000) is unchanged -- this is a synthetic-source test-determinism fix scoped to one test's own generated config file, not a production tuning change.
- **Files modified:** `tests/test_end_to_end.py`
- **Verification:** Re-ran the full two-process test 3 times standalone (all pass) plus 2 full `pytest -m "not slow"` runs (both green, 269 passed / 2 skipped) after the fix, versus the one observed failure before it.
- **Committed in:** `1243476` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 Rule 3 blocking issue -- a test-determinism fix caught by running the new test inside the full suite, not merely in isolation, exactly as `01-CONTEXT.md`'s "prove it under damage/load, don't just reason about it" pattern from earlier plans in this phase would predict)
**Impact on plan:** No scope creep. The fix is entirely confined to the new test's own generated config file; `config/logger.json`'s shipped default and every other test's behavior are unchanged.

## Issues Encountered

None beyond the deviation above, caught and fixed within the same session before the Task 2 commit.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- `01-12` (the replay frame source) and `01-13` (the sustained-rate soak test) are the two remaining Wave-5 plans in this phase; neither claims `GND-01`, `LINK-02`, or `LINK-04` in its own frontmatter (confirmed by reading both plans' `requirements:` fields directly this session), so this plan is their last claimant and all three are marked complete in `REQUIREMENTS.md`. `OPS-05` is also claimed by `01-12` and is left `Pending` per this plan's own invoking instruction.
- `telemetry.ground.cli.run_consumer_loop` and `GroundConsumerCounters` are now available for `01-13`'s soak test to drive at sustained rate if it chooses to exercise the ground side under load, though `01-13`'s own frontmatter (`CAP-02, CAP-03, CAP-05, CAP-06`) suggests its focus is the car-side pipeline under sustained full-combined-bus rate, not the ground station specifically.
- The channel/topic gap this plan documents (the wire protocol carries no per-frame channel field) is a real, permanent architectural fact worth keeping in mind for any future phase that wants per-bus disambiguation on the ground side -- it would need either a wire-protocol change (out of Phase 1's scope, and not requested by any current requirement) or importing Phase 0's `confirmed: false` `bus_assignment.by_ecu` model into the ground station's runtime, which this plan deliberately did not do.
- No blockers.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-02*
