---
phase: 1
slug: dual-path-capture-durable-archive-and-thin-live-link
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-01
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `01-RESEARCH.md` § Validation Architecture, which was written with concrete
> commands rather than placeholders. Phase 0's VALIDATION.md was left as an unfilled template;
> this one is populated at creation so the same gap does not recur.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 — installed, 127 tests currently passing |
| **Config file** | `pytest.ini` (`pythonpath = src`, `testpaths = tests`, `addopts = -ra`) — Wave 0 creates it |
| **Quick run command** | `python -m pytest -x -q --tb=short -m "not slow"` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~5 s quick (current suite is 3.75 s), soak test excluded from quick |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest -x -q --tb=short -m "not slow"`
- **After every plan wave:** Run `python -m pytest -q` (full suite, including the soak test)
- **Before `/gsd-verify-work`:** Full suite green, PLUS the ARCH-03 physical power-pull result
  recorded in the phase's verification artifacts — it cannot be automated
- **Max feedback latency:** 10 seconds for the quick loop

---

## Per-Task Verification Map

Task IDs are assigned by the planner. This table maps **requirements to their test targets**;
the planner must attach each row's automated command to the task that implements it.

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| CAP-02, CAP-03, CAP-04 | Fan-out sustains rate; telemetry structurally cannot block archive | integration | `pytest tests/test_fanout.py -x` | ❌ W0 |
| CAP-05, CAP-06 | Discards and errors counted with frame context, never swallowed | unit | `pytest tests/test_fanout.py::test_discard_counting -x` | ❌ W0 |
| ARCH-01, ARCH-04 | MCAP writer produces a valid readable archive at the batched cadence | integration | `pytest tests/test_archive_writer.py -x` | ❌ W0 |
| ARCH-02, ARCH-03 | Crash mid-write recovers every pre-crash complete record | integration (SIGKILL proxy) + manual | `pytest tests/test_archive_crash_recovery.py -x` | ❌ W0 |
| ARCH-05 | `.done` written only after close+flush returns, ordering correct | unit | `pytest tests/test_session.py::test_done_marker_ordering -x` | ❌ W0 |
| LINK-01, LINK-02 | COBS+CRC frame/deframe; corrupted input discarded and counted | unit | `pytest tests/test_framing.py -x` | ❌ W0 |
| LINK-03, LINK-04 | Identical encode→decode chain over LoopbackLink and UdpLink | integration | `pytest tests/test_link.py -x` | ❌ W0 |
| GND-01 | Full chain capture→encode→frame→link→deframe→decode against the DBC | integration | `pytest tests/test_end_to_end.py -x` | ❌ W0 |
| OPS-05 | Config loader rejects unknown keys, missing keys, malformed values | unit | `pytest tests/test_logger_config.py -x` | ❌ W0 |
| OPS-06 | Clean-machine provisioning from the pinned manifest | unit | `pytest tests/test_logger_config.py::test_requirements_pinned -x` | ❌ W0 |
| CAP-01 | One implementation captures both buses concurrently | integration | `pytest tests/test_fanout.py::test_dual_bus_capture -x` | ❌ W0 |
| CAP-02 (soak) | Sustained ~4,000 fps, zero archive drops, HWM + discard counts logged | soak (`@pytest.mark.slow`) | `pytest tests/test_soak.py -x --tb=short` | ❌ W0 |
| OPS-04 | Each run lands in its own discrete session directory | unit | `pytest tests/test_session.py -x` | ❌ W0 |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pytest.ini` — `pythonpath = src`, `testpaths = tests`, and a registered `slow` marker so
      the soak test is excludable from the quick loop
- [ ] `tests/test_fanout.py` — CAP-01/02/03/04/05/06
- [ ] `tests/test_archive_writer.py` — ARCH-01/04, exercises the writer directly
- [ ] `tests/test_archive_crash_recovery.py` — ARCH-02/03 automated half; MUST carry an inline
      comment stating its own scope limit (see Manual-Only below)
- [ ] `tests/test_session.py` — ARCH-05, OPS-04, session naming with UTC + monotonic fallback
- [ ] `tests/test_framing.py` — LINK-01/02
- [ ] `tests/test_link.py` — LINK-03/04, both link implementations against one shared suite
- [ ] `tests/test_end_to_end.py` — GND-01, full chain over loopback
- [ ] `tests/test_logger_config.py` — OPS-05/06, mirrors the existing `tests/test_gate_config.py`
- [ ] `tests/test_soak.py` — CAP-02 sustained rate, marked `slow`; reuse
      `telemetry.synth.generator.SyntheticFrameSource` as the load source, driven through the real
      fan-out and writer rather than the measurement CLI
- [ ] `tests/conftest.py` additions — a `logger_config` fixture mirroring the existing
      `gate_config` fixture, once `config/logger.json` exists

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Physical power-pull durability | ARCH-02, ARCH-03 | A SIGKILL proxy does **not** prove fsync correctness — the OS page cache survives a process kill, so a broken fsync can still pass the automated test. Only cutting real power exercises the path. | Run a session at load on the CM4, physically disconnect power mid-write, repeat ≥3 times. After each cut, reopen with `NonSeekingReader(f).iter_messages(log_time_order=False)` and confirm every record written before the cut is readable and that no `.done` marker exists for the interrupted session. |
| Sustained rate on target hardware | CAP-02 | Throughput was measured on x86-64 dev hardware; the CM4's Cortex-A72 is the real target and the GIL/queue costs differ. | Run `tests/test_soak.py` on the CM4 itself and record the achieved fps, queue high-water marks, and archive drop count (must be zero). |
| Dual-bus capture against real hardware | CAP-01 | No neoVI hardware is attached to the dev machine; `python-ics` is stubbed for automated tests. | Attach the neoVI PI, run the logger against both live buses, confirm frames from both appear in one archive. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or a declared Wave 0 dependency
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all ❌ references above
- [ ] No watch-mode flags in any command
- [ ] Feedback latency < 10s on the quick loop
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
