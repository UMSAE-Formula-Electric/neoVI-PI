"""
telemetry.ops.heartbeat -- the atomic status-file writer/reader (OPS-02)
that lets a second process answer "is the logger alive *and* capturing"
without opening a terminal on the logger itself.

**Five distinguishable states, not six.** `booting`, `waiting-for-hardware`,
`capturing`, `degraded`, `stopped-error` (`HEARTBEAT_STATES`) -- a clean
stop is signalled by the file's ABSENCE, not by a sixth state
(`03-CONTEXT.md`'s locked decision). `HeartbeatPublisher.remove()` is what
produces that absence.

**Atomic write (verified against `Doc/library/os.rst`, python/cpython 3.12
branch, this session): `os.replace()`'s rename is a POSIX guarantee, but
only within one filesystem.** `write_heartbeat` therefore creates its temp
file in the target's own parent directory -- never a fixed temp directory,
which could be a different mount (e.g. a tmpfs `/tmp` on the real image) and
make the rename cross-device and non-atomic. The temp file is named with
the writing process's pid so two writers could never collide, though this
project's locked "no separate supervisor process" decision means there is
only ever one. This atomicity claim is scoped to Linux, the deployment
target: on the Windows dev box `os.replace` still succeeds over an existing
file (which is what makes this module testable here), but the POSIX
rename() guarantee is what the car actually relies on.

**Staleness must survive a reboot boundary, not just a process restart**
(`03-RESEARCH.md` Pitfall 5, corroborating `docs.python.org/3/library/time.html`
fetched this session: *"Changed in version 3.5: the clock is now the same
for all processes"* -- `time.monotonic()` IS safely comparable across two
processes on the same boot). The danger is narrower and more dangerous than
"not comparable": the clock's reference point resets at reboot, so a
heartbeat file written on a previous boot and never cleaned up (e.g. the
systemd unit crash-looped past `StartLimitBurst`, then the whole machine
was power-cycled) can carry a `written_at_monotonic` value the *current*
boot's `time.monotonic()` cannot have produced yet -- `now < written_at`
computes a **negative** age, which a naive `age > threshold` staleness
check reads as fresh. `read_heartbeat` checks `now < written_at` explicitly,
before the ordinary threshold comparison, and reports it as its own named
reason (`clock-went-backwards`) rather than folding it into a generic
"stale" bucket -- the worst possible outcome for a health indicator is a
dead logger reading as alive, and this is the one case that could produce
that outcome silently.

`written_at_utc` is informational only, never used for the staleness
comparison: the CM4 has no RTC battery (the same fact
`telemetry.archive.session` already documents for session naming), so the
wall clock can be epoch-garbage at boot.

`written_at_monotonic` is also compared against a second, independent
`_IMPLAUSIBLE_AGE_S` bound (86400.0 seconds / 24 hours) -- a chosen
heuristic, not a measurement, picked because no plausible in-session gap
between heartbeat writes should ever approach it. It exists to catch a
heartbeat file inspected long after the process that wrote it has vanished,
a case `now < written_at` cannot catch (the age there is positive, just
enormous).
"""

import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

logger = logging.getLogger(__name__)

HEARTBEAT_SCHEMA_VERSION = 1

STATE_BOOTING = "booting"
STATE_WAITING_FOR_HARDWARE = "waiting-for-hardware"
STATE_CAPTURING = "capturing"
STATE_DEGRADED = "degraded"
STATE_STOPPED_ERROR = "stopped-error"

HEARTBEAT_STATES = (
    STATE_BOOTING,
    STATE_WAITING_FOR_HARDWARE,
    STATE_CAPTURING,
    STATE_DEGRADED,
    STATE_STOPPED_ERROR,
)

REASON_CLOCK_WENT_BACKWARDS = "clock-went-backwards"
REASON_IMPLAUSIBLE_AGE = "implausible-age"
REASON_STALE = "stale"

