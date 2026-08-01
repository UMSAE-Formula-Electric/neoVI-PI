# Physical Power-Pull Test (ARCH-03)

A repeatable bench procedure for proving the durable archive survives an
abrupt, physical loss of power to the neoVI PI — not a simulated crash, not
a shutdown command, an actual interruption of DC power to the running
hardware. This is the real ARCH-02/ARCH-03 proof. Run it on the bench with
the CM4 in front of you; no prior context from planning is assumed.

## Purpose

ARCH-02 requires the durable MCAP archive to survive an abrupt power cut
with every record written before the cut intact and readable afterward.
ARCH-03 requires that this be proven by a repeatable *physical* test, not
merely inferred from code review or from an automated proxy. This document
is that procedure. It exists so anyone on the team — not just whoever wrote
the archive writer — can run the real test, record a real result, and know
exactly what "pass" means.

## Why an automated test is not enough

`tests/test_archive_crash_recovery.py` includes a kill-based proxy test
that `SIGKILL`s the archive writer process mid-session and then runs
`telemetry.archive.reader.recover_session` against what is left. That test
is useful and it runs in every CI pass, but it cannot prove the thing
ARCH-03 actually asks for, for one specific reason:

**Killing a process does not crash the operating system.** The kernel
keeps running. Any bytes the application already handed to `write()` —
even bytes it never explicitly `fsync`ed — can still sit safely in the OS
page cache and read back correctly once the process is gone, simply
because nothing actually forced the machine to lose them. A completely
broken `fsync` implementation (one that calls `write()` correctly but
never calls `fsync`/`fdatasync` at all) can therefore still pass the
SIGKILL proxy test, because the proxy test never exercises the actual
persistence boundary — the point at which data is either on the physical
storage device or it is gone.

Only interrupting power to the machine itself exercises that boundary. A
power cut can lose whatever was sitting in the page cache unsynced, can
interrupt an in-flight filesystem journal transaction, and can expose
whatever the storage device itself does (or does not) guarantee about a
write in flight when power disappears. None of that is reachable by
killing a process on a machine that stays powered on and running.

**A passing `test_archive_crash_recovery.py` run does not license skipping
this procedure.** The automated suite is a necessary check on write-cadence
correctness; it is not a substitute for this one. ARCH-03 stays open until
this procedure has actually been run and its results recorded, regardless
of how green the test suite is.

## Equipment

- The neoVI PI (Raspberry Pi CM4) hardware, with the archive writer
  runnable on it (either against real hardware capture, or against a
  synthetic/looped-back frame source — either is acceptable for this
  procedure; what matters is that records are actually being written to
  the archive at a known, controlled rate throughout the run).
- A way to physically interrupt DC power to the CM4 on demand:
  - The car's kill switch feeding the neoVI PI, if testing in-vehicle —
    this is closer to the real failure mode this test exists to catch
    than the barrel connector is.
  - The barrel/PoE power connector itself, if testing on the bench outside
    the car.
  - Either is acceptable; neither is a shutdown command, and neither is
    `kill`/`SIGKILL`/`sudo shutdown` — physically remove power.
- A stopwatch or any wall-clock timer, to note approximately when during
  the run each cut happens.
- A way to inspect the resulting session directory after each boot: SSH
  access to the CM4, a monitor/keyboard, or pulling the NVMe and mounting
  it elsewhere — any of these is fine, the point is being able to run
  `telemetry.archive.reader.recover_session` and look at the session
  directory's contents afterward.
- A notebook, spreadsheet, or the phase's own verification artifacts file
  to record each run's results (see "Recording results" below).

## Procedure

Repeat the following steps **at least three times**, cutting power at a
different point in the run each time. A single successful pull proves
nothing about consistency — the failure modes this test exists to catch
(a partial device write in flight at the moment power disappears,
filesystem journal replay taking an unexpected path on remount) are
probabilistic, not deterministic, and can pass once and fail on the next
attempt at a different cut point.

