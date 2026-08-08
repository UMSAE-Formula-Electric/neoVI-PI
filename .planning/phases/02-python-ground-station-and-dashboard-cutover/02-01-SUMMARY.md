---
phase: 02-python-ground-station-and-dashboard-cutover
plan: 01
subsystem: telemetry-ground-station
tags: [sse, http.server, threading, drop-oldest, urllib, dbc-decode]

# Dependency graph
requires:
  - phase: 01-dual-path-capture-durable-archive-and-thin-live-link
    provides: LoopbackLink/UdpLink, COBS+CRC framing, Deframer, DBC decode
      loop (telemetry.ground.cli.run_consumer_loop), config/logger.json and
      config/gate.json typed loaders
provides:
  - src/telemetry/ground/state.py — SignalState, build_message_index,
    SignalStateCounters, GroundStateError, MessageLocation, UNMAPPED_CHANNEL
  - src/telemetry/ground/server.py — SseHub, DashboardServer,
    SseHubCounters, make_handler_class, SSE_CLIENT_QUEUE_MAXSIZE,
    SSE_HEARTBEAT_S
  - telemetry.ground.cli main() extended additively with --serve,
    --http-host, --http-port
  - one Python process that decodes a signal off a real link and pushes it
    to an already-connected SSE client, with a mid-session client catching
    up via a snapshot-first event
affects: [02-02-dashboard-port, 02-03-simulator, 02-04-legacy-retirement]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Drop-oldest per-client fan-out (SseHub.broadcast): check-then-evict-
      then-count via put_nowait/get_nowait, mirroring FanOut.submit — never
      raises, never blocks, freshest frame always survives"
    - "Log-once-then-count for concurrently-reachable failures: a
      closure-scoped lock + single-key dict (not a class attribute) guards
      the 'has this been logged yet' decision across handler threads,
      distinct from FanOutCounters' single-writer no-lock convention"
    - "SSE wire framing: one generic 'message' event (no event: line),
      data: JSON with a type discriminator ('snapshot' | 'update')"
    - "Cross-thread shutdown: DashboardServer.shutdown() is called only
      from the decode thread's finally block, never from the SIGINT/SIGTERM
      handler (same-thread deadlock with serve_forever())"

key-files:
  created:
    - src/telemetry/ground/state.py
    - src/telemetry/ground/server.py
    - tests/test_ground_server.py
  modified:
    - src/telemetry/ground/cli.py

key-decisions:
  - "SSE framing: one generic message event, JSON type discriminator —
    matches the ported dashboard.html's existing single-handler dispatch"
  - "ts unit is epoch milliseconds (was seconds in can-dashboard/server.js)
    — a plain Date.now() - ts subtraction against the 3000ms staleness bar"
  - "Test file split pure telemetry.ground.state unit tests (no server, no
    link) from full-stack SSE tests (real DashboardServer + real
    LoopbackLink fed real COBS-framed bytes) rather than routing every
    assertion through the full stack"

patterns-established:
  - "Pattern: SSE per-client bounded queue + drop-oldest, applied one layer
    downstream of CAP-04's telemetry-deque guarantee — the same
    never-blocks-the-producer discipline extended to the browser edge"

requirements-completed: []  # deliberate — GND-02/04/05 are also claimed by
  # 02-02 (a later plan); per the phase's locked anti-pattern rule, only the
  # plan that finishes ALL of a requirement's scope may mark it Complete.
  # 02-01 proves the vertical slice; 02-02 ports dashboard.html on top of it.

