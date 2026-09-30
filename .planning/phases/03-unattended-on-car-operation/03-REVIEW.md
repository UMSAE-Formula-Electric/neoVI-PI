---
phase: 03-unattended-on-car-operation
reviewed: 2026-09-30T00:00:00Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - config/logger.json
  - deploy/install.sh
  - deploy/telemetry-logger.service
  - docs/runbook.md
  - src/telemetry/logger/cli.py
  - src/telemetry/logger/config.py
  - src/telemetry/ops/__init__.py
  - src/telemetry/ops/cli.py
  - src/telemetry/ops/disk_monitor.py
  - src/telemetry/ops/hardware_wait.py
  - src/telemetry/ops/heartbeat.py
  - src/telemetry/ops/led.py
  - tests/test_deploy_unit_file.py
  - tests/test_logger_cli_ops.py
  - tests/test_logger_config.py
  - tests/test_ops_cli.py
  - tests/test_ops_disk_monitor.py
  - tests/test_ops_hardware_wait.py
  - tests/test_ops_heartbeat.py
  - tests/test_ops_led.py
  - tests/test_ops_tracer.py
  - tests/test_runbook_coverage.py
findings:
  critical: 1
  warning: 6
  info: 3
  total: 10
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-09-30T00:00:00Z
**Depth:** standard
**Files Reviewed:** 22 (21 listed files reviewed directly; `tests/test_logger_cli_ops.py` also exercises `src/telemetry/logger/cli.py` and is counted once)
**Status:** issues_found

## Summary

The heartbeat staleness/reboot-boundary logic, the disk-space banding
(`free_bytes` compared directly, never a `total`-derived percentage), and the
`sdk.RuntimeError`-via-injection convention in `hardware_wait.py` were all
checked against the specific hazards called out for this phase and all three
hold up under adversarial reading — the code does what its docstrings claim.

The most serious finding is in `deploy/install.sh`: the script enables and
starts the systemd unit (`enable --now`) **before** creating and chowning the
archive/heartbeat directories the unprivileged service account needs to
write to on first boot — the exact inversion of what "Addition 3"'s own
comment says it exists to prevent. The existing unit-file test suite already
has the technique (string-offset ordering checks) to have caught this and
simply never applied it to this ordering, which is the same failure shape
this project has recorded before (a green test suite that checks shape, not
the behavior that actually matters).

Beyond that, review surfaced several narrower gaps: an uncovered exception
window between session/writer/link/fan-out construction and the capture-loop
`try` block that can leave the heartbeat frozen with no explanatory
`stopped-error` state; a `wait_for_hardware` that ignores
`capture.hardware_serial` entirely, so a wrong-but-present device can be
mistaken for "hardware ready" on a multi-device box; a narrow TOCTOU race in
`telemetry.ops.cli.main` between its `exists()` check and its `read_heartbeat`
call; and a maintainability issue where `telemetry.ops.cli` hardcodes
heartbeat state name literals instead of importing the single-source
constants it already imports two of.

## Critical Issues

### CR-01: `deploy/install.sh` starts the service before the directories it needs exist

**File:** `deploy/install.sh:63-80`
**Issue:** The script runs, in order: install the unit (line 63),
`daemon-reload` (line 64), **`systemctl enable --now` (line 65)** — which
forks the `ExecStart` process (`User=telemetry`) essentially immediately,
since `Type=simple` does not wait for readiness — and only *after* that
creates and chowns the archive root and heartbeat directory (lines 75-80):

```bash
sudo install -m 644 "${SCRIPT_DIR}/${UNIT_NAME}" "/etc/systemd/system/${UNIT_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable --now "${UNIT_NAME}"     # <- starts the service NOW

ARCHIVE_ROOT="${DEPLOY_ROOT}/sessions"
HEARTBEAT_DIR="${DEPLOY_ROOT}/var"

sudo mkdir -p "${ARCHIVE_ROOT}"
sudo mkdir -p "${HEARTBEAT_DIR}"
sudo chown "${SERVICE_USER}:${SERVICE_USER}" "${ARCHIVE_ROOT}" "${HEARTBEAT_DIR}"
```

The script's own comment on this block (lines 67-74) says it exists so "the
unprivileged process can actually write to them **on first boot**" — but by
the time it runs, the process has already started and almost certainly
already attempted (and, on a normally-permissioned `/opt/telemetry` owned by
root with `755`, failed) to `mkdir` its session directory
(`telemetry.archive.session.new_session`) and its heartbeat file's parent
(`telemetry.ops.heartbeat.write_heartbeat`'s own
`path.parent.mkdir(parents=True, exist_ok=True)`), since the unprivileged
`telemetry` account has no write permission on `/opt/telemetry` itself until
this later block runs. `Restart=always` / `RestartSec=2` means the unit
self-heals on its next restart (by then the directories exist), so this is
not a permanently broken install — but it is a guaranteed spurious failed
start on every fresh install, and it is the literal inversion of the
ordering the script's own comment claims.

