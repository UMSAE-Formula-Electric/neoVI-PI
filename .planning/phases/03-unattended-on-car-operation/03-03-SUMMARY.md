---
phase: 03-unattended-on-car-operation
plan: 03
subsystem: ops
tags: [typing-protocol, heartbeat, led, package-legitimacy, i2c]

# Dependency graph
requires:
  - phase: 03-01
    provides: "HeartbeatPublisher and its periodic-tick / publish_now write loop, which this plan's LedIndicator call site hooks into"
provides:
  - "LedIndicator Protocol (typing.Protocol, two methods: set_state/close) mirroring telemetry.link.base.Link's structural-typing convention"
  - "NullLedIndicator, the no-op default HeartbeatPublisher injects when no led= is supplied"
  - "A call site inside HeartbeatPublisher's write loop and publish_now that drives the indicator on every write, wrapped so a raising indicator never takes down the status file or the publisher thread"
  - "A resolved human decision on the real membrane LED: approve-and-replan, with smbus2 approved and RPi.GPIO descoped through the package-legitimacy-check seam"
  - "The neoVI PI boot-config path (/boot/firmware/config.txt) confirmed against real hardware, superseding Intrepid's own doc"
affects: ["03-05 (heartbeat/OPS-02 requirement owner)", "a future MembraneLedIndicator driver plan"]

# Tech tracking
tech-stack:
  added: []
  patterns: ["typing.Protocol seam for swappable hardware indicators, mirroring Link/FrameSource"]

key-files:
  created:
    - src/telemetry/ops/led.py
    - tests/test_ops_led.py
  modified:
    - src/telemetry/ops/heartbeat.py
    - tests/test_ops_heartbeat.py
    - .planning/phases/03-unattended-on-car-operation/03-RESEARCH.md

key-decisions:
  - "Checkpoint resolved approve-and-replan (real membrane LED wanted this milestone), not the plan's own planned default of defer"
  - "smbus2 approved for a future MembraneLedIndicator follow-up plan; RPi.GPIO descoped (strongly indicated not needed -- pure I2C shutdown register -- but not proven against the full membrane.py)"
  - "Boot overlay path resolved to /boot/firmware/config.txt, user-confirmed against real hardware, contradicting Intrepid's own doc (which is wrong for Bookworm)"
  - "This plan (03-03) still ships only NullLedIndicator -- the concrete MembraneLedIndicator is deliberately left for a follow-up plan that also needs real neoVI PI hardware to verify"
  - "Task 2 was executed before Task 1 by the previous executor; recorded honestly rather than silently renumbered"

patterns-established:
  - "A checkpoint's resume signal can flip a plan's shipped default (defer vs approve-and-replan) without reopening the plan itself -- the abstraction ships either way; only the docstring recording the decision changes"

requirements-completed: []

coverage:
  - id: D1
    description: "LedIndicator Protocol + NullLedIndicator exist with a two-method surface mirroring Link, and are satisfied/exercised by tests"
    verification:
      - kind: unit
        ref: "tests/test_ops_led.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "HeartbeatPublisher drives the indicator on every periodic tick and publish_now; a raising indicator never kills the status-file write or the publisher thread; close() fires exactly once"
    verification:
      - kind: unit
        ref: "tests/test_ops_heartbeat.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "requirements.txt stays byte-identical -- no new runtime dependency entered the project this plan"
    verification:
      - kind: other
        ref: "git diff --exit-code -- requirements.txt"
        status: pass
    human_judgment: false
  - id: D4
    description: "Human checkpoint on the two candidate packages (smbus2/RPi.GPIO) resolved and recorded, including the package-legitimacy-check verdicts and the boot-path confirmation"
    verification: []
    human_judgment: true
    rationale: "The checkpoint's outcome is a human decision (approve-and-replan), not something a test can assert; recorded in 03-RESEARCH.md's Package Legitimacy Audit table and this SUMMARY's Decisions section."

duration: 22min
completed: 2026-09-30
status: complete
---

# Phase 03 Plan 03: Status LED Seam and Package Checkpoint Summary

**`LedIndicator` Protocol seam wired into `HeartbeatPublisher`, plus a resolved human checkpoint approving a future real membrane LED driver (smbus2 approved, RPi.GPIO descoped, boot path confirmed) with nothing installed yet**

## Performance

