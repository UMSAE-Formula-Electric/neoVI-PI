# Phase 2: Python Ground Station and Dashboard Cutover - Research

**Researched:** 2026-08-02
**Domain:** Python stdlib `http.server` + Server-Sent Events; porting a WebSocket dashboard client to `EventSource`; safe deletion of superseded code
**Confidence:** HIGH

## Summary

Phase 2 grows `src/telemetry/ground/cli.py`'s existing receive-decode loop into a process that
*also* serves the ported `dashboard.html` over stdlib `http.server`, pushing state via
Server-Sent Events. Every claim about `http.server`/SSE mechanics below was verified directly
against the installed interpreter (`inspect.getsource`) and by running small probe scripts against
a real `ThreadingHTTPServer` on 127.0.0.1 — not transcribed from memory, per this project's #1
recorded failure mode. Two claims about `EventSource` browser behavior are cited from MDN/WHATWG
(no browser is available in this session to run them directly).

The single hardest technical fact this research surfaced, not obvious from the locked decisions
alone: **the decoded record's `timestamp_us` is not a wall-clock timestamp.** It comes from the
neoVI hardware's `TimeSystem` field multiplied by an explicitly-named
`TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED` constant (`src/telemetry/capture/hardware_source.py`).
It is not synchronized between the car and the pit laptop, and its very unit is unconfirmed. The
new UI-SPEC's staleness feature computes "now minus `ts`" in the browser using `Date.now()`, so
`ts` in `state[channel][msg_id].signals[name]` **must** be stamped with the ground station's own
local wall-clock receive time (`time.time()`), never `frame.timestamp_us`. Getting this wrong
would silently make every stale-signal indicator meaningless.

The second load-bearing gap: **the decoded record has no `channel` field.** GND-01's own module
docstring records this as deliberate — "the wire protocol carries no per-frame channel/bus data by
design, so channel disambiguation is left to consumers." But 02-CONTEXT.md's locked state shape is
`state[channel][msg_id]...`. `tests/test_end_to_end.py` already solves exactly this problem, in
already-tested production test code, by deriving `message_name -> channel` once from
`assign_rates(db, gate_config)` (which returns each message's `.bus`) joined against
`logger_config.channels` (which maps `.bus -> .name`). The ground CLI should build this same static
lookup once at startup and use it to fill in the state dict's channel key.

**Primary recommendation:** Extend `ground/cli.py`'s existing `on_record` callback (already the
single choke point through which every decoded signal passes) to do three things instead of one:
emit the existing JSON record (unchanged, GND output survives), update `state[channel][msg_id]`
under a `threading.Lock` with `ts=time.time()`, and push a small JSON payload onto every registered
per-client `queue.Queue`. Run `http.server.ThreadingHTTPServer.serve_forever()` on the main thread
(per the locked threading model) and call `httpd.shutdown()` from the link-receive/decode thread
once it observes `stop_event` — calling it from the serving thread itself deadlocks, confirmed
against the stdlib source below.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Server Architecture & Dependencies**

- Transport to the browser is Server-Sent Events over the stdlib `http.server`. Zero new runtime
  dependencies — `requirements.txt` stays at its current 8 exact pins. Data flows server→browser
  only, so WebSocket's bidirectionality is unused; `EventSource` also brings its own reconnect,
  making the client simpler than the WebSocket code it replaces.
- No package legitimacy gate is required for this phase. That blocking human checkpoint (the 01-01
  precedent) exists for new third-party packages; SSE adds none. If planning finds a reason to
  reverse the transport decision and pull in `aiohttp`, the gate re-applies and Phase 2 gains a
  blocking checkpoint — do not add a dependency silently.
- Threading model: a link-receive/decode thread plus the main-thread HTTP server, with shared state
  guarded by a lock. This mirrors the `FanOut`/`ArchiveRunner` discipline already proven in Phase 1.
  Do NOT convert the link layer to asyncio — `link/base.py` states the transport owns its own
  thread, "no asyncio," per `01-CONTEXT.md`.
- The headless JSON-record output survives. `--output` / stdout records stay alongside dashboard
  serving. `tests/test_end_to_end.py`'s two-process UDP run depends on it and is the only
  no-hardware proof of the full car→pit chain; removing it would delete that proof.

**Dashboard Reuse & Delivery**

- Port `can-dashboard/dashboard.html` rather than rewriting it. It is ~22 KB of working UI —
  channel tabs, search, per-message and per-signal visibility toggles, range bars, status
  indicator. Only the transport client changes (WebSocket → `EventSource`).
- It moves to `src/telemetry/ground/static/` and is served by the Python process, keeping
  everything under the telemetry package.
- Stays a single file with inline CSS and JS. Matches the existing artifact and the project's
  "no build pipeline" convention — do not introduce a bundler or split assets.
- Link health in the UI is minimal for this phase: connection state and last-frame age, reusing the
  existing status indicator. Distinguishing "steady" from "we stopped hearing from it" is
  explicitly Phase 6's goal — do not pull that scope forward.

**State Model & Snapshot**

- State shape is `state[channel][msg_id].signals[name] = {value, unit, ts}`. This mirrors the shape
  `can-dashboard/server.js` already produces, so the dashboard's rendering logic ports unchanged.
  It also keeps message-level grouping, which Phase 4's per-message subset toggles will need
  something to bind to.
- A newly connected browser receives a full state snapshot as the first event, then incremental
  updates (GND-05). This is what `server.js` does today; preserve the behaviour.
- State is bounded by the DBC. Only known `(frame_id, is_extended)` pairs ever enter state, so it
  caps at the DBC's message count and needs no eviction logic. This structurally fixes the
  unbounded-growth issue `.planning/codebase/CONCERNS.md` flagged in `server.js` — note it as fixed
  by construction rather than by a TTL.
