---
phase: 02-python-ground-station-and-dashboard-cutover
fixed_at: 2026-08-08T18:08:01Z
review_path: .planning/phases/02-python-ground-station-and-dashboard-cutover/02-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-08-08T18:08:01Z
**Source review:** .planning/phases/02-python-ground-station-and-dashboard-cutover/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (1 critical + 5 warnings; the 2 Info findings were explicitly out of scope
  per `fix_scope: critical_warning` and were left untouched)
- Fixed: 6
- Skipped: 0

Each finding was fixed and committed atomically on an isolated worktree branch
(`gsd-reviewfix/02-199`), then fast-forwarded onto `add-pedal-percent-msg`. Full test suite after
all six fixes: **323 passed, 0 failed** (315 pre-existing + 8 new regression tests added by this
pass).

## Fixed Issues

### CR-01: Message-level collapse and message-level visibility toggle are non-functional (`getElementById` vs `CSS.escape` id mismatch)

**Files modified:** `src/telemetry/ground/static/dashboard.html`, `tests/test_ground_server.py`
**Commit:** `c015acf`
**Applied fix:** Removed the erroneous `CSS.escape()` wrapping from the four `getElementById('mg-'
+ ...)` lookups in `createMessageGroup`, `ensureMessageRow`, `toggleMsg`, and `toggleCollapse`, so
each lookup now uses the same bare `groupKey` literal that `group.id = 'mg-' + groupKey` actually
assigns. This matches the review's primary suggested fix exactly (dropping `CSS.escape` rather than
standardizing on `escId()`, since the id-assignment line was left untouched and simplest-fix wins
when both options are equivalent).

