---
phase: 02-python-ground-station-and-dashboard-cutover
plan: 03
subsystem: telemetry-ground-station
tags: [simulator, synthetic-data, udp, dashboard-demo, cli]

# Dependency graph
requires:
  - phase: 02-python-ground-station-and-dashboard-cutover (plan 01)
    provides: SseHub/DashboardServer, telemetry.ground.cli --serve, GroundStateError/SignalState
  - phase: 02-python-ground-station-and-dashboard-cutover (plan 02)
    provides: dashboard.html served over HTTP/SSE, staleness dimming, GND-02/04/05 complete
  - phase: 01-dual-path-capture-durable-archive-and-thin-live-link
    provides: SyntheticFrameSource, TelemetryPipeline, Encoder, COBS+CRC framing, UdpLink,
      LoggerConfig/GateConfig typed loaders
provides:
  - src/telemetry/ground/simulate.py — python -m telemetry.ground.simulate, a car stand-in that
    drives SyntheticFrameSource through the real encode/batch/frame/link path (Encoder ->
    TelemetryPipeline -> COBS+CRC -> Link.send()), narrowed to config.telemetry.allowlist, paced
    in real time, with --loop, --bracket, --pacing, --duration-s
  - build_car_link (module-level, testable) — the car-side mirror of
    telemetry.ground.cli._build_link's role reversal; refuses --link-kind loopback with
    UnreachableLinkKind rather than appearing to run while sending into a void
  - feed_frames (module-level, testable) — the pacing loop, callable and provably bounded without
    a subprocess or socket
  - tests/test_ground_simulate.py — 3 new tests: bytes deframe to allowlisted DBC messages with
    zero framing failures, loopback link kind refused, pacing multiplier bounds a short run
affects: [02-04-legacy-retirement]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A CLI entry point's frame-feeding loop and link-construction are each their own
      module-level function (feed_frames, build_car_link), independent of argparse, so
      tests/test_ground_simulate.py drives real behavior with no subprocess and no socket --
      mirrors the testability shape run_consumer_loop already established in telemetry.ground.cli"
    - "Real-time pacing via threading.Event.wait(timeout=remaining) as the sleep primitive, not
      time.sleep() -- the stop event is checked promptly even mid-sleep, and offsets are always
      computed relative to the first frame's own timestamp, never as an absolute wall-clock
      target, so a paced loop can never appear hung"

key-files:
  created:
    - src/telemetry/ground/simulate.py
    - tests/test_ground_simulate.py
  modified: []

key-decisions:
  - "GND-03 and CAP-01 left Pending in REQUIREMENTS.md -- both are also claimed by 02-04's own
    requirements frontmatter (the plan that physically deletes can-dashboard/ and the four legacy
    logger files), so this plan, though it also lists GND-03, does not mark it complete. Verified
    by grepping every phase-2 plan's requirements: frontmatter before writing this summary."
  - "TelemetryPipeline checks stop_event BEFORE popping its deque (by design -- the live path is
    lossy at stop for whatever is still queued). Task 2's test synchronizes by polling
    pipeline.counters.frames_sent up to a bounded deadline before setting stop_event, not by
    checking queue emptiness (which produced a flaky false-empty read on a queue with unconsumed
    items still present) -- this is a correct-by-construction fix to the test's own
    synchronization, not a pipeline change."
  - "No watchdog timer added (unlike telemetry.logger.cli's real-time hardware/synthetic
    watchdog): feed_frames(loop=False) already terminates once frame_source.frames() is
    exhausted, and a watchdog fixed at --duration-s real seconds would fire early relative to a
    <1.0 --pacing run (real playback time is duration_s/pacing, not duration_s) -- adding one
    would work against the plan's own pacing design rather than for it."

requirements-completed: []  # GND-03 stays Pending -- see key-decisions above; 02-04 completes it.