- Staleness is carried as a per-signal `ts` and rendered by the UI (greyed when old). No
  server-side staleness computation or push; threshold alarms are Phase 7.

**Legacy Retirement**

- Delete the Node server and the whole `can-dashboard/` directory — `server.js`, `simulate.js`,
  `README.md` — after `dashboard.html` is ported. Closes GND-03.
- Delete the four legacy Python loggers: `src/neoVI_logger.py`, `src/new_logger.py`,
  `src/references.py`, `src/neoVI_sender.py`. This closes CAP-01, whose "duplicate implementation
  is removed from the repository" clause was deliberately deferred out of Phase 1 for rollback
  safety (`01-CONTEXT.md` § Deferred Ideas). Verify nothing imports them before deleting.
- Replace `simulate.js` with a Python simulator reusing `SyntheticFrameSource`, so the dashboard
  stays demoable with no car and no radio present. This preserves a capability the project's
  hardware-availability constraint depends on.
- Update `.claude/CLAUDE.md` in this same phase. It currently documents the Node server, its
  stdin/stdout JSON pipe, and the legacy loggers at length. Leaving that prose standing after the
  code is deleted is this project's #1 recorded anti-pattern (prose outliving what produced it).

### Claude's Discretion

- Exact SSE event framing (single `message` event vs named events for snapshot/update).
- HTTP route layout, port default, and CLI flag names for the serving mode.
- How the simulator is invoked (subcommand vs separate module).
- Test structure, beyond the requirement that the two-process UDP run keeps working.

### Deferred Ideas (OUT OF SCOPE)

- Client-driven control of the transmitted subset — Phase 4. Browser→ground-station is trivial (an
  HTTP `POST` alongside the SSE stream); the real work is ground-station→car, which `ground/cli.py`
  does not do today (it never calls `link.send()`), and the wire has no command frame type. Do not
  build any of this in Phase 2.
- Live time-series plots and full link-health surfacing — Phase 6.
- Limit alarms — Phase 7.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GND-02 | The ground station runs as a single process serving both the decode pipeline and the browser dashboard | `ThreadingHTTPServer.serve_forever()` on the main thread + the existing `run_consumer_loop` on a background thread, sharing `state` under one lock — see Architecture Patterns § Pattern 1 and Pattern 4 |
| GND-03 | The Node.js server is retired and removed from the repository | Deletion Blast Radius audit below confirms `can-dashboard/` is only referenced in docstrings/docs, never imported by runtime code — safe to delete outright |
| GND-04 | The ground station maintains current signal state and pushes updates to connected browsers | Pattern 2 (per-client queue fan-out) + Pattern 3 (composite `on_record`) |
| GND-05 | A newly connected browser receives a full state snapshot rather than waiting for each signal to next update | Pattern 1's `do_GET` writes the snapshot synchronously before entering its push loop, verified live in the SSE probe (§ Code Examples) |
| CAP-01 | A single logger implementation captures both CAN buses concurrently; the duplicate implementation is removed from the repository | Deletion Blast Radius audit confirms all four legacy loggers are referenced only in historical comments, never imported — safe to delete |

</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| CAN frame decode (DBC → named signals) | API/Backend | — | Already Phase 1's GND-01; unchanged in Phase 2 |
| Live signal state (`state[channel][msg_id]...`) | API/Backend | — | In-memory dict in the one Python process, guarded by a lock; no persistence, no DB tier exists in this project |
| SSE streaming to browsers | API/Backend | — | `http.server` handler threads own the long-lived response; browser only opens `EventSource` |
| Static dashboard file (`dashboard.html`) | API/Backend | Browser/Client | Backend serves the bytes (`GET /`); browser parses/renders — no CDN, no separate static host per locked decision |
| Dashboard rendering (tabs, toggles, search, staleness) | Browser/Client | — | All existing `dashboard.html` DOM/JS logic, ported not rewritten |
| Headless JSON record output (stdout / `--output-file`) | API/Backend | — | Unchanged sibling output path alongside the new serving mode |
| Channel resolution for state keys | API/Backend | — | Computed once at startup via `assign_rates`/`logger_config.channels` (see Pitfall 2), not per-frame, not in the browser |
| Demo/no-hardware simulator | API/Backend | — | Drives frames into the same decode pipeline `SyntheticFrameSource` already feeds on the car side; no browser-side simulation |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `http.server` (stdlib) | Python 3.12.10 (installed, verified via `python --version`) | `ThreadingHTTPServer`/`BaseHTTPRequestHandler` for serving both the static dashboard and the SSE stream | Locked decision: zero new runtime deps. `ThreadingHTTPServer = socketserver.ThreadingMixIn + HTTPServer`, `daemon_threads = True` by default (verified via `inspect.getsource`) — every connection gets its own thread that cannot outlive the process |
| `queue` (stdlib) | 3.12.10 | Per-client bounded `Queue` for the producer→SSE-handler fan-out | Already the pattern this project uses for cross-thread handoff (`FanOut.archive_queue`) |
| `threading` (stdlib) | 3.12.10 | Lock around shared `state`; `Event` for shutdown coordination | Matches every other Phase 1 module's threading discipline exactly |
| `EventSource` (browser built-in) | — | Client-side SSE consumer, replaces the `WebSocket` object in the ported `dashboard.html` | Native auto-reconnect; no library needed |

No supporting/alternatives tables — this phase introduces zero new packages by locked decision.
`requirements.txt` and `requirements-dev.txt` are unchanged; re-verify their pin count stays at 8
non-dev / 2 dev entries as a phase-exit check (`tests/test_requirements_pinned` already enforces
this — do not weaken it).

**Installation:** none. `pip install -r requirements.txt` is unaffected by this phase.

