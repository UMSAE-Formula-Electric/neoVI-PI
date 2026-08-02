---
phase: 01-dual-path-capture-durable-archive-and-thin-live-link
plan: 13
subsystem: testing
tags: [soak-test, fanout, archive-writer, telemetry-pipeline, percentile-timing]

# Dependency graph
requires:
  - phase: 01-dual-path-capture-durable-archive-and-thin-live-link (01-06)
    provides: ArchiveRunner/ArchiveWriter flush-and-sync cadence this soak times
  - phase: 01-dual-path-capture-durable-archive-and-thin-live-link (01-07)
    provides: FanOutCounters discard/filter/error accounting this soak asserts and reports
  - phase: 01-dual-path-capture-durable-archive-and-thin-live-link (01-10)
    provides: TelemetryPipeline and its counters, encode/framing/send stages this soak times
provides:
  - tests/test_soak.py, the repeatable sustained-load soak phase success criterion 3 is verified
    against, emitting a structured JSON record with per-stage median/p95 timing and its own
    machine provenance
affects: [Phase 5 (TEST-03's soak becomes a repeatable automated version of this same load; the
  saturation/p99-latency soak reuses this timing harness), any future CM4 hardware run that needs
  a comparable record to measure against]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-stage timing instrumentation lives entirely in the test file, wrapping the exact bound
      method / module-level function production code already calls (writer._flush_and_sync,
      encoder.encode, pipeline_module.pack_batch/cobs_frame via monkeypatch.setattr, link.send) --
      no production module is modified to add measurement."
    - "Every timed distribution reports median and p95, never a mean alone -- a mean hides
      exactly the intermittent stall this measurement exists to surface (01-RESEARCH.md Open
      Question 2)."
    - "A structured measurement record is nested by concern (provenance/configuration/throughput/
      archive/telemetry/pipeline/fan_out_submit), written to a file, printed, and reparsed with an
      assertion on every top-level section -- so the record's own shape is verified, not just its
      values."
    - "Every measured figure in the record carries its own provenance field (platform.platform(),
      python version, and an explicit 'measured on x86-64 dev hardware, NOT the CM4' marker) --
      never left to a docstring aside a reader could miss."

key-files:
  created: []
  modified:
    - tests/test_soak.py
    - .planning/REQUIREMENTS.md

key-decisions:
  - "The plan's literal 'discard + enqueued + filtered == submitted' accounting identity double-
    counts against FanOutCounters' real semantics and was corrected to 'filtered + unknown_id +
    payload_too_long + unexpected_error + enqueued == submitted', with discard reported separately.
    See Deviations for the full reasoning."
  - "Achieved sustained rate is re-measured, not transcribed from Task 1's committed figure --
    this run measured 42,880.6 fps (18,689 frames over 0.436 s wall clock) against a 3,730 fps
    combined target, on Windows-11-10.0.26200-SP0 / Python 3.12.10 dev hardware. Run-to-run
    variance exists (Task 1's own commit measured 39,303 fps in a separate run); the structured
    record's own provenance field is what future readers should trust, not any single number
    copied into prose."
  - "CAP-01 was found marked Complete in REQUIREMENTS.md (introduced by 01-12) in violation of
    the recorded user decision (01-CONTEXT.md deferred block) that legacy logger deletion moves to
    Phase 2. Reverted to Pending as part of this plan's traceability pass -- see Deviations."

requirements-completed: [CAP-02, CAP-03, CAP-05, CAP-06]

coverage:
  - id: D1
    description: "A sustained run at the combined target rate (3,730 fps) through the real
      FanOut/ArchiveRunner/ArchiveWriter/TelemetryPipeline over LoopbackLink drops zero frames on
      the archive path, and the archive read back afterwards holds exactly the multiset of frames
      submitted (no duplicates, no reordering masked by a count-only check)"
    requirement: CAP-02
    verification:
      - kind: integration
        ref: "tests/test_soak.py#test_sustained_combined_bus_load_zero_archive_drops"
        status: pass
    human_judgment: false
  - id: D2
    description: "The archive consumer's never-drop guarantee and the telemetry consumer's
      structurally divergent drop-oldest policy both hold under sustained combined-bus load"
    requirement: CAP-03
    verification:
      - kind: integration
        ref: "tests/test_soak.py#test_sustained_combined_bus_load_zero_archive_drops"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every frame the telemetry path discards, filters, or enqueues is counted and
      reported as an exact number (both queues' high-water marks, discard count, and allowlist-
      filtered count), never inferred from an absence of failure"
    requirement: CAP-05
    verification:
      - kind: integration
        ref: "tests/test_soak.py#test_sustained_combined_bus_load_zero_archive_drops"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every hardware/decode/encode error counter on the fan-out and the telemetry
      pipeline is asserted zero for a clean sustained run, with frame-context logging already in
      place from 01-07/01-08 for the nonzero case"
    requirement: CAP-06
    verification:
      - kind: integration
        ref: "tests/test_soak.py#test_sustained_combined_bus_load_zero_archive_drops"
        status: pass
    human_judgment: false
  - id: D5
    description: "The soak emits a structured JSON record (provenance/configuration/throughput/
      archive/telemetry/pipeline/fan_out_submit) with median and p95 per-stage timing for fan-out
      submit, archive flush/sync, and telemetry encode/framing/send, written to a file, printed,
      and reparsed with a completeness assertion"
    verification:
      - kind: integration
        ref: "tests/test_soak.py#test_sustained_combined_bus_load_zero_archive_drops"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-08-02