This is exactly the failure shape called out for this review: the existing
test suite (`tests/test_deploy_unit_file.py`) already has the technique to
catch this — `test_install_script_daemon_reload_precedes_enable` checks two
strings' relative `.index()` offsets in the script text to pin execution
order for this same bash script — and simply never applied that same
technique to the mkdir/chown-vs-enable ordering, so a real ordering defect
shipped past a green suite that otherwise looks like it covers exactly this
class of bug.

**Fix:** Move the archive-root/heartbeat-directory creation and `chown`
block before `sudo systemctl enable --now`:
```bash
sudo install -m 644 "${SCRIPT_DIR}/${UNIT_NAME}" "/etc/systemd/system/${UNIT_NAME}"
sudo systemctl daemon-reload

ARCHIVE_ROOT="${DEPLOY_ROOT}/sessions"
HEARTBEAT_DIR="${DEPLOY_ROOT}/var"
sudo mkdir -p "${ARCHIVE_ROOT}"
sudo mkdir -p "${HEARTBEAT_DIR}"
sudo chown "${SERVICE_USER}:${SERVICE_USER}" "${ARCHIVE_ROOT}" "${HEARTBEAT_DIR}"

sudo systemctl enable --now "${UNIT_NAME}"
```
and add a regression test to `tests/test_deploy_unit_file.py` mirroring
`test_install_script_daemon_reload_precedes_enable`:
```python
def test_install_script_creates_directories_before_enabling(install_text):
    mkdir_offset = install_text.index('mkdir -p "${ARCHIVE_ROOT}"')
    enable_offset = install_text.index("enable --now")
    assert mkdir_offset < enable_offset
```

## Warnings

### WR-01: Session/link/fan-out construction failures leave the heartbeat frozen with no explanation

