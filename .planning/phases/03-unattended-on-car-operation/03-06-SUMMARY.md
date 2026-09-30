---
phase: 03-unattended-on-car-operation
plan: 06
subsystem: infra
tags: [systemd, deploy, install-script, structural-lint, ops-01]

# Dependency graph
requires:
  - phase: 03-01
    provides: "config.ops.heartbeat_path and the earliest-point-known heartbeat construction convention this unit's ExecStart process relies on"
  - phase: 03-04
    provides: "the waiting-for-hardware boot race and the terminal stopped-error heartbeat state that make Restart=always paired with a rate limit the correct, honest supervision contract -- the logger stays alive through an unpowered bus instead of exiting, preserving the restart budget for real faults"
  - phase: 03-05
    provides: "telemetry-status, the command the runbook and this plan's install-script comments point an operator at for diagnosis after the unit starts"
provides:
  - "deploy/telemetry-logger.service: a version-controlled systemd unit -- StartLimitIntervalSec/StartLimitBurst in [Unit] (verified zero-warning against real systemd-analyze verify, systemd 259 via WSL), Restart=always, User=telemetry non-root, no device-unit After= dependency"
  - "deploy/install.sh: one-command install -- idempotent service-account creation, a /opt/telemetry layout check, install -m 644 + daemon-reload + enable --now in the correct order, archive-root/heartbeat-dir creation+chown"
  - "tests/test_deploy_unit_file.py: a hand-rolled, line-based structural checker (parse_unit_file) proving the unit's shape -- never configparser"