status: complete
---

# Phase 1 Plan 13: Sustained Load Soak and Per-Stage Timing Record Summary

**A repeatable soak drives ~18,700 synthetic frames through the real production capture path at
42,880 fps against a 3,730 fps combined target, zero archive-path drops, and emits a nested JSON
record with median/p95 timing for every stage plus its own machine provenance.**

## Performance

- **Duration:** 45 min (this session; continuation of an earlier paused session)
- **Started:** 2026-08-02T11:47:00Z (this continuation)
- **Completed:** 2026-08-02T11:52:00Z
- **Tasks:** 2 (both complete)
- **Files modified:** 2 (`tests/test_soak.py`, `.planning/REQUIREMENTS.md`)

## Accomplishments

- `tests/test_soak.py` drives `SyntheticFrameSource` through the real `FanOut`, `ArchiveRunner`,
  `ArchiveWriter`, and `TelemetryPipeline` over a `LoopbackLink` — not the measurement CLI —
  sustaining 42,880.6 fps against the 3,730 fps combined bus target with zero archive-path drops
  and the archive read-back matching the submitted multiset exactly.
- Every discard, filter, and error counter on the fan-out and telemetry pipeline is asserted and
  reported as a number: telemetry high-water mark 1,000 (queue depth), archive high-water mark
  16,314 (of a 50,000-deep queue), 13 telemetry discards (drop-oldest, expected), 14,139 allowlist-
  filtered, all six error counters zero.
- Per-stage timing instrumented entirely from the test file — no production code touched — for
  fan-out submit, archive flush/sync, telemetry encode, framing (`pack_batch` + `cobs_frame`
  combined), and `Link.send`, each reported as median and p95 (never a mean alone).
- The whole run is emitted as one nested JSON record (`provenance` / `configuration` /
  `throughput` / `archive` / `telemetry` / `pipeline` / `fan_out_submit`), written to
  `tmp_path/"soak_record.json"`, printed to captured output, and reparsed with an assertion on
  every top-level section key.
- Corrected a requirement-traceability error inherited from 01-12: CAP-01 was marked Complete in
  `.planning/REQUIREMENTS.md` in violation of the recorded deferral decision; reverted to Pending
  and documented. CAP-02, CAP-03, CAP-05, CAP-06 verified against the codebase and marked Complete
  as the last plan in Phase 1 to claim them.

## Task Commits

Each task was committed atomically:

1. **Task 1: Sustained full-rate load through the real capture path** — `171535c` (feat) —
   completed in an earlier session; measured 39,303 fps in that run against the same 3,730 fps
   target.
