---
phase: 02-python-ground-station-and-dashboard-cutover
reviewed: 2026-08-08T17:51:04Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - src/telemetry/ground/state.py
  - src/telemetry/ground/server.py
  - src/telemetry/ground/cli.py
  - src/telemetry/ground/simulate.py
  - src/telemetry/ground/static/dashboard.html
  - tests/test_ground_server.py
  - tests/test_ground_simulate.py
  - tests/test_end_to_end.py
  - tests/test_legacy_cutover.py
  - .vscode/launch.json
findings:
  critical: 1
  warning: 5
  info: 2
  total: 8
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-08-08T17:51:04Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

`state.py`, `server.py`, and `cli.py` are solid: the `SignalState`/`SseHub` locking discipline
matches what their docstrings claim, the drop-oldest SSE fan-out is correctly non-blocking, the
static route is a fixed allow-list with no path-traversal surface, and the cross-thread shutdown
sequencing (`shutdown()` called only from the decode thread, never from the signal handler) is
implemented exactly as documented. The test suite backing this phase (`test_ground_server.py`,
`test_ground_simulate.py`, `test_end_to_end.py`) is genuinely end-to-end — real sockets, real
`DashboardServer`, real COBS/CRC framing, no mocks of project code — and exercises the documented
edge cases (dead-client unregistration, slow-client drop-oldest, snapshot-then-update ordering,
shutdown-from-a-different-thread).

The defect surface that remains is concentrated in `static/dashboard.html`'s client-side
JavaScript, which has no automated interaction coverage (the test suite explicitly says so — its
dashboard tests are file-content regex assertions, not a browser). One finding there is a genuine
BLOCKER: two of the dashboard's advertised per-message interactions (collapse/expand a message
group, toggle a message's visibility) are completely non-functional due to a
`getElementById`/`CSS.escape` mismatch. The remaining findings are smaller robustness and
observability gaps in `cli.py`, `server.py`, and `simulate.py`.

## Critical Issues

### CR-01: Message-level collapse and message-level visibility toggle are non-functional (`getElementById` vs `CSS.escape` id mismatch)

**File:** `src/telemetry/ground/static/dashboard.html:547,551,581,679,695`
**Issue:**
The actual DOM id assigned to a message group is the *raw, unescaped* `groupKey` string
(`ch + '|' + id`, e.g. `"MAIN|0x195"`):

```js
// line 551
group.id = 'mg-' + groupKey;
```

But every lookup of that same element passes the key through `CSS.escape()` first:

```js
// lines 547, 581 (createMessageGroup / ensureMessageRow "already exists" guard)
if (document.getElementById('mg-' + CSS.escape(groupKey))) return;

// line 679 (toggleMsg)
const group = document.getElementById('mg-' + CSS.escape(groupKey));

// line 695 (toggleCollapse)
const group = document.getElementById('mg-' + CSS.escape(groupKey));
```

`CSS.escape` is designed to produce a string safe to splice into a *CSS selector* (it
backslash-escapes `|` and every other non `[a-zA-Z0-9_-]` character); `getElementById` takes a
*literal* id string and does no selector parsing. For `groupKey = "MAIN|0x195"`:

- the element's actual `id` attribute is `"mg-MAIN|0x195"`
- `CSS.escape(groupKey)` produces `"MAIN\|0x195"` (a literal backslash followed by `|`)
- `getElementById('mg-MAIN\\|0x195')` therefore **never matches**, confirmed directly against the
  spec algorithm (`cssEscape("MAIN|0x195") !== "MAIN|0x195"`).