affects: ["03-07 (sole OPS-01 marker; owns the honesty gate deciding whether this plan's structural proof is sufficient, plus the single Pi bring-up item covering the four deployment assumptions listed below)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Hand-rolled line-based parser returning section -> ORDERED LIST of (key, value) pairs (never a dict) so a systemd unit's legitimately repeatable keys survive a structural lint intact -- the stdlib INI-style parser is unsafe for this artifact type and is never imported"
    - "Checker and its tests live in one file (tests/test_deploy_unit_file.py) rather than a separate production module, since no ops/ package concern owns deploy/ artifacts and 03-PATTERNS.md flagged this as a no-analog artifact type"

key-files:
  created:
    - deploy/telemetry-logger.service
    - deploy/install.sh
    - tests/test_deploy_unit_file.py
  modified: []

key-decisions:
  - "StartLimitIntervalSec/StartLimitBurst placed in [Unit], verified live twice this session -- once against 03-RESEARCH.md's WSL systemd 259 finding (reproduced independently: copying the shipped file into native WSL and running systemd-analyze verify against it returns exit code 0 with zero warnings), and once by the hand-rolled checker's own parsed-section assertions"
  - "install.sh's three additions beyond the researched Pattern 2 (idempotent service-account creation, a /opt/telemetry layout check, archive-root/heartbeat-dir creation+chown) are each commented in the script as additions the research pattern did not cover, and named again in this SUMMARY's deployment-assumptions list for 03-07's single Pi bring-up item -- not treated as proven by any command runnable on this Windows dev box"
  - "The checker's own docstrings and comments never write the literal string the plan's central trap forbids -- git grep -n confirms zero occurrences in tests/test_deploy_unit_file.py, checked twice (once after RED, once after GREEN)"
  - "The stop-timeout guard test (TimeoutStopSec >= 2x _SHUTDOWN_JOIN_TIMEOUT_S) passes vacuously against the shipped file, which declares no such key by design (03-RESEARCH.md's own instruction: an unverified number would be a figure with no measurement behind it) -- the test's docstring states this explicitly so a future reader does not mistake vacuous passage for proof"

patterns-established:
  - "A no-analog deploy/ artifact type gets its structural lint colocated with its checker function in one test file, rather than forcing a production-module split that has no other caller"

requirements-completed: []  # Marks: none, per this plan's own frontmatter and objective. OPS-01's status is decided by 03-07's honesty gate; .planning/REQUIREMENTS.md is untouched by this plan.

coverage:
  - id: D1
    description: "deploy/telemetry-logger.service reproduces the researched, systemd-analyze-verify-clean unit structure: rate-limit keys in [Unit], Restart=always, non-root User=, no device-unit After= dependency, ExecStart/PYTHONPATH matching the invocation the tracer proved"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_unit_section_contains_both_rate_limit_keys"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_service_section_key_set_excludes_rate_limit_keys"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_service_declares_restart_always"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_service_declares_non_root_user"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_service_execstart_names_logger_cli_module"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_service_environment_sets_pythonpath_to_src"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_no_after_value_names_a_device_unit"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_install_declares_wantedby_multi_user_target"
        status: pass
      - kind: other
        ref: "wsl -e systemd-analyze verify /tmp/gsd-verify/telemetry-logger.service (systemd 259) -- exit 0, zero warnings"
        status: pass
    human_judgment: false
  - id: D2
    description: "deploy/install.sh is one command: creates the service account idempotently, verifies the /opt/telemetry layout, installs the unit with explicit mode bits, daemon-reload before enable --now, and creates+chowns the archive root and heartbeat directory"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_unit_user_account_name_appears_literally_in_install_script"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_install_script_sets_strict_mode"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_install_script_uses_mode_setting_install_invocation"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_install_script_daemon_reload_precedes_enable"
        status: pass
      - kind: other
        ref: "bash -n deploy/install.sh"
        status: pass
    human_judgment: false
  - id: D3
    description: "The structural checker is hand-rolled and line-based, never the stdlib INI-style parser; it preserves duplicate keys (proven against a synthetic snippet, not the shipped unit) and rejects malformed/misplaced lines by naming the line number"
    requirement: "OPS-01"
    verification:
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_duplicate_key_within_one_section_survives_as_both_values"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_malformed_line_raises_naming_line_number"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_key_value_line_before_any_section_header_raises"
        status: pass
      - kind: unit
        ref: "tests/test_deploy_unit_file.py::test_comment_and_blank_lines_are_skipped"
        status: pass
      - kind: other
        ref: "git grep -n \"configparser\" -- tests/test_deploy_unit_file.py (checked after both RED and GREEN commits; zero matches both times)"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-09-30
status: complete
---

# Phase 3 Plan 6: systemd Unit, Install Script, and Structural Lint Summary

**`deploy/telemetry-logger.service` (rate-limit keys correctly in `[Unit]`, non-root `User=telemetry`, no device-unit dependency) plus `deploy/install.sh` (one command: account creation, layout check, `daemon-reload`-before-`enable --now`, archive/heartbeat directory ownership) proven by a hand-rolled, line-based structural checker in `tests/test_deploy_unit_file.py` that never imports the stdlib INI parser and preserves duplicate keys by construction.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 2 (Task 1 unit + install script, Task 2 TDD structural lint)
- **Files modified:** 3 created (`deploy/telemetry-logger.service`, `deploy/install.sh`, `tests/test_deploy_unit_file.py`), 0 modified

## Accomplishments

- `deploy/telemetry-logger.service` reproduces 03-RESEARCH.md's Pattern 1 verbatim: `StartLimitIntervalSec=60`/`StartLimitBurst=5` in `[Unit]` (not `[Service]`, where systemd would silently ignore them), `Restart=always` with `RestartSec=2`, `User=telemetry` (dedicated non-root account), `WorkingDirectory=/opt/telemetry` with `Environment=PYTHONPATH=src`, `ExecStart=/usr/bin/python3 -m telemetry.logger.cli`, and `After=network.target local-fs.target`/`Wants=network.target` with deliberately no device-unit dependency — the `waiting-for-hardware` retry loop (03-04) owns that race in application code.
- `deploy/install.sh` reproduces Pattern 2's verified commands in order (`install -m 644` → `systemctl daemon-reload` → `systemctl enable --now`) plus three flagged additions: idempotent `telemetry` system-account creation (`useradd --system --no-create-home --shell /usr/sbin/nologin`, skipped if the account already exists), a fail-fast check that `/opt/telemetry` looks like a real deployed checkout (`src/telemetry` and `config/logger.json` present) before installing anything, and creation+chown of the archive root (`/opt/telemetry/sessions`) and heartbeat directory (`/opt/telemetry/var`) so the unprivileged service can actually write both on first boot. The script never silently overwrites an existing unit file — it checks first and prints a note if one is already present, satisfying this project's "check-then-act, never clobber" rule for anything under `/etc`.
- `tests/test_deploy_unit_file.py` hand-rolls `parse_unit_file(text) -> dict[str, list[tuple[str, str]]]` — a line-based structural checker returning an **ordered list** of `(key, value)` pairs per section (never a dict), so a section's legitimately repeated key survives intact. 19 tests cover: duplicate-key preservation (against a synthetic snippet, never the shipped unit, which has only one `After=` line), malformed-line and pre-section-header rejection (both naming the offending line number), the shipped file's exactly-three-sections-each-once shape, the rate-limit keys' section placement (positive in `[Unit]`, negative in `[Service]`), `Restart=always`, a non-root `User=`, `ExecStart`/`Environment` matching the proven invocation, `WantedBy=multi-user.target`, no `After=` naming a `.device` unit, a conditional (currently-vacuous, explicitly documented as such) stop-timeout guard tied to `_SHUTDOWN_JOIN_TIMEOUT_S`, unit/installer account-name agreement, and three `install.sh` shape assertions (strict mode, the mode-setting `install` invocation, `daemon-reload` preceding `enable --now`).
- **Supplementary, non-gating verification**: the shipped unit was copied into WSL Ubuntu's native filesystem (not through the `/mnt/c` Windows mount, which produces a spurious executable-bit warning) and run through the real `systemd-analyze verify` binary (systemd 259) — exit code 0, zero warnings, independently reproducing 03-RESEARCH.md's own finding rather than trusting the prior session's report. This is a validation tool, not a toolchain dependency, and is explicitly not a gate for this plan per the plan's own `<human-check>` text.

## Task Commits

Each task was committed atomically. Task 2 (`tdd="true"`) has two commits, RED then GREEN:

1. **Task 1: `deploy/telemetry-logger.service` and `deploy/install.sh`** — `429cfb4` (feat)
2. **Task 2 RED: failing structural-checker tests** — `28df103` (test)
3. **Task 2 GREEN: implement the checker** — `05ce793` (feat)

**Plan metadata:** (this commit, see below)

## Files Created/Modified

- `deploy/telemetry-logger.service` — the systemd unit; verified zero-warning against real `systemd-analyze verify` (systemd 259, via WSL) both in 03-RESEARCH.md's prior session and independently reproduced this session
- `deploy/install.sh` — the one-command installer; `bash -n`-clean; three additions beyond the researched pattern, each commented as such
- `tests/test_deploy_unit_file.py` — `parse_unit_file` (the hand-rolled checker) plus 19 tests covering every behavior bullet in the plan

## Decisions Made

- **`StartLimitIntervalSec`/`StartLimitBurst` placement verified twice, independently.** Once by reproducing 03-RESEARCH.md's own WSL `systemd-analyze verify` finding against the actual shipped file (not just trusting the prior session's report text), and once structurally by the checker's parsed-section assertions. Both agree: `[Unit]`, never `[Service]`.
- **The stop-timeout guard test is deliberately vacuous today, and says so in its own docstring.** The shipped unit declares no `TimeoutStopSec` at all — per 03-RESEARCH.md's own instruction, an unverified number would be a figure with no measurement behind it. The test exists to catch a *future* edit that adds one shorter than `_SHUTDOWN_JOIN_TIMEOUT_S * 2`, not to prove anything about the current text.
- **The checker and its tests live in one file, not a checker module plus a separate test file.** No `src/telemetry/ops/` (or any other) package concern owns `deploy/` artifacts, and 03-PATTERNS.md explicitly flagged this artifact type as having no in-repo analog — colocating avoids inventing a production module with exactly one caller.
- **`configparser` never appears in `tests/test_deploy_unit_file.py`**, not even in a comment explaining why it is avoided — the plan's verification requires the literal string to be absent, so the rationale is phrased generically ("the stdlib INI-style parser") wherever it would otherwise need naming. Confirmed via `git grep -n` after both the RED and the GREEN commit.
- **`/boot/firmware/config.txt` is not referenced anywhere in this plan's files** — neither the unit nor the install script touches boot configuration; the LED/I2C overlay work that path belongs to remains deferred per 03-03's SUMMARY.

