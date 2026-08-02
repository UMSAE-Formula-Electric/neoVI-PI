---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
reviewed: 2026-08-02T00:00:00Z
depth: standard
files_reviewed: 40
files_reviewed_list:
  - config/logger.json
  - docs/power-pull-test.md
  - src/telemetry/archive/__init__.py
  - src/telemetry/archive/reader.py
  - src/telemetry/archive/record.py
  - src/telemetry/archive/runner.py
  - src/telemetry/archive/session.py
  - src/telemetry/archive/writer.py
  - src/telemetry/capture/__init__.py
  - src/telemetry/capture/fanout.py
  - src/telemetry/capture/hardware_source.py
  - src/telemetry/capture/replay_source.py
  - src/telemetry/framing/__init__.py
  - src/telemetry/framing/cobs_frame.py
  - src/telemetry/framing/crc16.py
  - src/telemetry/framing/errors.py
  - src/telemetry/ground/__init__.py
  - src/telemetry/ground/cli.py
  - src/telemetry/ground/deframe.py
  - src/telemetry/link/__init__.py
  - src/telemetry/link/base.py
  - src/telemetry/link/loopback.py
  - src/telemetry/link/udp.py
  - src/telemetry/logger/__init__.py
  - src/telemetry/logger/cli.py
  - src/telemetry/logger/config.py
  - src/telemetry/logger/pipeline.py
  - src/telemetry/measure/cli.py
  - src/telemetry/wire/batcher.py
  - tests/conftest.py
  - tests/crash_writer_child.py
  - tests/test_archive_crash_recovery.py
  - tests/test_archive_writer.py
  - tests/test_end_to_end.py
  - tests/test_fanout.py
  - tests/test_framing.py
  - tests/test_hardware_source.py
  - tests/test_link.py
  - tests/test_logger_cli_smoke.py
  - tests/test_logger_config.py
  - tests/test_replay_source.py
  - tests/test_session.py
  - tests/test_soak.py
findings:
  critical: 1
  warning: 4
  info: 2
  total: 7
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-08-02T00:00:00Z
**Depth:** standard
**Files Reviewed:** 40 (28 source + 1 config/1 doc + 13 tests reviewed for reliability/scope reasons)
**Status:** issues_found

## Summary

This phase's implementation is unusually well-documented and, for the most
part, lives up to its own stated invariants: the archive/telemetry
divergence (CAP-03/CAP-04), the COBS+CRC framing order (LINK-01), the
crash-recovery reader's non-default `mcap` configuration, and the
Windows/Linux fsync split are all correctly implemented and covered by
targeted tests that pin the exact failure modes the docstrings describe.

The one finding that matters is `CR-01`: the `.done` marker — the single
signal this project uses everywhere (docs, `is_session_complete`, the
planned Phase 8 sync) to mean "this session's archive is complete and
trustworthy" — can be written even when `FanOut.submit()` already recorded
an `archive_overflow` (a documented, fatal, frames-were-dropped condition).
The shutdown gate in `telemetry.logger.cli._run_session` only checks
`archive_write_failure`, not `archive_overflow`, so a session that
structurally lost frames via CAP-03's own "fatal" overflow path still exits
0 and gets marked done. This directly contradicts CAP-03's stated purpose
("archive queue never drops... a full queue is fatal") and ARCH-05's
contract for what `.done` is supposed to guarantee.

The remaining findings are narrower: an unsynchronized cross-thread counter
write that can silently under-report the archive high-water mark, a
critical layout-divergence guard implemented as a bare `assert` (stripped
under `python -O`), a generator whose documented memory-safety cap only
fires if the caller fully drains it, and a `Link` implementation asymmetry
between `UdpLink.recv()` and `LoopbackLink.recv()` after `close()`.

Findings pre-authorized by the task's domain context (drop-oldest telemetry
queue, CRC-inside-COBS, the unconfirmed `TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED`
constant, and the fsync/flush conservatism) were treated as intentional and
are not repeated here.

## Critical Issues

### CR-01: `archive_overflow` does not prevent the `.done` marker or a zero exit code

**File:** `src/telemetry/logger/cli.py:444-461`
**Issue:**