1. **Start a session** at a controlled, known frame rate (either real
   hardware capture at a known bus load, or a synthetic/looped-back
   frame source configured for a fixed, known rate). Let it run long
   enough that a meaningful, known number of records has been written
   before you cut power in step 3.
2. **Note the last confirmed flush count** the logger reports (or, if
   using a build that does not print this, note the elapsed run time and
   the configured record rate, so you have an independent estimate of how
   many records should have been durable at any given moment).
3. **At a randomized point during the run, physically interrupt DC power**
   to the CM4 — trip the kill switch feeding the neoVI PI, or pull the
   barrel/PoE connector. Do this without warning to the running process:
   no shutdown command, no graceful stop, an actual cut. Vary the point in
   the run across repetitions (early, middle, late) rather than always
   cutting at the same moment.
4. **Restore power** and let the Pi boot normally.
5. **Run `recover_session`** (`telemetry.archive.reader.recover_session`)
   against the `.mcap` file in the last session directory that was active
   at the moment of the cut.
6. **Check the result** against the pass criteria below, and record it
   (see "Recording results").
7. Repeat from step 1 for the next repetition, cutting at a different
   point in the run.

## Pass criteria

A given repetition passes only if **all** of the following hold:

- **Every recovered record decodes correctly.** Nothing recovered by
  `recover_session` should fail to unpack, and nothing garbled should be
  silently accepted as a valid record.
- **The recovered count is consistent with what was captured before the
  cut.** It should be at or near the last confirmed flush count from step
  2 — it is expected and acceptable for the very last, not-yet-flushed
  handful of records to be lost (that is what the flush cadence bounds,
  by design), but the recovered count should not fall meaningfully short
  of what was already confirmed durable.
- **The interrupted session has no `.done` marker.** Check directly (the
  marker file should not exist in the session directory) and also confirm
  `telemetry.archive.reader.is_session_complete` reports the session as
  incomplete for that directory.
- **No partial or garbage record is silently accepted as real data.** A
  record cut off mid-write by the power loss must be dropped by recovery,
  not returned as a corrupted or truncated value.

If any repetition fails any one of these, that is the ARCH-02/ARCH-03
result to report — do not average it away against passing repetitions, and
do not silently rerun until it passes.

## Recording results

For **each** repetition, record the following in the phase's verification
artifacts (not just in this document):

- The date the repetition was run.
- Approximately where in the run power was cut (early/middle/late, or an
  elapsed-time estimate).
- The recovered record count from `recover_session`.
- The last confirmed flush count from before the cut (step 2), for
  comparison against the recovered count.
- Whether the session directory carried a `.done` marker (it should not).
- Pass/fail against every bullet in "Pass criteria" above.

**ARCH-03 is not closed on the strength of the automated proxy test
alone.** It closes only once at least three repetitions of this procedure
have been run on real hardware and their results recorded here, per "Why
an automated test is not enough" above.

## Known limits

- `ArchiveWriter`'s fsync cadence calls `os.fdatasync` on Linux (the CM4's
  actual target platform) but falls back to `os.fsync` on Windows, where
  `os.fdatasync` does not exist at all. The Windows dev laptop this
  project's day-to-day development happens on never exercises the
  `fdatasync` branch — only this procedure, run on the real CM4, does.
- `telemetry.archive.session.mark_done`'s directory-entry fsync
  (`os.fsync` on an open directory file descriptor) is guarded to run only
  on non-Windows platforms, because `os.fsync()` on a directory descriptor
  raises `PermissionError` on Windows (verified directly during this
  phase's research). That call, too, is Linux-only and is proven at all
  only by this procedure running on real hardware — the ordering logic
  around it is unit-tested on Windows, but the syscall itself is not.
- This procedure intentionally does not prescribe an exact frame rate,
  session duration, or number of repetitions beyond the "at least three"
  floor — those are left to whoever runs it, appropriate to what hardware
  and time are available on a given bench session. What must not change is
  that each repetition is a genuine physical power interruption, not a
  process kill or a shutdown command.
