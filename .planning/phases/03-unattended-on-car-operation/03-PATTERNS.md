# Phase 3: Unattended On-Car Operation - Pattern Map

**Mapped:** 2026-08-09
**Files analyzed:** 15 (new) + 3 (modified)
**Analogs found:** 13 / 15 new files have a strong in-repo analog; 2 (`deploy/telemetry-logger.service`,
`deploy/install.sh`) and `docs/runbook.md` have no analog for the artifact *type* itself (documented
below, not forced).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/telemetry/ops/config.py` | config | CRUD (parse/validate) | `src/telemetry/logger/config.py` | exact |
| `config/logger.json` (gains `ops` section) | config | CRUD | itself (extend in place) | exact |
| `src/telemetry/ops/heartbeat.py` (writer) | service | file-I/O | `src/telemetry/archive/session.py` (`mark_done`) + `src/telemetry/capture/fanout.py` (`FanOutCounters`) | role-match |
| `src/telemetry/ops/heartbeat.py` (reader) | utility | file-I/O | `src/telemetry/archive/reader.py` (read-side companion to a writer) | role-match |
| `src/telemetry/ops/disk_monitor.py` | utility | transform | `src/telemetry/logger/config.py` (injectable-callable/validation style) | role-match |
| `src/telemetry/ops/hardware_wait.py` | service | event-driven (retry/poll) | `src/telemetry/capture/hardware_source.py` (`HardwareFrameSource.open`/SDK exception handling) | exact |
| `src/telemetry/ops/led.py` | provider | request-response (no-op) | `src/telemetry/link/base.py` (`Link` Protocol) | exact |
| `src/telemetry/ops/cli.py` (`telemetry-status`) | route/CLI | request-response | `src/telemetry/ground/cli.py` (health-line CLI) + `src/telemetry/logger/cli.py` (arg-parsing/signal-handling shape) | exact |
| `src/telemetry/logger/config.py` (extended) | config | CRUD | itself | exact |
| `src/telemetry/logger/cli.py` (extended: publish heartbeat, startup disk check) | controller | event-driven | itself | exact |
| `deploy/telemetry-logger.service` | config | — | none in-repo (new artifact type) | no analog |
| `deploy/install.sh` | utility | file-I/O | none in-repo (new artifact type) | no analog |
| `docs/runbook.md` | — (doc) | — | `docs/power-pull-test.md` (closest doc analog; different purpose) | partial |
| `tests/test_ops_heartbeat.py` | test | file-I/O | `tests/test_archive_crash_recovery.py` style + `tests/test_hardware_source.py` fake-SDK style | role-match |
| `tests/test_ops_disk_monitor.py` | test | transform | `tests/test_logger_config.py` (injected-callable fixture style) | role-match |
| `tests/test_ops_hardware_wait.py` | test | event-driven | `tests/test_hardware_source.py` (fake SDK, `sdk.RuntimeError`) | exact |
| `tests/test_ops_cli.py` | test | request-response | `tests/test_ground_cli.py` (if present) or `tests/test_logger_cli.py` | role-match |
| `tests/test_deploy_unit_file.py` | test | transform (structural lint) | none in-repo (new artifact type) | no analog |
| `tests/test_runbook_coverage.py` | test | transform (content-presence) | none in-repo (new artifact type) | no analog |

## Pattern Assignments

### `src/telemetry/ops/config.py` (config, CRUD)

**Analog:** `src/telemetry/logger/config.py` (full file read, 471 lines)

**Imports pattern** (lines 33-39):
```python
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple
```

**Frozen-dataclass-per-block pattern** (lines 94-168): every config section is its own
`@dataclass(frozen=True)` (`ArchiveConfig`, `TelemetryConfig`, `LinkConfig`...), aggregated into
one top-level frozen dataclass (`LoggerConfig`). The new `ops` section should be its own
`OpsConfig` frozen dataclass (thresholds, heartbeat path, cadence, stale_after_s), either merged
into `LoggerConfig` directly (extend `REQUIRED_TOP_LEVEL_KEYS` with `"ops"`, add an `ops:
OpsConfig` field) — matching CONTEXT.md's instruction that this MUST extend the existing loader,
not introduce a second mechanism.

**Fail-closed key-diffing pattern** (lines 206-219, reused per block):
```python
def _diff_keys(value: object, required: set, block_name: str) -> None:
    """Diff `value`'s keys against `required` in both directions, so unknown
    keys and missing keys each raise separately and each name the offending
    key -- the shared shape every per-block parser starts from."""
    if not isinstance(value, dict):
        raise LoggerConfigError(f"{block_name} must be a JSON object, got {value!r}")
    keys = set(value.keys())
    unknown = keys - required
    if unknown:
        raise LoggerConfigError(f"unknown key(s) in {block_name}: {sorted(unknown)}")
    missing = required - keys
    if missing:
        raise LoggerConfigError(f"{block_name} missing required key(s): {sorted(missing)}")