`FanOut.submit()` (`src/telemetry/capture/fanout.py:144-158`) treats a full
archive queue as fatal by design — CAP-03's entire point: "archive queue
never drops... a full queue is fatal by locked decision... logs at
critical severity, sets the overflow flag, sets the stop event, and
returns." At least one frame that hit this path is *never archived* — it
is not queued, not written, not recoverable.

But `_run_session`'s shutdown gate for whether to call `mark_done` (and for
the process exit code) only inspects `archive_write_failure`, never
`archive_overflow`:

```python
archive_closed_cleanly = False
try:
    writer.close()
    archive_closed_cleanly = not fan_out.counters.archive_write_failure   # <-- archive_overflow ignored
except Exception:
    logger.critical("archive writer failed to close cleanly", exc_info=True)

if archive_closed_cleanly:
    mark_done(session, writer)
    logger.info("session %s marked done", session.session_name)
```

Since the `ArchiveWriter` itself never saw an I/O failure (the frame was
lost *before* it ever reached the writer, at the fan-out layer), `writer.close()`
succeeds and `archive_write_failure` stays `False`. `archive_closed_cleanly`
therefore evaluates `True`, `mark_done()` writes the `.done` marker, the
human/JSON summary reports `"archive_marked_done": true`, and
`_run_session` returns exit code `0` — even though the session structurally
lost data.

