---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
verified: 2026-08-02T00:00:00Z
status: human_needed
score: 5/5 must-haves verified (in software; 3 items require manual hardware verification)
behavior_unverified: 0
overrides_applied: 0
deferred:
  - truth: "The duplicate legacy logger implementation (src/neoVI_logger.py, src/new_logger.py, src/references.py, src/neoVI_sender.py) is removed from the repository"
    addressed_in: "Phase 2"
    evidence: "ROADMAP.md's own scope note on Phase 1 criterion 1 ('the removal clause re-targets to Phase 2, which is already the retirement phase'); 01-CONTEXT.md § Deferred Ideas records the user's explicit rollback-safety decision; REQUIREMENTS.md keeps CAP-01 Pending with a placement note naming Phase 2 alongside GND-03 (Node server retirement)."
human_verification:
  - test: "Physically pull power on the car mid-session, repeatedly (≥3 times), and reopen the archive with recover_session()/NonSeekingReader"
    expected: "Every record written before the cut is intact and readable; no .done marker exists for the interrupted session"
    why_human: "A SIGKILL proxy cannot prove fsync correctness — the OS page cache survives a process kill, so a broken fsync could still pass an automated test. Only cutting real power on the bench exercises the actual durability path. Procedure documented in docs/power-pull-test.md."
  - test: "Run tests/test_soak.py on the CM4 (Cortex-A72) itself, not the x86-64 dev box"
    expected: "Sustained ~4,000 fps combined with zero archive-path drops, recorded queue high-water marks and discard counts"
    why_human: "All Phase 1 throughput figures (e.g. 42,880.6 fps) were measured on x86-64 Windows dev hardware. The CM4 is the real deployment target and its GIL/queue costs differ; 01-VALIDATION.md explicitly lists this as manual-only, not replaced by the dev-box soak run."
  - test: "Attach the neoVI PI hardware, run telemetry.logger.cli --source hardware against both live CAN buses"
    expected: "Frames from both buses appear tagged by channel in one archive; TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED assumption about SpyMessage.TimeSystem units gets confirmed or corrected"
    why_human: "No neoVI hardware is attached to the dev machine; python-ics is stubbed/faked for all automated tests in tests/test_hardware_source.py. The Windows-only timeGetTime() docstring basis for the UNCONFIRMED constant may not describe what the compiled extension reports on Linux/the CM4."
---

# Phase 1: Dual-Path Capture — Durable Archive and Thin Live Link Verification Report

**Phase Goal:** The car runs one logger that never loses a frame to disk and simultaneously delivers frames to a ground station over a swappable link, with no radio present
**Verified:** 2026-08-02
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