```
Write `_parse_ops(value) -> OpsConfig` following the exact shape of `_parse_archive`/`_parse_telemetry`
(lines 267-336): `_diff_keys` first, then per-field `_require_positive_number`/`_require_positive_int`/
`_require_non_empty_str` (lines 186-204), then construct the dataclass. Add `"ops"` to
`REQUIRED_TOP_LEVEL_KEYS` (line 41-49) and call `_parse_ops(raw["ops"])` inside `load_logger_config`
(around line 426) as a sibling of `archive = _parse_archive(raw["archive"])`.

**Error type** (lines 89-91): reuse `LoggerConfigError` directly — do not invent `OpsConfigError`.
CONTEXT.md and RESEARCH.md both say the `ops` section extends this exact loader/exception, not a
parallel one.

**Path resolution** (lines 84-86, 280-290): repo-relative paths resolved via
`_REPO_ROOT = Path(__file__).resolve().parents[N]`, never hardcoded absolute — the heartbeat path
default should follow the same `(_REPO_ROOT / value).resolve()` convention used for `archive.root_dir`.

---

### `src/telemetry/ops/heartbeat.py` (service — writer half, file-I/O)

**Analog for atomic-write discipline:** `src/telemetry/archive/session.py` `mark_done` (lines 196-219, read above)

```python
def mark_done(session: SessionPaths, writer: ArchiveWriter) -> None:
    """Write `session.done_path` only after `writer.is_closed` is true.
    Raises `RuntimeError` if the writer has not been closed yet — never
    write the marker optimistically."""
    if not writer.is_closed:
        raise RuntimeError(...)
    with open(session.done_path, "w", encoding="utf-8") as f:
        f.write("")
        f.flush()
        os.fsync(f.fileno())
    # Directory-entry fsync is Linux-only (verified: os.fsync() on a
    # directory fd raises PermissionError on Windows). Guarded so the
    # ordering logic is exercisable on the dev laptop while the syscall
    # itself is only real on Linux/the CM4.
    if sys.platform != "win32":
        dir_fd = os.open(session.directory, os.O_RDONLY)
        try:
            ...
```
**Apply directly:** the heartbeat's temp-write-then-`os.replace` (RESEARCH.md Pattern 3) should
follow this file's `sys.platform != "win32"` guard convention for anything Linux-only (e.g. directory
fsync, if added) so the writer stays testable on the Windows dev box exactly like `mark_done` is.

**Counters-read pattern (do not re-derive):** `src/telemetry/capture/fanout.py` `FanOutCounters`
(lines 87-109, read above) and `HardwareSourceCounters` (`hardware_source.py` lines 114-124):
```python
@dataclass
class HardwareSourceCounters:
    """CAP-06's counters. Written only by the thread calling
    captured_frames()/frames(); safe to read from other threads only
    after that thread has stopped -- the same single-writer rationale as
    telemetry.capture.fanout.FanOutCounters."""
    poll_count: int = 0
    hardware_error_count: int = 0
    poll_exception_count: int = 0
    excluded_message_count: int = 0