## Deviations from Plan

None — plan executed exactly as written. Both tasks matched their `<action>` and `<done>` criteria without needing a Rule 1–4 fix.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. `deploy/install.sh` is written to run on a real Pi with `sudo`, which is out of scope for this Windows dev-box session (and is exactly the boundary 03-07's single Pi bring-up item exists to cover).

## Next Phase Readiness

- The systemd unit and installer are version-controlled and reproducible, not prose — the phase's single most recorded failure mode (a unit file that exists only in a runbook and drifts from reality) cannot recur for this artifact.
- The one systemd mistake that fails silently rather than loudly (rate-limit keys in the wrong section) is caught by a parsed, hand-rolled assertion, never the stdlib INI parser.
- **Four deployment assumptions are carried forward, unverified from this Windows dev box, as items for 03-07's single Pi bring-up verification** — not new UAT items, per this plan's own `<output>` instruction:
  1. The `/opt/telemetry` layout itself (that the deployed checkout actually lives there, with `src/telemetry` and `config/logger.json` present).
  2. The service-account creation step (`useradd --system --no-create-home --shell /usr/sbin/nologin`) actually succeeding and producing an account the unit can run as on real Raspberry Pi OS Bookworm.
  3. The archive-root and heartbeat-directory ownership (`chown telemetry:telemetry`) actually granting the unprivileged process write access it needs on first boot.
  4. `After=local-fs.target` being sufficient ordering for the NVMe-backed archive path (03-RESEARCH.md's Assumption A2) — if the archive volume turns out to be a separate, later-mounting filesystem, this would surface immediately as a startup failure on first real deployment, not silently.
- **OPS-01 remains Pending**, exactly as this plan's frontmatter and objective specify. `.planning/REQUIREMENTS.md` was not touched. 03-07 owns the honesty-gate decision on whether this plan's structural proof plus the eventual Pi bring-up item is sufficient to mark it Complete.
- No blockers. Full suite: 416 → 435 passing (+19, all in `tests/test_deploy_unit_file.py`). `git diff --exit-code -- requirements.txt` confirmed clean (no new runtime dependency — this plan installs nothing).

## Self-Check: PASSED

- FOUND: deploy/telemetry-logger.service
- FOUND: deploy/install.sh
- FOUND: tests/test_deploy_unit_file.py
- FOUND commit: 429cfb4
- FOUND commit: 28df103
- FOUND commit: 05ce793
- Full test suite: 435 passed (baseline 416 + 19 new)
- `git diff --exit-code -- requirements.txt`: clean (no changes)
- `git grep -n "configparser" -- tests/test_deploy_unit_file.py`: zero matches
- `bash -n deploy/install.sh`: parses cleanly
- Supplementary: `wsl -e systemd-analyze verify` against the shipped unit (systemd 259): exit 0, zero warnings

---
*Phase: 03-unattended-on-car-operation*
*Completed: 2026-09-30*