# A chosen heuristic (24 hours), not a measurement -- see the module
# docstring's note on why this exists alongside the reboot-boundary guard.
_IMPLAUSIBLE_AGE_S = 86400.0

_DEFAULT_THREAD_NAME = "ops-heartbeat"

# Windows-only retry budget for the final `os.replace` below (see
# `_replace_with_windows_retry`'s docstring for why this exists).
_WINDOWS_REPLACE_RETRY_ATTEMPTS = 50
_WINDOWS_REPLACE_RETRY_DELAY_S = 0.001


class HeartbeatReadError(Exception):
    """Raised for a missing file, an unreadable file, non-JSON content, or
    a payload missing `state`/`written_at_monotonic` -- `read_heartbeat`
    never guesses at a malformed or absent heartbeat."""


@dataclass(frozen=True)
class HeartbeatSnapshot:
    """What `HeartbeatPublisher` writes on its next tick. `extras` is the
    seam later plans (03-02's disk state, 03-03's hardware-wait and
    terminal states) hang additional fields off of -- this module stays
    ignorant of disk and hardware, it only carries whatever `snapshot_fn`
    returns."""

    state: str
    detail: Optional[str]
    extras: Mapping[str, object]


@dataclass(frozen=True)
class HeartbeatReading:
    """What `read_heartbeat` returns: the raw parsed payload plus the
    staleness verdict computed against the caller's own clock (`now_fn`)."""

    payload: dict
    age_s: float
    stale: bool
    staleness_reason: Optional[str]