```
The heartbeat writer must accept these existing counters objects (`FanOutCounters`,
`TelemetryPipelineCounters`, `HardwareSourceCounters`) as constructor/call arguments and read fields
off them for its payload — never re-count frames independently. Same "single-writer, safe cross-
thread read after the writer stops" caveat applies to the heartbeat's own state if driven from the
capture-loop thread.

**Module docstring style** (mirrors `telemetry/logger/config.py` lines 1-31 and
`telemetry/capture/hardware_source.py` lines 1-58): open with a paragraph naming which phase/req
IDs this satisfies (OPS-02), what it deliberately does NOT do, and cite the concrete verified fact
driving the design (`os.replace` same-filesystem atomicity, `time.monotonic()` reboot-boundary
caveat) inline, the way `hardware_source.py` cites the `ics.RuntimeError` MRO fact.

---

### `src/telemetry/ops/hardware_wait.py` (service, event-driven retry/poll)

**Analog:** `src/telemetry/capture/hardware_source.py` (full file read, 273 lines) — this is the
strongest exact match in the whole phase.

**SDK injection + lazy import pattern** (lines 73-81):
```python
def _default_sdk():
    """Lazily imports and returns the real `ics` module. Imported only here,
    only when no SDK object is injected -- so constructing a
    HardwareFrameSource with an injected fake never touches the SDK, and
    merely importing this module never does either."""
    import ics
    return ics
```
`wait_for_hardware` must accept an `sdk: Optional[object] = None` parameter with the identical
lazy-default pattern, so `telemetry.ops.hardware_wait` is importable and unit-testable on Windows
with zero SDK contact, exactly like this module.

**Catch the SDK's own exception type, never the builtin** (lines 48-57, 157-163, 229-237): every
SDK call in `HardwareFrameSource` is wrapped as `except self._sdk.RuntimeError`, never bare
`RuntimeError`. `wait_for_hardware`'s `except sdk.RuntimeError:` (RESEARCH.md Pattern 4) must follow
this identically — copy the surrounding comment verbatim, this is a previously-hit, already-
documented project failure mode:
```python
try:
    devices = self._sdk.find_devices()
except self._sdk.RuntimeError as exc:
    ...
```

**`open()` fail-fast device selection** (lines 165-208): shows the exact call shape
(`sdk.find_devices()` → empty check → serial match) that `wait_for_hardware`'s retry loop wraps in
a `while` instead of raising immediately. Reuse `find_devices()` as the single hardware-presence
check — RESEARCH.md's Pattern 4 already sketches this; this analog is where the emptytuple-vs-
exception duality (docstring lines 41-57) is documented and should be cited/preserved, not
re-derived.

**Stop-event responsiveness** (lines 210-224): `self._stop_event.wait(timeout=self._poll_interval_s)`
inside the loop — `wait_for_hardware`'s backoff sleep must use `stop_event.wait(timeout=...)`, never
a bare `time.sleep`, so `stop_event.set()` interrupts promptly (T-01-29-style requirement, reused
verbatim from this analog).

---

### `src/telemetry/ops/led.py` (provider, request-response no-op)

**Analog:** `src/telemetry/link/base.py` (full file read, 22 lines) — exact structural match, already
cited correctly in RESEARCH.md Pattern 6.

```python
from typing import Optional, Protocol

class Link(Protocol):
    """A synchronous, swappable byte-pipe transport. The transport owns its
    own thread (if it needs one) -- no asyncio, per 01-CONTEXT.md."""
    def send(self, data: bytes) -> None: ...
    def recv(self, timeout: Optional[float] = None) -> Optional[bytes]: ...
    def close(self) -> None: ...
```
**Apply directly:** `LedIndicator(Protocol)` with `set_state(self, state: str) -> None: ...` and
`close(self) -> None: ...`, docstring naming which concrete implementations exist/are deferred —
mirror `Link`'s docstring style (name the concrete implementations and which phase adds each one).
`NullLedIndicator` is the `LoopbackLink`-equivalent trivial default — check
`src/telemetry/link/loopback.py` if a second, slightly-more-concrete example of "trivial Protocol
implementation" docstring style is wanted, but `Link` alone is sufficient.

---

### `src/telemetry/ops/cli.py` (`telemetry-status`, route/CLI, request-response)

**Analog 1 — health-line cadence:** `src/telemetry/ground/cli.py` `run_consumer_loop` (lines
364-419, read above):
```python
now = now_fn()
if now - last_health_t >= health_interval_s:
    _emit_health(deframer.counters, counters, elapsed_s=now - start_t)
    last_health_t = now