**File:** `src/telemetry/logger/cli.py:446-599`
**Issue:** `_run_session` constructs the session (`new_session`, line 446),
`ArchiveWriter` (454), the link (460), `FanOut` (461), `ArchiveRunner` (469),
and `TelemetryPipeline` (475) — none of this is inside a `try`/`except`; the
`try:` block that maps a capture-loop exception to `capture_failed = True`
(and, further down, to a `stopped-error` terminal heartbeat) only begins at
line 599, *after* all of the above and after `archive_runner.start()` /
`telemetry_pipeline.start()` / `publisher.start()`. A real, plausible-on-a-car
failure in this window — e.g. `new_session()` raising `PermissionError` or
`OSError` because the archive filesystem isn't mounted yet, or `_build_link`
raising on a bad UDP bind — propagates straight out of `_run_session` and out
of `main()` uncaught (neither has a surrounding `try`/`except`), crashing the
process with a raw traceback and **no `stopped-error` heartbeat write at
all**. The status file is left at whatever it last held (`booting` or
`waiting-for-hardware`) and only becomes actionable once
`heartbeat_stale_after_s` elapses and `telemetry-status` reports staleness —
it never gets the specific, named explanation `_run_session`'s later
terminal-state logic promises for every other bad ending. The same gap
applies to `main()`'s own call to `wait_for_hardware_fn` (`src/telemetry/logger/cli.py:872-874`):
an exception the SDK does not own is documented to propagate (correctly, per
`hardware_wait.py`'s own docstring), but nothing in `main()` catches it to
publish a `stopped-error` snapshot first.
**Fix:** Wrap session/writer/link/fan-out construction (and the
`wait_for_hardware_fn` call in `main()`) in the same `except Exception:`
pattern already used for the capture loop, publishing a `stopped-error`
snapshot naming the exception before re-raising or exiting:
```python
try:
    session = new_session(config.archive.root_dir, config_hash=config.config_hash)
    writer = ArchiveWriter(...)
    link = _build_link(config.link)
    fan_out = FanOut(...)
    ...
except Exception as exc:
    publisher.publish_now(HeartbeatSnapshot(
        state=STATE_STOPPED_ERROR,
        detail=f"session setup failed: {exc}",
        extras={},
    ))
    raise
```

### WR-02: `wait_for_hardware` ignores `capture.hardware_serial`

**File:** `src/telemetry/ops/hardware_wait.py:76-83`, cross-referenced with
`src/telemetry/logger/cli.py:600-606, 862-874`
**Issue:** `wait_for_hardware`'s only readiness signal is whether
`sdk.find_devices()` returns anything non-empty — it has no parameter for,
and never consults, `config.capture.hardware_serial`. `main()` calls it with
no serial information at all (`wait_for_hardware_fn(stop_event=stop_event,
on_waiting=_on_waiting)`, lines 872-874), while the real capture path
(`HardwareFrameSource`, constructed later inside `_run_session`, line
600-606) is given `hardware_serial=config.capture.hardware_serial` and
presumably filters on it. On a bench or pit setup with more than one neoVI
device attached, `wait_for_hardware` can report "hardware present" as soon
as *any* device shows up, even if it is not the one `hardware_serial` names —
`_run_session` then proceeds straight to `new_session()` (already creating a
session directory) before discovering, inside `HardwareFrameSource.open()`,
that the configured serial isn't among the found devices, landing in the
broad `except Exception` and a `stopped-error` terminal state instead of the
intended continued retry loop. Low likelihood with the shipped
`hardware_serial: null` config, but a real gap the moment a serial is
configured.
**Fix:** Either pass `hardware_serial` into `wait_for_hardware` and filter
`find_devices()`'s result against it, or document explicitly (in both this
module's docstring and the config schema) that `wait_for_hardware` is a
presence-only probe and does not honor per-serial device selection.

### WR-03: TOCTOU race between `heartbeat_path.exists()` and `read_heartbeat` misreports exit code 1 instead of 4

**File:** `src/telemetry/ops/cli.py:320-342`
**Issue:** `main()` checks `heartbeat_path.exists()` (line 320) and, if
absent, exits with `EXIT_NOT_RUNNING` (4) — the documented "clean stop"
signal. If the file exists at that check but is removed by
`HeartbeatPublisher.remove()` (a real, in-flight race on a car if an operator
runs `telemetry-status` at the exact moment the logger is finishing a clean
shutdown) before the subsequent `read_heartbeat(...)` call (line 337-339),
`read_heartbeat` raises `HeartbeatReadError` (its `except OSError` catches
`FileNotFoundError`), which `main()` maps to `EXIT_ERROR` (1) — "the status
file is present but unreadable/malformed" — not `EXIT_NOT_RUNNING` (4). A
script polling exit codes to distinguish "not running" from "genuine error"
gets the wrong answer in this narrow window.
**Fix:** Treat a `FileNotFoundError` surfaced through `HeartbeatReadError`
(or catch it before calling `read_heartbeat`) as `EXIT_NOT_RUNNING`, e.g. by
re-checking existence in the except branch, or by having `read_heartbeat`
raise a distinguishable exception subtype for "file vanished between the
check and the read."

### WR-04: `telemetry.ops.cli` hardcodes heartbeat state-name literals instead of the constants it already imports

**File:** `src/telemetry/ops/cli.py:82-83, 89-114`
**Issue:** The module imports `STATE_CAPTURING` and `STATE_DEGRADED` from
`telemetry.ops.heartbeat` and uses them at lines 282 (`state in
(STATE_CAPTURING, STATE_DEGRADED)`), but `_FRESH_OK_STATES` /
`_FRESH_BAD_STATES` (lines 82-83) and every key in `_STATE_INFO` (lines
89-114) are hand-typed string literals (`"booting"`, `"waiting-for-hardware"`,
`"capturing"`, `"degraded"`, `"stopped-error"`) rather than
`STATE_BOOTING`/`STATE_WAITING_FOR_HARDWARE`/`STATE_STOPPED_ERROR` (not even
imported) or the two constants already in scope. This is exactly the
restate-instead-of-import anti-pattern `telemetry.logger.config` explicitly
calls out avoiding (`MAX_DELTA_T_US`, `01-CONTEXT.md`'s "#1 recorded
anti-pattern"). The `_missing_state_info` guard at import time (lines
116-127) only protects `_STATE_INFO`'s keys against drifting from
`HEARTBEAT_STATES` — `_FRESH_OK_STATES`/`_FRESH_BAD_STATES` have no such
guard, so a renamed state constant at the source silently falls through
`_exit_code_for` into the `EXIT_ERROR` catch-all (fail-safe, not fail-open,
but still an untested, unguarded path).
**Fix:** Import all five state constants and build the literals from them:
```python
from telemetry.ops.heartbeat import (
    STATE_BOOTING, STATE_WAITING_FOR_HARDWARE, STATE_CAPTURING,
    STATE_DEGRADED, STATE_STOPPED_ERROR, HEARTBEAT_STATES, ...
)
_FRESH_OK_STATES = frozenset({STATE_BOOTING, STATE_WAITING_FOR_HARDWARE, STATE_CAPTURING})
_FRESH_BAD_STATES = frozenset({STATE_DEGRADED, STATE_STOPPED_ERROR})
```
and add the same "every `HEARTBEAT_STATES` member must appear in
`_FRESH_OK_STATES | _FRESH_BAD_STATES`" import-time guard already used for
`_STATE_INFO`.

### WR-05: `--heartbeat-path` override resolution differs between the writer and the reader

**File:** `src/telemetry/logger/cli.py:280-284`, `src/telemetry/ops/cli.py:309-313`
**Issue:** `telemetry.logger.cli._apply_overrides` resolves a
`--heartbeat-path` override with `Path(args.heartbeat_path).resolve()`
(absolute, relative to CWD at resolve time). `telemetry.ops.cli.main` builds
the same override with a bare `Path(args.heartbeat_path)` — no `.resolve()`
call. If either process is later invoked from a different working directory
with the same relative `--heartbeat-path` value, the writer and reader can
resolve to two different files with no error from either side (the reader
would just report "not running" against the wrong path). Every test in this
review passes absolute (`tmp_path`-derived) paths, so this divergence is
untested and currently invisible.
**Fix:** Resolve `args.heartbeat_path` in `telemetry.ops.cli.main` the same
way the writer does: `Path(args.heartbeat_path).resolve()`.

### WR-06: `HeartbeatPublisher`'s LED is never closed on the hardware-wait clean-stop path

**File:** `src/telemetry/logger/cli.py:875-882`
**Issue:** When `wait_for_hardware_fn` returns `False` (operator stopped the
logger while it was still waiting for hardware), `main()` calls
`publisher.remove()` and returns — it never calls `publisher.join()`, which
is the only code path that calls `HeartbeatPublisher._close_led()`
(`src/telemetry/ops/heartbeat.py:349-364`). Harmless today because
`NullLedIndicator.close()` is a no-op and the periodic thread was never
started on this path either, but the moment the approved
`MembraneLedIndicator` (per `telemetry.ops.led`'s own module docstring) is
wired in, this specific shutdown path would leave a physical LED in
whatever state `_on_waiting`'s last `publish_now` set it to, rather than
turned off, while every other shutdown path in this module does close it.
**Fix:** Call `publisher.join(timeout=...)` (or at least
`publisher._close_led()`) alongside `publisher.remove()` on this path, for
parity with every other exit from `main()`/`_run_session`.

## Info

### IN-01: LED error counters are tracked but never surfaced in the shutdown summary

**File:** `src/telemetry/ops/heartbeat.py:312-313`
**Issue:** `HeartbeatPublisher.led_error_count` and
`led_error_log_suppressed_count` are incremented (`_drive_led`,
`src/telemetry/ops/heartbeat.py:328-347`) but `_build_summary` in
`src/telemetry/logger/cli.py` (which otherwise surfaces every other
subsystem's suppressed-error counters, e.g.
`telemetry_error_log_suppressed_count`) never reads them. A flaky physical
LED driver would only be visible in the journal's rate-limited WARNING line,
never in the same machine-readable end-of-session summary every other
failure mode reaches.
**Fix:** Once a real `led` is passed to `HeartbeatPublisher` (currently
always the default `NullLedIndicator`, so this has zero effect today), add
`publisher.led_error_count`/`led_error_log_suppressed_count` to
`_build_summary`'s dict for parity with the other counters.

### IN-02: `test_deploy_unit_file.py` and `test_runbook_coverage.py` are explicitly content/shape checks, not behavior proofs

**File:** `tests/test_deploy_unit_file.py`, `tests/test_runbook_coverage.py`
**Issue:** Both files say so themselves in their own module docstrings
(`test_deploy_unit_file.py:19-24`: "deliberately does NOT attempt semantic
validation... that is exactly what real systemd's own verification tool is
for"; `test_runbook_coverage.py:15-24`: "This is a content-presence scan,
not behavioural coverage... it does not run a single command the document
describes"). Noted here only because CR-01 is a concrete instance of exactly
the gap both files' docstrings warn a reader not to assume is closed: a
green run of either file says nothing about whether `install.sh`'s
*execution order* (beyond the one ordering pair it does check) or the
runbook's *procedure* actually works.
**Fix:** No action required beyond what CR-01 already proposes (the
`daemon-reload`-style `.index()` ordering check extended to the mkdir/chown
pair) — this entry exists to make the connection explicit for future
readers of this review.

### IN-03: `disk_warn_free_bytes` / `disk_critical_free_bytes` remain unvalidated against `archive.queue_depth` / expected write rate

**File:** `config/logger.json:52-53`, `src/telemetry/logger/config.py:166-178`
**Issue:** Both figures are explicitly documented (in `OpsConfig`'s own
docstring and `docs/runbook.md`) as chosen round numbers, not measurements —
this is already called out honestly in-repo, so this is not a new
correctness defect, just a reminder surfaced during this review that no
validation exists (nor is one possible yet) tying these thresholds to a
real full-rate session's archive growth rate.
**Fix:** None needed now; the existing docstring/runbook language already
sets the expectation to recalibrate once a real session's growth rate is
measured on the car (already tracked as an open item).

---

_Reviewed: 2026-09-30T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