def write_heartbeat(
    path,
    snapshot: HeartbeatSnapshot,
    *,
    now_fn: Callable[[], float] = time.monotonic,
    wall_clock_fn: Callable[[], float] = time.time,
) -> None:
    """Write `snapshot` to `path` atomically: a reader (a different
    process, by design) must never observe a partially-written file. See
    the module docstring for why the temp file is created in `path`'s own
    parent directory rather than any fixed temp location."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": HEARTBEAT_SCHEMA_VERSION,
        "state": snapshot.state,
        "detail": snapshot.detail,
        "written_at_monotonic": now_fn(),
        # Informational only -- never used for staleness (see module
        # docstring: no RTC battery, can be epoch-garbage at boot).
        "written_at_utc": datetime.fromtimestamp(
            wall_clock_fn(), tz=timezone.utc
        ).isoformat(),
        "pid": os.getpid(),
        "extras": dict(snapshot.extras),
    }
    data = json.dumps(payload, sort_keys=True).encode("utf-8")

    # Named with the writing process's pid so two writers could never
    # collide -- costs nothing to guard even though the locked "no
    # separate supervisor process" decision means there is only ever one.
    tmp_path = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    with open(tmp_path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    _replace_with_windows_retry(tmp_path, path)


def _replace_with_windows_retry(src: Path, dst: Path) -> None:
    """`os.replace(src, dst)`, with a short bounded retry scoped to Windows
    only. Observed live this session under `tests/test_ops_heartbeat.py`'s
    concurrent-reader test: NTFS can transiently deny a rename over a
    destination another thread has open at that exact instant, a race
    POSIX `rename()` has no equivalent of (confirmed against
    `Doc/library/os.rst`'s atomicity guarantee, which is what the car
    actually relies on). This retry exists purely for Windows dev-box
    testability under concurrent access -- it never changes behaviour on
    Linux, the deployment target, where the `else` branch below is the
    entire function."""
    if sys.platform != "win32":
        os.replace(src, dst)
        return

    last_exc: Optional[PermissionError] = None
    for _ in range(_WINDOWS_REPLACE_RETRY_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(_WINDOWS_REPLACE_RETRY_DELAY_S)
    raise last_exc


def read_heartbeat(
    path,
    *,
    stale_after_s: float,
    now_fn: Callable[[], float] = time.monotonic,
) -> HeartbeatReading:
    """Parse `path` and compute its staleness against `now_fn()`. Raises
    `HeartbeatReadError` for a missing file, unreadable file, non-JSON
    content, or a payload missing `state`/`written_at_monotonic` -- never
    guesses. See the module docstring for the three staleness rules, in
    the order they are checked."""
    path = Path(path)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HeartbeatReadError(f"could not read heartbeat at {path}: {exc}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HeartbeatReadError(
            f"heartbeat at {path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise HeartbeatReadError(
            f"heartbeat at {path} must be a JSON object, got {type(payload).__name__}"
        )
    if "state" not in payload:
        raise HeartbeatReadError(f"heartbeat at {path} is missing required key 'state'")
    if "written_at_monotonic" not in payload:
        raise HeartbeatReadError(
            f"heartbeat at {path} is missing required key 'written_at_monotonic'"
        )

    written_at = payload["written_at_monotonic"]
    now = now_fn()
    age_s = now - written_at

    if now < written_at:
        # The reboot-boundary regression (module docstring) -- a naive
        # `age > threshold` check would read this as fresh, which is
        # exactly wrong for a health indicator.
        stale, reason = True, REASON_CLOCK_WENT_BACKWARDS
    elif age_s > _IMPLAUSIBLE_AGE_S:
        stale, reason = True, REASON_IMPLAUSIBLE_AGE
    elif age_s > stale_after_s:
        stale, reason = True, REASON_STALE
    else:
        stale, reason = False, None

    return HeartbeatReading(
        payload=payload, age_s=age_s, stale=stale, staleness_reason=reason
    )


class HeartbeatPublisher:
    """Owns the periodic write of a `HeartbeatSnapshot` at `interval_s` on
    its own daemon thread (named `ops-heartbeat`, this project's
    established thread-naming convention).

    `snapshot_fn` is a plain mutable attribute, not fixed at construction:
    `telemetry.logger.cli` constructs this with a `booting` snapshot before
    the archive/telemetry threads exist, then reassigns `snapshot_fn` to a
    closure reading the real counters once capturing actually starts. That
    closure reads Phase 1's counter dataclasses (`FanOutCounters`,
    `TelemetryPipelineCounters`, ...) concurrently with their single writer
    thread: each individual int field read is atomic in CPython, so no torn
    value is possible, but the SET of counters read together can be
    momentarily inconsistent (e.g. `frames_submitted` incremented but a
    dependent field not yet updated). That is acceptable for a liveness
    indicator and does NOT change those counters' own documented "safe to
    read only after the writer stops" contract for the shutdown summary --
    this publisher never blocks on or waits for that guarantee.
    """

    def __init__(
        self,
        path,
        interval_s: float,
        stop_event: threading.Event,
        snapshot_fn: Callable[[], HeartbeatSnapshot],
        *,
        now_fn: Callable[[], float] = time.monotonic,
        name: str = _DEFAULT_THREAD_NAME,
    ) -> None:
        self._path = Path(path)
        self._interval_s = interval_s
        self._stop_event = stop_event
        self.snapshot_fn = snapshot_fn
        self._now_fn = now_fn
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def publish_now(self, snapshot: HeartbeatSnapshot) -> None:
        """Write one snapshot synchronously -- used for the `booting` state
        before the periodic thread exists, and by the thread's own loop."""
        write_heartbeat(self._path, snapshot, now_fn=self._now_fn)

    def join(self, timeout: Optional[float] = None) -> None:
        self._thread.join(timeout=timeout)

    def remove(self) -> None:
        """Delete the status file, tolerating its absence -- the file's
        absence is what says 'the logger is not running' (module
        docstring), so a clean shutdown calls this exactly once."""
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass

    def _run(self) -> None:
        # Waits first, writes second: the initial `booting` write is the
        # caller's explicit `publish_now` call before `start()`, not this
        # loop's first iteration.
        while not self._stop_event.wait(timeout=self._interval_s):
            self.publish_now(self.snapshot_fn())
