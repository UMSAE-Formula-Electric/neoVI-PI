---
phase: 02-python-ground-station-and-dashboard-cutover
plan: 02
subsystem: telemetry-ground-station
tags: [sse, eventsource, http.server, dashboard, staleness, static-route]

# Dependency graph
requires:
  - phase: 02-python-ground-station-and-dashboard-cutover (plan 01)
    provides: SseHub/DashboardServer (SSE at /events, snapshot-first
      framing, drop-oldest fan-out), telemetry.ground.cli --serve/
      --http-host/--http-port, SignalState with epoch-millisecond ts
provides:
  - src/telemetry/ground/static/dashboard.html — the ported can-dashboard
    UI, EventSource transport (no WebSocket, no manual reconnect timer),
    per-signal staleness dimming (STALE_THRESHOLD_MS=3000, 1s sweep), a
    no-results search state distinct from the waiting-for-data empty state,
    and empty-state copy naming the real `python -m telemetry.ground.cli
    --serve` command
  - src/telemetry/ground/server.py — a root-path (`/`) static route serving
    the packaged dashboard, resolved from the module's own directory
    (never from the request), read per-request (not cached), with a real
    Content-Length; unlisted and traversal-shaped paths 404
  - tests/test_ground_server.py — 8 new tests (root serving, content-length,
    traversal-404, EventSource-only transport, no unresolved placeholder,
    empty-state command text, stale-vs-hidden CSS distinction, single
    threshold constant)
  - tests/test_end_to_end.py — test_serving_mode_is_one_process_no_pipe:
    one ground-station subprocess (--serve) proven, at the process level, to
    simultaneously emit decoded JSON on stdout, push the same signal over
    /events, and serve the dashboard at / — the discriminating proof of
    GND-02's "single process" claim
  - GND-02, GND-04, GND-05 marked Complete in REQUIREMENTS.md
affects: [02-03-simulator, 02-04-legacy-retirement]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Static route served from a fixed, module-relative path
      (DASHBOARD_HTML_PATH = Path(__file__).parent / 'static' /
      'dashboard.html'), never from self.path -- the request path only ever
      selects among the two allow-listed routes, never contributes to file
      resolution (T-02-01, ASVS V5)"
    - "Low-frequency setInterval staleness sweep, deliberately separate from
      the existing requestAnimationFrame render cadence -- a message going
      quiet produces no updates and therefore no animation-frame trigger,
      so the sweep is the only path that can ever dim a frozen value
      (deviation from 02-PATTERNS.md's cadence suggestion, pre-authorized
      by 02-02-PLAN.md Task 2's own action text)"

key-files:
  created:
    - src/telemetry/ground/static/dashboard.html
  modified:
    - src/telemetry/ground/server.py
    - tests/test_ground_server.py
    - tests/test_end_to_end.py
    - .planning/REQUIREMENTS.md

key-decisions:
  - "Dashboard file read per HTTP request, not cached at process startup --
    an engineer can edit dashboard.html and reload the browser without
    restarting the ground station"
  - "can-dashboard/dashboard.html is left in place (not deleted) after
    copying -- 02-04 retires the source directory once the port has run on
    the car; a failed port always has a working fallback until then"
  - "Staleness threshold (3000ms) declared as a single named JS constant
    (STALE_THRESHOLD_MS), asserted by test_staleness_threshold_is_declared_
    once to never drift into a second copy"
  - "Stale-value color reuses the existing --dim token (never introduces a
    new color, never --amber/--red, which are reserved for Phase 6
    link-level health) and is applied/removed before the existing .flash
    animation so the two never visually collide"

patterns-established:
  - "Pattern: sweep interval decoupled from render-triggered cadence for any
    future 'this stopped happening' UI signal -- a rAF/update-triggered
    render alone can never detect an absence of updates"

requirements-completed: [GND-02, GND-04, GND-05]