**Test coverage note (per this task's explicit verification requirement):** This project's
dashboard test suite has no DOM/browser harness — its dashboard tests are file-content assertions,
by the test file's own stated design, and that remains true after this fix. I added
`test_message_group_id_assignment_and_lookup_use_the_same_scheme`, a file-content regression test
asserting (a) the assignment line remains the raw, unescaped `groupKey` literal, (b) no `'mg-' +
CSS.escape(groupKey)` lookup exists anywhere in the file, and (c) every `getElementById('mg-' +
...)` lookup uses exactly `groupKey`, nothing else. This test **cannot prove that clicking a
message row in a real browser toggles `.collapsed`** — no browser automation exists in this repo
and I did not invent one, per instruction. What it does prove: the specific assignment/lookup
mismatch class that caused CR-01 (an escaping function's output being used where a literal id is
required) is not present in the shipped source, and the test is *discriminating* — I confirmed it
fails against the pre-fix source (reverted via `git stash`) and passes against the fix. This is a
regression guard against the exact bug class, not a proof of correct browser behavior; a genuine
click-and-observe UAT check remains the only thing that can prove the latter.

### WR-01: Signal min/max range tracking breaks whenever the true min or max is exactly `0`

**Files modified:** `src/telemetry/ground/static/dashboard.html`, `tests/test_ground_server.py`
**Commit:** `1a3835b`
**Applied fix:** Replaced the truthy checks `!signalMins[sigKey]` / `!signalMaxs[sigKey]` (in
`handleUpdate` and `createMessageGroup`) with explicit key-existence checks `!(sigKey in
signalMins)` / `!(sigKey in signalMaxs)`, exactly as the review's suggested fix specifies.

Added `test_signal_range_tracking_uses_key_existence_not_truthiness`, a file-content regression
test asserting the truthy-check pattern is absent and the existence-check pattern is present.
Same DOM-test caveat as CR-01 applies: this proves the specific bug pattern (falsy-`0` truthy
check) is absent from source, not that the mini-bar renders a specific width in a browser.

### WR-02: `fetch('/state')` fallback targets a route the server never implements

**Files modified:** `src/telemetry/ground/server.py`, `tests/test_ground_server.py`
**Commit:** `82b8d36`
**Applied fix:** Chose the review's first option (implement the route) rather than removing the
dead fetch call, because the underlying gap the review names — no working recovery path for an
`EventSource` reconnect race that drops the initial snapshot — is a real robustness gap worth
closing, not just an honesty-of-comments issue, and the implementation cost was low. Added
`STATE_ROUTE = "/state"` to the server's fixed route allowlist (now three routes, not two — updated
the surrounding "exactly two routes" comments to "exactly three") and a `_serve_state()` handler
that returns `snapshot_provider()`'s current snapshot as a finite JSON body (200, `Content-Type:
application/json`, `Content-Length` set — unlike `/events`, which deliberately omits it). A
`snapshot_provider()` failure here returns an ordinary HTTP 500 (no headers have been sent yet at
that point, unlike `_serve_events`'s post-headers-sent case, so a normal error status is safe and
does not risk permanently stopping `EventSource` retries the way it would on the `/events` route).

Added two tests: `test_state_route_returns_the_snapshot_as_json` (full-stack, real
`DashboardServer`, asserts `GET /state` returns 200 JSON equal to the injected snapshot) and
`test_dashboard_state_fallback_fetches_a_route_the_server_implements` (a regex-anchored guard that
`dashboard.html`'s `fetch('/state')` literal names the same `STATE_ROUTE` constant the server
defines, so the two files cannot silently drift apart again).

### WR-03: SSE client-write-failure logging is log-once-ever, not log-once-per-cause

**Files modified:** `src/telemetry/ground/server.py`, `tests/test_ground_server.py`
**Commit:** `e028cc5`
**Applied fix:** Replaced the single process-lifetime `_write_failure_state = {"logged": False}`
flag with `_write_failure_state = {"logged_addresses": set()}`, keyed on `self.client_address`
exactly as the review's suggested fix specifies, so a distinct client address disconnecting still
gets its own first-seen warning line rather than being silently absorbed by whichever client
disconnected first.

Added `test_write_failure_logging_is_keyed_per_client_address`: opens two distinct SSE client
connections (each its own ephemeral source port, hence a distinct `client_address`), closes both
without draining, broadcasts until both are unregistered, and asserts (via `caplog`) that **two**
distinct warning log records were produced, not one. I confirmed this test fails against the
pre-fix code (only one warning logged, the second client's disconnect silently suppressed) before
confirming it passes against the fix — a genuinely discriminating regression test, not a
tautology.

### WR-04: `DashboardServer` construction in `main()` is not guarded

**Files modified:** `src/telemetry/ground/cli.py`, `tests/test_ground_cli.py` (new file)
**Commit:** `b9073a6`
**Applied fix:** Wrapped the `DashboardServer(...)` construction in `try`/`except OSError`,
mirroring the existing guard pattern used for config/DBC/gate-config/message-index loads earlier in
the same function: log the failure, close `link`, close `output_file` if open, cancel `watchdog` if
running, then `raise SystemExit(1) from exc` — matching the review's suggested fix.

Created `tests/test_ground_cli.py` (no test file previously existed for `cli.py`) with
`test_dashboard_server_bind_failure_exits_via_system_exit_and_closes_the_link`: monkeypatches
`DashboardServer` to a stub that raises `OSError` on construction and `_build_link` to return a
recording `Link` double, drives `main(argv=["--serve"])` in-process (no subprocess needed), and
asserts `SystemExit(1)` is raised and the link was closed. Confirmed to fail against the pre-fix
code (raw `OSError` propagates instead of `SystemExit`, link never closed) before confirming it
passes against the fix.

### WR-05: `telemetry.ground.simulate --loop` busy-spins with no wait if the synthetic stream is empty

**Files modified:** `src/telemetry/ground/simulate.py`, `tests/test_ground_simulate.py`
**Commit:** `4b1fd46`
**Applied fix:** Chose the review's first suggested option — validate `--duration-s > 0` in
`_parse_args`, alongside the existing `--pacing > 0` check — over the second option (an explicit
`stop_event.wait()` fallback inside `feed_frames` for an empty pass), because it is the simpler,
lower-risk change that turns a misconfigured demo run into an immediate, clear CLI error rather
than a CPU-burning no-op, without touching `feed_frames`' pacing logic at all.

Added `test_zero_or_negative_duration_s_is_rejected_at_parse_time` (asserts `--duration-s 0` and a
negative value both exit via `SystemExit(2)` with the new error text on stderr) and
`test_omitted_duration_s_still_parses` (a positive value and the omitted default are unaffected).
Confirmed the first test fails against the pre-fix code (no `SystemExit` raised) before confirming
it passes against the fix.

## Skipped Issues

None — all six in-scope findings were fixed.

## Out of Scope (not modified, per task instructions)

- **IN-01** (unescaped `innerHTML` interpolation) and **IN-02** (unused `--channel-colors` CSS
  variable) — Info-severity, explicitly excluded by `fix_scope: critical_warning`.
- `REQUIREMENTS.md` — not touched, per explicit instruction; all five of this phase's requirements
  were already correctly marked Complete before this fix pass and remain so.
- `.claude/CLAUDE.md` — in the reviewed file set but had no Critical/Warning findings against it;
  not modified.
- The SSE/telemetry fan-out's drop-oldest behavior (`SseHub.broadcast`) — by design per this task's
  anti-pattern list, not touched.

## Full Test Suite Result

```
323 passed in 37.22s
```

315 pre-existing + 8 new tests added across the six fixes above (1 for CR-01, 1 for WR-01, 2 for
WR-02, 1 for WR-03, 1 for WR-04, 2 for WR-05). Zero failures.

---

_Fixed: 2026-08-08T18:08:01Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
