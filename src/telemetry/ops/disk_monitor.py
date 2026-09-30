"""
telemetry.ops.disk_monitor -- two-stage free-space thresholds measured
against the archive root (OPS-03): `check_disk_space` bands the current
free-byte figure into `ok` / `warn` / `critical` against two configured
byte counts (`OpsConfig.disk_warn_free_bytes` / `disk_critical_free_bytes`,
`telemetry.logger.config`), so `telemetry.logger.cli` can refuse to start a
new session below critical and go `degraded` mid-run without either of
those callers needing to touch `shutil` directly.

**`shutil.disk_usage(...).free` is the honest number, verified against
CPython's own `Lib/shutil.py` this phase's research session
(03-RESEARCH.md, "Disk Space Semantics").** On Linux it is
`f_bavail * f_frsize` -- space available to an *unprivileged* user, already
excluding root-reserved blocks. That is exactly right for a service running
as a dedicated non-root systemd user (03-CONTEXT.md's locked decision), with
no adjustment needed. Separately, `total` is computed from `f_blocks` while
`used` is computed from `f_bfree` (all free blocks, including the ones
reserved for root) -- so on a real ext4 filesystem `used + free` can be
strictly less than `total`. This module therefore compares `free_bytes`
directly against the two configured byte counts and never derives a
percentage from `total`; deriving `used_percent = used / total` would be
subtly wrong on exactly the filesystem this project deploys to.

**What this module deliberately does NOT do: it never deletes, rotates, or
prunes anything.** Auto-pruning session data was rejected outright in
03-CONTEXT.md as directly contradicting this project's core value -- "no
run's data is ever lost." A full disk is a `critical` reading that refuses
a *new* session and warns loudly during one already running; it is never a
trigger to remove existing data.

The `disk_usage_fn` seam (default: the stdlib `shutil.disk_usage`) mirrors
this project's established injectable-callable convention
(`telemetry.ground.cli`'s `now_fn`, `telemetry.capture.hardware_source`'s
`sdk` injection) so this module is unit-testable on the Windows dev box
without touching the real filesystem's free space.
"""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

DISK_OK = "ok"
DISK_WARN = "warn"
DISK_CRITICAL = "critical"

# The comparison is strictly-less-than at both boundaries, so a reading
# exactly AT a threshold resolves to the better band -- "warn" at exactly
# critical_free_bytes, "ok" at exactly warn_free_bytes. See the module's
# behaviour tests for the boundary pairs this pins.
_DEFAULT_DISK_USAGE_FN = shutil.disk_usage


@dataclass(frozen=True)
class DiskReading:
    """One measurement: which path was actually measured (see
    `check_disk_space`'s ancestor-resolution note), the raw free/total byte
    counts, and the resulting band."""

    measured_path: Path
    free_bytes: int
    total_bytes: int
    state: str


def _nearest_existing_ancestor(path: Path) -> Path:
    """`path` itself if it exists, else the nearest ancestor directory that
    does. The archive root legitimately does not exist yet at first boot --
    `telemetry.archive.session.new_session` creates it -- and measuring the
    filesystem it will live on does not require the leaf directory to
    already be there. Never creates anything. `Path.parents` always
    terminates at the filesystem root (e.g. `C:\\` or `/`), which always
    exists, so this is guaranteed to return."""
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    # Unreachable: the filesystem root is always in `path.parents` and
    # always exists on a real filesystem.
    raise LookupError(f"no existing ancestor found for {path}")  # pragma: no cover


def check_disk_space(
    path,
    *,
    warn_free_bytes: int,
    critical_free_bytes: int,
    disk_usage_fn: Callable = _DEFAULT_DISK_USAGE_FN,
) -> DiskReading:
    """Resolve `path` to its nearest existing ancestor, measure that
    ancestor's filesystem exactly once via `disk_usage_fn`, and band the
    resulting `free` byte count against the two configured thresholds.

    Never raises for a non-existent `path` and never creates one. Never
    derives a percentage from `total` -- see the module docstring's note on
    why `used + free` can be less than `total` on a real Linux filesystem.
    """
    measured_path = _nearest_existing_ancestor(Path(path))
    usage = disk_usage_fn(measured_path)
    free_bytes = usage.free
    total_bytes = usage.total

    if free_bytes < critical_free_bytes:
        state = DISK_CRITICAL
    elif free_bytes < warn_free_bytes:
        state = DISK_WARN
    else:
        state = DISK_OK

    return DiskReading(
        measured_path=measured_path,
        free_bytes=free_bytes,
        total_bytes=total_bytes,
        state=state,
    )