coverage:
  - id: D1
    description: "Opening the ground station's HTTP root in a browser
      serves the dashboard, which connects over SSE and renders live values
      with no second process and no stdout pipe (GND-02, D-06)"
    requirement: "GND-02"
    verification:
      - kind: integration
        ref: "tests/test_ground_server.py#test_root_serves_the_dashboard"
        status: pass
      - kind: integration
        ref: "tests/test_end_to_end.py#test_serving_mode_is_one_process_no_pipe"
        status: pass
    human_judgment: false
  - id: D2
    description: "A newly connected browser immediately shows every
      signal's current value via the snapshot-first SSE event (GND-05);
      subsequent decoded signals push to already-connected clients (GND-04)"
    requirement: "GND-04, GND-05"
    verification:
      - kind: integration
        ref: "tests/test_end_to_end.py#test_serving_mode_is_one_process_no_pipe"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every ported UI affordance -- channel tabs, search,
      per-message and per-signal visibility toggles, range bars, status
      indicator -- still works after the transport swap (D-05)"
    verification: []
    human_judgment: true
    rationale: "These functions (buildChannelTabs, toggleMsg, toggleSig,
      applySearch, the mini range bar) were ported byte-identical except
      for the explicitly-scoped transport block, empty-state copy, and
      staleness additions -- confirmed by diff review, not executed in a
      browser DOM this session (no browser automation tool was available;
      recorded in .planning/WINDOWS.md id=1)."
  - id: D4
    description: "A signal whose value has stopped refreshing for longer
      than 3000ms renders dimmed (distinct from a manually hidden row) and
      reverts the instant a fresh value arrives, including when the whole
      link goes quiet (D-12)"
    verification:
      - kind: unit
        ref: "tests/test_ground_server.py#test_stale_treatment_is_distinct_from_hidden"
        status: pass
      - kind: unit
        ref: "tests/test_ground_server.py#test_staleness_threshold_is_declared_once"
        status: pass
    human_judgment: true
    rationale: "File-content assertions prove the CSS rule and the single
      threshold constant exist and are structurally correct, but cannot
      prove a value actually dims in a rendered browser after 3s or that
      the sweep interval fires against a genuinely quiet link -- this is
      exactly the honest limit 02-02-PLAN.md's Task 2 names. No browser
      automation tool was available this session; recorded as an unrun
      human-check in .planning/WINDOWS.md id=1."
  - id: D5
    description: "The empty-state instructions name the real Python serving
      command with no unresolved placeholder token; filtering to zero
      matches while data IS flowing shows a distinct no-results message,
      never the waiting-for-data copy"
    verification:
      - kind: unit
        ref: "tests/test_ground_server.py#test_dashboard_has_no_unresolved_copy_placeholder"
        status: pass
      - kind: unit
        ref: "tests/test_ground_server.py#test_empty_state_names_the_python_serving_command"
        status: pass
    human_judgment: true
    rationale: "The empty-state copy itself is fully automated-verified. The
      no-results *interaction* (typing a nonsense string while data is
      flowing) is a DOM/JS-execution behavior no test in this suite drives
      without a browser; deferred alongside D3/D4 per .planning/WINDOWS.md
      id=1."

# Metrics
duration: 25min
completed: 2026-08-08
status: complete
---

# Phase 2 Plan 02: Ground Station Dashboard Port Summary

**The ported `can-dashboard/dashboard.html` is now served by the same Python process over Server-Sent Events, with per-signal staleness dimming and honest empty/no-results copy — GND-02, GND-04, and GND-05 closed.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-08-08T16:26:00Z (approx)
- **Completed:** 2026-08-08T16:50:00Z
- **Tasks:** 3
- **Files modified:** 5 (`server.py`, `static/dashboard.html` created, `test_ground_server.py`, `test_end_to_end.py`, `REQUIREMENTS.md`)

## Accomplishments