**Version verification:** `python --version` on the actual dev interpreter reports `Python
3.12.10` [VERIFIED: installed interpreter, this session]. `http.server`'s module file resolves to
`C:\Users\ethan\AppData\Local\Programs\Python\Python312\Lib\http\server.py` — confirmed the same
interpreter STATE.md already pins for this project. All API signatures cited below
(`ThreadingHTTPServer`, `BaseServer.shutdown`, `BaseServer.serve_forever`,
`BaseHTTPRequestHandler.send_response`/`end_headers`/`flush_headers`) were read directly via
`inspect.getsource` against this interpreter, not transcribed from any version of the online docs.

## Package Legitimacy Audit

Not applicable — this phase introduces zero new third-party packages (locked decision, explicitly
exempted from the gate). `requirements.txt`'s 8 exact pins are unchanged. If a future planning pass
reverses the SSE decision in favor of a library (e.g. `aiohttp`, `sse-starlette`), re-run the full
Package Legitimacy Gate protocol before that plan is written — do not add a dependency silently.

## Architecture Patterns

### System Architecture Diagram

```
   Car (radio link / loopback / UDP)
            |
            v
   +-------------------------------------------------------------+
   |  Ground station process (single Python interpreter)         |
   |                                                               |
   |  [link-receive/decode thread]                                |
   |    link.recv() -> Deframer.feed() -> _decode_and_emit()      |
   |         |                                                     |
   |         v  on_record(**fields)  (single choke point)          |
   |    +----+----------------------------------------------+     |
   |    | 1. _emit_record()  -> stdout JSON / --output-file  |     |
   |    | 2. state[channel][msg_id].signals[name] =          |     |
   |    |      {value, unit, ts=time.time()}  (under Lock)   |     |
   |    | 3. for each registered client queue: push update   |     |
   |    +----+----------------------------------------------+     |
   |         |                                                     |
   |         | (on stop_event) --------------------------+         |
   |         v                                            |        |
   |    calls httpd.shutdown()  <---- from THIS thread ---+        |
   |                                                               |
   |  [main thread]                                                |
   |    httpd = ThreadingHTTPServer(...)                            |
   |    httpd.serve_forever()   (blocks here)                       |
   |      |                                                         |
   |      +--> GET /            -> serve static dashboard.html      |
   |      +--> GET /events      -> per-request handler thread:      |
   |             register a queue.Queue in the shared client set    |
   |             write snapshot event immediately (GND-05)          |
   |             loop: block on queue.get(timeout) -> write SSE     |
   |                    frame; on write failure, deregister + exit  |
   +-------------------------------------------------------------+
            |
            v
   Browser: new EventSource('/events')
     -> onmessage: JSON.parse -> if snapshot: rebuildAll()
                                  if update:   handleUpdate()
     (unchanged dashboard.html rendering logic, only the transport
      object changed from WebSocket to EventSource)
```

### Recommended Project Structure

```
src/telemetry/ground/
├── cli.py              # existing GND-01 loop, extended: --serve flag, composite on_record
├── deframe.py           # unchanged
├── server.py            # NEW: ThreadingHTTPServer + SSE handler + static file route
├── state.py              # NEW: SignalState class — the locked dict + Lock + client-queue registry
├── simulate.py           # NEW: replaces can-dashboard/simulate.js, drives SyntheticFrameSource
└── static/
    └── dashboard.html    # ported from can-dashboard/dashboard.html, EventSource client
```

### Pattern 1: SSE handler — snapshot-first, then a per-client push loop

Verified live against `http.server.ThreadingHTTPServer` on 127.0.0.1, Python 3.12.10 (see § Code
Examples for the exact runnable probe and its captured output).

**What:** `do_GET` for the `/events` route registers a small bounded `queue.Queue` in a
lock-guarded set of "all connected clients," writes one `event: snapshot` frame containing the
full current `state` immediately, then loops on `queue.get(timeout=1.0)`, writing each item it
receives as an `event: update` SSE frame. On any write failure (`BrokenPipeError`,
`ConnectionAbortedError`, `OSError`) it deregisters its own queue and returns — `do_GET` returning
is enough; because `ThreadingHTTPServer.daemon_threads = True`, nothing else needs to reap the
thread.

**When to use:** Exactly this phase's GND-04/GND-05 requirement — every new connection must see
current state before the next real update arrives, and slow/dead clients must not affect anyone
else.

**Example (verified, this session — see Code Examples for the full script and its real output):**
```python
def do_GET(self):
    if self.path != "/events":
        self.send_response(404); self.end_headers(); return
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-cache")
    self.send_header("Connection", "keep-alive")
    self.end_headers()

    q: "queue.Queue[bytes]" = queue.Queue(maxsize=64)
    with clients_lock:
        clients.add(q)
    self.wfile.write(sse_frame("snapshot", state_snapshot()))
    try:
        while True:
            try:
                chunk = q.get(timeout=1.0)
            except queue.Empty:
                self.wfile.write(b": ping\n\n")  # heartbeat; detects dead sockets early
                continue
            self.wfile.write(chunk)
    except (BrokenPipeError, ConnectionAbortedError, OSError):
        pass
    finally:
        with clients_lock:
            clients.discard(q)
```
Do **not** set a `Content-Length` header on this response — the stream has no known end; omitting
it is what makes an indefinitely-long body legal under both HTTP/1.0 and HTTP/1.1.

### Pattern 2: Per-client bounded queue with drop-oldest, matching `FanOut`'s existing discipline