2. **Task 2: Per-stage timing and the reported soak record** — two commits, split across the pause:
   - `55fd078` (wip) — the five timing wrappers (fan-out submit, `writer._flush_and_sync`,
     `encoder.encode`, `pipeline_module.pack_batch`/`cobs_frame`, `link.send`) and the
     `_percentile` helper, committed WIP and verified passing before the pause.
   - `ba196f9` (feat) — this session's work: replaced the flat 13-key print with the nested
     structured record (`provenance`/`configuration`/`throughput`/`archive`/`telemetry`/
     `pipeline`/`fan_out_submit`), the `tmp_path/"soak_record.json"` write, and the reparse
     completeness assertion.

**Deviation commit:** `dc4bde8` (fix) — corrected `.planning/REQUIREMENTS.md` traceability for
CAP-01/02/03/05/06 (see Deviations below).

**Plan metadata:** (this commit, following SUMMARY creation)

_Note: Task 2 was WIP-committed once mid-task by the user's own pause, then finished in this
continuation — not a TDD red/green/refactor split._

## Files Created/Modified

- `tests/test_soak.py` — the sustained-load soak: drives the real production assembly, asserts
  zero archive drops and an exact archive read-back multiset match, per-stage timing wrappers,
  and the nested structured JSON record with provenance
- `.planning/REQUIREMENTS.md` — CAP-01 reverted to Pending (was erroneously Complete); CAP-02,
  CAP-03, CAP-05, CAP-06 marked Complete; a placement note added explaining the CAP-01 deferral

## Decisions Made

- **Corrected accounting identity instead of the plan's literal one.** The plan's action text
  specifies asserting `discard + enqueued + filtered == submitted`. Read against
  `FanOutCounters`'s actual semantics (`src/telemetry/capture/fanout.py` `submit()`, lines
  165–180), that identity double-counts. `submit()` routes every submitted frame through exactly
  one of three outcomes: filtered by the allowlist (`telemetry_filtered_count`), rejected by the
  CAP-06 precheck (`telemetry_unknown_id_count` / `telemetry_payload_too_long_count` /
  `telemetry_unexpected_error_count`), or appended to the bounded telemetry deque
  (`telemetry_enqueued`, incremented exactly once per append). `telemetry_discard_count` is
  incremented *in addition to* `telemetry_enqueued`, on the same append call, precisely when that
  append happened to evict an already-full deque's oldest entry (`was_full` check at line 173,
  both counters incremented for that one incoming frame at lines 176–177). It is not a fourth,
  disjoint bucket of frames that never got enqueued — it is a flag on a subset of the
  already-counted enqueue events, marking which ones cost an older entry its slot. Summing it
  alongside `enqueued` therefore counts every evicting frame twice: once because it was appended
  (enqueued), and again because that same append evicted something (discard). The corrected
  identity implemented and commented in the test (`tests/test_soak.py` lines ~296–312) is
  `telemetry_filtered_count + telemetry_unknown_id_count + telemetry_payload_too_long_count +
  telemetry_unexpected_error_count + telemetry_enqueued == frames_submitted`, with
  `telemetry_discard_count` asserted and reported separately, never summed into the identity.
- **Re-measured rather than transcribed the achieved rate.** Task 1's own commit reported 39,303
  fps; this session's verification run measured 42,880.6 fps under the same target. Both are
  legitimate — the synthetic load generation and thread-scheduling cost varies run to run on
  shared dev hardware — but the plan's own non-negotiable (never transcribe a number from a prior
  document; verify or run) means this SUMMARY reports the figure from the run that actually
  produced this SUMMARY, not the earlier committed number. The soak record's `provenance` section
  makes this reproducible: rerun `pytest tests/test_soak.py -s` on any machine and the record
  names exactly which machine and Python version produced its own numbers.
- **Reverted CAP-01 to Pending rather than leaving 01-12's error in place.** Discovered while
  verifying which requirements this plan is the last claimant of. See Deviations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Reverted CAP-01's erroneous Complete marking in REQUIREMENTS.md**
- **Found during:** Task 2 wrap-up, requirement traceability verification
- **Issue:** `git log -p` showed 01-12 (`eca63ea`) flipped CAP-01's checkbox and traceability row
  to Complete. This contradicts the locked user decision recorded in
  `01-CONTEXT.md`'s `<deferred>` block: CAP-01's "single implementation captures both buses" half
  is met, but its "duplicate implementation removed from the repository" half is deliberately
  deferred to Phase 2 (the user chose to keep `src/neoVI_logger.py`, `src/new_logger.py`,
  `src/references.py`, `src/neoVI_sender.py` for rollback safety). This is the same class of
  mistake the tracer made once already in this phase (reverted in `27e9931`) — a requirement
  marked Complete by a plan that only proved part of it.