- `src/telemetry/ground/static/dashboard.html`: `can-dashboard/dashboard.html` ported verbatim except for three explicitly-scoped regions — the ~25-line transport block (WebSocket → `EventSource`, manual reconnect timer deleted entirely), the empty-state copy (real `python -m telemetry.ground.cli --serve` command, no `{SERVING_FLAG}` placeholder), and two new-this-phase additions (staleness dimming, no-results search state)
- `telemetry.ground.server.DashboardServer` grows a root-path (`/`) static route: the served file is always `Path(__file__).parent / "static" / "dashboard.html"`, never anything derived from the request, so there is no path-traversal surface (T-02-01); read per request (not cached) so an engineer can edit-and-reload without restarting the process; unlisted and traversal-shaped paths 404
- Per-signal staleness (D-12): `STALE_THRESHOLD_MS = 3000` declared once; `.sig-value.stale` reuses `--dim` (never `--amber`/`--red`, reserved for Phase 6 link-health), placed so a fresh value's `.flash` animation always wins if both classes briefly coexist, and is explicitly distinct from the `.hidden` row's `opacity: 0.35` treatment. A dedicated `setInterval(sweepStaleness, 1000)` re-evaluates every currently-rendered signal regardless of whether new updates are arriving — a deliberate, plan-directed deviation from 02-PATTERNS.md's animation-frame-cadence suggestion (see Deviations below)
- No-results search state: filtering to zero matches while data is flowing now shows `No signals match "<query>"` with a clear-search button, distinct from the `Waiting for CAN data…` empty state, which stays reserved for the genuinely-empty case
- `tests/test_end_to_end.py::test_serving_mode_is_one_process_no_pipe`: spawns the ground station as ONE subprocess with `--serve`, discovers both its UDP and HTTP addresses from its own stderr (never hardcoded), sends it a real COBS-framed UDP batch, and asserts the same decoded signal appears on stdout, over `/events`, and via a `/` GET — the only test in the suite that distinguishes "one process serving both" from "the pipeline and the server happen to both exist" (GND-02's actual claim)
- Full suite: 299 → 308 passing (8 new tests in `test_ground_server.py`, 1 new test in `test_end_to_end.py`)
- GND-02, GND-04, GND-05 marked Complete in `REQUIREMENTS.md` (checklist and traceability table); GND-03 and CAP-01 confirmed untouched (re-grepped every phase-2 plan's `requirements:` frontmatter first — 02-03 claims GND-03, 02-04 claims GND-03 and CAP-01, no later plan claims 02-02's three)

## Task Commits

1. **Task 1: Serve the ported dashboard from the Python process** — `73cb2e2` (feat)
2. **Task 2: Staleness dimming and honest empty/no-results copy** — `e17e5e0` (feat)
3. **Task 3: Prove it is one process, then close GND-02/04/05** — `a5aa005` (test)

**Plan metadata:** (this commit)

## Files Created/Modified

- `src/telemetry/ground/static/dashboard.html` — ported dashboard: EventSource transport, staleness dimming, no-results state, real serving-command copy
- `src/telemetry/ground/server.py` — root-path static route (`DASHBOARD_ROUTE`, `DASHBOARD_HTML_PATH`, `_serve_dashboard`)
- `tests/test_ground_server.py` — 8 new tests across Task 1 (route/transport) and Task 2 (copy/staleness) behaviors
- `tests/test_end_to_end.py` — `test_serving_mode_is_one_process_no_pipe` plus its own spawn/multi-pattern-drain/SSE-read helpers
- `.planning/REQUIREMENTS.md` — GND-02, GND-04, GND-05 → Complete

## Decisions Made

- Dashboard file read per HTTP request rather than cached at startup, trading a few filesystem reads per page load for edit-and-reload without a process restart
- `can-dashboard/dashboard.html` left in place after copying (not deleted) — 02-04 retires the whole source directory once the port has proven itself; a failed port always has a working fallback until then
- Staleness threshold declared once as `STALE_THRESHOLD_MS` (pinned by its own test) rather than inlined at each use site
- Stale-value color reuses `--dim` deliberately, never introduces a new token and never touches `--amber`/`--red` (Phase 6 link-health scope)

## Deviations from Plan

### Plan-directed deviation (pre-authorized, not a Rule 1-4 auto-fix)

**Staleness sweep cadence.** 02-PATTERNS.md's pattern map suggested recomputing staleness only at the existing `requestAnimationFrame` cadence inside `scheduleRender`/`flushUpdates`. 02-02-PLAN.md's own Task 2 action text overrides this explicitly and instructs recording the reason: that cadence only fires when updates are arriving, and only re-renders the specific keys those updates touch. The exact situation staleness exists to reveal — a single message going quiet, or the whole link dropping — produces no updates at all, so nothing would ever trigger a re-render and nothing would ever dim under the rAF-only approach. Implemented instead as a dedicated `setInterval(sweepStaleness, 1000)` that re-evaluates every currently-rendered signal in the active channel once a second, independent of whether any update arrived. This was specified by the plan itself, not discovered mid-execution — recorded here per the plan's explicit instruction, not as an unplanned Rule 1-4 fix.

No other deviations. Every other line of the ported dashboard, the server route, and the test files follows the plan's action text as written.

**Total deviations:** 1 plan-directed (staleness sweep cadence, pre-authorized). Zero Rule 1-4 auto-fixes were needed — the 02-01 tracer's interfaces (epoch-millisecond `ts`, snapshot/update SSE framing) were already exactly what this plan's transport port and staleness logic needed.

## Issues Encountered

- **Task 2's human-check was not run this session.** The plan's Task 2 `<verify>` names a browser-based human check (empty-state copy live, data flowing and un-dimming, staleness dimming within ~3s, reconnect-across-process-restart with the tab left open, no-results search interaction) as an honest limit its own file-content tests cannot prove. No browser automation tool was available in this execution environment to drive that check. Everything automatable was verified instead: the dashboard's served bytes and copy (file-content tests), and the full server → SSE → client data path end-to-end at the network level (`test_serving_mode_is_one_process_no_pipe`, which proves live data flow, snapshot-then-update ordering, and root-path serving all from one process). The unrun browser check is recorded in `.planning/WINDOWS.md` (id=1, kind `unrun-verify`) rather than silently skipped, and reflected as `human_judgment: true` on the corresponding coverage entries (D3, D4, D5) above.
- `ThreadingHTTPServer` continues to print a `ConnectionAbortedError`/`ConnectionResetError` traceback to stderr on Windows when a test closes its `urllib` connection mid-stream before the server notices — this is `socketserver`'s own default `handle_error` behavior on an aborted connection (not a test failure; all 308 tests pass), first noted in 02-01-SUMMARY.md. Deployment target is Linux/CM4, where this is a non-issue.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The dashboard now runs entirely from the Python process; 02-03 can add a synthetic-frame simulator against this same `--serve` path with no further server/dashboard changes needed
- 02-04 can retire `can-dashboard/` (still present, unreferenced by anything except itself) and the four legacy logger files once the port has been confirmed on hardware
- One open item in `.planning/WINDOWS.md` (id=1): Task 2's browser-based human-check should be run with real browser tooling before `/gsd-ship` — recommend running it manually (or via `/gsd-verify-work 2`) once a browser is available, covering the six points 02-02-PLAN.md's Task 2 `<verify>` names
- No blockers. `requirements.txt` is unchanged (D-01); no new dependency introduced

## Self-Check: PASSED

All created/modified files exist on disk (`src/telemetry/ground/static/dashboard.html`, `src/telemetry/ground/server.py`, `tests/test_ground_server.py`, `tests/test_end_to_end.py`, `.planning/REQUIREMENTS.md`, this SUMMARY.md); all three cited task commits (`73cb2e2`, `e17e5e0`, `a5aa005`) are present in `git log --oneline --all`.

---
*Phase: 02-python-ground-station-and-dashboard-cutover*
*Completed: 2026-08-08*
