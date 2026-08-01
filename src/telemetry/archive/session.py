"""
telemetry.archive.session — session directory naming and the `.done`
marker write ordering (ARCH-05, OPS-04), built directly on
`01-RESEARCH.md` Pattern 3 — there is no in-repo precedent for either
concern (`01-PATTERNS.md`'s "No Analog Found" table).

**Session naming.** Sessions are named from UTC as `YYYYMMDD-HHMMSS` when
the clock looks plausible. The CM4 has no RTC battery, so the wall clock
can be meaningless epoch-garbage at boot — a purely time-derived name in
that state would collide across sessions and carry no real information. A
clock reporting a year before `_SANITY_FLOOR_YEAR` is treated as
implausible, and naming falls back to a monotonic counter persisted under
the archive root, zero-padded so counter-derived sessions still sort in
creation order. `SessionPaths.naming_source` records which branch produced
a given name (`NAMING_SOURCE_CLOCK` or `NAMING_SOURCE_COUNTER`), and that
value is also written into the session's `session.json` sidecar alongside
the producing config's hash, so post-session analysis can always tell a
real timestamp from a fallback and know exactly which config produced the
run. The clock itself is an injectable callable (`clock=` on `new_session`)
specifically so the fallback branch is testable without touching the
system clock.

If the counter's own persisted state file is missing or unreadable, the
starting counter is derived from the highest existing counter-named
directory already under the archive root rather than restarting at zero —
a lost state file must never cause a name collision that silently
overwrites a previous run (T-01-15).

Each session gets its own directory under the archive root — this is
OPS-04's "discrete sessions rather than one unbounded file", and it is what
makes an interrupted session identifiable afterward: a directory with an
`.mcap` file and no `.done` marker beside it is, by construction, a session
that never finished.

**`.done` marker ordering (ARCH-05).** `mark_done` takes the writer as a
required argument and raises if `writer.is_closed` is not yet true — this
makes "only after the archive writer's close-and-flush returns" a
structural precondition, not a calling convention someone can forget to
follow. The write itself: write the (empty) marker file, flush it, fsync
its own descriptor, then fsync the containing directory entry. The
directory fsync is guarded behind a `sys.platform` check —
`01-RESEARCH.md` verified this session that `os.fsync()` on a directory
file descriptor raises `PermissionError` on Windows — so the ordering
logic itself stays exercisable on the dev laptop even though the syscall
is Linux-only. The marker is never written optimistically.
"""

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from telemetry.archive.writer import ArchiveWriter

MCAP_FILENAME = "session.mcap"
DONE_FILENAME = ".done"
SIDECAR_FILENAME = "session.json"

NAMING_SOURCE_CLOCK = "clock"
NAMING_SOURCE_COUNTER = "counter"

_UTC_NAME_FORMAT = "%Y%m%d-%H%M%S"

# A clock reporting a year before this is treated as epoch-garbage rather
# than a real timestamp — the CM4 has no RTC battery and can boot with the
# wall clock at or near the Unix epoch.
_SANITY_FLOOR_YEAR = 2020

_COUNTER_PREFIX = "counter-"
_COUNTER_DIGITS = 8
_COUNTER_STATE_FILENAME = ".session_counter"


@dataclass(frozen=True)
class SessionPaths:
    """One session's on-disk layout, plus which naming source produced its
    name."""

    directory: Path
    mcap_path: Path
    done_path: Path
    session_name: str
    naming_source: str


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _is_plausible(now: datetime) -> bool:
    """A UTC year before `_SANITY_FLOOR_YEAR` means the clock has not been
    set — treat it as unusable rather than naming a session from it."""
    return now.year >= _SANITY_FLOOR_YEAR


def _counter_name(value: int) -> str:
    return f"{_COUNTER_PREFIX}{value:0{_COUNTER_DIGITS}d}"