**What:** `queue.Queue` has no built-in drop-oldest eviction (unlike `collections.deque(maxlen=N)`,
which `FanOut.telemetry_queue` already uses) — `put_nowait` on a full `Queue` raises `queue.Full`
and drops the *new* item, which is backwards for a live view (a stalled browser should lose old
data, not the newest). Wrap the push:
```python
def push_dropping_oldest(q: queue.Queue, item: bytes, counters) -> None:
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        q.put_nowait(item)
        counters.sse_client_dropped_count += 1
```
**When to use:** Every push from the decode thread to a client's queue. This is the same
drop-oldest-and-count discipline `FanOut.submit` already applies to `telemetry_queue` — a slow
browser tab must never be able to apply backpressure to the decode thread, mirroring CAP-04's
structural guarantee for the telemetry path. [Derived from this codebase's own established
pattern in `src/telemetry/capture/fanout.py`, not from an external source — CITED: project
convention, not stdlib/spec.]

### Pattern 3: One composite `on_record` — reuse, do not duplicate, the existing choke point

`run_consumer_loop`'s `on_record: Callable[..., None]` parameter is already the single place every
decoded signal passes through (`src/telemetry/ground/cli.py:295-331`). `main()` currently wires it
to just `_emit_record`. Compose, don't replace:
```python
def on_record(**fields) -> None:
    _emit_record(sys.stdout, output_file, **fields)      # unchanged, GND output survives
    signal_state.update(**fields)                         # NEW: state[channel][msg_id].signals[name] = {...}
    sse_hub.broadcast("update", signal_state.last_delta)   # NEW: fan out to connected browsers
```
This requires zero changes to `run_consumer_loop`'s signature or `_decode_and_emit`'s call sites —
only `main()`'s local `on_record` closure grows.

### Pattern 4: Threading model and shutdown — `shutdown()` must be called from the OTHER thread

Per the locked decision, `serve_forever()` runs on the **main** thread, and the link-receive/decode
loop runs on a background thread. Verified directly from stdlib source
(`socketserver.BaseServer.shutdown`, this session):

> "Blocks until the loop has finished. This must be called while `serve_forever()` is running in
> another thread, or it will deadlock."

Because `serve_forever()` owns the main thread, `httpd.shutdown()` can **only** safely be called
from the link-receive/decode thread — not from the SIGINT/SIGTERM handler itself (Python delivers
signal handlers on the main thread, which is the same thread already blocked inside
`serve_forever()`; calling `shutdown()` there is the exact same-thread deadlock the docs warn
about, even though it looks like a different call frame). The existing
`_install_signal_handlers`/`stop_event` pattern in `ground/cli.py` already composes with this
correctly with no new mechanism: the signal handler sets `stop_event` (as today); the
link-receive/decode loop already re-checks `stop_event` every `recv_timeout_s` (T-01-29's existing
bound); add one line so that when it observes `stop_event`, it calls `httpd.shutdown()` once before
its own thread returns. Verified live: calling `shutdown()` from a second thread against a real
`ThreadingHTTPServer.serve_forever()` running on another thread returned in ~0.3s, one
`poll_interval` (`serve_forever`'s default `poll_interval=0.5`) — no hang, no exception (see § Code
Examples).

### Pattern 5: Deriving `channel` for the state dict from the DBC bus assignment

