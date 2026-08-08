---
phase: 02-python-ground-station-and-dashboard-cutover
verified: 2026-08-08T19:00:00Z
status: passed
score: 9/9 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 2: Python Ground Station and Dashboard Cutover Verification Report

**Phase Goal:** The pit engineer opens a browser and watches the car's live signals arriving over
the new link, served by one Python process
**Verified:** 2026-08-08T19:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A single Python process on the pit laptop receives the link, decodes signals, holds current state, and serves the browser dashboard — no second process, no same-machine pipe | ✓ VERIFIED | `tests/test_end_to_end.py::test_serving_mode_is_one_process_no_pipe` (passing); live browser session this phase confirmed one `--serve` subprocess simultaneously fed `/events` and `/` while stdout still carried JSON records |
| 2 | The browser shows live current values for both buses fed by the telemetry link, not by a local stdout pipe | ✓ VERIFIED | Live Chrome session this phase: stats bar read `Channels 2 / Messages 12 / Signals 43` at ~4000 msg/s fed by a real simulator over real UDP; both channel tabs populated (MAIN 11 messages, SENSOR 1 = `Battery_Volt_1_Overall_Param_Std` 0x101) |
| 3 | A browser opened mid-session immediately shows every signal's current value instead of waiting for each signal to next update | ✓ VERIFIED | `tests/test_ground_server.py::test_first_event_is_snapshot` + `test_client_receives_update_after_snapshot` (passing); live session: EventSource reconnect after a server restart returned straight to full `.live` state with `performance.getEntriesByType('navigation').length === 1` (no page reload) |
| 4 | The Node.js server is removed from the repository and nothing in the system depends on it | ✓ VERIFIED | Filesystem check this session: `can-dashboard/` does not exist. `tests/test_legacy_cutover.py::test_node_dashboard_directory_removed` and `::test_nothing_imports_the_removed_modules` pass (ast-based import scan, zero real imports found) |

### Observable Truths (Requirement CAP-01, mapped to this phase's deletion half)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 5 | A single logger implementation captures both CAN buses concurrently; the duplicate implementation is removed from the repository | ✓ VERIFIED | Filesystem check: `src/neoVI_logger.py`, `src/new_logger.py`, `src/references.py`, `src/neoVI_sender.py` do not exist. `tests/test_legacy_cutover.py::test_legacy_logger_modules_removed` passes. Capture-both-buses half was already Complete from Phase 1 (unchanged here) |

### Additional Plan-Level Must-Haves (02-01 through 02-04 frontmatter)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 6 | A slow/dead SSE client cannot block the decode thread or grow server memory without bound (drop-oldest, counted, unregistered) | ✓ VERIFIED | `test_slow_client_loses_oldest_not_newest`, `test_broadcast_never_blocks_on_a_full_client`, `test_dead_client_is_unregistered` all pass — these are the discriminating tests, not presence-only |
| 7 | `ts` is the ground station's own wall clock, never the frame's hardware timestamp; SIGINT/SIGTERM shutdown works from the decode thread only | ✓ VERIFIED | `test_update_ts_is_wall_clock_not_frame_timestamp`, `test_shutdown_from_decode_thread_returns_promptly` both pass |
| 8 | Every ported UI affordance — channel tabs, search, per-message/per-signal toggles, status indicator — still works; staleness dims and reverts; no-results copy is distinct from waiting-for-data copy | ✓ VERIFIED | Live session confirmed: staleness (all 36 `.sig-value` gained `.stale` after transmission stopped, cleared on resume), no-results search state, message-group collapse/toggle (CR-01 fix: `getElementById('mg-MAIN\|0xA0')` now resolves) — see Anti-Patterns/Code Review section below for the bug this replaced |
| 9 | A Python simulator (`telemetry.ground.simulate`) drives the dashboard with real DBC-shaped traffic over the real wire path, with no re-implementation of value generation, paced in real time, with no car/hardware/radio present | ✓ VERIFIED | `test_simulator_output_deframes_to_allowlisted_dbc_messages` (zero framing failures), `test_pacing_multiplier_bounds_a_short_run`, live two-process UDP demo (`batches_received=batches_ok=98/98`, `records_decoded=5418`, `records_decode_failed=0`) |