def _highest_existing_counter(root_dir: Path) -> int:
    """Scan `root_dir` for already-created counter-named session
    directories and return the highest counter value found, or -1 if none
    exist. Used to reseed the counter when its own state file is missing
    or unreadable, so a lost state file can never cause a name collision."""
    highest = -1
    if not root_dir.exists():
        return highest
    for entry in root_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith(_COUNTER_PREFIX):
            continue
        digits = entry.name[len(_COUNTER_PREFIX) :]
        if digits.isdigit():
            highest = max(highest, int(digits))
    return highest


def _next_counter_value(root_dir: Path) -> int:
    """Read-and-increment the persisted counter state file under one open
    of that state. If it is missing or unreadable, the starting value is
    derived from the highest existing counter-named directory rather than
    zero (T-01-15) — this is what makes a lost state file safe rather than
    collision-prone."""
    root_dir.mkdir(parents=True, exist_ok=True)
    state_path = root_dir / _COUNTER_STATE_FILENAME

    current: Optional[int] = None
    if state_path.exists():
        try:
            current = int(state_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            current = None

    if current is None:
        current = _highest_existing_counter(root_dir) + 1

    state_path.write_text(str(current + 1), encoding="utf-8")
    return current


def _write_sidecar(session: "SessionPaths", config_hash: Optional[str]) -> None:
    """Record which naming source produced this session's name and which
    config produced the run, so post-session analysis never has to guess
    at either."""
    payload = {
        "session_name": session.session_name,
        "naming_source": session.naming_source,
        "config_hash": config_hash,
    }
    sidecar_path = session.directory / SIDECAR_FILENAME
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def new_session(
    root_dir,
    clock: Optional[Callable[[], datetime]] = None,
    config_hash: Optional[str] = None,
) -> SessionPaths:
    """Create a new, empty session directory under `root_dir`.

    Named from UTC as `YYYYMMDD-HHMMSS` when `clock()` (defaulting to the
    real system clock) reports a plausible year; falls back to a
    monotonic, zero-padded counter name otherwise (OPS-04, CONTEXT.md's
    locked naming decision). Creates `root_dir` itself if it does not yet
    exist. `config_hash`, if given, is recorded in the session's
    `session.json` sidecar alongside which naming source was used.
    """
    root_dir = Path(root_dir)
    now = (clock or _default_clock)()

    if _is_plausible(now):
        session_name = now.strftime(_UTC_NAME_FORMAT)
        naming_source = NAMING_SOURCE_CLOCK
    else:
        session_name = _counter_name(_next_counter_value(root_dir))
        naming_source = NAMING_SOURCE_COUNTER

    directory = root_dir / session_name
    directory.mkdir(parents=True, exist_ok=False)

    session = SessionPaths(
        directory=directory,
        mcap_path=directory / MCAP_FILENAME,
        done_path=directory / DONE_FILENAME,
        session_name=session_name,
        naming_source=naming_source,
    )
    _write_sidecar(session, config_hash)
    return session


def mark_done(session: SessionPaths, writer: ArchiveWriter) -> None:
    """Write `session.done_path` only after `writer.is_closed` is true.
    Raises `RuntimeError` if the writer has not been closed yet — never
    write the marker optimistically."""
    if not writer.is_closed:
        raise RuntimeError(
            f"refusing to write {session.done_path} — the archive writer "
            f"for session {session.session_name!r} has not been closed "
            f"(is_closed is False); ARCH-05 requires close-and-flush to "
            f"return first"
        )

    with open(session.done_path, "w", encoding="utf-8") as f:
        f.write("")
        f.flush()
        os.fsync(f.fileno())

    # Directory-entry fsync is Linux-only (verified this session:
    # os.fsync() on a directory fd raises PermissionError on Windows).
    # Guarding it here keeps the ordering logic above exercisable on the
    # dev laptop while the syscall itself is only real on Linux/the CM4.
    if sys.platform != "win32":
        dir_fd = os.open(session.directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