coverage:
  - id: D1
    description: "A Python simulator drives the dashboard with realistic, DBC-shaped CAN data
      with no car, no neoVI hardware, and no radio present, over the real encode/batch/frame/link
      path (GND-03, D-15)"
    requirement: "GND-03"
    verification:
      - kind: integration
        ref: "tests/test_ground_simulate.py#test_simulator_output_deframes_to_allowlisted_dbc_messages"
        status: pass
    human_judgment: false
  - id: D2
    description: "A loopback link kind is refused with an explanation rather than silently
      sending into a void"
    requirement: "GND-03"
    verification:
      - kind: unit
        ref: "tests/test_ground_simulate.py#test_simulator_refuses_a_link_kind_that_cannot_reach_another_process"
        status: pass
    human_judgment: false
  - id: D3
    description: "Frames are paced in real time (not delivered as one instantaneous burst), and
      --loop lets a demo run for as long as someone is watching it"
    requirement: "GND-03"
    verification:
      - kind: unit
        ref: "tests/test_ground_simulate.py#test_pacing_multiplier_bounds_a_short_run"
        status: pass
    human_judgment: false
  - id: D4
    description: "The dashboard (telemetry.ground.cli --serve) actually renders the simulated
      values when opened in a browser: both channel tabs populate, values change at plausible
      rates, the status indicator reflects live state, stopping the simulator dims values within
      ~3s and restarting un-dims them"
    verification: []
    human_judgment: true
    rationale: "No browser automation tool was available this session (claude-in-chrome extension
      not connected). Verified everything automatable instead: two real subprocesses
      (telemetry.ground.cli --serve --link-kind udp + telemetry.ground.simulate --link-kind udp)
      over a real UDP socket pair, with the ground station's own link-health log reporting
      batches_received=batches_ok=98/98, records_decoded=5418, records_decode_failed=0, zero
      cobs/crc/batch_format discards, and a direct HTTP fetch of both /events (SSE snapshot
      containing real decoded signal values) and / (the dashboard HTML) succeeding. The
      browser-rendering half specifically is unrun, recorded in .planning/WINDOWS.md (id=2, kind
      unrun-verify)."

# Metrics
duration: 15min
completed: 2026-08-08
status: complete
---

# Phase 2 Plan 03: Python Car-Stand-In Simulator Summary

**`python -m telemetry.ground.simulate` drives DBC-shaped synthetic CAN traffic through the real Encoder/TelemetryPipeline/COBS+CRC/UdpLink path — a working Python replacement for the retired `can-dashboard/simulate.js`, proven end to end against a real two-process UDP demo.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-08-08T17:00:52Z (approx, first task commit)
- **Completed:** 2026-08-08T17:07:18Z
- **Tasks:** 2
- **Files modified:** 2 (`simulate.py` created, `test_ground_simulate.py` created)

## Accomplishments

- `src/telemetry/ground/simulate.py`: a car stand-in that reuses every existing piece of the real
  wire path — `SyntheticFrameSource` (unchanged, narrowed via `only_message_names` to
  `config.telemetry.allowlist`, the same 12-message critical-channel subset the real live path
  carries), `Encoder`, `TelemetryPipeline` fed by a `collections.deque(maxlen=...)` (the same
  bounded-deque shape `FanOut` gives the telemetry side on the car), COBS+CRC framing, and
  `UdpLink` — with zero re-implementation of per-signal value generation, unlike the retired
  `can-dashboard/simulate.js`'s hardcoded 15-signal random-walk table
- `build_car_link`: the mirror image of `telemetry.ground.cli._build_link`'s documented role
  reversal — binds `(local_host, local_port)` and sends to `(remote_host, remote_port)`, exactly
  what `telemetry.logger.cli._build_link` already does for the real car. Refuses `--link-kind
  loopback` with `UnreachableLinkKind`, naming the specific reason (an in-process `LoopbackLink`
  cannot reach a ground station running as a separate process) rather than appearing to run while
  sending into a void
- `feed_frames`: paces `SyntheticFrameSource.frames()` in real time by holding each frame until
  the wall clock reaches its own offset from the first frame's timestamp (divided by
  `--pacing`), using `stop_event.wait(timeout=remaining)` as the sleep primitive so a stop request
  is always honored promptly, never sleeping on an absolute clock target; `--loop` restarts
  iteration and re-bases the pacing clock once exhausted
- Both `build_car_link` and `feed_frames` are independently callable, subprocess-free functions —
  `tests/test_ground_simulate.py` drives them directly against a real `Deframer` and a recording
  `Link` stand-in
- Verified live: `python -m telemetry.ground.simulate --link-kind udp --duration-s 5` runs, sends
  framed batches, and exits 0; `--link-kind loopback` exits 1 with the refusal message
- Two-terminal demo run as real subprocesses over real UDP: ground station's link-health line
  reported `batches_received=98 batches_ok=98 ... records_decoded=5418
  records_decode_failed=0`, with zero cobs/crc/batch_format discards; a direct HTTP fetch of
  `/events` returned a real decoded-signal SSE snapshot and `/` served the dashboard HTML