coverage:
  - id: D1
    description: "One decoded signal travels link -> decode -> state store
      -> SSE -> an already-connected client, carrying channel, id, name,
      signal, value, unit, and a wall-clock ts"
    verification:
      - kind: integration
        ref: "tests/test_ground_server.py#test_client_receives_update_after_snapshot"
        status: pass
      - kind: integration
        ref: "tests/test_ground_server.py#test_update_ts_is_wall_clock_not_frame_timestamp"
        status: pass
    human_judgment: false
  - id: D2
    description: "A client connecting mid-session receives the full current
      state as its first event, before any update event"
    verification:
      - kind: integration
        ref: "tests/test_ground_server.py#test_first_event_is_snapshot"
        status: pass
    human_judgment: false
  - id: D3
    description: "One Python process runs both the decode loop and the HTTP
      server; headless stdout JSON output and the two-process UDP
      end-to-end test are unchanged"
    verification:
      - kind: integration
        ref: "tests/test_end_to_end.py"
        status: pass
      - kind: other
        ref: "python -m telemetry.ground.cli --help (shows --serve,
          --http-host, --http-port)"
        status: pass
    human_judgment: false
  - id: D4
    description: "A slow or dead SSE client cannot block the decode thread
      or grow server memory: full client queues drop-oldest and count it,
      broadcasts never block, dead clients are unregistered, unlisted
      routes 404, /events sends no Content-Length"
    verification:
      - kind: unit
        ref: "tests/test_ground_server.py#test_slow_client_loses_oldest_not_newest"
        status: pass
      - kind: unit
        ref: "tests/test_ground_server.py#test_broadcast_never_blocks_on_a_full_client"
        status: pass
      - kind: integration
        ref: "tests/test_ground_server.py#test_unknown_path_returns_404"
        status: pass
      - kind: integration
        ref: "tests/test_ground_server.py#test_events_response_sends_no_content_length"
        status: pass
      - kind: integration
        ref: "tests/test_ground_server.py#test_dead_client_is_unregistered"
        status: pass
    human_judgment: false

# Metrics
duration: 35min
completed: 2026-08-08
status: complete
---

# Phase 2 Plan 01: Ground Station SSE Tracer Summary

**One Python process serves live decoded CAN signals over Server-Sent Events with a bounded, drop-oldest per-client fan-out — proven end to end against a real link, real COBS framing, and a real DBC decode, with `urllib` standing in for the browser this plan does not yet build.**

## Performance