**Score:** 9/9 must-haves verified (0 present-but-behavior-unverified)

**Minor item disclosed, not scored as a gap:** WR-01's mini-range-bar fix (`signalMins`/`signalMaxs` truthy-check → key-existence-check, so a signal idling at exactly `0` no longer collapses its range to a flat 50%) is backed only by a file-content regression test — REVIEW-FIX.md's own words: "cannot prove the mini-bar renders a specific width in a browser." The live session this phase did not explicitly screenshot/inspect the mini-bar's rendered width. Unlike the CR-01 message-toggle bug (a functional break, explicitly re-verified live) or the staleness/no-results items (explicitly re-verified live), this one is a cosmetic sub-affordance not named in any ROADMAP success criterion or v1 requirement, the fix is a one-line JS-semantics correction whose correctness is plain from reading it (the same "reviewable by reading it" standard this project's own 02-01 plan applies to the `SignalState` lock), and it is regression-tested against the exact bug pattern found. Judgment call: treated as adequately verified by code review + regression test, not elevated to a phase-blocking human-verification item. Disclosed here rather than silently dropped.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/telemetry/ground/state.py` | `SignalState`, `build_message_index`, counters, collision guard | ✓ VERIFIED | Exists, substantive, wired into `cli.py`'s `on_record` closure |
| `src/telemetry/ground/server.py` | `SseHub`, `DashboardServer`, three-route allowlist (`/events`, `/`, `/state`) | ✓ VERIFIED | Exists, substantive; route allowlist confirmed via grep (`EVENTS_ROUTE`, `DASHBOARD_ROUTE`, `STATE_ROUTE`) |
| `src/telemetry/ground/static/dashboard.html` | Ported UI, EventSource transport, staleness dimming, no-results state | ✓ VERIFIED | Exists; grep confirms `STALE_THRESHOLD_MS=3000`, `sweepStaleness`/`setInterval`, no WebSocket constructor |
| `src/telemetry/ground/simulate.py` | Car stand-in reusing `SyntheticFrameSource`/`Encoder`/`TelemetryPipeline`/`Link` | ✓ VERIFIED | Exists, tested, demoed live over real UDP |
| `tests/test_legacy_cutover.py` | Durable regression gate (4 assertions, ast-based) | ✓ VERIFIED | Exists, all 4 assertions pass; confirmed originally RED (3/4 failing) before deletion per 02-04-SUMMARY.md |
| `can-dashboard/` (must NOT exist) | Deleted directory | ✓ VERIFIED | `ls can-dashboard` → "No such file or directory" |
| `src/neoVI_logger.py`, `src/new_logger.py`, `src/references.py`, `src/neoVI_sender.py` (must NOT exist) | Deleted files | ✓ VERIFIED | All four confirmed absent from disk |
| `.claude/CLAUDE.md` | Describes the system that exists, no Node/npm/WebSocket references | ✓ VERIFIED | Read directly this session — Technology Stack/Conventions/Architecture sections fully describe the `telemetry` package with real paths and real pins; `grep -iE "node\.?js|npm|websocket|can-dashboard"` returns zero hits |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `cli.py on_record` closure | `SignalState.update()` → `SseHub.broadcast()` | direct call chain | ✓ WIRED | Confirmed by `test_client_receives_update_after_snapshot` and live two-process demo |
| `GET /` | `static/dashboard.html` | `DASHBOARD_HTML_PATH = Path(__file__).parent / "static" / "dashboard.html"`, never `self.path` | ✓ WIRED | `test_root_serves_the_dashboard`, `test_traversal_style_path_is_404_not_a_file_read` pass |
| `dashboard.html EventSource('/events')` | `onmessage` → `rebuildAll()`/`handleUpdate()` | transport swap only | ✓ WIRED | `test_ported_dashboard_uses_the_event_stream_transport` (no WebSocket constructor found); live session confirmed rendering |
| `simulate.py feed_frames` | `Encoder → TelemetryPipeline → COBS+CRC → UdpLink.send()` | real wire path, no re-implementation | ✓ WIRED | `test_simulator_output_deframes_to_allowlisted_dbc_messages` — zero framing failures through the real `Deframer` |
| `tests/test_legacy_cutover.py` | deleted paths + `.claude/CLAUDE.md` | ast-based import scan + string scan | ✓ WIRED | All 4 assertions pass in current tree |

### Behavioral Spot-Checks / Full Test Suite

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite | `python -m pytest -q` | `323 passed` (run directly by this verifier) | ✓ PASS |
| Legacy cutover gate | `pytest tests/test_legacy_cutover.py` | `4 passed` | ✓ PASS |
| Ground station core | `pytest tests/test_ground_server.py tests/test_ground_simulate.py tests/test_ground_cli.py tests/test_end_to_end.py` | `44 passed` | ✓ PASS |
| Shutdown-from-decode-thread (state-transition truth) | `pytest tests/test_ground_server.py::test_shutdown_from_decode_thread_returns_promptly` | `1 passed` | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| GND-02 | 02-01, 02-02 | Ground station runs as a single process serving both decode pipeline and browser dashboard | ✓ SATISFIED | `test_serving_mode_is_one_process_no_pipe`; live session; REQUIREMENTS.md ticked + traceability Complete |
| GND-03 | 02-03 (partial), 02-04 (closes) | Node.js server retired and removed | ✓ SATISFIED | Filesystem + `test_legacy_cutover.py`; REQUIREMENTS.md ticked + traceability Complete |
| GND-04 | 02-01, 02-02 | Ground station maintains current signal state and pushes updates to connected browsers | ✓ SATISFIED | `test_client_receives_update_after_snapshot`; live session |
| GND-05 | 02-01, 02-02 | Newly connected browser receives full state snapshot | ✓ SATISFIED | `test_first_event_is_snapshot`; live reconnect confirmed |
| CAP-01 | Phase 1 (capture half) + 02-04 (deletion half) | Single logger implementation; duplicate removed from repo | ✓ SATISFIED | Filesystem + `test_legacy_cutover.py::test_legacy_logger_modules_removed`; REQUIREMENTS.md ticked + traceability Complete |

**No orphaned requirements.** Grepped every phase-2 plan's `requirements:` frontmatter: GND-02/04/05 → 02-01 & 02-02; GND-03 → 02-03 (claimed, not marked) & 02-04 (marks); CAP-01 → 02-04 (marks). This exactly matches the phase's declared requirement list (GND-02, GND-03, GND-04, GND-05, CAP-01) — every one accounted for by exactly one closing plan, no plan-numbering violation found.

### Anti-Patterns Found

A prior code review (`02-REVIEW.md`, standard depth, 10 files) found 1 critical + 5 warnings + 2 info findings. A subsequent fix pass (`02-REVIEW-FIX.md`) resolved all 6 critical/warning findings, each with its own commit and a discriminating regression test (confirmed to fail against the pre-fix code, then pass against the fix — not a tautological test). Verified directly this session:

| File | Finding | Severity | Status |
|------|---------|----------|--------|
| `static/dashboard.html:547-695` | CR-01: `getElementById`/`CSS.escape` mismatch broke message collapse/toggle | Critical | ✓ FIXED — grep confirms no `CSS.escape` in any `getElementById('mg-'+...)` lookup; live-verified working (WINDOWS.md id=2) |
| `static/dashboard.html:475-573` | WR-01: truthy check broke min/max range tracking at value `0` | Warning | ✓ FIXED — grep confirms `!(sigKey in signalMins)` pattern; regression-tested (not live-screenshotted, see disclosed item above) |
| `static/dashboard.html:795`, `server.py` | WR-02: `/state` fallback fetch 404'd, silently swallowed | Warning | ✓ FIXED — `STATE_ROUTE = "/state"` confirmed in server.py's route allowlist; live-verified returns 200 (WINDOWS.md id=2) |
| `server.py:189-199` | WR-03: SSE write-failure logging silenced after first client ever, not per-client | Warning | ✓ FIXED — keyed on `client_address`, regression-tested with two distinct clients |
| `cli.py:501-511` | WR-04: unguarded `DashboardServer` construction could crash instead of clean `SystemExit(1)` | Warning | ✓ FIXED — wrapped in `try/except OSError`, new `tests/test_ground_cli.py` |
| `simulate.py:167-192` | WR-05: `--loop` with empty frame stream busy-spins with no wait | Warning | ✓ FIXED — `--duration-s > 0` now validated at parse time |
| `static/dashboard.html` (IN-01, IN-02) | Unescaped `innerHTML` interpolation (info); unused `--channel-colors` CSS var (info) | Info | Explicitly out of scope (`fix_scope: critical_warning`); accepted risk — names/values source only from the local DBC, not wire-carried values |

No unresolved `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers found in any phase-2-modified file (`src/telemetry/ground/**`) — confirmed by direct grep this session.