**Test suite:** `python -m pytest -x -q --tb=short` → **287 passed** (matches the recorded baseline exactly; re-run independently for this verification, not transcribed). Code review (`01-REVIEW.md`) found 1 critical + 4 warnings; `01-REVIEW-FIX.md` shows all 5 fixed with new regression tests, confirmed by reading the fixed code directly (`_run_session`'s shutdown gate now checks both `archive_write_failure` and `archive_overflow`; `FanOutCounters._archive_hwm_lock` guards the one shared field; the batch-header guard raises `RuntimeError` instead of a bare `assert`; `Deframer.feed()`'s overflow check runs before the first yield; both `Link.recv()` implementations raise `RuntimeError` after `close()`).

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | One logger captures both CAN buses into a single MCAP archive on the onboard NVMe, and each run lands in its own discrete session rather than one unbounded file | ✓ VERIFIED (with a deliberately deferred sub-clause) | `src/telemetry/logger/cli.py` is the single entry point wiring one `HardwareFrameSource` (or `SyntheticFrameSource` for `--source synthetic`) across all configured channels into one `FanOut` → one `ArchiveWriter` per session. `src/telemetry/capture/hardware_source.py` resolves every configured channel's net-ID against one device handle and tags each frame with its channel — genuinely dual-bus, one implementation. `src/telemetry/archive/session.py::new_session` creates one directory per run (`OPS-04`). **The "duplicate implementation is gone from the repository" clause is NOT met** — `src/neoVI_logger.py`, `src/new_logger.py`, `src/references.py`, `src/neoVI_sender.py` all still exist (confirmed via `ls`, all four files present with 2026-07-30 timestamps, untouched by any Phase 1 commit). This is a **locked, documented user decision**, not a gap: ROADMAP.md itself carries the scope note on this exact criterion, `01-CONTEXT.md § Deferred Ideas` records the rollback-safety rationale, and `REQUIREMENTS.md` keeps CAP-01 correctly Pending with a placement note. See Deferred Items below. |
| 2 | Power is physically pulled mid-session, repeatedly, and the archive reopens afterward with every record written before the cut intact and readable, and the interrupted session is not marked complete | ✓ VERIFIED (software path) / needs human (physical proof) | `telemetry.archive.reader.recover_session` (exercised by `tests/test_archive_crash_recovery.py`, 8 tests) correctly recovers a clean prefix from footerless, half-truncated, and mid-record-truncated `.mcap` files, using the non-default `NonSeekingReader(f).iter_messages(log_time_order=False)` configuration the module docstring explains is required (the library's own default reader configurations either raise `RecordLengthLimitExceeded` or silently recover zero records — pinned by `test_default_mcap_readers_fail_on_a_footerless_file`). `mark_done()` (`session.py`) structurally cannot run before `writer.is_closed`, and `_run_session` in `cli.py` (post CR-01 fix) withholds `.done` on both `archive_write_failure` and `archive_overflow`. The kill-based proxy test (`test_killed_writer_recovers_at_least_every_fsync_confirmed_record`) confirms write-cadence correctness and explicitly, correctly disclaims proving fsync durability in its own module docstring. **The literal physical power-pull is not automatable and has not been run** — `docs/power-pull-test.md` (173 lines) documents the exact repeatable bench procedure. Routed to human verification, per the known-partials guidance. |
| 3 | A sustained run at full combined bus load (~4,000 frames/s) reports zero frames dropped on the archive path, with queue high-water marks, telemetry-path discard counts, and any hardware or decode errors logged with frame context rather than swallowed | ✓ VERIFIED (in software, off-target hardware) | `tests/test_soak.py::test_sustained_combined_bus_load_zero_archive_drops` drives the real production assembly (`FanOut`, `ArchiveRunner`, `ArchiveWriter`, `TelemetryPipeline` over `LoopbackLink` — not the measurement CLI) at the combined `config/gate.json` target (3,730 fps), asserting `archive_overflow is False`, `archive_write_failure is False`, an exact archive-readback multiset match, all six telemetry/pipeline error counters at zero, and reports high-water marks + discard counts as an explicit JSON record (not inferred from absence of failure). Latest recorded run: 42,880.6 fps, archive HWM 16,314/50,000, telemetry HWM 1,000/1,000, 13 drop-oldest discards (expected/by design), 14,139 allowlist-filtered, 0 errors — confirmed present in `01-13-SUMMARY.md` and structurally the same assertions re-ran clean in this verification's full-suite pass. **All measurements are on x86-64 Windows dev hardware, never the CM4's Cortex-A72** — the test's own failure message and `soak_record["provenance"]` say so explicitly, and `01-VALIDATION.md` lists the CM4 run as manual-only. Routed to human verification for the hardware-target figure. |
| 4 | A frame captured on the car arrives at the ground station decoded against the DBC, having crossed the batching, COBS+CRC framing, and link layers, with no radio hardware anywhere in the chain and corrupt batches discarded and counted instead of passed upstream | ✓ VERIFIED | `tests/test_end_to_end.py::test_one_frame_reaches_the_archive_and_the_pit` (in-process, `LoopbackLink`) and `test_two_process_capture_to_pit_run_over_udp_no_radio_present` (two real subprocesses — `telemetry.logger.cli` and `telemetry.ground.cli` — over one real loopback UDP socket) both prove the full chain: capture → fan-out → allowlist filter → CFR encode → batch → CRC-16 → COBS → `Link` → deframe → CFR decode → DBC decode, and assert the DBC-decoded value matches the value encoded at the source. `test_corrupted_batch_is_discarded_and_counted_not_decoded` and `test_ground_consumer_discards_corrupt_batch_and_keeps_running` confirm corrupt batches are dropped and counted (`DeframeCounters.cobs_failures`/`crc_failures`/`batch_format_failures`), never passed upstream to the DBC decoder, and the consumer loop keeps running afterward. `src/telemetry/framing/cobs_frame.py` documents and implements the CRC-inside-COBS ordering correction over the research sketch, so a delimiter-scanning receiver can never split a valid frame at a false zero byte hiding in a raw CRC trailer. Two independent `Link` implementations (`LoopbackLink`, `UdpLink`) pass one shared parameterised test suite (`tests/test_link.py`), and neither imports or requires any radio/serial hardware. |
| 5 | Channels, DBC path, and link settings are read from a config file with no source edit, and a clean machine can be provisioned from the dependency manifest | ✓ VERIFIED | `config/logger.json` (schema_version 1) carries `dbc_path`, `channels` (both buses, symbolic net-ID names), `capture`, `archive`, `telemetry.allowlist` (12 messages), and `link` (including both `loopback`/`udp` shapes). `telemetry.logger.config.load_logger_config` is a typed, fail-closed loader (`LoggerConfigError`) mirroring the Phase-0 idiom; `tests/test_logger_config.py` (27 tests) proves unknown-key rejection, missing-key rejection, malformed-JSON rejection, and every field-level validation rule fails closed with a named exception rather than a silent default. Both `telemetry.logger.cli` and `telemetry.ground.cli` read the same file and take only `--config`/`--archive-root`/`--link-kind` as narrow CLI overrides — no setting requires editing source. `requirements.txt` carries exact `==` pins for every runtime dependency (`cantools`, `cobs`, `crccheck`, `lz4`, `mcap`, `python-ics`, `pytest`, `zstandard`), and `tests/test_logger_config.py::test_requirements_pinned` asserts every listed package is pinned exactly. |

**Score:** 5/5 truths present and correct in software; 2 of the 5 carry an explicit, previously-documented human-verification requirement (physical power-pull for #2, CM4-hardware rate for #3, plus dual-bus-on-real-hardware which underlies #1's "both buses" claim) that no automated test can close.

### Deferred Items

Item not yet met but explicitly, deliberately addressed in a later phase — carried in this report's frontmatter `deferred` block per Step 9b. Not a gap.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Duplicate legacy logger implementation removed from the repository (CAP-01's second clause) | Phase 2 | ROADMAP.md's own scope note directly under Phase 1 criterion 1; `01-CONTEXT.md § Deferred Ideas`; REQUIREMENTS.md CAP-01 Pending with placement note naming Phase 2 (which already retires the Node server via GND-03) |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/telemetry/logger/cli.py` | Single car-side entry point wiring capture → fan-out → archive → link | ✓ VERIFIED | 524 lines; wires `HardwareFrameSource`/`SyntheticFrameSource`, `FanOut`, `ArchiveRunner`, `TelemetryPipeline`; strict shutdown order; CR-01 fix present (`archive_closed_cleanly` checks both `archive_write_failure` and `archive_overflow`) |
| `src/telemetry/capture/hardware_source.py` | One consolidated python-ics capture source, both buses | ✓ VERIFIED | 273 lines; resolves all configured channels against one SDK/device; lazy `ics` import; documented `TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED` constant awaiting hardware confirmation (not a defect — self-disclosed) |
| `src/telemetry/capture/fanout.py` | Structural CAP-03/04/05/06 divergent fan-out | ✓ VERIFIED | 256 lines; archive `put_nowait` fatal-on-full, telemetry `deque(maxlen=N)` drop-oldest; `_archive_hwm_lock` guards the one cross-thread field (WR-01 fix present) |
| `src/telemetry/archive/{session,writer,reader,runner}.py` | Session lifecycle, MCAP writer, crash-recovery reader, archive runner | ✓ VERIFIED | Session naming (clock + counter fallback), `.done` marker ordering enforced structurally, `recover_session` proven against footerless/truncated files |
| `src/telemetry/framing/{cobs_frame,crc16,errors}.py` | COBS+CRC framing, LINK-01/02 | ✓ VERIFIED | CRC-inside-COBS ordering correctly implemented; `CobsDecodeFailed`/`CrcMismatch` distinctly raised and counted |
| `src/telemetry/link/{base,loopback,udp}.py` | Swappable Link abstraction, loopback + UDP | ✓ VERIFIED | Shared `Link` Protocol; both implementations pass one parameterised test suite; WR-04 fix present (`recv()` after `close()` raises `RuntimeError` on both) |
| `src/telemetry/ground/{cli,deframe}.py` | Headless ground station, GND-01 | ✓ VERIFIED | Deframe→decode loop; WR-03 fix present (buffer-overflow check runs before first yield, not after generator exhaustion) |
| `src/telemetry/logger/config.py` | Typed, fail-closed config loader, OPS-05 | ✓ VERIFIED | Unknown-key/missing-key/malformed-value rejection all tested |
| `config/logger.json` | Channels, DBC path, allowlist, link settings | ✓ VERIFIED | All required fields present and consistent with dual-bus, 12-message allowlist |
| `requirements.txt` | Pinned runtime manifest, OPS-06 | ✓ VERIFIED | 8 exact `==` pins; `test_requirements_pinned` passes |
| `docs/power-pull-test.md` | Repeatable physical durability procedure | ✓ VERIFIED (exists, not yet executed) | 173 lines, referenced by both the crash-recovery test module docstring and 01-VALIDATION.md |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `telemetry.logger.cli._run_session` | `telemetry.capture.fanout.FanOut.submit` | direct call per captured frame | ✓ WIRED | Confirmed in `cli.py` lines 420-423 |
| `FanOut.archive_queue` | `telemetry.archive.runner.ArchiveRunner` | shared `queue.Queue`, consumer thread | ✓ WIRED | `ArchiveRunner` constructed with `fan_out.archive_queue` and `fan_out.counters` in `cli.py` |
| `FanOut.telemetry_queue` | `telemetry.logger.pipeline.TelemetryPipeline` | shared `deque`, consumer thread | ✓ WIRED | `TelemetryPipeline` constructed with `fan_out.telemetry_queue` in `cli.py` |
| `TelemetryPipeline` | `telemetry.wire.encoder.Encoder` → `telemetry.wire.batcher.pack_batch` → `telemetry.framing.cobs_frame.frame` → `Link.send` | direct call chain | ✓ WIRED | Exercised end-to-end and per-stage timed in `tests/test_soak.py`; corroborated by `test_end_to_end.py` |
| `Link.recv` (ground) | `telemetry.ground.deframe.Deframer.feed` → DBC decode → stdout JSON | direct call chain in `run_consumer_loop` | ✓ WIRED | `tests/test_end_to_end.py::test_two_process_capture_to_pit_run_over_udp_no_radio_present` proves this over a real two-process UDP socket |
| `archive.writer.close()` | `archive.session.mark_done()` | conditional on `archive_closed_cleanly` | ✓ WIRED | Gate now checks both failure flags (CR-01 fix), regression-tested by `test_cli_archive_overflow_leaves_no_done_marker_and_exits_nonzero` |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|---|---|---|---|---|
| CAP-01 | 01-07, 01-09, 01-10, 01-12 | Single implementation, both buses; duplicate removed | ◐ PARTIAL — correctly Pending | First half met (`hardware_source.py`); removal half deliberately deferred to Phase 2 (see Deferred Items). REQUIREMENTS.md already correctly reflects Pending. |
| CAP-02 | 01-13 | Sustains ~4,000 fps combined, zero archive-path drops | ✓ SATISFIED (software; CM4 pending) | `test_soak.py`, 42,880.6 fps @ zero drops on dev hardware |
| CAP-03 | 01-04, 01-06, 01-07, 01-13 | Fan-out to two consumers, divergent overflow policy | ✓ SATISFIED | `fanout.py`; asserted under soak load |
| CAP-04 | 01-04, 01-07 | Telemetry structurally cannot block capture/archive | ✓ SATISFIED | Deque-based, no shared lock with archive queue |
| CAP-05 | 01-07, 01-10, 01-13 | Telemetry discards counted and reported | ✓ SATISFIED | `telemetry_discard_count`, exercised at soak load |
| CAP-06 | 01-07, 01-09, 01-10, 01-13 | Hardware/decode errors logged with frame context | ✓ SATISFIED | Per-frame-id rate-limited logging, all error counters zero at clean soak |
| ARCH-01 | 01-04, 01-06, 01-12 | Every frame written to local MCAP archive | ✓ SATISFIED | `ArchiveWriter`, exact-match soak readback |
| ARCH-02 | 01-05 | Archive survives abrupt power cut, pre-cut data intact | ✓ SATISFIED (recovery path); physical proof pending | `recover_session`, kill-proxy test with disclosed scope limit |
| ARCH-03 | 01-05 | Durability proven by repeatable physical power-pull | ◐ PARTIAL — correctly Pending | `docs/power-pull-test.md` exists; not yet executed. Routed to human verification. |
| ARCH-04 | 01-06 | Batched flush cadence, never stalls capture | ✓ SATISFIED | Record-count/elapsed-time cadence in `ArchiveWriter` |
| ARCH-05 | 01-04, 01-05 | `.done` marker only after close-and-flush | ✓ SATISFIED | Structural precondition + CR-01 fix |
| LINK-01 | 01-04, 01-08 | COBS+CRC batched framing, resync at delimiter | ✓ SATISFIED | CRC-inside-COBS ordering correctly implemented |
| LINK-02 | 01-04, 01-08, 01-11 | CRC-failing frames discarded and counted | ✓ SATISFIED | `DeframeCounters`, tested at ground CLI level |
| LINK-03 | 01-04, 01-08 | Transport abstracted, no change to layers above | ✓ SATISFIED | Shared parameterised `Link` test suite (loopback + UDP) |
| LINK-04 | 01-04, 01-08, 01-11 | Full chain runs with no radio hardware | ✓ SATISFIED | Two-process real-UDP test with no radio/serial import anywhere |
| GND-01 | 01-04, 01-11 | Ground station receives, decompresses, DBC-decodes | ✓ SATISFIED | `ground/cli.py`, end-to-end tests |
| OPS-04 | 01-03, 01-04, 01-05, 01-10 | Discrete sessions, not one unbounded file | ✓ SATISFIED | `new_session` per-run directory |
| OPS-05 | 01-03, 01-09, 01-10, 01-11, 01-12 | Config-driven, no hardcoding | ✓ SATISFIED | `config/logger.json`, fail-closed loader |
| OPS-06 | 01-01, 01-02 | `requirements.txt` for clean-machine install | ✓ SATISFIED | Pinned manifest, tested |

No orphaned requirements: all 18 requirement IDs named in this verification's task scope (CAP-01..06, ARCH-01..05, LINK-01..04, GND-01, OPS-04..06) are declared across at least one of the 13 plans' `requirements:` frontmatter, and REQUIREMENTS.md's Traceability table agrees with every status above (CAP-01 and ARCH-03 both correctly Pending; all others Complete).

### Anti-Patterns Found

None. Scanned all files under `src/telemetry/` for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/`console.log`-equivalent stubs/hardcoded-empty-return patterns. The only `XXX` hits are `Vector__XXX`, cantools' own DBC-format sentinel for "no declared sender" (`src/telemetry/synth/rates.py`), not a debt marker. Code review (`01-REVIEW.md`) found 1 critical + 4 warnings + 2 info; all 5 critical/warning findings are fixed and regression-tested per `01-REVIEW-FIX.md`, confirmed by direct code reading above. 2 info-level findings (empty `logger/__init__.py` docstring, redundant double critical-level log line) remain open but are cosmetic, non-blocking, and out of scope for fix-gating per the review's own severity classification.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full test suite is green | `python -m pytest -x -q --tb=short` | `287 passed in 23.67s` | ✓ PASS |
| Soak assertions (CAP-02/03/05/06) hold | included in full-suite run above (`tests/test_soak.py`, not separately re-run to avoid a second full pass) | passed as part of the 287 | ✓ PASS |
| Legacy files genuinely still present (confirms the deferred-scope claim is accurate, not silently already-deleted) | `ls -la src/neoVI_logger.py src/new_logger.py src/references.py src/neoVI_sender.py` | all 4 present, 2026-07-30 timestamps | ✓ PASS |
| No debt markers in phase-owned source | `grep -rnE "TBD|FIXME|XXX" src/telemetry/` | only the DBC-format `Vector__XXX` sentinel, not a marker | ✓ PASS |

### Human Verification Required

1. **Physical power-pull durability (ARCH-02/ARCH-03)**
   **Test:** Run a session at load on the CM4, physically disconnect power mid-write, repeat ≥3 times.
   **Expected:** After each cut, `recover_session`/`NonSeekingReader` recovers every record written before the cut, and no `.done` marker exists for the interrupted session.
   **Why human:** A SIGKILL proxy cannot prove fsync correctness — the OS page cache survives a process kill. Procedure: `docs/power-pull-test.md`.

2. **Sustained rate on target hardware (CAP-02)**
   **Test:** Run `tests/test_soak.py` on the CM4 itself.
   **Expected:** ~4,000 fps combined sustained, zero archive drops, high-water marks recorded.
   **Why human:** Every throughput figure to date (e.g. 42,880.6 fps) was measured on x86-64 dev hardware, not the CM4's Cortex-A72.

3. **Dual-bus capture against real hardware (CAP-01)**
   **Test:** Attach the neoVI PI, run the logger against both live buses.
   **Expected:** Frames from both buses appear in one archive; confirm or correct `TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED`.
   **Why human:** No neoVI hardware attached to the dev machine; `python-ics` is stubbed for automated tests.

### Gaps Summary

No blocking gaps. All must-have artifacts, wiring, and requirements are present, substantive, and correctly wired in software, confirmed by direct code reading (not SUMMARY prose) and an independently re-run 287-test suite. The two intentionally-partial items (CAP-01's removal clause, ARCH-03's physical proof) are both locked, previously-documented decisions accurately reflected in REQUIREMENTS.md and ROADMAP.md — neither is a new finding. Status is `human_needed` rather than `passed` solely because three specific, previously-scoped hardware verifications (physical power-pull, CM4-target soak, real dual-bus capture) remain outstanding and cannot be closed by any automated check in this repository.

---

_Verified: 2026-08-02_
_Verifier: Claude (gsd-verifier)_