```
Uses an injectable `now_fn: Callable[[], float] = time.monotonic` — `telemetry.ops.cli`'s staleness
check should take the identical injectable-clock seam so tests can fake elapsed time without real
sleeps, matching this file's own convention.

**Analog 2 — arg parsing / signal / entry-point shape:** `src/telemetry/logger/cli.py` `_parse_args`
(lines 116-175) and `main` (lines 484-523). Copy the `argparse.ArgumentParser(description=...)` +
`parser.add_argument("--log-level", ...)` shape verbatim; `telemetry-status` is a read-only,
short-lived CLI so it does not need `logger/cli.py`'s signal-handler-before-construction ordering,
but it should reuse `_configure_logging` (lines 99-104) verbatim for consistency (stderr for humans,
stdout reserved for the one machine-readable line — same "two outputs" discipline documented in the
module docstring, lines 46-49).

**Exit-code convention** (lines 495-520): `raise SystemExit(1) from exc` on any recoverable
configuration/read failure — `telemetry-status` should exit non-zero and print a clear stderr
message rather than raising a raw traceback when the heartbeat file is missing or malformed.

---

### `src/telemetry/logger/cli.py` (extended: publish heartbeat at 1 Hz, startup disk check)

**This is the existing file being modified, not a new analog target.** Two integration points,
both already read above:

1. **Startup disk check** slots into `main()` (lines 484-523) between config load (line 496) and
   `_run_session` (line 517) — call `check_disk_space(config.archive.root_dir, ...)` here and
   `raise SystemExit(1)` on `critical`, following the exact `try/except LoggerConfigError:
   logger.error(...); raise SystemExit(1) from exc` shape already used at lines 497-499 and 513-515.
2. **Heartbeat publish** needs a periodic call site. `_run_session`'s existing watchdog-timer pattern
   (lines 409-418) is the closest in-file precedent for "an independent timer drives something at a
   cadence separate from the main capture loop":
   ```python
   watchdog = threading.Timer(args.duration_s, stop_event.set)
   watchdog.daemon = True
   watchdog.name = "logger-duration-watchdog"
   watchdog.start()
   ```
   A 1 Hz heartbeat writer should use the same `threading.Timer`-rescheduling-itself idiom (or a
   small dedicated daemon thread loop keyed off `stop_event.wait(timeout=1.0)`, matching
   `HardwareFrameSource.captured_frames()`'s poll-loop shape) — name the thread explicitly
   (`name="ops-heartbeat"`) per this project's established thread-naming convention (`name="capture"`,
   `name="writer"` per `.claude/CLAUDE.md`).
3. **Shutdown ordering constraint:** the module docstring (lines 38-49) fixes a strict shutdown order
   (stop capture → drain archive → close link → close writer → `mark_done` only if clean). The
   heartbeat/disk-check additions must not be inserted inside that ordered block — they observe
   state, they do not participate in the archive lifecycle. Final heartbeat state on exit (e.g.
   `stopped-error` if `archive_closed_cleanly` is `False`, mirroring the `_log_human_summary`
   branch at lines 315-324) should be written *after* the existing summary logic, not interleaved
   with it.

---

## Shared Patterns

### Fail-closed config, named exception
**Source:** `src/telemetry/logger/config.py` `LoggerConfigError`, `_diff_keys`, `_require_*` helpers (lines 89-219)
**Apply to:** `src/telemetry/ops/config.py` (`ops` section parsing) — every malformed `ops.*` key
must raise `LoggerConfigError` naming the offending key/value; never silently default a threshold.

### `sdk.RuntimeError`, never the builtin
**Source:** `src/telemetry/capture/hardware_source.py` lines 48-57, 229-237 (module docstring +ircode)
**Apply to:** `src/telemetry/ops/hardware_wait.py` — the single most-repeated, previously-hit
project failure mode; copy the catch shape and the explanatory comment, do not paraphrase it away.

### `typing.Protocol`, minimal method surface, injectable-fake-friendly
**Source:** `src/telemetry/link/base.py` (`Link`, 3 methods), same convention in
`src/telemetry/wire/frame_source.py` (`FrameSource`, per RESEARCH.md)
**Apply to:** `src/telemetry/ops/led.py` (`LedIndicator`) — 2-3 methods, no more.

### Repo-relative path resolution
**Source:** `src/telemetry/logger/config.py` lines 84-86, 171-175, 280-290
**Apply to:** any new path default in `src/telemetry/ops/config.py` (heartbeat status-file path) —
`_REPO_ROOT = Path(__file__).resolve().parents[N]`, never a hardcoded absolute path.

### Module-level logger, CLI-only logging configuration
**Source:** `src/telemetry/logger/cli.py` lines 92, 99-104 (`_configure_logging`); reiterated in
`.claude/CLAUDE.md`
**Apply to:** every new `telemetry.ops.*` module gets `logger = logging.getLogger(__name__)` at
module scope; only `telemetry/ops/cli.py`'s `main()` calls `logging.basicConfig`.

### Injectable-callable seam for OS-touching calls
**Source:** `src/telemetry/ground/cli.py`'s `now_fn: Callable[[], float] = time.monotonic` parameter
(line 374); `HardwareFrameSource`'s `sdk: Optional[object] = None` injection (`hardware_source.py`
line 140)
**Apply to:** `src/telemetry/ops/disk_monitor.py` (`disk_usage_fn: Callable = shutil.disk_usage`) and
`src/telemetry/ops/heartbeat.py` (a `now_fn=time.monotonic` seam for the staleness check) — the
established way this project keeps OS-touching code unit-testable on the Windows dev box without a
new test-only branch inside the production function.

### Dataclass counters, single-writer convention
**Source:** `src/telemetry/capture/fanout.py` `FanOutCounters` (lines 87-109), `HardwareSourceCounters`
(`hardware_source.py` lines 114-124), `TelemetryPipelineCounters` (`logger/pipeline.py:98`, not read
this session but named identically in RESEARCH.md and CONTEXT.md)
**Apply to:** the heartbeat writer must *consume* these dataclasses' fields, never define a fourth,
overlapping counters class.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `deploy/telemetry-logger.service` | config (systemd unit) | — | No `deploy/` directory or any systemd/process-supervision artifact exists in this repo today; this phase creates the artifact type from scratch. Use RESEARCH.md's verified Pattern 1 (the `systemd-analyze verify`-clean unit text) directly rather than inventing a local precedent. |
| `deploy/install.sh` | utility (install script) | file-I/O | Same — no existing shell install script in-repo to pattern-match against. RESEARCH.md Pattern 2 is the source of truth. |
| `tests/test_deploy_unit_file.py` | test | transform (structural lint) | No existing unit-file or INI-adjacent parser/test in this repo; RESEARCH.md's Pitfall 2 explicitly rules out `configparser` and specifies a hand-rolled line checker — there is nothing in-repo to copy the checker's shape from. |
| `tests/test_runbook_coverage.py` | test | transform (content-presence) | No existing "documentation content-presence" test in this repo (`docs/power-pull-test.md` has no corresponding test file). Write as a plain text-scan test (`assert state_name in runbook_text for state_name in HEARTBEAT_STATES`), no analog needed — this is a simple pattern, not a risky one. |
| `docs/runbook.md` | documentation | — | `docs/power-pull-test.md` (read, lines 1-40) is the closest *document* in the repo but serves a different purpose (a single bench procedure for one prior phase's ARCH-03 requirement, not a general operating runbook covering start/verify/retrieve/troubleshoot). Useful for house style (direct address, "why this matters" framing before the steps, req-ID citations in the opening paragraph) but not a structural template for `runbook.md`'s multi-section, state-table-driven content. Say so plainly rather than force a match. |

## Metadata

**Analog search scope:** `src/telemetry/logger/`, `src/telemetry/capture/`, `src/telemetry/link/`,
`src/telemetry/archive/`, `src/telemetry/ground/`, `docs/`, `config/`, `tests/` (grep only, not
individually read — file names confirm no `deploy/` precedent and no existing `test_ops_*`/
`test_deploy_*` files).
**Files scanned/read in full or targeted ranges:** `src/telemetry/logger/config.py` (471 lines,
full), `src/telemetry/link/base.py` (22 lines, full), `src/telemetry/capture/hardware_source.py`
(273 lines, full), `src/telemetry/logger/cli.py` (524 lines, full), `src/telemetry/ground/cli.py`
(lines 360-424, targeted), `src/telemetry/archive/session.py` (lines 190-220, targeted),
`src/telemetry/capture/fanout.py` (lines 80-110, targeted), `src/telemetry/archive/writer.py`
(grep only — `records_written`/`is_closed`/`close()` line numbers confirmed at 49, 84, 118, 127,
134, 171, 192, 196), `docs/power-pull-test.md` (lines 1-40), `config/logger.json` (full, 49 lines).
**Pattern extraction date:** 2026-08-09