- **Duration:** ~22 min across two executor sessions (139b20f at 23:44:57, checkpoint resolution + this continuation closing at 00:06:12)
- **Started:** 2026-09-29T23:44:57-05:00 (approx, first commit timestamp)
- **Completed:** 2026-09-30T00:06:12-05:00
- **Tasks:** 2 (Task 2 executed first, then Task 1's checkpoint, now resolved)
- **Files modified:** 5 (`src/telemetry/ops/led.py`, `src/telemetry/ops/heartbeat.py`, `tests/test_ops_led.py`, `tests/test_ops_heartbeat.py`, `.planning/phases/03-unattended-on-car-operation/03-RESEARCH.md`)

## Accomplishments

- `LedIndicator` (a `typing.runtime_checkable` `Protocol`, two methods: `set_state`/`close`) and `NullLedIndicator`, mirroring `telemetry.link.base.Link`'s structural-typing convention
- `HeartbeatPublisher` gained an optional `led:` constructor argument (defaulting to `NullLedIndicator()`), called on every periodic tick and `publish_now`, after the status file write, wrapped so a raising indicator never kills the write or the publisher thread; `close()` fires exactly once on stop
- The Task 1 blocking checkpoint was resolved by the user: **approve-and-replan** for a real membrane LED this milestone
- `smbus2` ran through the package-legitimacy-check seam and is **approved** for a future driver plan; `RPi.GPIO` ran the same seam and is **descoped** (not approved, not needed for the currently-understood pure-I2C shutdown path)
- The neoVI PI's boot-config overlay path is now **confirmed** as `/boot/firmware/config.txt` against real hardware, correcting Intrepid's own published doc (which is wrong for Bookworm)
- `src/telemetry/ops/led.py`'s docstrings rewritten to describe the resolved decision rather than the plan's original deferred-default framing

## Task Commits

Each task was committed atomically:

1. **Task 2: `LedIndicator` Protocol, `NullLedIndicator`, publisher call site** - `139b20f` (feat) -- executed by the previous executor session
2. **Task 1: Package gate checkpoint** - resolved by the user; results committed by the orchestrator in `c589fb6` (docs: boot path + package legitimacy verdicts in 03-RESEARCH.md)
3. **This continuation: `led.py` docstring update to the resolved decision** - `9c49bc1` (docs)

**Plan metadata:** (this commit, see below)

_Note: this plan's checkpoint (Task 1) runs first by design in the plan file, deciding Task 2's scope, but the previous executor session ran Task 2 before reaching the checkpoint. See Deviations below._

## Files Created/Modified

- `src/telemetry/ops/led.py` - `LedIndicator` Protocol, `NullLedIndicator`; docstrings now describe the resolved approve-and-replan decision, the `smbus2`/`RPi.GPIO` legitimacy verdicts, and the confirmed `/boot/firmware/config.txt` boot path
- `src/telemetry/ops/heartbeat.py` - `HeartbeatPublisher.__init__` gained `led: Optional[LedIndicator] = None`; write loop and `publish_now` call `led.set_state(...)` after the status-file write, wrapped in a log-once-then-suppress guard; stop path calls `led.close()` exactly once
- `tests/test_ops_led.py` - Protocol-satisfaction assertions, repeated-call safety, recording/raising double behavior
- `tests/test_ops_heartbeat.py` - N-tick call-count assertions against a recording double; raising-double survival assertion; single `close()` assertion
- `.planning/phases/03-unattended-on-car-operation/03-RESEARCH.md` - boot path resolved from `[ASSUMED]` to user-confirmed; `## Package Legitimacy Audit` table added recording both verdicts (committed by the orchestrator prior to this continuation, not by this agent)

## Decisions Made

- **Checkpoint resolved `approve-and-replan`, not the plan's planned default `defer`.** The user wants the real membrane LED working this milestone. Nothing was installed by this decision alone — it authorizes a *follow-up* plan for a concrete `MembraneLedIndicator`, and routed the two candidate packages through the package-legitimacy-check seam now so that follow-up plan doesn't have to re-run it.
- **`smbus2` approved.** `SUS` verdict's sole reason was `unknown-downloads` (a checker metadata-fetch failure, the identical artifact Phase 0 adjudicated for `cantools`/`pytest` — not a supply-chain finding). Substantively clean: exists, not deprecated, `postinstall: null`, repo `github.com/kplindegaard/smbus2`, last published 2026-04-09.
- **`RPi.GPIO` descoped, not approved.** Same `SUS`/`unknown-downloads`-only verdict, substantively clean too, but not currently needed: in Intrepid's `membrane.py` it drives `MULTI_BUTTON`/`TRIG_BUTTON` (operator input, out of scope for OPS-01/02/03/07), while the LED driver itself is pure I2C and shuts down via an I2C register. **This is strongly indicated, not proven** — the follow-up driver plan must confirm against the full `membrane.py` before relying on it, and may still need to add `RPi.GPIO` back if that confirmation goes the other way.
- **Boot overlay path resolved to `/boot/firmware/config.txt`.** User-confirmed against this car's real neoVI PI hardware — provenance is explicitly recorded as user-confirmed, not a measurement this project took, and it corrects Intrepid's own published doc (which says `/boot/config.txt`, wrong for current Raspberry Pi OS Bookworm images).
- **This plan still ships only `NullLedIndicator`.** The concrete `MembraneLedIndicator` needs real neoVI PI hardware to verify and is deliberately left for a follow-up plan, per the checkpoint's own `approve-and-replan` semantics ("a new plan is written for the concrete driver... because it also needs real hardware to verify and this phase has exactly one hardware-only item budgeted").
- **No requirement marked Complete in this plan.** OPS-02 ownership stays with 03-05 per the plan's own frontmatter ("Marks: none. Addresses OPS-02; 03-05 is the sole marker"); `.planning/REQUIREMENTS.md` untouched by this plan.

## Deviations from Plan

### Out-of-order task execution (not an auto-fix — recorded per orchestrator instruction)

The plan's own Task 1 (the package checkpoint) explicitly says it "runs FIRST because it decides the scope of Task 2." The previous executor session instead executed Task 2 first, then reached and stopped at Task 1's blocking checkpoint. This was flagged honestly by that session rather than hidden, and this continuation preserves that fact rather than renumbering or silently correcting the history. In practice this did not change the shipped outcome: Task 2's implementation (`LedIndicator`/`NullLedIndicator`/the publisher call site) is exactly what the plan specifies regardless of checkpoint outcome, since both `defer` and `approve-and-replan` ship the identical seam — only the *docstring's description of the human decision* depends on the checkpoint's answer, and that has now been corrected to match the actual resolution in this continuation's commit (`9c49bc1`).

### Auto-fixed Issues

None — plan executed as specified once resumed; no Rule 1/2/3 auto-fixes were needed in this continuation.

---

**Total deviations:** 1 (out-of-order task execution, honestly flagged, no functional impact)
**Impact on plan:** None on the shipped code. The only correction needed in this continuation was updating `led.py`'s docstrings to reflect the real checkpoint answer instead of the plan's assumed default.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. The approved `smbus2` package is not installed by this plan; installation is explicitly deferred to the follow-up `MembraneLedIndicator` driver plan.

## Follow-up Plan Needed

**A concrete `MembraneLedIndicator` implementation is not yet planned.** It will need to:
- Add `smbus2` to `requirements.txt` with an exact pin (approved package; not yet installed)
- Confirm against the full `membrane.py` reference script whether `RPi.GPIO` is genuinely unneeded (currently strongly indicated, not proven) before deciding whether to add it too
- Target I2C bus 10, address `0x3c`, per Intrepid's reference script
- Assume the `i2c_vc` device-tree overlay is enabled in `/boot/firmware/config.txt` (user-confirmed path for this car)
- **Requires real neoVI PI hardware to verify** — this is the one hardware-only item this phase has budgeted for the LED driver, per the checkpoint's own resume-signal text.

## Next Phase Readiness

- The `LedIndicator` seam is complete, tested, and already live in `HeartbeatPublisher` — a future `MembraneLedIndicator` can be injected with no call-site changes.
- The human decision this plan's checkpoint exists to produce is now fully resolved and recorded in both `03-RESEARCH.md` and this SUMMARY.
- `requirements.txt` remains byte-identical to before this plan; no new runtime dependency entered the project.
- 03-05 remains the sole owner of marking OPS-02 Complete in `.planning/REQUIREMENTS.md`.

---
*Phase: 03-unattended-on-car-operation*
*Completed: 2026-09-30*

## Self-Check: PASSED

- FOUND: src/telemetry/ops/led.py
- FOUND: .planning/phases/03-unattended-on-car-operation/03-03-SUMMARY.md
- FOUND commit: 139b20f
- FOUND commit: c589fb6
- FOUND commit: 9c49bc1
- Full test suite: 378 passed (matches baseline)
- `git diff --exit-code -- requirements.txt`: clean (no changes)
