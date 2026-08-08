---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 02
current_phase_name: python-ground-station-and-dashboard-cutover
status: executing
stopped_at: Completed 02-02-PLAN.md
last_updated: "2026-08-08T16:52:05.232Z"
last_activity: 2026-08-08
last_activity_desc: Phase 02 execution started
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 24
  completed_plans: 22
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-08-01)

**Core value:** The pit sees what the car is doing while it is doing it, and no run's data is ever lost.
**Current focus:** Phase 02 — python-ground-station-and-dashboard-cutover

## Current Position

Phase: 02 (python-ground-station-and-dashboard-cutover) — EXECUTING
Plan: 3 of 4
Status: Ready to execute
Last activity: 2026-08-08 — Phase 02 execution started

Progress: [█████████░] 92%

## Performance Metrics

**Velocity:**

- Total plans completed: 7
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 0 | 7 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 00 P01 | 15min | 3 tasks | 10 files |
| Phase 00 P02 | 20min | 2 tasks | 8 files |
| Phase 00 P03 | 25min | 2 tasks | 2 files |
| Phase 00 P04 | 20min | 2 tasks | 4 files |
| Phase 00 P05 | 35min | 3 tasks | 6 files |
| Phase 00 P06 | 70min | 3 tasks | 5 files |
| Phase 00 P07 | 25min | 1 tasks | 3 files |
| Phase 01 P02 | 12min | 2 tasks | 15 files |
| Phase 01 P03 | 20min | 1 tasks | 5 files |
| Phase 01 P04 | 55min | 1 tasks | 17 files |
| Phase 01 P05 | 55min | 3 tasks | 6 files |
| Phase 01 P06 | 35min | 2 tasks | 4 files |
| Phase 01-dual-path-capture-durable-archive-and-thin-live-link P07 | 40min | 2 tasks | 2 files |
| Phase 01-dual-path-capture-durable-archive-and-thin-live-link P08 | 20min | 2 tasks | 4 files |
| Phase 01 P09 | 30min | 2 tasks | 2 files |
| Phase 01 P10 | 55min | 2 tasks | 3 files |
| Phase 01 P11 | 90min | 2 tasks | 2 files |
| Phase 01-dual-path-capture-durable-archive-and-thin-live-link P12 | 55min | 2 tasks | 3 files |
| Phase 01 P13 | 45min | 2 tasks | 2 files |
| Phase 02 P01 | 35min | 2 tasks | 4 files |
| Phase 02 P02 | 25min | 3 tasks | 5 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Compression ratio is a go/no-go gate (Phase 0), measured offline against an existing log before any transport/framing layout is committed.
- [Roadmap]: Archive path and thin live link ship together in Phase 1 — they share the capture fan-out and neither proves anything alone.
- [Roadmap]: Radio integration is isolated in Phase 9 with zero v1 requirements, so unpurchased RFD900x hardware can slip without blocking any other phase.
- [Roadmap]: Ground station is Python end to end; the Node server is retired in Phase 2 once the Python process serves the dashboard.
- [Phase 0, 2026-07-31]: Dev interpreter is **native Windows CPython 3.12.10**, installed via `winget install Python.Python.3.12` to `C:\Users\ethan\AppData\Local\Programs\Python\Python312\`. WSL Ubuntu's Python 3.14.4 was considered and rejected — it would force a `wsl -e bash -c "cd /mnt/c/… && …"` wrapper around every verify command in every plan, and `cantools==42.0.3` has no settled 3.14 wheel support. Plans may assume bare `python` / `pytest` on PATH.
- [Phase 0, 2026-07-31]: Package legitimacy gate **approved** for `cantools==42.0.3` and `pytest==9.1.1`. Both RESEARCH.md `SUS` verdicts were metadata artifacts, not legitimacy findings: `too-new` (recency of point release 42.0.3) and `unknown-downloads` (checker could not fetch a count). `cantools` is already an existing dependency — imported in `src/neoVI_logger.py` and `src/new_logger.py` (not `src/references.py`, contrary to the plan's parenthetical). No other package is introduced; `cobs` and CRC-16 libraries stay uninstalled per D-06.
- [Phase ?]: [Phase 0-01, 2026-07-31]: Corrected two RESEARCH.md DBC Ground Truth figures against direct cantools measurement: cycle-time-bearing message count is 19 (not 23), and the third multiplexed message is M175_Diag_Data_Message (not INV_Diag_Buffer, which exists but is unmultiplexed). See 00-01-SUMMARY.md Deviations.
- [Phase ?]: Task 2 hardening required no encoder/decoder code changes — Task 1's tracer slice already implemented every malformed-input guard the plan's behavior block specifies; verified by writing all 21 assertions first and observing them pass against the untouched implementation
- [Phase ?]: INV_Diag_Buffer confirmed genuinely extended-ID (is_extended_frame=True, frame_id 0xAA5) via direct cantools measurement before use as the extended-ID ablation subject, independent of its separate multiplexed-message correction from 00-01
- [Phase ?]: [Phase 0-03, 2026-08-01] Corrected the plan's own Task 2 behavior block, which had inherited RESEARCH.md's wrong third-multiplexed-message figure (INV_Diag_Buffer instead of the measured M175_Diag_Data_Message, already corrected once in 00-01-SUMMARY.md); the classifier test pins the measured set.
- [Phase ?]: [Phase 0-03, 2026-08-01] The structural checksum rule measures 12 candidate messages on this DBC (heartbeats, fault codes, SOH values), not the empty bucket the plan anticipated -- reported as an inspectable, non-empty candidate list per T-00-10 rather than forced to an assumed-empty count; likely false positives per RESEARCH.md's flagged Assumption A2 risk, to be hand-reviewed when GATE-02's report is written in plan 00-06.
- [Phase ?]: [Phase 0-04, 2026-07-31] Pre-registered the D-13 pass threshold (option-a: 200 kbit/s baseline, 120/170 kbit/s average/peak caps, 40%/15% headroom, typical bracket gates) in 00-THRESHOLD.md and checked in every D-12 modelling assumption to config/gate.json behind a typed loader (src/telemetry/measure/config.py) that raises GateConfigError rather than defaulting on malformed input.
- [Phase ?]: [Phase 0-04, 2026-07-31] User added a fifth confirmed:false assumption beyond the plan's original four: total bus frame rate. Verified against cantools that only 19/128 DBC messages declare GenMsgCycleTime (summing to ~1,690.67 fps); the prose-cited ~3,730-4,000 fps combined figure is not DBC-derivable. Recorded in gate.json's bus_targets/default_period_ms_by_ecu and surfaced in 00-THRESHOLD.md alongside the pre-registered 6-byte/frame CFR header-floor risk (179-192 kbit/s at the prose rate vs 81 kbit/s at the DBC floor), which is explicitly not grounds to move the bar if it fires.
- [Phase ?]: [Phase 0-05, 2026-07-31] Resolved the plan's abbreviated default_period_ms_by_ecu[sender] lookup against the actual gate.json shape (nested one level deeper at default_period_ms_by_ecu.seed_period_ms_by_ecu, NO_SENDER not _default as the fallback key); rate model achieves bus1 2900.0005 fps / bus2 830.0050 fps against 2900/830 targets (both within 0.001%).
- [Phase ?]: [Phase 0-05, 2026-07-31] Confirmed empirically that cantools message.encode(strict=False) disables the declared physical min/max check but still enforces the raw bit-width range; entropy mutation domain is therefore 2**length (or signed two's-complement range), not the signal's declared min/max.
- [Phase ?]: [Phase 0-05, 2026-07-31] Rule-3 deviation: updated tests/test_wire_roundtrip.py's two SyntheticFrameSource call sites (old seed= keyword) to the new (db, dictionary, config, bracket_name) signature via a new session-scoped gate_config fixture in tests/conftest.py, since this plan's own interface contract removed the seed parameter. src/telemetry/measure/cli.py's equivalent call site is deliberately left for 00-06-PLAN.md, which already owns widening it.
- [Phase ?]: measure_stream now takes a plain frame iterable (not a FrameSource object) so cli.py can materialize the frame list once per bracket and reuse it across all four D-10 ablations
- [Phase ?]: Per-ID all-in bytes/frame apportions each batch's D-06 overhead_breakdown proportional to each ID's share of the batch's clean bytes (executor's documented modelling choice, since the interface contract only specifies the batch-level formula)
- [Phase ?]: meta.threshold_comparison covers only average_kbps and peak_kbps for thresholds.gating_bracket (typical), matching 00-THRESHOLD.md's pass-requires-BOTH condition; measured typical bracket came in at 306.08 kbit/s avg / 314.43 kbit/s peak, both over the pre-registered ceilings (120/170 kbit/s) -- the pre-registered header-overhead risk materializing as measured fact
- [Phase ?]: No-go: typical bracket 305.13/313.55 kbit/s avg/peak vs pre-registered 120/170 kbit/s ceilings; live path carries a named 12-message critical-channel subset (74.62 kbit/s), full-rate NVMe archive unaffected
- [Phase ?]: Worst-case bracket (344.51 kbit/s) exceeds the 200 kbit/s baseline budget; carried forward as a Phase 1 real-traffic re-check condition per D-14, not a reason to fail the gate twice
- [Phase ?]: EMUS BMS _Ext-message modelling error (34 messages don't exist on the real standard-ID-only bus) recorded as a documented arithmetic correction (~261.85 kbit/s), not a re-run of the committed gate config
- [Phase ?]: [Phase 1-02, 2026-08-01] python-ics pinned as python-ics==1!26.3.9 (PEP 440 epoch 1) in requirements.txt, correcting 01-RESEARCH.md's epoch-dropping illustrative install line; lz4 and zstandard pinned explicitly as mcap's transitive deps; requirements-dev.txt kept byte-identical as Phase 0 provenance record
- [Phase ?]: [Phase 1-03, 2026-08-01] config/logger.json + typed loader mirrors telemetry.measure.config exactly (OPS-05); netid format validated without importing ics, real resolution is a test-only check; resolve_allowlist kept as a separate free function so config loading stays cantools/ics-free; telemetry.batch_max_age_s validated against wire/encoder.py's MAX_DELTA_T_US (imported, not restated); all 12 critical-channel allowlist names resolve against the real DBC; test_requirements_pinned cross-checks requirements.txt/requirements-dev.txt never drift (OPS-06)
- [Phase ?]: Tracer (01-04): CRC-16 trailer placed inside the COBS envelope, not outside as RESEARCH.md Pattern 7 sketched, to preserve LINK-01's delimiter resync property
- [Phase ?]: Tracer (01-04): one shared, encoding-less MCAP schema plus one channel per configured channel name (/can/{name}), verified against real mcap==1.4.0 Writer signatures
- [Phase ?]: Tracer (01-04): recomputed critical-subset bit rate with the batcher's 1-byte length prefix is 81.94 kbit/s (was 74.62 kbit/s), still well under the 120 kbit/s pass bar
- [Phase ?]: recover_session catches (mcap.exceptions.EndOfFile, struct.error) as one pair -- struct.error is not an mcap exception type and would silently escape an mcap-only except clause
- [Phase ?]: Session naming fallback sanity floor: a clock reporting a UTC year before 2020 is treated as implausible (CM4 has no RTC battery)
- [Phase ?]: Counter-derived session names use zero-padded counter-NNNNNNNN so they sort in creation order and reseed from the highest existing counter directory rather than zero when the state file is lost
- [Phase ?]: [Phase 1-06, 2026-08-01] ArchiveWriter.close() now routes its final sync through the same _flush_and_sync() helper add() uses, so flush_count correctly accounts for it; both cadence trackers reset together on every sync so a count-triggered sync also restarts the elapsed-time window
- [Phase ?]: [Phase 1-06, 2026-08-01] ArchiveRunner's inter-module sentinel is named STOP (public), not new_logger.py's file-local _STOP convention, since the producer and consumer of the sentinel live in different modules; a writer exception is logged critical, recorded on FanOutCounters.archive_write_failure, and re-raised after stop_event is set
- [Phase ?]: [Phase 1-06, 2026-08-01] Empirically reverified this session: a single ArchiveWriter.add() call under the default cadence leaves the file at 0 bytes on disk (Python's own io.BufferedWriter holds unflushed small writes); with flush_every_records=1 the same record produces a non-zero file immediately readable via recover_session while the writer is still open
- [Phase ?]: 01-07: CAP-06 telemetry precheck reuses UnknownFrameId/PayloadTooLong from wire.dictionary/wire.encoder rather than a new exception family; the actual CFR Encoder is not called from FanOut
- [Phase ?]: 01-07: FanOut gains optional dictionary= (default None) to stay backward compatible with 01-04/01-06's existing FanOut() call sites
- [Phase ?]: 01-07: telemetry-path error log rate limiting keys on (frame_id, is_extended) only, not per error type
- [Phase ?]: 01-08: CRC-inside-COBS delimiter-safety regression pinned by test (exhaustive batch_seq search for a CRC trailer containing a zero byte); UdpLink added, proven against LoopbackLink via one shared parameterised suite; LoopbackLink.close() given a real closed-state contract (send-after-close now raises) to satisfy LINK-03's shared-suite requirement
- [Phase ?]: 01-08: Winsock's recvfrom raises WSAEMSGSIZE on an oversized UDP datagram instead of POSIX's silent truncation -- UdpLink.recv() now catches errno.EMSGSIZE and returns None; the deployment target (Linux/CM4) is unaffected, this is a dev-box-only (Windows) code path
- [Phase ?]: hardware_source: SDK object injected via constructor arg defaulting to a lazily-imported real ics module; SDK's own RuntimeError type caught (never the builtin, since ics.RuntimeError does not subclass it); timestamp unit/epoch carried forward as a named UNCONFIRMED constant pending hardware bring-up
- [Phase ?]: [Phase 1-10, 2026-08-02] TelemetryPipeline closes batches on whichever of frame count, max age, or the CFR delta-t window (BatchWindowExceeded) comes first, re-encoding the triggering frame as the first record of the next batch rather than dropping it
- [Phase ?]: [Phase 1-10, 2026-08-02] cli.py installs signal handlers before any resource construction (before config load), resolving a self-contradicting ordering in the plan's own action text; --duration-s is enforced by an independent threading.Timer since HardwareFrameSource blocks internally between polls
- [Phase ?]: [Phase 1-10, 2026-08-02] mark_done is gated on writer.close() succeeding AND FanOutCounters.archive_write_failure being false; synthetic mode tags every frame with the first configured channel since SyntheticFrameSource models per-message rate/entropy, not per-bus separation
- [Phase ?]: GND-01 ground station emits a 'topic' field, not 'channel' -- the wire protocol carries no per-frame channel/bus data by design, so channel disambiguation is left to consumers (Phase 6 or later) rather than invented on the wire
- [Phase ?]: Two-process UDP test bounds both car and ground subprocesses via their own --duration-s watchdog (added to ground/cli.py), not termination signals -- Popen.terminate() on Windows never reaches a child's Python signal handlers
- [Phase ?]: Archive-mode gate runs report a single 'measured' bracket (outside BRACKET_NAMES); duration_s/achieved_bus_fps come from the archive's own timestamps, never gate.json; provenance/limitation text is fully replaced (T-01-30), not appended, for a real-log report.
- [Phase ?]: [Phase 1-13, 2026-08-02] Corrected the plan's discard+enqueued+filtered==submitted identity: telemetry_discard_count flags a subset of already-counted telemetry_enqueued appends (which evicted an older entry), not a fourth disjoint bucket -- summing it double-counts; corrected identity omits it from the sum and reports it separately
- [Phase ?]: [Phase 1-13, 2026-08-02] Reverted CAP-01 to Pending in REQUIREMENTS.md: 01-12 had marked it Complete in violation of the recorded user decision (01-CONTEXT.md deferred block) to keep legacy logger files through Phase 1 for rollback safety; CAP-02/03/05/06 verified against the codebase and marked Complete as the last plan claiming them
- [Phase ?]: [Phase 2-01, 2026-08-08] Task 1 tracer's 7 behavior assertions split state.py-only unit tests (channel derivation, collision guard) from full-stack SSE tests driven against a real DashboardServer + real LoopbackLink fed real COBS-framed bytes via urllib as the bounded SSE client stand-in
- [Phase ?]: [Phase 2-01, 2026-08-08] SseHub.broadcast() drop-oldest wrapper mirrors FanOut.submit's check-then-evict-then-count discipline; SSE write failures counted via a closure-scoped log-once-then-suppress lock, distinct from FanOutCounters' single-writer no-lock convention since multiple handler threads can hit it concurrently
- [Phase ?]: [Phase 2-02, 2026-08-08] Dashboard file read per HTTP request, not cached at process startup -- an engineer can edit dashboard.html and reload without restarting the ground station
- [Phase ?]: [Phase 2-02, 2026-08-08] can-dashboard/dashboard.html left in place after copying (not deleted) -- 02-04 retires the source directory once the port has proven itself on the car
- [Phase ?]: [Phase 2-02, 2026-08-08] Staleness sweep implemented as a dedicated 1s setInterval, deliberately deviating from 02-PATTERNS.md's animation-frame-cadence suggestion (pre-authorized by the plan itself) -- a message going quiet produces no updates and therefore no rAF trigger, so only a time-based sweep can ever dim a frozen value
- [Phase ?]: [Phase 2-02, 2026-08-08] GND-02, GND-04, GND-05 marked Complete in REQUIREMENTS.md after re-confirming no later phase-2 plan claims them (02-03 claims GND-03; 02-04 claims GND-03, CAP-01)

### Pending Todos

None yet.

### Blockers/Concerns

- **RFD900x not purchased.** Procurement is a standing parallel-track action starting now, not gated by software sequencing. Phase 9 cannot start until hardware arrives.
- **Requirement count corrected.** REQUIREMENTS.md originally stated 55 v1 requirements; the actual count is 57. Traceability and coverage figures now reflect 57.
- **Testing season is weeks away.** Phase ordering assumes work may stop at any phase boundary with a usable subset on the car.
- **Worktree parallelism degraded to sequential.** HEAD is on branch `add-pedal-percent-msg`, diverged from `origin/HEAD`, so `worktree.base-check` reports `head-diverged-from-fork` and plans run one at a time on the main working tree (#683). This will slow Phase 1, which is large enough to have genuinely parallel waves. To restore parallel worktrees, run `gsd-tools worktree set-baseref` (sets `worktree.baseRef:"head"`).
- **[Phase 0] 00-VALIDATION.md is still an unfilled template.** Every `{placeholder}` is intact. `workflow.nyquist_validation` is on. Non-blocking — every task in the 7 plans carries an `<automated>` verify, and phase verification passed 4/4 without it. Run `/gsd-validate-phase 0` to fill it. The `verify:post` nyquist and security hooks were both declined at the Phase 0 boundary; `/gsd-secure-phase 0` is likewise still available.
- **[Phase 0] The classifier's 12 checksum-bucket candidates were never hand-reviewed.** RESEARCH.md Assumption A2 predicted false positives (heartbeats, fault codes, SOH values). Reported as an inspectable candidate list with per-assignment reasons rather than asserted correct — auditable without re-running anything.
- **[Phase 0 → 1] The gate's numbers rest on a modelled stream, not captured traffic.** Bus assignment and total frame rate both carry `confirmed: false`, and the EMUS `_Ext` correction was recorded arithmetically rather than re-measured. Phase 1's first bench or track session should re-run the gate against a real captured log — which needs the deferred real-log reader for the D-08 frame-source interface, scope Phase 1 must absorb.
- [Phase 2-02] Task 2's browser-based human-check (staleness dimming, reconnect-across-restart, no-results search interaction) was not run -- no browser automation tool was available this session. Recorded as .planning/WINDOWS.md id=1 (kind unrun-verify). Should be run manually or via /gsd-verify-work 2 before /gsd-ship.

## Deferred Verification

| Phase | State | Resume |
|-------|-------|--------|
| 1 | verification_deferred_human | /gsd-verify-work 1 |

Phase 1 passed 5/5 must-haves in software (287 tests, 0 open code-review findings) but three items
need hardware that is not available in the dev session. Items are persisted in
`.planning/phases/01-dual-path-capture-durable-archive-and-thin-live-link/01-UAT.md`:

1. **Physical power-pull durability test** (ARCH-02/ARCH-03) — `docs/power-pull-test.md`. A SIGKILL
   proxy cannot prove fsync correctness; the OS page cache survives a process kill.

2. **CM4-target soak** (CAP-02) — every throughput figure to date (42,880.6 fps) is x86-64 dev
   hardware, never the Cortex-A72.

3. **Real dual-bus hardware capture** (CAP-01) — also the only way to confirm or correct
   `TIME_SYSTEM_TO_MICROSECONDS_UNCONFIRMED`.

Per explicit user decision on 2026-08-02, the autonomous run continued to Phase 2 rather than
halting — Phase 2 has no hardware dependency. Phase 1 remains formally unverified until
`/gsd-verify-work 1` passes.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-08-08T16:52:05.214Z
Stopped at: Completed 02-02-PLAN.md
Resume file: None

**Resume with:** `/gsd-autonomous` to continue with Phase 1.

Phase 0 closed with a signed **no-go**: the live path carries a named 12-message critical-channel
subset (74.62 kbit/s), not the full bus. Verification passed 4/4 must-haves with GATE-01/02/03 all
traced. Code review found 0 critical / 5 warning / 3 info; all 5 warnings were fixed as
validation-only hardening and the published report still reproduces byte-identically at
`config_hash 1dcefe671220`. Test suite 118 → 127 passing.

PROJECT.md was reconciled against the measurement at this transition — the "full bus fits with
roughly 40% headroom" claim, the "5–8 bytes/frame" target, and the "unverified assumption" note
were all superseded rather than left standing. Two new Active requirements were added for the
config-driven subset allowlist and its version negotiation.
