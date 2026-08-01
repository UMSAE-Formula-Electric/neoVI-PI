"""
telemetry.archive.session — session directory naming and the `.done`
marker write ordering (ARCH-05, OPS-04), built directly on
`01-RESEARCH.md` Pattern 3 — there is no in-repo precedent for either
concern (`01-PATTERNS.md`'s "No Analog Found" table).

**Session naming.** For this tracer, sessions are named from UTC as
`YYYYMMDD-HHMMSS`; `01-05` adds the monotonic-counter fallback the CM4
needs because it boots with no RTC battery (the wall clock can be
epoch-garbage at boot). `SessionPaths.naming_source` records which of the
two produced a given name, so post-session analysis can tell a real
timestamp from a fallback — for this plan it is always `"utc"`.

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

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from telemetry.archive.writer import ArchiveWriter

MCAP_FILENAME = "session.mcap"
DONE_FILENAME = ".done"


@dataclass(frozen=True)
class SessionPaths:
    """One session's on-disk layout, plus which naming source produced its
    name."""

    directory: Path
    mcap_path: Path
    done_path: Path
    session_name: str
    naming_source: str


def new_session(root_dir) -> SessionPaths:
    """Create a new, empty session directory under `root_dir`, named from
    UTC as `YYYYMMDD-HHMMSS`. Creates `root_dir` itself if it does not yet
    exist."""
    root_dir = Path(root_dir)
    session_name = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    directory = root_dir / session_name
    directory.mkdir(parents=True, exist_ok=False)

    return SessionPaths(
        directory=directory,
        mcap_path=directory / MCAP_FILENAME,
        done_path=directory / DONE_FILENAME,
        session_name=session_name,
        naming_source="utc",
    )


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