- **Fix:** Reverted CAP-01's checkbox and traceability row to `[ ]` / Pending, and added a
  "Notes on placement" entry in REQUIREMENTS.md explaining the deferral and naming the four
  legacy files kept for rollback, matching PROJECT.md's own recorded deferred-scope language.
- **Files modified:** `.planning/REQUIREMENTS.md`
- **Verification:** Re-read the corrected file; checkbox and traceability row now agree (Pending);
  the placement note cross-references `01-CONTEXT.md`.
- **Committed in:** `dc4bde8` (separate deviation commit, not folded into either task commit)

**2. [Rule 1 - Bug] Fixed CAP-03's inconsistent checkbox-vs-traceability state**
- **Found during:** Same traceability verification pass
- **Issue:** CAP-03's checkbox was already `[x]` Complete (set correctly by an earlier plan) but
  its Traceability table row still read `Pending` — the two views of the same requirement had
  drifted apart.
- **Fix:** Set the traceability row to `Complete`, matching the checkbox and the actual codebase
  state (`FanOut`'s divergent archive-never-drop / telemetry-drop-oldest overflow policies,
  implemented in 01-06/01-07, exercised again by this plan's soak).
- **Files modified:** `.planning/REQUIREMENTS.md`
- **Verification:** Checkbox and traceability row now both read Complete.
- **Committed in:** `dc4bde8`

---

**Total deviations:** 2 auto-fixed (both Rule 1 — correctness of the requirement ledger, not new
code behavior)
**Impact on plan:** Neither deviation touched `tests/test_soak.py` or any production code. Both
are corrections to `.planning/REQUIREMENTS.md`'s bookkeeping, made because this plan is the phase's
last opportunity to close out CAP-02/03/05/06 accurately and CAP-01's error would otherwise ship
into the phase transition unnoticed.

## Issues Encountered

None beyond the deviations above. The one remaining code edit (the structured record) worked on
the first `pytest` run; no debugging iteration was needed.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **Phase 1 is now complete: all 13 plans done.** `python -m pytest -q` — the full suite including
  the soak — is green at 283 passed.
- **CAP-02, CAP-03, CAP-05, CAP-06 are Complete.** CAP-01 remains correctly Pending, carried
  forward to Phase 2 alongside GND-03 (Node server retirement) for combined legacy cleanup.
- **What Phase 1 does NOT close, still outstanding per `01-VALIDATION.md`'s Manual-Only
  Verifications table:**
  - The physical power-pull durability test (ARCH-02/ARCH-03) — a SIGKILL proxy cannot prove
    fsync correctness; only cutting real power on the bench does. Procedure in
    `docs/power-pull-test.md`.
  - Running this same soak on the CM4 itself — every fps figure in this record (and in
    01-RESEARCH.md) is x86-64 dev-hardware-only; the record's own `provenance` field says so
    explicitly so this caveat cannot be silently dropped by a future reader.
  - Dual-bus capture against real neoVI hardware — no hardware is attached to the dev machine.
- **Every prose figure in this SUMMARY has a provenance trail.** The 42,880.6 fps number is this
  session's actual measured run, reproducible by rerunning `pytest tests/test_soak.py -s` and
  reading the printed record's own `provenance`/`throughput` sections — not a transcription.
- **Ready for phase transition:** code review → phase verification → `/gsd-transition` to Phase 2.

---
*Phase: 01-dual-path-capture-durable-archive-and-thin-live-link*
*Completed: 2026-08-02*

## Self-Check: PASSED

- FOUND: `tests/test_soak.py`
- FOUND: `.planning/REQUIREMENTS.md`
- FOUND: `.planning/phases/01-dual-path-capture-durable-archive-and-thin-live-link/01-13-SUMMARY.md`
- FOUND commit: `171535c` (Task 1)
- FOUND commit: `55fd078` (Task 2 WIP instrumentation)
- FOUND commit: `ba196f9` (Task 2 structured record)
- FOUND commit: `dc4bde8` (requirement traceability fix)
