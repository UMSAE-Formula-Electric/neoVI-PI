---
schema_version: 1
open_count: 2
waived_count: 0
fixed_count: 2
total_count: 4
last_updated: 2026-09-30T07:04:28.817Z
---

# Broken Windows Ledger

> Cross-phase defect register. `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 2 | unrun-verify | src/telemetry/ground/static/dashboard.html |  | 02-02 Task 2 human-check (browser dimming, reconnect-across-restart, no-results DOM) not run this session -- no browser automation tool available; file-content assertions and end-to-end SSE/UDP data-flow verified instead | fixed | Run in a real Chrome browser during the phase-2 code-review gate. Staleness: all 36 .sig-value elements gained .stale after transmission stopped (3000ms threshold, --dim color, no row opacity change -- exactly as 02-UI-SPEC.md specifies), and all 36 cleared on resume. Reconnect-across-restart: ground station killed -> status dot .error + 'Reconnecting...'; restarted -> auto-returned to .live + 'Live' with performance.getEntriesByType('navigation').length === 1, proving EventSource reconnected with NO page reload. No-results DOM: searching 'zzzznotarealsignal' rendered the specified empty state with 'No signals match' + 'Clear search'. | 2026-08-08T16:48:13.531Z | 2026-08-08T18:23:03.800Z |
| 2 | 2 | unrun-verify | src/telemetry/ground/simulate.py |  | 02-03 Task 2 human-check (browser dashboard demo: two channel tabs populate, status indicator, staleness-dim-on-stop, re-brighten-on-restart) not run this session -- no browser automation tool available. Automated proxy verified instead: two real subprocesses (ground station --serve + simulator --loop) over real UDP, ground station link-health reported batches_received=batches_ok=98/98, records_decoded=5418, records_decode_failed=0, zero cobs/crc/batch_format discards; /events SSE snapshot and / root both returned real decoded signal data over HTTP. | fixed | Run in a real Chrome browser during the phase-2 code-review gate. Both channel tabs populate (MAIN 11 messages / SENSOR 1 = Battery_Volt_1_Overall_Param_Std 0x101); stats bar read Channels 2 / Messages 12 / Signals 43. Status indicator showed a green .live dot at ~4000 msg/s under load. Staleness-dim-on-stop and re-brighten-on-restart both confirmed (see id=1). Also verified live: the /state route added by WR-02 returns 200, and CR-01's fix -- getElementById('mg-MAIN\|0xA0') now resolves, so message collapse (msg-group collapsed, display:none, height 0) and the message visibility toggle (msg-group hidden, opacity 0.35) both work, which is precisely what CR-01 reported as permanently broken. | 2026-08-08T17:07:04.665Z | 2026-08-08T18:23:03.800Z |
| 3 | 2 | unmet-truth | src/telemetry/ground/simulate.py |  | A running simulator does NOT recover when its UDP peer restarts. Observed live: with the simulator running, the ground station was killed and restarted; the browser's EventSource reconnected cleanly to 'Live' with no page reload, but no further data arrived (0 msg/s, all 36 values stale) even though BOTH processes were confirmed alive. Killing and restarting the simulator alone immediately restored 4079 msg/s and cleared all staleness -- isolating the fault to the sender, not the receiver or the browser. Root cause NOT confirmed this session; the leading hypothesis is the documented Windows UDP behaviour where ICMP port-unreachable surfaces as WSAECONNRESET and wedges the sender's socket (the same class of dev-box-only quirk already recorded for WSAEMSGSIZE in 01-08), which would mean the Linux/CM4 deployment target is unaffected. Not a phase-2 blocker: simulate.py is a dev/demo stand-in, not the car-side logger, and no phase-2 requirement covers sender-side link recovery. Natural owner is phase 4 (Wire Protocol Hardening, 'recovers on its own') or phase 5. | open |  | 2026-08-08T18:23:03.800Z |  |
| 4 | 3 | unmet-truth | tests/test_logger_cli_ops.py |  | test_mid_run_disk_log_repeats_once_the_rate_limit_interval_elapses is load-sensitive and asserts determinism it does not have. It runs _run_session on a background thread for a 0.3s REAL wall-clock window with heartbeat_interval_s=0.02, expecting ~15 heartbeat ticks and asserting >1. The clock it reasons about is ALREADY simulated via now_fn(step=100.0), so only the thread scheduling is real -- under full-suite load on Windows the thread can be starved to a single tick inside that 300ms window and the assertion fails. Observed failing ONCE by the code-fixer agent during a full-suite run while applying WR-01/WR-04; NOT reproducible afterward across 5 isolated runs plus 2 consecutive clean full-suite runs (463/463 both). Pre-existing from 03-02; NOT introduced by the CR-01/WR-01/WR-04 fixes. Fix: gate on an observed tick count rather than a fixed real-time window -- the logical claim ('re-logs once the interval elapses') does not depend on wall-clock at all. Natural owner: the gap pass carrying WR-02/03/05/06 from 03-REVIEW.md. | open |  | 2026-09-30T07:04:28.817Z |  |

````json
[
  {
    "id": 1,
    "kind": "unrun-verify",
    "phase": "2",
    "file": "src/telemetry/ground/static/dashboard.html",
    "line": null,
    "description": "02-02 Task 2 human-check (browser dimming, reconnect-across-restart, no-results DOM) not run this session -- no browser automation tool available; file-content assertions and end-to-end SSE/UDP data-flow verified instead",
    "status": "fixed",
    "reason": "Run in a real Chrome browser during the phase-2 code-review gate. Staleness: all 36 .sig-value elements gained .stale after transmission stopped (3000ms threshold, --dim color, no row opacity change -- exactly as 02-UI-SPEC.md specifies), and all 36 cleared on resume. Reconnect-across-restart: ground station killed -> status dot .error + 'Reconnecting...'; restarted -> auto-returned to .live + 'Live' with performance.getEntriesByType('navigation').length === 1, proving EventSource reconnected with NO page reload. No-results DOM: searching 'zzzznotarealsignal' rendered the specified empty state with 'No signals match' + 'Clear search'.",
    "recorded_at": "2026-08-08T16:48:13.531Z",
    "resolved_at": "2026-08-08T18:23:03.800Z"
  },
  {
    "id": 2,
    "kind": "unrun-verify",
    "phase": "2",
    "file": "src/telemetry/ground/simulate.py",
    "line": null,
    "description": "02-03 Task 2 human-check (browser dashboard demo: two channel tabs populate, status indicator, staleness-dim-on-stop, re-brighten-on-restart) not run this session -- no browser automation tool available. Automated proxy verified instead: two real subprocesses (ground station --serve + simulator --loop) over real UDP, ground station link-health reported batches_received=batches_ok=98/98, records_decoded=5418, records_decode_failed=0, zero cobs/crc/batch_format discards; /events SSE snapshot and / root both returned real decoded signal data over HTTP.",
    "status": "fixed",
    "reason": "Run in a real Chrome browser during the phase-2 code-review gate. Both channel tabs populate (MAIN 11 messages / SENSOR 1 = Battery_Volt_1_Overall_Param_Std 0x101); stats bar read Channels 2 / Messages 12 / Signals 43. Status indicator showed a green .live dot at ~4000 msg/s under load. Staleness-dim-on-stop and re-brighten-on-restart both confirmed (see id=1). Also verified live: the /state route added by WR-02 returns 200, and CR-01's fix -- getElementById('mg-MAIN|0xA0') now resolves, so message collapse (msg-group collapsed, display:none, height 0) and the message visibility toggle (msg-group hidden, opacity 0.35) both work, which is precisely what CR-01 reported as permanently broken.",
    "recorded_at": "2026-08-08T17:07:04.665Z",
    "resolved_at": "2026-08-08T18:23:03.800Z"
  },
  {
    "id": 3,
    "kind": "unmet-truth",
    "phase": "2",
    "file": "src/telemetry/ground/simulate.py",
    "line": null,
    "description": "A running simulator does NOT recover when its UDP peer restarts. Observed live: with the simulator running, the ground station was killed and restarted; the browser's EventSource reconnected cleanly to 'Live' with no page reload, but no further data arrived (0 msg/s, all 36 values stale) even though BOTH processes were confirmed alive. Killing and restarting the simulator alone immediately restored 4079 msg/s and cleared all staleness -- isolating the fault to the sender, not the receiver or the browser. Root cause NOT confirmed this session; the leading hypothesis is the documented Windows UDP behaviour where ICMP port-unreachable surfaces as WSAECONNRESET and wedges the sender's socket (the same class of dev-box-only quirk already recorded for WSAEMSGSIZE in 01-08), which would mean the Linux/CM4 deployment target is unaffected. Not a phase-2 blocker: simulate.py is a dev/demo stand-in, not the car-side logger, and no phase-2 requirement covers sender-side link recovery. Natural owner is phase 4 (Wire Protocol Hardening, 'recovers on its own') or phase 5.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-08T18:23:03.800Z",
    "resolved_at": null
  },
  {
    "id": 4,
    "kind": "unmet-truth",
    "phase": "3",
    "file": "tests/test_logger_cli_ops.py",
    "line": null,
    "description": "test_mid_run_disk_log_repeats_once_the_rate_limit_interval_elapses is load-sensitive and asserts determinism it does not have. It runs _run_session on a background thread for a 0.3s REAL wall-clock window with heartbeat_interval_s=0.02, expecting ~15 heartbeat ticks and asserting >1. The clock it reasons about is ALREADY simulated via now_fn(step=100.0), so only the thread scheduling is real -- under full-suite load on Windows the thread can be starved to a single tick inside that 300ms window and the assertion fails. Observed failing ONCE by the code-fixer agent during a full-suite run while applying WR-01/WR-04; NOT reproducible afterward across 5 isolated runs plus 2 consecutive clean full-suite runs (463/463 both). Pre-existing from 03-02; NOT introduced by the CR-01/WR-01/WR-04 fixes. Fix: gate on an observed tick count rather than a fixed real-time window -- the logical claim ('re-logs once the interval elapses') does not depend on wall-clock at all. Natural owner: the gap pass carrying WR-02/03/05/06 from 03-REVIEW.md.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-09-30T07:04:28.817Z",
    "resolved_at": null
  }
]
````
