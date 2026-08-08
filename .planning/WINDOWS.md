---
schema_version: 1
open_count: 2
waived_count: 0
fixed_count: 0
total_count: 2
last_updated: 2026-08-08T17:07:04.665Z
---

# Broken Windows Ledger

> Cross-phase defect register. `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 2 | unrun-verify | src/telemetry/ground/static/dashboard.html |  | 02-02 Task 2 human-check (browser dimming, reconnect-across-restart, no-results DOM) not run this session -- no browser automation tool available; file-content assertions and end-to-end SSE/UDP data-flow verified instead | open |  | 2026-08-08T16:48:13.531Z |  |
| 2 | 2 | unrun-verify | src/telemetry/ground/simulate.py |  | 02-03 Task 2 human-check (browser dashboard demo: two channel tabs populate, status indicator, staleness-dim-on-stop, re-brighten-on-restart) not run this session -- no browser automation tool available. Automated proxy verified instead: two real subprocesses (ground station --serve + simulator --loop) over real UDP, ground station link-health reported batches_received=batches_ok=98/98, records_decoded=5418, records_decode_failed=0, zero cobs/crc/batch_format discards; /events SSE snapshot and / root both returned real decoded signal data over HTTP. | open |  | 2026-08-08T17:07:04.665Z |  |

````json
[
  {
    "id": 1,
    "kind": "unrun-verify",
    "phase": "2",
    "file": "src/telemetry/ground/static/dashboard.html",
    "line": null,
    "description": "02-02 Task 2 human-check (browser dimming, reconnect-across-restart, no-results DOM) not run this session -- no browser automation tool available; file-content assertions and end-to-end SSE/UDP data-flow verified instead",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-08T16:48:13.531Z",
    "resolved_at": null
  },
  {
    "id": 2,
    "kind": "unrun-verify",
    "phase": "2",
    "file": "src/telemetry/ground/simulate.py",
    "line": null,
    "description": "02-03 Task 2 human-check (browser dashboard demo: two channel tabs populate, status indicator, staleness-dim-on-stop, re-brighten-on-restart) not run this session -- no browser automation tool available. Automated proxy verified instead: two real subprocesses (ground station --serve + simulator --loop) over real UDP, ground station link-health reported batches_received=batches_ok=98/98, records_decoded=5418, records_decode_failed=0, zero cobs/crc/batch_format discards; /events SSE snapshot and / root both returned real decoded signal data over HTTP.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-08T17:07:04.665Z",
    "resolved_at": null
  }
]
````
