---
status: testing
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
source: [01-VERIFICATION.md]
started: 2026-08-02T12:17:06.371Z
updated: 2026-08-02T12:17:06.371Z
---

## Current Test

number: 1
name: Physical power-pull durability test
expected: |
  Power is physically pulled on the car mid-session, repeatedly (≥3 times), and the archive
  reopens via recover_session()/NonSeekingReader with every record written before the cut
  intact and readable. No .done marker exists for any interrupted session.
awaiting: user response

## Tests

### 1. Physically pull power on the car mid-session, repeatedly (≥3 times), and reopen the archive with recover_session()/NonSeekingReader
expected: Every record written before the cut is intact and readable; no `.done` marker exists for the interrupted session
why_human: A SIGKILL proxy cannot prove fsync correctness — the OS page cache survives a process kill, so a broken fsync could still pass an automated test. Only cutting real power on the bench exercises the actual durability path. Procedure documented in `docs/power-pull-test.md`.
requirements: ARCH-02, ARCH-03
result: [pending]

### 2. Run tests/test_soak.py on the CM4 (Cortex-A72) itself, not the x86-64 dev box
expected: Sustained ~4,000 fps combined with zero archive-path drops, recorded queue high-water marks and discard counts
why_human: All Phase 1 throughput figures (e.g. 42,880.6 fps) were measured on x86-64 Windows dev hardware. The CM4 is the real deployment target and its GIL/queue costs differ; `01-VALIDATION.md` explicitly lists this as manual-only, not replaced by the dev-box soak run.
requirements: CAP-02
result: [pending]

### 3. Attach the neoVI PI hardware, run telemetry.logger.cli --source hardware against both live CAN buses
expected: Frames from both buses appear tagged by channel in one archive; the `TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED` assumption about `SpyMessage.TimeSystem` units gets confirmed or corrected
why_human: No neoVI hardware is attached to the dev machine; python-ics is stubbed/faked for all automated tests in `tests/test_hardware_source.py`. The Windows-only `timeGetTime()` docstring basis for the UNCONFIRMED constant may not describe what the compiled extension reports on Linux/the CM4.
requirements: CAP-01
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
