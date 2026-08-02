# Phase 2: Python Ground Station and Dashboard Cutover - Context

**Gathered:** 2026-08-02
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 4 grey areas, all user-accepted

<domain>
## Phase Boundary

The pit engineer opens a browser and watches the car's live signals arriving over the telemetry
link, served by **one** Python process on the pit laptop.

Phase 2 turns the headless Phase 1 ground station (`src/telemetry/ground/cli.py`, which emits JSON
records to stdout) into a single process that additionally holds current signal state and serves a
browser dashboard. It retires everything the Python path replaces: the Node.js server (GND-03) and
the four legacy Python loggers deferred out of Phase 1 (closing CAP-01).

**In scope:** GND-02, GND-03, GND-04, GND-05, and the deferred half of CAP-01.

**Explicitly NOT in scope:**
- Live time-series plots and full link-health telemetry — Phase 6.
- Limit alarms and thresholds — Phase 7.
- Any uplink / client-driven control of what the car transmits — Phase 4 (see `<deferred>`).
- Any change to the wire protocol, framing, or the car-side pipeline.

</domain>

<decisions>
## Implementation Decisions

### Server Architecture & Dependencies

- **Transport to the browser is Server-Sent Events over the stdlib `http.server`.** Zero new
  runtime dependencies — `requirements.txt` stays at its current 8 exact pins. Data flows
  server→browser only, so WebSocket's bidirectionality is unused; `EventSource` also brings its own
  reconnect, making the client simpler than the WebSocket code it replaces.
- **No package legitimacy gate is required for this phase.** That blocking human checkpoint (the
  01-01 precedent) exists for new third-party packages; SSE adds none. If planning finds a reason to
  reverse the transport decision and pull in `aiohttp`, the gate re-applies and Phase 2 gains a
  blocking checkpoint — do not add a dependency silently.
- **Threading model: a link-receive/decode thread plus the main-thread HTTP server, with shared
  state guarded by a lock.** This mirrors the `FanOut`/`ArchiveRunner` discipline already proven in
  Phase 1. Do NOT convert the link layer to asyncio — `link/base.py` states the transport owns its
  own thread, "no asyncio", per `01-CONTEXT.md`.
- **The headless JSON-record output survives.** `--output` / stdout records stay alongside dashboard
  serving. `tests/test_end_to_end.py`'s two-process UDP run depends on it and is the only
  no-hardware proof of the full car→pit chain; removing it would delete that proof.

### Dashboard Reuse & Delivery

- **Port `can-dashboard/dashboard.html` rather than rewriting it.** It is ~22 KB of working UI —
  channel tabs, search, per-message and per-signal visibility toggles, range bars, status indicator.
  Only the transport client changes (WebSocket → `EventSource`).
- **It moves to `src/telemetry/ground/static/` and is served by the Python process**, keeping
  everything under the telemetry package.
- **Stays a single file with inline CSS and JS.** Matches the existing artifact and the project's
  "no build pipeline" convention — do not introduce a bundler or split assets.
- **Link health in the UI is minimal for this phase:** connection state and last-frame age, reusing
  the existing status indicator. Distinguishing "steady" from "we stopped hearing from it" is
  explicitly Phase 6's goal — do not pull that scope forward.

### State Model & Snapshot

- **State shape is `state[channel][msg_id].signals[name] = {value, unit, ts}`.** This mirrors the
  shape `can-dashboard/server.js` already produces, so the dashboard's rendering logic ports
  unchanged. It also keeps message-level grouping, which Phase 4's per-message subset toggles will
  need something to bind to.
- **A newly connected browser receives a full state snapshot as the first event**, then incremental
  updates (GND-05). This is what `server.js` does today; preserve the behaviour.
- **State is bounded by the DBC.** Only known `(frame_id, is_extended)` pairs ever enter state, so
  it caps at the DBC's message count and needs no eviction logic. This structurally fixes the
  unbounded-growth issue `.planning/codebase/CONCERNS.md` flagged in `server.js` — note it as fixed
  by construction rather than by a TTL.
- **Staleness is carried as a per-signal `ts` and rendered by the UI** (greyed when old). No
  server-side staleness computation or push; threshold alarms are Phase 7.

### Legacy Retirement

- **Delete the Node server and the whole `can-dashboard/` directory** — `server.js`, `simulate.js`,
  `README.md` — after `dashboard.html` is ported. Closes GND-03.
- **Delete the four legacy Python loggers**: `src/neoVI_logger.py`, `src/new_logger.py`,
  `src/references.py`, `src/neoVI_sender.py`. **This closes CAP-01**, whose "duplicate
  implementation is removed from the repository" clause was deliberately deferred out of Phase 1 for
  rollback safety (`01-CONTEXT.md` § Deferred Ideas). Verify nothing imports them before deleting.
- **Replace `simulate.js` with a Python simulator reusing `SyntheticFrameSource`**, so the dashboard
  stays demoable with no car and no radio present. This preserves a capability the project's
  hardware-availability constraint depends on.