### Broken Windows Ledger Cross-Check

`.planning/WINDOWS.md` currently shows 2 fixed and 1 open item, all phase-2-scoped:

- **id=1** (unrun browser check for 02-02's dashboard DOM interactions) — **fixed**, with a detailed live-Chrome verification note matching the `already_verified_this_session` evidence given to this verifier. Cross-checked and consistent.
- **id=2** (unrun browser check for 02-03's simulator-driven dashboard demo) — **fixed**, same cross-check, consistent (channel tabs, stats bar, `/state` and CR-01 fix confirmed live).
- **id=3** (open, "observation") — a running `telemetry.ground.simulate` instance does not recover when its UDP peer (the ground station) restarts; the browser and receiver both recovered cleanly, only the sender wedged. Root cause unconfirmed, leading hypothesis is a Windows-only `WSAECONNRESET`-on-ICMP-port-unreachable artifact (same class as a prior recorded Windows-only quirk), which would mean the Linux/CM4 deployment target is unaffected.

**Verifier's independent assessment of id=3:** Agreed as out of phase-2 scope. `simulate.py` is explicitly a dev/demo stand-in for the car (its own module docstring says so, per 02-03-PLAN.md's action text), not the car-side logger `telemetry.logger.cli` that CAP-01/GND-0x actually govern. No phase-2 requirement (GND-02/03/04/05, CAP-01) covers sender-side link-recovery behavior — that is squarely PROTO-05/PROTO-06 (Phase 4, keyframe-based resync) and LINK-05/LINK-06 (Phase 5, saturation/backpressure) territory, both still Pending by design. Leaving this open (not waived) in WINDOWS.md is the correct call — it is a real, reproducible defect worth root-causing before it either (a) turns out to also affect the real `UdpLink`/`telemetry.logger.cli` path (unconfirmed either way this session) or (b) is confirmed Windows-dev-box-only and closed with that finding recorded. Recommend the next phase to touch `link/udp.py` (natural owner: Phase 4 or 5, as the ledger already suggests) investigate before relying on unattended sender-side recovery.

## Gaps Summary

None. All 4 ROADMAP success criteria, both halves of CAP-01, and every plan-level must-have across
02-01 through 02-04 are verified either by a passing automated test that discriminates fixed from
broken behavior, or by the live Chrome browser session already run this phase (single process,
both channel tabs live at ~4000 msg/s, snapshot-on-connect, staleness dimming and reversion,
EventSource reconnect-with-no-reload across a server restart, no-results search state, and the
CR-01/WR-02 fixes' live re-verification). The full test suite (323 tests) passes with zero
failures, re-run directly by this verifier rather than trusted from SUMMARY.md. `can-dashboard/`
and the four legacy logger modules are confirmed absent from disk, not just from a claimed grep.
`.claude/CLAUDE.md` was read directly and confirmed to describe only the system that exists — this
matters because the phase's own review artifacts (02-REVIEW-FIX.md) record this project's #1
recorded failure mode (stale documentation) as exactly the kind of claim that must be checked, not
transcribed, and the file's content as read here fully backs the claim.

One disclosed, non-blocking judgment call (the mini-range-bar visual fix, WR-01) and one disclosed,
correctly-still-open ledger item (WINDOWS.md id=3, simulator-side UDP recovery, out of phase-2
scope) are recorded above rather than silently omitted.

---

_Verified: 2026-08-08T19:00:00Z_
_Verifier: Claude (gsd-verifier)_