Concretely:
- `toggleCollapse(groupKey)` (bound to every `.msg-header`'s `onclick`) hits `if (!group) return;`
  on line 696 every time — clicking a message row to collapse/expand it does nothing, ever.
- `toggleMsg(groupKey)` (bound to the message-level on/off switch) finds `group === null`, so
  `if (group) group.classList.toggle('hidden', cur);` (line 681) is silently skipped — the switch
  itself flips visually (its own lookup uses the *consistent* `escId()` scheme), but the message
  row it is supposed to hide/show never actually hides or shows.

The equivalent per-*signal* toggle (`toggleSig`) does not have this bug — it consistently uses
`escId()` for both the id assignment (line 603) and the lookup (line 688), so it works correctly.
Only the message-group id generation/lookup pair is inconsistent.

This is not caught by the existing test suite by design (`tests/test_ground_server.py`'s dashboard
tests are file-content regex assertions, not a real DOM/browser interaction test, per that file's
own module docstring), so it shipped silently.

**Fix:** Use the same scheme everywhere. Simplest fix — stop using `CSS.escape` for
`getElementById` lookups entirely (it is the wrong API for this call; `getElementById` needs no
escaping at all) and match the literal id that was actually assigned:

```js
// lines 547, 581
if (document.getElementById('mg-' + groupKey)) return;

// line 679 (toggleMsg)
const group = document.getElementById('mg-' + groupKey);

// line 695 (toggleCollapse)
const group = document.getElementById('mg-' + groupKey);
```

(Alternatively, standardize the message-group id on `escId(groupKey)` the same way
`.msg-toggle`/`.signals-table`/`.sig-*` already do, updating `group.id = 'mg-' + escId(groupKey);`
on line 551 and every lookup to match — either fix works, but the id-assignment and every lookup
of it must use the *same* transform.)

## Warnings

### WR-01: Signal min/max range tracking breaks whenever the true min or max is exactly `0`

**File:** `src/telemetry/ground/static/dashboard.html:475-476,572-573`
**Issue:** The per-signal seen-range tracking used by the "mini bar" indicator (`sig-bar`) uses a
truthy check instead of an existence check:

```js
// handleUpdate, lines 475-476
if (!signalMins[sigKey] || value < signalMins[sigKey]) signalMins[sigKey] = value;
if (!signalMaxs[sigKey] || value > signalMaxs[sigKey]) signalMaxs[sigKey] = value;

// createMessageGroup, lines 572-573
if (!signalMins[sigKey]) signalMins[sigKey] = sigData.value;
if (!signalMaxs[sigKey]) signalMaxs[sigKey] = sigData.value;
```

In JavaScript, `0` is falsy, so once a signal's tracked minimum reaches `0`,
`!signalMins[sigKey]` is `true` *unconditionally* on every subsequent update, regardless of the
new `value` — the "minimum" is overwritten with whatever the latest value happens to be instead of
staying at the true historical minimum. This is not a rare edge case: `Pedal_Press_Percent` (the
exact signal used throughout this phase's own test suite, `BUS1_SIGNAL` in
`tests/test_ground_server.py`) idles at `0` at rest, so this will trigger on essentially every real
session. The visible effect is `renderSignalValue`'s range computation
(`const range = max - min; const pct = range === 0 ? 50 : ...`) constantly collapsing toward
`range === 0`, so the mini bar mostly shows a flat 50% instead of the signal's actual position
within its observed range.

**Fix:** Use an explicit "have we seen this key before" check instead of a truthy check, e.g.:

```js
if (!(sigKey in signalMins) || value < signalMins[sigKey]) signalMins[sigKey] = value;
if (!(sigKey in signalMaxs) || value > signalMaxs[sigKey]) signalMaxs[sigKey] = value;
```

### WR-02: `fetch('/state')` fallback targets a route the server never implements

**File:** `src/telemetry/ground/static/dashboard.html:795` (route absence: `src/telemetry/ground/server.py:58-59,210-223`)
**Issue:** The dashboard's load-time fallback —

```js
// Fetch current state on load (fallback if WS snapshot missed)
fetch('/state').then(r => r.json()).then(s => {
  if (Object.keys(state).length === 0 && Object.keys(s).length > 0) {
    state = s;
    rebuildAll();
  }
}).catch(() => {});
```

— requests `GET /state`, but `server.py`'s `do_GET` only ever serves `EVENTS_ROUTE` (`/events`) or
`DASHBOARD_ROUTE` (`/`); every other path, including `/state`, returns `404`
(`src/telemetry/ground/server.py:216-223`). This request therefore 404s on every single page load,
its rejection is silently swallowed by the empty `.catch(() => {})`, and the "fallback if WS
snapshot missed" comment describes behavior that does not exist. This is currently masked because
the SSE stream's first event is always a snapshot by design
(`test_first_event_is_snapshot`/`test_client_receives_update_after_snapshot`), but the one case
this code was explicitly written to cover — an `EventSource` reconnect race that drops the initial
snapshot — has no working recovery path despite the code appearing to provide one.

**Fix:** Either implement a `GET /state` route on `DashboardServer` that returns
`snapshot_provider()` as JSON, or remove the dead fetch call and its stale comment so the file does
not claim a safety net it doesn't have.

### WR-03: SSE client-write-failure logging is log-once-ever, not log-once-per-cause, across the server's whole lifetime

**File:** `src/telemetry/ground/server.py:189-199,286-304`
**Issue:** `_write_failure_state = {"logged": False}` is created once per `DashboardServer`
instance (inside `make_handler_class`'s closure) and shared by *every* connected client's handler
thread for the process's entire lifetime:

```python
_write_failure_lock = threading.Lock()
_write_failure_state = {"logged": False}
...
with _write_failure_lock:
    if _write_failure_state["logged"]:
        hub.counters.write_failure_log_suppressed_count += 1
    else:
        _write_failure_state["logged"] = True
        logger.warning(...)
```

Every other rate-limited log site in this codebase (documented in `.claude/CLAUDE.md`'s Error
Handling conventions, and implemented in `telemetry.ground.cli._decode_and_emit`,
`telemetry.ground.deframe`, `telemetry.capture.fanout`) suppresses *per offending key*
(`frame_id`, `message_name`) so that a *different* recurring problem still gets its own first-seen
log line. Here there is no key at all: the very first SSE client disconnect of the session (which,
on a flaky pit-lane wifi link, is entirely routine) permanently silences the warning for every
later client, every later address, and every later cause, for the rest of the process's life —
only the counter (`client_write_failures` / `write_failure_log_suppressed_count`) still moves. An
engineer tailing stderr during a multi-hour test day would see exactly one warning ever, no matter
how many browser tabs reconnect and drop.

**Fix:** Key the suppression on something that actually identifies a distinct problem, e.g.
`self.client_address`, mirroring the `(frame_id, is_extended)`-keyed pattern used elsewhere:

```python
_write_failure_state = {"logged_addresses": set()}
...
with _write_failure_lock:
    if self.client_address in _write_failure_state["logged_addresses"]:
        hub.counters.write_failure_log_suppressed_count += 1
    else:
        _write_failure_state["logged_addresses"].add(self.client_address)
        logger.warning(...)
```

### WR-04: `DashboardServer` construction in `main()` is not guarded, unlike every other startup failure mode in the same function

**File:** `src/telemetry/ground/cli.py:501-511`
**Issue:** Every other failure this function can hit during startup is caught by its specific
exception type and turned into `logger.error(...); raise SystemExit(1)` (config load, DBC load,
gate config load, message index build — lines 429-474). `DashboardServer(...)` is not:

```python
dashboard_server = DashboardServer(
    host=args.http_host,
    port=args.http_port,
    hub=sse_hub,
    snapshot_provider=signal_state.snapshot,
)
```

`ThreadingHTTPServer.__init__` (called inside `DashboardServer.__init__`) calls `bind()`/`listen()`
and raises a plain `OSError` (e.g. `[Errno 98] Address already in use` — a routine operator mistake
when re-running against a port still held by a previous invocation) with no `try`/`except` around
it anywhere in `main()`. The process then exits via an unhandled traceback instead of the
consistent, logged `SystemExit(1)` path, and `link`, `output_file`, and the duration `watchdog`
(already opened/started earlier in this same function) are never closed or canceled on this path.

**Fix:** Wrap the construction the same way every other startup step in this function already is:

```python
try:
    dashboard_server = DashboardServer(
        host=args.http_host, port=args.http_port, hub=sse_hub,
        snapshot_provider=signal_state.snapshot,
    )
except OSError as exc:
    logger.error("failed to bind dashboard server to %s:%d: %s", args.http_host, args.http_port, exc)
    link.close()
    if output_file is not None:
        output_file.close()
    if watchdog is not None:
        watchdog.cancel()
    raise SystemExit(1) from exc
```

### WR-05: `telemetry.ground.simulate --loop` busy-spins with no wait if the synthetic stream is empty

**File:** `src/telemetry/ground/simulate.py:167-192,262-264`
**Issue:** `_parse_args` validates `--pacing` (`> 0`) but not `--duration-s`. If `--duration-s 0`
(or any value producing an empty `SyntheticFrameSource.frames()` stream, e.g. a duration too short
for any configured message's period) is combined with `--loop`:

```python
while not stop_event.is_set():
    wall_clock_start = now_fn()
    first_frame_timestamp_us: Optional[int] = None
    for raw_frame in frame_source.frames():   # yields nothing
        ...
    if not loop:
        break
```

the inner `for` loop's body — which contains the only `stop_event.wait(timeout=remaining)` call in
this function — never executes, so the outer `while` loop spins continuously with no sleep of any
kind between iterations, burning a full CPU core until `stop_event` is next observed set (it *is*
still checked every outer iteration, so it remains killable by signal, but does no useful work
while doing so).

**Fix:** Validate `--duration-s > 0` alongside the existing `--pacing` check in `_parse_args`, or
add an explicit `stop_event.wait(timeout=...)` fallback in `feed_frames` when a full pass yields
zero frames, so a misconfigured demo run degrades to "does nothing" rather than "burns a CPU core
doing nothing."

## Info

### IN-01: Message/channel/signal names are spliced into `innerHTML` unescaped

**File:** `src/telemetry/ground/static/dashboard.html:512,559,606,609`
**Issue:** `buildChannelTabs()`, `createMessageGroup()`, and `addSignalRow()` build markup via
template-literal `innerHTML` assignment using `ch`, `msgData.name`, `id`, `sig`, and `unit`
directly, with no HTML-escaping (decoded signal *values* are the one thing that correctly goes
through `el.textContent`, not `innerHTML`). Under the current trust model this is not remotely
exploitable — every one of those strings originates from the locally-loaded DBC schema
(`message.name`, `signal.name`, `signal.unit`, and `config/logger.json`'s channel names), never
from wire-carried signal *values* — but it is a latent injection primitive if that assumption ever
changes (e.g., a future revision sources channel names from a network-supplied config, or a signal
comment/description field is added to the rendered row). Worth a defensive escape given how cheap
it is (`textContent`-based row construction, or a small `escapeHtml()` helper) versus how easy it
would be to reintroduce this trust assumption incorrectly later.

**Fix:** Build these fragments via `textContent` assignment or a minimal escaping helper rather
than raw template-literal interpolation into `innerHTML`.

### IN-02: `--channel-colors` CSS custom property is declared but never referenced

**File:** `src/telemetry/ground/static/dashboard.html:24`
**Issue:** `--channel-colors: #4f8ef7, #a78bfa, #34c77b, #f0a028, #e8504a, #38bdf8;` is declared in
`:root` but no rule or script anywhere in the file reads it — channel tabs render with no
per-channel color differentiation despite this token existing. Either dead leftover from an
earlier design pass, or a feature (color-coding channel tabs) that was designed but never wired
up.

**Fix:** Either wire `.ch-tab` styling to cycle through this list (e.g. via
`nth-child`-indexed inline `style` when tabs are built in `buildChannelTabs()`), or remove the
unused declaration.

---

_Reviewed: 2026-08-08T17:51:04Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