- Full suite: 308 → 311 passing (3 new tests in `test_ground_simulate.py`)
- GND-03 and CAP-01 confirmed left Pending — re-grepped every phase-2 plan's `requirements:`
  frontmatter first: 02-04 claims both `GND-03, CAP-01`, so this plan (which also lists GND-03 in
  its own frontmatter) does not mark it complete

## Task Commits

1. **Task 1: A car stand-in that speaks the real wire** — `49d3c23` (feat)
2. **Task 2: Prove the simulator's bytes are real telemetry, then demo it** — `606c03c` (test)

**Plan metadata:** (this commit)

## Files Created/Modified

- `src/telemetry/ground/simulate.py` — the simulator CLI: `main`, `build_car_link`,
  `feed_frames`, `UnreachableLinkKind`
- `tests/test_ground_simulate.py` — 3 tests: byte-level deframe/allowlist proof, loopback
  refusal, pacing-multiplier wall-clock bound
- `.planning/WINDOWS.md` — id=2 (`unrun-verify`, browser-rendering half of the two-terminal demo)

## Decisions Made

- GND-03 stays Pending: also claimed by 02-04's frontmatter, which is the plan that actually
  deletes `can-dashboard/`; marking it here would violate the "never mark complete if a later
  plan claims it" rule
- Test synchronization fix: `TelemetryPipeline` checks `stop_event` before popping its deque
  (lossy-at-stop by design), so a test must wait for `pipeline.counters.frames_sent` to reach the
  fed count — not for the deque to look empty — before signalling stop; the queue-emptiness check
  raced and produced a genuinely flaky (~50%) false failure, fixed to poll the counter instead
- No watchdog timer in `main()`: `feed_frames(loop=False)` already terminates on its own once the
  generated frames are exhausted, and a real-seconds watchdog fixed at `--duration-s` would cut a
  `--pacing < 1.0` run short before it finished playing back — omitted deliberately rather than
  copied from `telemetry.logger.cli`'s pattern, which doesn't have this pacing interaction

## Deviations from Plan

None — plan executed exactly as written. The only correction made during execution was to this
plan's own new test file's synchronization logic (a flaky wait condition caught immediately by
running the new test 5-8 times in a row before moving on), not to any production code path Task 1
wrote.

## Issues Encountered

- **Task 2's browser-rendering human-check was not run this session.** No browser automation tool
  was available (the `claude-in-chrome` extension is not connected in this environment).
  Everything automatable about the two-terminal demo was verified instead: two real subprocesses
  communicating over a real UDP socket pair, with the ground station's own link-health counters
  (`batches_received=batches_ok=98/98`, `records_decoded=5418`, `records_decode_failed=0`, zero
  cobs/crc/batch_format discards) and a direct HTTP fetch of both `/events` (a real decoded-signal
  SSE snapshot) and `/` (the dashboard HTML) confirming the full chain delivers real data all the
  way to the HTTP layer. Only the final "does it render correctly in an actual browser tab" step
  is unrun, recorded in `.planning/WINDOWS.md` (id=2, kind `unrun-verify`) — the same honest
  pattern 02-02-SUMMARY.md used for its own unrun browser check (id=1).
- `ThreadingHTTPServer` again printed a `ConnectionAbortedError` traceback to stderr on Windows
  during the manual demo, when the `urllib`-based `/events` probe closed its connection mid-stream
  — the same pre-existing, non-blocking `socketserver` artifact noted in 02-01-SUMMARY.md and
  02-02-SUMMARY.md (not a regression, not a test failure; deployment target is Linux/CM4).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- 02-04 can now safely retire `can-dashboard/` and the four legacy logger files: the demo
  capability the JavaScript simulator provided now exists in Python, proven both at the byte
  level (automated tests) and at the network level (real two-process UDP run)
- Two open items remain in `.planning/WINDOWS.md` before `/gsd-ship`: id=1 (02-02's dashboard DOM
  interactions) and id=2 (this plan's browser-rendering confirmation) — both need real browser
  tooling, recommended together once available (or via `/gsd-verify-work 2`)
- No blockers. `requirements.txt` is unchanged; no new dependency introduced

## Self-Check: PASSED

All created/modified files exist on disk (`src/telemetry/ground/simulate.py`,
`tests/test_ground_simulate.py`, `.planning/WINDOWS.md`, this SUMMARY.md); both cited task commits
(`49d3c23`, `606c03c`) are present in `git log --oneline --all`. Verified directly this session.

---
*Phase: 02-python-ground-station-and-dashboard-cutover*
*Completed: 2026-08-08*