The decoded record has no `channel` field (GND-01's own docstring: "the wire protocol carries no
per-frame channel/bus data by design"). `tests/test_end_to_end.py` (lines ~792-804) already solves
this exact problem for its own two-bus coverage assertion — reuse it verbatim rather than
re-deriving:
```python
from telemetry.measure.config import GateConfig, load_gate_config
from telemetry.synth.rates import assign_rates

gate_config = load_gate_config(GateConfig.default_path())
name_to_bus = {r.name: r.bus for r in assign_rates(db, gate_config)}      # MessageRate.bus
bus_to_channel = {c.bus: c.name for c in logger_config.channels}          # ChannelConfig.bus -> .name
message_name_to_channel = {
    name: bus_to_channel[bus] for name, bus in name_to_bus.items() if bus in bus_to_channel
}
```
Compute this **once at startup**, not per-frame — it is a pure function of the DBC and
`config/logger.json`/`config/gate.json`, both already loaded by `main()`. `config/logger.json`'s
channels are `MAIN` (`bus1`) and `SENSOR` (`bus2`) [VERIFIED: `config/logger.json`, this session].

### Anti-Patterns to Avoid

- **Calling `httpd.shutdown()` from inside the SIGINT/SIGTERM signal handler.** Looks correct,
  deadlocks in practice — the handler runs on the same thread that's blocked in `serve_forever()`.
  See Pattern 4.
- **Using `frame.timestamp_us` as the state dict's `ts`.** It is hardware-relative and
  unit-unconfirmed (`TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED`), not wall-clock, and not
  synchronized between car and pit. See Pitfall 1.
- **Blocking `Queue.put()` (no timeout) from the decode thread into a client queue.** Re-introduces
  exactly the backpressure CAP-04 was built to structurally prevent, just one layer further
  downstream. Always use `put_nowait` + drop-oldest (Pattern 2).
- **Returning a non-200 or non-`text/event-stream` response on any `/events` error path.** Per
  MDN/WHATWG (cited below), `EventSource` does not retry after a "fail the connection" condition —
  unlike the current `dashboard.html`'s explicit `setTimeout(connect, 2000)` WebSocket retry loop,
  which retries unconditionally. The SSE route must always succeed once opened; if the server truly
  cannot serve it, closing the socket (not sending an error status) preserves auto-reconnect.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Reconnect-with-backoff on the browser | A manual `setTimeout(connect, 2000)` loop (what the WebSocket client does today) | `EventSource`'s built-in reconnect | This is the entire reason the locked decision picked SSE — "brings its own reconnect, making the client simpler than the WebSocket code it replaces" |
| Detecting a dead SSE client | Polling, `select()` on raw sockets, or a keepalive protocol | Attempt the next `wfile.write()`; a dead socket raises `BrokenPipeError`/`OSError` immediately | `BaseHTTPRequestHandler` already gives you this for free; verified live in this session's probe |
| Message-name → channel mapping for the state dict | A new hardcoded table, or inventing a wire-level channel field | `assign_rates(db, gate_config)` + `logger_config.channels`, exactly as `tests/test_end_to_end.py` already does | Already implemented, already tested, purely a function of config already loaded at startup |
| No-hardware demo data | A second bespoke synthetic-CAN generator (what `simulate.js` was) | `telemetry.synth.generator.SyntheticFrameSource`, the same one the car-side `--source synthetic` flag already drives | Locked decision explicitly names this; one generator, two callers |

**Key insight:** Every "new" piece of machinery this phase seems to need — reconnect, channel
resolution, demo data — already exists somewhere else in this codebase or in the browser platform
itself. The actual new code is thin glue: a state dict with a lock, a set of client queues, and a
`ThreadingHTTPServer` subclass.

## Runtime State Inventory

> This phase deletes files (`can-dashboard/`, four legacy loggers), which triggers this section.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — `can-dashboard/server.js`'s `state` object is entirely in-memory, process-local, never persisted to disk or any external store. Nothing to migrate. | None |
| Live service config | None — no external service (n8n, Datadog, Tailscale, etc.) is involved anywhere in this project. `server.js` only binds a local HTTP/WebSocket port at runtime; no registration outside the process. | None |
| OS-registered state | `.vscode/launch.json` has one debug configuration with `"program": "${file}"` (generic, not hardcoded to a legacy logger filename) and `"args": ["--channels", "DW CAN 01"]` — this arg shape matches the legacy loggers' `--channels` CLI convention, not `ground/cli.py`'s `--config` convention. Not a hard reference (no filename), but will silently misbehave if someone F5-debugs it against the new CLI. | Update `.vscode/launch.json`'s `args` to the new CLI's flags, or leave `program: ${file}` generic and drop the stale `args` |
| Secrets/env vars | None found — no `.env`, no CI secrets reference these files by name (`grep` for `neoVI_logger\|new_logger\|neoVI_sender\|references\.py\|can-dashboard` across the repo, verified this session). | None |
| Build artifacts | None — no `.egg-info`, no compiled binaries, no npm global install. `can-dashboard/node_modules` (if present from local `npm install`) is gitignored and disappears with the directory; not a tracked artifact. | None beyond deleting the directory |

**Deletion blast radius (grep-verified, this session):** 57 files match `neoVI_logger|new_logger|references\.py|neoVI_sender` and 13 files match `can-dashboard` project-wide. Every *code* hit
(`src/telemetry/**/*.py`, `tests/*.py`) is a **docstring or comment** citing the legacy file for
historical/design rationale (e.g. "mirrors `src/new_logger.py`'s `capture_thread`") — grepping
specifically for `import`/`from` statements referencing these names returns zero results. No test
imports the legacy loggers or `can-dashboard/*.js` [VERIFIED: `Grep` across the repo, this session].
Safe to delete both without touching any runtime import. The `.planning/` prose files that mention
them (ROADMAP.md, STATE.md, codebase/*.md, prior phase docs) are historical records, not code —
out of this phase's blast radius by construction (only `.claude/CLAUDE.md` is explicitly in scope
per the locked decision).

Root `README.md` is a two-line stub with no mention of the Node server or legacy loggers — no
update needed there.

## Common Pitfalls

### Pitfall 1: Using `frame.timestamp_us` as the staleness `ts`

**What goes wrong:** The UI-SPEC's staleness feature dims a signal value when `Date.now() - ts >
3000ms`. If `ts` is populated from the decoded record's `timestamp_us`, staleness becomes
meaningless or actively wrong — a signal could show as "stale" the instant it's decoded (if the
car's clock is behind wall-clock) or "always fresh" (if it's ahead), independent of whether data is
actually still arriving.
**Why it happens:** `timestamp_us` looks like a timestamp and is named like one, but per
`src/telemetry/capture/hardware_source.py`, it is `message.TimeSystem *
TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED` — hardware-relative, with an explicitly unconfirmed unit
conversion, and never synchronized between the car and the ground station's own clock.
**How to avoid:** Stamp `ts` with the ground station's own `time.time()` at the moment `on_record`
fires (i.e., "when the ground station last received a fresh value"), not with any field carried
over the wire.
**Warning signs:** Staleness dimming that doesn't correlate with the link actually dropping frames;
values that are dimmed on first arrival.

### Pitfall 2: Assuming a `channel` field exists on the decoded record

**What goes wrong:** `state[channel][msg_id]` cannot be built directly from `on_record`'s kwargs —
there is no `channel` key (only `topic`, `message_id`, `message_name`, `signal`, `value`, `unit`,
`timestamp_us`).
**Why it happens:** GND-01 deliberately left channel/bus disambiguation off the wire (documented in
`ground/cli.py`'s own module docstring) since Phase 1 had no consumer that needed it.
**How to avoid:** Build the `message_name -> channel` lookup once at startup via `assign_rates` +
`logger_config.channels` (Pattern 5) and look it up per record — it's a dict lookup, not a
per-frame computation.
**Warning signs:** A `KeyError` on `fields["channel"]`, or a state dict keyed by `None`.

### Pitfall 3: `httpd.shutdown()` called from the signal handler thread

**What goes wrong:** The process hangs on `Ctrl+C`/`SIGTERM` instead of exiting.
**Why it happens:** Python signal handlers execute on the main thread. If `serve_forever()` also
runs on the main thread (as the locked threading model specifies) and the handler calls
`shutdown()`, both calls are on the same thread — `shutdown()`'s `self.__is_shut_down.wait()` blocks
forever because the thing that would set that event (`serve_forever`'s own `finally` block) can
never run while `shutdown()` is blocking it.
**How to avoid:** Only ever call `httpd.shutdown()` from the link-receive/decode thread (see
Pattern 4). The signal handler should do nothing more than `stop_event.set()`, exactly as it does
today.
**Warning signs:** Process never exits on Ctrl+C during manual testing; a hung CI job running the
serving-mode CLI under `--duration-s`.

### Pitfall 4: `EventSource` giving up permanently after one error response

**What goes wrong:** If `/events` ever returns a non-200 status or wrong `Content-Type` (e.g. a
route typo, or an unhandled exception in `do_GET` before headers are sent), the browser's
`EventSource` sets `readyState = CLOSED` and **stops retrying entirely** — unlike the ported
client's previous WebSocket behavior, which retried unconditionally via `setTimeout`.
**Why it happens:** Per the WHATWG SSE spec / MDN (cited below): "When a user agent fails the
connection... it does not attempt to reconnect."
**How to avoid:** Make the `/events` route's happy path unconditional — always send `200
text/event-stream` before doing anything that could fail, and treat any later failure as a socket
close (write exception → `finally` cleanup), never as an HTTP error response after headers are
already committed. Test this specifically (a client left running across a server restart should
reconnect on its own — verify manually since JS `readyState` behavior needs a real browser, not
just the Python-side pytest suite).
**Warning signs:** Dashboard shows "Reconnecting…" that never resolves even after the ground
station process is confirmed running again; requires a manual page reload to recover.

### Pitfall 5: `Content-Length` on the SSE response

**What goes wrong:** If `do_GET` calls `self.send_header("Content-Length", ...)` (e.g. copy-pasted
from the static-file route) before starting the SSE loop, some HTTP clients will consider the body
complete after that many bytes and stop reading — breaking the indefinitely-long stream.
**Why it happens:** `Content-Length` is the right header for the static `dashboard.html` route
(finite, known size) and easy to reflexively add everywhere.
**How to avoid:** Never set `Content-Length` on `/events`; omit it entirely (verified this session —
the probe's SSE route sends no `Content-Length` and streams correctly across multiple writes on one
connection).

## Code Examples

Verified patterns — run live against `http.server.ThreadingHTTPServer` on Python 3.12.10, this
session (script and captured stdout below, not from documentation):

### SSE endpoint, multi-client fan-out, snapshot-then-update framing

```python
# Source: this session's own probe script, run against the installed
# interpreter (C:\Users\ethan\AppData\Local\Programs\Python\Python312\)
import http.server, json, queue, threading, time, urllib.request

clients_lock = threading.Lock()
clients = set()

def broadcast(event: str, data: dict):
    payload = f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")
    with clients_lock:
        for q in list(clients):
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass  # see Pattern 2 for the drop-oldest wrapper used in production

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *args): pass
    def do_GET(self):
        if self.path != "/events":
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = queue.Queue(maxsize=64)
        with clients_lock:
            clients.add(q)
        self.wfile.write(f"event: snapshot\ndata: {json.dumps({'hello': 'world'})}\n\n".encode())
        try:
            while True:
                try:
                    chunk = q.get(timeout=1.0)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    continue
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionAbortedError, OSError):
            pass
        finally:
            with clients_lock:
                clients.discard(q)

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
srv.daemon_threads = True
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
```

**Captured output from running this exact script, this session:**
```
status 200 text/event-stream
LINES:
'event: snapshot\n'
'data: {"hello": "world"}\n'
'\n'
'event: update\n'
'data: {"n": 1}\n'
'\n'
CLIENT2 LINES: ["'event: snapshot\\n'", '\'data: {"hello": "world"}\\n\'']
clients set size after close (may lag until next write): 2
shutdown took 0.297 s
```
This confirms, live: snapshot-first framing (GND-05), fan-out to two independent clients (GND-04),
and that a disconnected client's queue is not removed from `clients` until the next write attempt
against it fails (confirms Pitfall-style "detect on write, not on read" — expected and fine, since
the next broadcast's `put_nowait` on a stale queue is harmless; the entry is reaped on the *next*
write cycle inside that client's own handler thread, not by the broadcaster).

### Cross-thread `shutdown()`, verified non-deadlocking

```python
# Source: stdlib socketserver.BaseServer.shutdown() docstring, read via
# inspect.getsource against the installed interpreter, this session:
#   "Blocks until the loop has finished. This must be called while
#    serve_forever() is running in another thread, or it will deadlock."
t0 = time.monotonic()
srv.shutdown()       # called from a thread OTHER than the one running serve_forever()
srv.server_close()
print("shutdown took", time.monotonic() - t0, "s")   # -> 0.297 s, one poll_interval (default 0.5s)
```

### Bounded pytest read against a live streaming response (no browser, no new dependency)

```python
# Source: this session's own probe — confirms urllib.request.urlopen's
# `timeout=` parameter bounds every subsequent readline() on an open
# streaming response, not just the initial connect.
import urllib.request

resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/events", timeout=1.0)
line1 = resp.readline()   # returns immediately with buffered bytes
line2 = resp.readline()
line3 = resp.readline()   # blank line terminating the SSE frame
try:
    resp.readline()        # blocks up to 1.0s, then...
except TimeoutError:
    pass                    # ...raises real TimeoutError -- confirmed, this session
```
Captured, this session: three buffered lines returned instantly (`b'event: snapshot\n'`,
`b'data: {}\n'`, `b'\n'`); the fourth `readline()` call raised `TimeoutError` after exactly 1.0s.
This is the mechanism a GND-05 pytest assertion should use: open the stream with a short `timeout`,
read the expected snapshot lines, assert their content, then either close the response or let a
bounded number of further reads happen — never loop unconditionally on `readline()` with no
deadline.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `ws` npm package + `http` (Node) | stdlib `http.server` + SSE (Python) | This phase (GND-02/03) | Removes the only npm dependency in the repo; `can-dashboard/` and its `package.json`/`node_modules` go away entirely |
| Client: `new WebSocket(...)` with manual `setTimeout(connect, 2000)` reconnect | Client: `new EventSource(...)` with built-in reconnect | This phase | Less client code; but see Pitfall 4 — the failure semantics are not identical, they're stricter about what counts as retryable |
| `server.js`'s in-memory `state` object, unbounded key growth flagged in `.planning/codebase/CONCERNS.md` | Python `state` dict, provably bounded by the DBC's fixed `(frame_id, is_extended)` set | This phase | Structural fix, not a TTL/eviction policy — note this explicitly rather than re-solving a problem that no longer exists |

**Deprecated/outdated:**
- `can-dashboard/server.js`, `can-dashboard/simulate.js`, `can-dashboard/README.md`: deleted whole
  by this phase (GND-03).
- `src/neoVI_logger.py`, `src/new_logger.py`, `src/references.py`, `src/neoVI_sender.py`: deleted
  whole by this phase (CAP-01), confirmed safe by the Deletion Blast Radius audit above.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `state[channel][msg_id]`'s message-id key should be formatted as a hex string (e.g. `"0x1A2"`) to match `dashboard.html`'s existing rendering/search expectations (which display and search `msg.id` as text), rather than a bare Python int. Not verified against a real browser render this session. | Pattern 3 / Don't Hand-Roll table (implicit in the state shape) | If left as an int, `dashboard.html`'s `.msg-id` badge and search-by-id would show/match differently than the ported file's existing convention; low severity (cosmetic), easy to catch in manual UAT |
| A2 | `EventSource`'s no-retry-after-fatal-error behavior (Pitfall 4) is asserted from MDN/WHATWG text search, not exercised against a real browser in this session — no browser tooling was available. | Common Pitfalls § Pitfall 4 | If the actual behavior is more forgiving than described, Pitfall 4's "always return 200 unconditionally" guidance is still safe/harmless to follow, just possibly stricter than required — low risk either way |

## Open Questions

1. **Exact SSE event framing: named events vs a `type` field inside a generic `message` event.**
   - What we know: `dashboard.html`'s current `ws.onmessage` handler already dispatches on
     `msg.type` (`'snapshot'` vs `'update'`) inside a single message type; if Phase 2 keeps that
     shape (`event:` omitted, default `message` event, `data: {"type": "snapshot", ...}`), the
     client-side change shrinks to swapping `new WebSocket(...)` for `new EventSource(...)` and
     `ws.onmessage` for `es.onmessage` — the smallest possible diff, and the framing this research's
     probe demonstrated also works equally well with named events (`event: snapshot`).
   - What's unclear: Whether named events are worth the slightly larger diff (client needs
     `es.addEventListener('snapshot', ...)` / `es.addEventListener('update', ...)` instead of one
     `onmessage`) for the marginal benefit of the browser's native event-type filtering.
   - Recommendation: Use the generic `message` event with `type` inside the JSON payload —
     minimizes the diff against the existing, working `dashboard.html` logic, consistent with the
     "port, don't rewrite" locked decision. This is explicitly left to Claude's discretion in
     02-CONTEXT.md; record whichever choice the plan makes in its own PLAN.md rationale.

2. **Should the periodic SSE heartbeat/ping (`: ping\n\n`) be included in Phase 2, or deferred?**
   - What we know: it is not required for correctness (browsers detect a dead connection via TCP
     timeout eventually regardless), but it does let the *server* detect and reap a half-dead
     client sooner (a write attempt on an already-broken socket fails fast).
   - What's unclear: Given the client-side status indicator's minimal Phase 2 scope ("connection
     state and last-frame age," full health deferred to Phase 6), a slow-to-reap dead client thread
     has no user-visible cost in this phase — it just holds one extra daemon thread until the next
     real broadcast.
   - Recommendation: Include it — it's ~3 lines, matches the verified probe pattern exactly, and
     removes a whole class of "why didn't this client's queue clean up" debugging later.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python interpreter | Entire phase | Yes | 3.12.10 (native Windows CPython, per `.claude/gsd-core` memory and STATE.md) | — |
| `http.server`, `queue`, `threading` (stdlib) | SSE server, state, fan-out | Yes | Bundled with 3.12.10 | — |
| A browser | Manual UAT of the dashboard, and Pitfall 4's `EventSource` fatal-error behavior | Not verified this session (no browser tool invoked) | — | Manual UAT step in the plan; do not claim Pitfall 4's browser-side behavior as directly verified, only as CITED |
| Node.js / npm | Nothing — being retired | N/A after this phase | — | — |

**Missing dependencies with no fallback:** none — this phase has no external dependency beyond the
already-verified Python interpreter.

**Missing dependencies with fallback:** browser-based manual verification of `EventSource`
reconnect semantics; fallback is a documented manual UAT step, since no automated browser tooling
is available in this dev session.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 [VERIFIED: `requirements.txt` pin] |
| Config file | `pytest.ini` (`pythonpath = src`, `testpaths = tests`) |
| Quick run command | `python -m pytest -x -q --tb=short tests/test_ground_server.py` (new file this phase adds) |
| Full suite command | `python -m pytest -x -q --tb=short` (287 passing before this phase; the two-process UDP test in `tests/test_end_to_end.py` must still pass unchanged) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GND-02 | One process serves both decode + dashboard | integration | `pytest tests/test_ground_server.py::test_serving_mode_starts_http_and_decode -x` | ❌ Wave 0 |
| GND-03 | `can-dashboard/` no longer exists; nothing imports it | static/grep-based | `pytest tests/test_legacy_cutover.py::test_can_dashboard_dir_removed -x` (a plain `assert not (REPO_ROOT / "can-dashboard").exists()`) | ❌ Wave 0 |
| GND-04 | Connected client receives pushed updates | integration | `pytest tests/test_ground_server.py::test_client_receives_update_after_snapshot -x` (uses the bounded-`urlopen` pattern above) | ❌ Wave 0 |
| GND-05 | New connection's first event is a full snapshot | integration | `pytest tests/test_ground_server.py::test_first_event_is_snapshot -x` | ❌ Wave 0 |
| CAP-01 | Four legacy loggers removed, nothing imports them | static/grep-based | `pytest tests/test_legacy_cutover.py::test_legacy_loggers_removed_and_unreferenced -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest -x -q --tb=short tests/test_ground_server.py
  tests/test_legacy_cutover.py`
- **Per wave merge:** full suite (`python -m pytest -x -q --tb=short`) — must include
  `tests/test_end_to_end.py`'s two-process UDP run, unchanged and still green.
- **Phase gate:** full suite green before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `tests/test_ground_server.py` — new file; covers GND-02, GND-04, GND-05 using the bounded
  `urlopen(timeout=...)` pattern verified above (no browser, no new dependency).
- [ ] `tests/test_legacy_cutover.py` — new file; covers GND-03, CAP-01 via filesystem-existence and
  grep-style "no import references remain" assertions.
- [ ] No framework install needed — pytest is already pinned and installed.

## Security Domain

`security_enforcement: true`, `security_asvs_level: 1` in `.planning/config.json`.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | This is a pit-side, local-network-only dashboard with no login concept anywhere in the project's design (`Out of Scope` table has no auth line; "Multiple trackside receive sites" and remote access are explicitly out of scope) |
| V3 Session Management | No | No session/cookie state exists; each `EventSource` connection is stateless from the server's perspective beyond its registered queue |
| V4 Access Control | No | No user roles or permission boundaries exist in this UI |
| V5 Input Validation | Yes | The HTTP server must not trust `self.path` blindly — restrict routes to an explicit allowlist (`/`, `/events`, maybe `/static/...`) and reject everything else with 404, rather than resolving arbitrary paths against the filesystem (classic path-traversal risk for any hand-rolled static file server) |
| V6 Cryptography | No | No TLS, no secrets, no crypto in this phase — plain HTTP on the pit's local network, consistent with the project's existing radio-link security posture (none defined, out of scope for v1) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via `self.path` (e.g. `GET /../../../../etc/passwd`) if the static route ever does naive `os.path.join(static_dir, self.path)` | Tampering / Information Disclosure | Serve exactly one known file (`dashboard.html`) for `/` and reject every other path except the explicit `/events` route — do not implement a general-purpose static file server. `http.server.SimpleHTTPRequestHandler` (stdlib) does have path-traversal protections built in if it's ever reused instead, but a single-file allowlist is simpler and strictly safer for this phase's actual needs |
| Unbounded per-client queue growth becoming a DoS vector against server memory | Denial of Service | Already covered by Pattern 2's bounded `queue.Queue(maxsize=N)` + drop-oldest — a client that never reads cannot grow server memory unboundedly |
| A malformed/oversized request line the stdlib itself doesn't protect against | Denial of Service | `BaseHTTPRequestHandler.handle_one_request` already caps `rfile.readline(65537)` and responds `414 Request-URI Too Long` past that — verified via `inspect.getsource`, no action needed, just don't override this behavior |

## Sources

### Primary (HIGH confidence)

- `inspect.getsource(http.server.ThreadingHTTPServer)`, `inspect.getsource(socketserver.BaseServer.shutdown)`, `inspect.getsource(socketserver.BaseServer.serve_forever)`, `inspect.getsource(http.server.BaseHTTPRequestHandler.handle_one_request/send_response/end_headers/flush_headers)` — read directly against the installed Python 3.12.10 interpreter, this session.
- Live probe scripts run against a real `http.server.ThreadingHTTPServer` on `127.0.0.1`, this session (SSE framing, multi-client fan-out, cross-thread `shutdown()`, bounded `urlopen` reads) — full output captured above.
- `src/telemetry/ground/cli.py`, `src/telemetry/capture/fanout.py`, `src/telemetry/capture/hardware_source.py`, `src/telemetry/synth/rates.py`, `src/telemetry/logger/config.py`, `config/logger.json`, `tests/test_end_to_end.py` — read directly, this session.
- `Grep` across the whole repo for `neoVI_logger|new_logger|references\.py|neoVI_sender|can-dashboard` — this session, confirming the deletion blast radius.

### Secondary (MEDIUM confidence)

- [Using server-sent events - MDN](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events) — `data:`/`event:`/`id:`/`retry:` field spec.
- [EventSource: error event - MDN](https://developer.mozilla.org/en-US/docs/Web/API/EventSource/error_event) and [EventSource: readyState property - MDN](https://developer.mozilla.org/en-US/docs/Web/API/EventSource/readyState) — fatal-error / no-reconnect behavior (Pitfall 4, Assumption A2).
- [HTML Standard § 9.2 Server-sent events - WHATWG](https://html.spec.whatwg.org/multipage/server-sent-events.html) — normative "fail the connection" / no-retry semantics.

### Tertiary (LOW confidence)

- None used as the basis for any claim in this document — every claim is either directly verified against the installed interpreter/repo (this session) or cited from an official spec/doc page above.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages; every stdlib API cited was read from the actual installed source, not documentation prose.
- Architecture: HIGH — the SSE/threading/shutdown patterns were run live against a real server this session, not assumed from memory.
- Pitfalls: HIGH for Pitfalls 1/2/3/5 (each grounded in this project's own source code, read directly this session); MEDIUM for Pitfall 4 (grounded in official spec/MDN text, not exercised against a real browser this session).

**Research date:** 2026-08-02
**Valid until:** 2026-09-01 (30 days — stdlib behavior is stable across patch releases; re-verify if the project's Python version changes)