- **Update `.claude/CLAUDE.md` in this same phase.** It currently documents the Node server, its
  stdin/stdout JSON pipe, and the legacy loggers at length. Leaving that prose standing after the
  code is deleted is this project's #1 recorded anti-pattern (prose outliving what produced it).

### Claude's Discretion

- Exact SSE event framing (single `message` event vs named events for snapshot/update).
- HTTP route layout, port default, and CLI flag names for the serving mode.
- How the simulator is invoked (subcommand vs separate module).
- Test structure, beyond the requirement that the two-process UDP run keeps working.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/telemetry/ground/cli.py` (~18 KB) — the Phase 1 headless consumer. Already has arg parsing,
  logging setup, signal handlers, link construction (`_build_link`), DBC decode (`_decode_frame`),
  per-signal unit lookup (`_signal_unit`), `GroundConsumerCounters`, health emission, and
  `run_consumer_loop`. Phase 2 extends this, it does not replace it.
- `src/telemetry/ground/deframe.py` — `Deframer.feed()`, COBS+CRC deframing with a buffer-overflow
  memory cap (the cap now runs unconditionally, per code-review finding WR-03).
- `can-dashboard/dashboard.html` — working UI to port; channel tabs, search, visibility toggles,
  range bars, auto-reconnect.
- `can-dashboard/server.js` — reference for the state shape and snapshot-on-connect semantics; being
  deleted, but read it before deleting.
- `SyntheticFrameSource` — reused for the replacement simulator.

### Established Patterns
- Threads + `threading.Event` for shutdown; daemon for producers, non-daemon where a flush must
  complete. Shared state via explicit locks, single-writer discipline documented in module
  docstrings (`fanout.py` names its one deliberate exception).
- Typed, fail-closed config loading: `config/logger.json` + `src/telemetry/logger/config.py` raises
  rather than defaulting on malformed input. `measure/config.py` is the original of this pattern.
- Structured logging to stderr; stdout reserved for JSON records.
- Exact `==` pins in `requirements.txt`, each verified against the installed interpreter, never
  transcribed from prose.

### Integration Points
- `Link` Protocol (`src/telemetry/link/base.py`) — `send()` / `recv()` / `close()`. Already
  bidirectional by design; the ground station holds a `Link` but never calls `send()` in Phase 1.
  Keep it that way in Phase 2, but do not architect the ground station as receive-only — Phase 4
  needs that door open.
- `config/logger.json` — the 12-message `telemetry.allowlist`, by message name, resolved to
  `(frame_id, is_extended)`.
- `tests/test_end_to_end.py` — the two-process UDP car→pit run. Must keep passing.

</code_context>

<specifics>
## Specific Ideas

- The dashboard's existing per-message and per-signal visibility toggles should survive the port —
  they are the closest thing the UI already has to the subset control Phase 4 will make real.
- The state model's message-level grouping is deliberately retained as the binding surface for that
  future control, not just because `server.js` happened to be shaped that way.

</specifics>

<deferred>
## Deferred Ideas

- **Client-driven control of the transmitted subset — Phase 4.** The pit engineer selects which
  messages the car transmits, mid-session, from the dashboard. Raised during this discuss; deferred
  deliberately. The reasoning, recorded so Phase 4 inherits it rather than rediscovering it:
  - **The browser→ground-station hop is trivial** (an HTTP `POST` alongside the SSE stream). The
    real work is **ground station→car**: `ground/cli.py` never calls `link.send()` today, and the
    wire carries no command frame type. `Link` is already bidirectional, so the abstraction is
    ready; the wiring is not.
  - **Granularity is per-MESSAGE, not per-signal.** The dictionary is keyed on
    `(frame_id, is_extended)` and a CAN frame is atomic on the wire — requesting one signal from
    `M166_Current_Info` still transmits the whole message. Any UI must offer message-level toggles.
  - **The bandwidth case is real:** the current subset measures 81.94 kbit/s against the 120 kbit/s
    pass bar, so ~38 kbit/s of headroom is unusable because the subset freezes at config load. And
    `config/logger.json` cannot be edited while the car is on track — an uplink is the only way to
    change the subset without ending the session.
  - **Hard constraint for whoever builds it:** the car MUST enforce the pre-registered bandwidth cap
    and refuse or degrade a request that would exceed it. Phase 0's gate was pre-registered
    precisely so the budget could not drift; a runtime control must not make it advisory.
  - Phase 4 already owns "dictionary/allowlist version negotiation" per `01-CONTEXT.md`'s deferred
    block, and STATE.md records two Active requirements for the config-driven subset allowlist and
    its negotiation. This is the same machinery.
  - RFD900x is half-duplex, so uplink steals downlink air time. Control messages are tiny and rare,
    so the cost should be negligible — but Phase 9 measures that rather than assuming it.
- Live time-series plots and full link-health surfacing — Phase 6.
- Limit alarms — Phase 7.

</deferred>