- **Duration:** 35 min (this session; Task 1's implementation was WIP-committed in an earlier session at `42f5774`)
- **Started:** 2026-08-08T15:53:00Z (approx, this session's resume)
- **Completed:** 2026-08-08T16:21:00Z
- **Tasks:** 2
- **Files modified:** 4 (`state.py`, `server.py`, `cli.py`, `tests/test_ground_server.py`)

## Accomplishments

- `telemetry.ground.state.SignalState`/`build_message_index`: derives each DBC message's pit-facing channel from its bus assignment (`assign_rates` + `logger_config.channels`), fail-closing on a `(channel, id_key)` collision instead of silently overwriting one message's values with another's
- `telemetry.ground.server.SseHub`/`DashboardServer`: a stdlib-`http.server`-based SSE endpoint at `/events` — snapshot-first framing for a newly-connected client, drop-oldest bounded per-client queues so a slow browser tab can never apply backpressure to the decode thread, and a route allowlist that never joins a request path onto the filesystem
- `telemetry.ground.cli` grows additively: `--serve`/`--http-host`/`--http-port`; in serving mode the existing decode loop runs on a named thread while `serve_forever()` blocks the main thread, with `shutdown()` called only from the decode thread's own `finally` (the SIGINT handler still only sets `stop_event`, avoiding the same-thread deadlock `serve_forever()`+signal-handler would otherwise cause)
- 12 new tests in `tests/test_ground_server.py`, all real-code, no mocks: 3 pure `state.py` unit tests, 4 full-stack SSE tests against a real `DashboardServer` + real `LoopbackLink` fed real COBS-framed bytes, 5 Task 2 fan-out/hardening tests
- Headless (no `--serve`) behavior is byte-for-byte unchanged: `tests/test_end_to_end.py`'s 8 tests, including the two-process real-UDP-socket run, pass untouched

## Task Commits

Task 1's three implementation files (`state.py`, `server.py`, `cli.py`) were WIP-committed in an earlier session; this session completed the task and continued the plan:

1. **Task 1: End-to-end "one decoded signal reaches a connected client"** — `42f5774` (wip, prior session: implementation), `a271991` (test: the 7 tracer assertions)
2. **Task 2: bounded per-client fan-out and hardened routes** — `b6fd657` (test, RED), `854f137` (feat, GREEN)

**Plan metadata:** (this commit)

## Files Created/Modified

- `src/telemetry/ground/state.py` — `SignalState`, `build_message_index`, counters, collision guard
- `src/telemetry/ground/server.py` — `SseHub`, `DashboardServer`, drop-oldest broadcast, hardened route handler
- `src/telemetry/ground/cli.py` — `--serve`/`--http-host`/`--http-port`, serving-mode threading, shutdown-counters logging
- `tests/test_ground_server.py` — 12 tests (created this session)

## Decisions Made

- SSE wire framing: one generic `message` event (no `event:` line), `data:` JSON with a `type` discriminator (`"snapshot"` | `"update"`) — matches the ported `dashboard.html`'s existing single-handler dispatch, so 02-02's client diff is a transport swap, not a rewrite
- `ts` unit is epoch milliseconds, not `can-dashboard/server.js`'s epoch seconds — makes 02-02's staleness check a plain `Date.now() - ts` subtraction against the 3000ms bar
- Test file structure: pure `telemetry.ground.state` unit tests (channel derivation, collision guard, no server/link) kept separate from full-stack SSE tests (real `DashboardServer` + real `LoopbackLink` + real COBS framing) — routing the state-layer assertions through the full stack would have added setup cost with no discriminating power
- SSE write-failure log-once state uses a closure-scoped lock + single-key dict rather than a class attribute, because unlike `FanOutCounters`' single-writer capture thread, multiple SSE handler threads (one per connected client) can race on "has this been logged yet" — a genuine new read-modify-write this module didn't have in Task 1

## No DBC Messages Resolved to UNMAPPED

Every message in `build_message_index`'s real-DBC run (`test_real_dbc_message_index_has_no_collisions`) resolved to a configured channel — `epbr2026_DBC_v1.0.dbc`'s bus assignment (`config/gate.json`'s `bus_assignment.by_ecu`/`default_bus`) covers every sender the DBC declares, so `UNMAPPED_CHANNEL` was exercised only by the fake-message collision test, never by real traffic.

## Deviations from Plan

None — plan executed exactly as written. The plan's own interface contract, SSE framing decision, and `ts` unit decision were followed verbatim; no Rule 1-4 auto-fixes were needed.

## Issues Encountered

None. `ThreadingHTTPServer` prints a `ConnectionAbortedError` traceback to stderr on Windows when a test closes its `urllib` response mid-heartbeat before the server notices — this is `socketserver`'s own default `handle_error` behavior on an aborted connection, not a test failure (all 299 tests pass); noted here per this project's platform-divergence-tracking convention (deployment target is Linux/CM4, where this is a non-issue).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The vertical slice (link -> decode -> state -> SSE -> client) is proven with production-quality code and a real test harness; 02-02 can port `dashboard.html` on top of `SseHub`/`DashboardServer` with only a transport-object swap on the client side
- `GND-02`/`GND-04`/`GND-05` remain Pending in REQUIREMENTS.md by design — 02-02 is the plan that finishes the browser port and marks them Complete
- No blockers. `requirements.txt` is unchanged (D-01); no new dependency was introduced

## Self-Check: PASSED

All created files exist on disk (`state.py`, `server.py`, `cli.py`, `tests/test_ground_server.py`, this SUMMARY.md); all four cited commits (`42f5774`, `a271991`, `b6fd657`, `854f137`) are present in `git log --oneline --all`.

---
*Phase: 02-python-ground-station-and-dashboard-cutover*
*Completed: 2026-08-08*