This is exactly the scenario `telemetry.archive.session.is_session_complete`
and `docs/power-pull-test.md` both document as the reason `.done` exists:
"a directory with an `.mcap` file and no `.done` marker beside it is, by
construction, a session that never finished." A downstream consumer that
trusts `.done` alone (the documented contract for the Phase 8 SYNC-02 sync
decision referenced in `telemetry/capture/fanout.py`'s own module
docstring, or a supervisor watching this process's exit code per
`telemetry.logger.cli`'s own docstring: "Phase 3's unattended-boot work
supervises this one process") will treat a session with silently dropped
archive frames as complete and safe to sync/finalize.

Note `_log_human_summary` *does* still log a `critical` line naming
`archive_overflow=True` alongside `archive_marked_done=True` — so a human
watching stderr in real time has a chance to notice — but nothing
structural (the marker file, the exit code, or `is_session_complete()`)
reflects it.

**Fix:**
```python
archive_closed_cleanly = False
try:
    writer.close()
    archive_closed_cleanly = (
        not fan_out.counters.archive_write_failure
        and not fan_out.counters.archive_overflow
    )
except Exception:
    logger.critical("archive writer failed to close cleanly", exc_info=True)

if archive_closed_cleanly:
    mark_done(session, writer)
    logger.info("session %s marked done", session.session_name)
else:
    logger.warning(
        "session %s left WITHOUT a .done marker -- the archive did not "
        "close cleanly (archive_write_failure=%s archive_overflow=%s)",
        session.session_name,
        fan_out.counters.archive_write_failure,
        fan_out.counters.archive_overflow,
    )
```
Also update `_run_session`'s docstring ("Returns... 1 if the archive did
not close cleanly") and add a regression test that drives `FanOut.submit()`
into overflow before shutdown and asserts no `.done` marker is written and
the process exits non-zero.

## Warnings

### WR-01: Unsynchronized cross-thread write to `FanOutCounters.archive_high_water_mark`

**File:** `src/telemetry/capture/fanout.py:161-163`, `src/telemetry/archive/runner.py:112-115`
**Issue:**

`telemetry.capture.fanout`'s own module docstring states the threading
invariant this whole package relies on for lock-free counter access:
"`FanOutCounters` is written only by the capture thread that calls
`submit()` and is read by other threads only after that capture thread has
stopped... so no lock guards it."

That invariant is violated for exactly one field. `ArchiveRunner` is
constructed with the *same* `FanOutCounters` instance
(`telemetry/logger/cli.py:356-361`: `ArchiveRunner(..., counters=fan_out.counters, ...)`)
and, on its own non-daemon thread, mutates it too:

```python
# archive/runner.py, running on the archive-writer thread, concurrently
# with FanOut.submit() running on the capture thread for the entire run:
def _record_high_water_mark(self) -> None:
    self._counters.archive_high_water_mark = max(
        self._counters.archive_high_water_mark, self._archive_queue.qsize()
    )
```
```python
# fanout.py, running on the capture thread:
self.counters.archive_high_water_mark = max(
    self.counters.archive_high_water_mark, self.archive_queue.qsize()
)
```

Both threads perform this read-max-write on the same attribute for the
entire duration of a session (the archive runner starts before capture
begins and both run concurrently until shutdown). This is a classic
read-modify-write race with no lock: thread A can read the old value,
thread B can read the same old value and write a smaller `max()` result
*after* A has already written a larger one, silently regressing the
recorded high-water mark below the true peak. `test_high_water_marks_track_deepest_occupancy_and_never_decrease`
(`tests/test_fanout.py`) only exercises `FanOut` in isolation and does not
catch this, since it never runs a concurrent `ArchiveRunner` against the
same counters object.

**Fix:** Either guard the increment with a small `threading.Lock` shared
between `FanOut` and `ArchiveRunner`, or — simpler and avoiding new lock
plumbing — stop sharing the field: give `ArchiveRunner` its own
high-water-mark counter (consumer-side queue depth as observed at drain
time) and report both figures separately in the summary, e.g.
`archive_producer_high_water_mark` / `archive_consumer_high_water_mark`,
merged with `max()` only after `join()` (a safe point, since both threads
have then stopped).

### WR-02: Critical layout-divergence guard implemented as a bare `assert`

**File:** `src/telemetry/wire/batcher.py:43-47`
**Issue:**

```python
assert BATCH_HEADER_STRUCT.size == overhead.BATCH_HEADER_BYTES, (
    f"BATCH_HEADER_STRUCT.size={BATCH_HEADER_STRUCT.size} does not match "
    f"overhead.BATCH_HEADER_BYTES={overhead.BATCH_HEADER_BYTES} — the real "
    f"batch header layout and the analytic overhead model have diverged"
)
```

The module's own docstring calls this "01-CRITICAL-CONSTRAINTS #4" — the
one thing keeping the real on-wire batch header size and the analytic
overhead model (used for the Phase 0 compression-ratio gate's own
pass/fail numbers) from silently diverging. A bare `assert` is stripped
entirely when Python runs with `-O`/`PYTHONOPTIMIZE=1` (`python -O -m
telemetry.logger.cli ...`), which would silently disable exactly the
protection this line exists for, with no runtime signal that it happened.
This is otherwise the only bare `assert` used for a production invariant
anywhere in the reviewed files (every other invariant check in this phase
correctly raises a named exception instead).

**Fix:**
```python
if BATCH_HEADER_STRUCT.size != overhead.BATCH_HEADER_BYTES:
    raise RuntimeError(
        f"BATCH_HEADER_STRUCT.size={BATCH_HEADER_STRUCT.size} does not match "
        f"overhead.BATCH_HEADER_BYTES={overhead.BATCH_HEADER_BYTES} — the real "
        f"batch header layout and the analytic overhead model have diverged"
    )
```

### WR-03: `Deframer.feed()`'s T-01-05 buffer-overflow cap only runs if the generator is fully drained

**File:** `src/telemetry/ground/deframe.py:79-104`
**Issue:**

`feed()` is a generator (it `yield`s recovered batches). The
`buffer_overflow_count`/eviction logic that is supposed to bound memory
growth for an undelimited stream lives *after* the `while True:` loop, as
tail code in the generator body:

```python
def feed(self, data: bytes) -> Iterator[List[RawFrame]]:
    self._buffer.extend(data)
    while True:
        ...
        yield recovered
    if len(self._buffer) > self._max_buffer_bytes:   # <-- only reached once the
        ...                                            #     generator is exhausted
        self._buffer = bytearray()
```

Generator tail code after the last `yield` only executes once the
generator is iterated to exhaustion (`StopIteration` raised) — a caller
that only partially consumes the generator (e.g. `next(deframer.feed(data))`,
or a `for ... in deframer.feed(data): break`) will silently skip the
overflow check for that call, defeating T-01-05's documented guarantee
("a stream that never presents a delimiter has its pending bytes discarded...
rather than growing memory without bound"). The one production caller today
(`telemetry.ground.cli.run_consumer_loop`) happens to always fully drain
the generator with a plain `for` loop, and every test in
`tests/test_framing.py` does the same via `list(...)`, so this is not
currently triggered — but nothing in the API signals the obligation, and a
future caller (or a refactor that adds an early exit for performance) could
reintroduce unbounded buffer growth with no test catching it.

**Fix:** Move the overflow check to run unconditionally on every `feed()`
call regardless of how much of the generator a caller consumes — e.g.
perform the delimiter-scan-and-yield into a local list first, then check/
reset the buffer, then yield from the list; or check-and-trim the buffer
at the *start* of `feed()` (before scanning for delimiters) so it runs
before the first `yield` is ever reached rather than after the last one.

### WR-04: `UdpLink.recv()` does not guard against a closed socket, unlike `LoopbackLink.recv()`

**File:** `src/telemetry/link/udp.py:92-118`, `src/telemetry/link/loopback.py:36-40`
**Issue:**

`tests/test_link.py`'s own module docstring states the design goal
explicitly: "One shared test suite, parameterised over both `Link`
implementations... so LINK-03's 'no change to the layers above' is
demonstrated by the same assertions passing against both." `01-08`'s
deviation note in `loopback.py` already harmonized `send()` after `close()`
across both implementations (`RuntimeError` on both). `recv()` was not
given the same treatment:

- `LoopbackLink.recv()` after `close()` still works: it reads from the
  internal `queue.Queue`, which is untouched by `close()`, and returns
  `None` on timeout exactly as before.
- `UdpLink.recv()` after `close()` calls `self._sock.settimeout(timeout)`
  and `self._sock.recvfrom(...)` on an already-closed socket, which raises
  `OSError: [Errno 9] Bad file descriptor` (or the Windows equivalent) —
  an exception type `recv()`'s own `except OSError` branch does catch, but
  only re-raises it (since `exc.errno != errno.EMSGSIZE`), so it escapes to
  the caller as an unhandled `OSError`, not the documented `None`
  "nothing arrived" contract every other `Link.recv()` timeout/no-data path
  gives its caller.

No test in `tests/test_link.py` exercises `recv()` after `close()` (only
`send()` after `close()` is asserted), so this divergence is currently
untested and unenforced, contrary to the file's own stated goal of "no
change to the layers above" being provable by one shared suite.

**Fix:**
```python
def recv(self, timeout: Optional[float] = None) -> Optional[bytes]:
    if self._closed:
        raise RuntimeError("cannot recv on a closed UdpLink")
    ...
```
(or, to match `LoopbackLink`'s more permissive behavior instead, return
`None` immediately when closed rather than touching the socket) — either
way, add the missing shared-suite test in `tests/test_link.py` so a future
change to either implementation can't reintroduce the divergence
unnoticed.

## Info

### IN-01: `src/telemetry/logger/__init__.py` is empty

**File:** `src/telemetry/logger/__init__.py:1`
**Issue:** Every sibling package under `telemetry` (`archive`, `capture`,
`framing`, `ground`, `link`) carries a populated module docstring
explaining the package's role, its requirements coverage, and its
dependency direction — an established, consistent convention throughout
this phase. `telemetry.logger` — arguably the most architecturally central
package (it wires every other package together in `cli.py`) — has none.
**Fix:** Add a short module docstring mirroring the sibling packages'
style, e.g. summarizing that this package owns the car-side entry point,
config loading, and the telemetry pipeline, and naming the requirements it
covers (OPS-05, CAP-05/06, ARCH-05).

### IN-02: Redundant double critical-level logging for one synthetic-config failure

**File:** `src/telemetry/logger/cli.py:388-394`, `424-427`
**Issue:** When `--source synthetic` is used and `load_gate_config` fails,
the specific `except GateConfigError` handler logs a `critical` message and
re-raises; the re-raised exception is then caught again by the outer
`except Exception:` in the same function, which logs a second, generic
`"capture terminated by an unhandled exception"` critical message with a
full traceback for the same root cause. This is harmless but noisy and can
make a single configuration error look like two independent failures in
the logs.
**Fix:** Either `return`/`raise SystemExit` immediately after the specific
log inside the `except GateConfigError` branch (skipping the outer
handler's generic message for this known cause), or drop the specific log
line and let the outer handler's `exc_info=True` traceback carry the
detail once.

---

_Reviewed: 2026-08-02T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
