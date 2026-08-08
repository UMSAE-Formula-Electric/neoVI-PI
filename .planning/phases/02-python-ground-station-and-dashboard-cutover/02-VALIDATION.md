---
phase: 02
slug: python-ground-station-and-dashboard-cutover
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-08
---

# Phase 02 — Validation Strategy

> Per-phase validation contract, reconstructed retroactively (State B: no prior
> VALIDATION.md existed; `02-VERIFICATION.md` — passed 9/9 — and the four
> plan/summary pairs were used as source material, then independently
> re-checked against the actual test files and a live pytest run rather than
> transcribed).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (pinned in `requirements.txt`) |
| **Config file** | none committed — plain `pytest` discovery over `tests/` |
| **Quick run command** | `python -m pytest -q tests/test_ground_server.py tests/test_ground_simulate.py tests/test_ground_cli.py tests/test_end_to_end.py tests/test_legacy_cutover.py` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~21s (ground-station subset); full suite not separately timed this session |

Re-run directly during this audit (2026-08-08): `44 passed` for the ground-station
subset above. (One harmless `ConnectionResetError` traceback appears in stderr
from a test that deliberately drops a client mid-response — it is printed by
`BaseHTTPServer`'s background thread, not a test failure; the `44 passed`
summary line is authoritative.)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01 (SignalState, snapshot, SSE hub) | 01 | 1 | GND-02, GND-04, GND-05 | integration | `pytest tests/test_ground_server.py -k "snapshot or update_after_snapshot or wall_clock or shutdown_from_decode_thread"` | ✅ | ✅ green |
| 02-01 (slow/dead client backpressure isolation) | 01 | 1 | GND-04 | integration | `pytest tests/test_ground_server.py -k "slow_client or broadcast_never_blocks or dead_client_is_unregistered"` | ✅ | ✅ green |
| 02-02 (dashboard.html port to EventSource, `/`, `/state` routes) | 02 | 2 | GND-02, GND-04, GND-05 | integration + file-content | `pytest tests/test_ground_server.py -k "root_serves or state_route or event_stream_transport or traversal"` | ✅ | ✅ green |
| 02-02 (staleness dim/revert, no-results copy, CR-01/WR-01 fixes) | 02 | 2 | GND-04 (UI affordance, no separate v1 ID) | file-content assertion + live manual re-check | `pytest tests/test_ground_server.py -k "stale or message_group_id or signal_range_tracking"` | ✅ | ⚠️ green, DOM-behavior unverified by automation (see Manual-Only) |
| 02-03 (simulate.py, real wire path, no re-implementation of encode) | 03 | 3 | GND-03 (dev-stand-in enabling removal) | integration | `pytest tests/test_ground_simulate.py` | ✅ | ✅ green |
| 02-04 (Node dashboard + legacy logger modules removed; regression gate) | 04 | 4 | GND-03, CAP-01 | integration (ast-based import scan + filesystem) | `pytest tests/test_legacy_cutover.py` | ✅ | ✅ green |
| 02-01/02-02 (single process serves decode pipeline + dashboard, no same-machine pipe) | 01, 02 | 1–2 | GND-02 | end-to-end (real subprocess, real UDP, real HTTP GET) | `pytest tests/test_end_to_end.py -k test_serving_mode_is_one_process_no_pipe` | ✅ | ✅ green |

*Status: ✅ green (verified by direct re-run this audit) · ⚠️ green-with-caveat · ❌ red · ⬜ pending*

Every requirement ID this phase owns (GND-02, GND-03, GND-04, GND-05, CAP-01) has
at least one passing automated test that discriminates the required behavior
from its absence (e.g. `test_serving_mode_is_one_process_no_pipe` opens a real
UDP+HTTP conversation against a real subprocess and would fail if the
architecture reverted to two processes joined by a stdout pipe;
`test_legacy_cutover.py` fails if any deleted module reappears or is
re-imported). None of these are presence-only/tautological tests — confirmed
by reading each test body, not by trusting its name.

---

## Wave 0 Requirements

None. `pytest` and all fixtures already existed from Phase 1; no new test
framework or scaffolding was required to cover this phase's requirements.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Dashboard DOM rendering: staleness dim-and-revert timing, message-group collapse/toggle click behavior, mini-range-bar width, no-results vs. waiting-for-data copy switching, channel-tab switching, live value rendering at ~4000 msg/s | GND-04, GND-05 (UI affordance layer; no dedicated v1 requirement ID names DOM rendering) | No browser-automation tooling (Selenium/Playwright) is installed or pinned in `requirements.txt`; the committed `tests/test_ground_server.py` dashboard tests are honest about this in their own docstrings ("this is a file-content assertion... it cannot prove a click in a real browser toggles `.collapsed`"). Adding a browser-automation dependency was out of scope for this retroactive audit — it is a nontrivial new dependency (binary browser download, CI implications) that the phase's own scope never budgeted for, and the project's stated constraint is to keep the ground station a single lean Python process. | Run `python -m telemetry.ground.cli --serve` (or `telemetry.ground.simulate` feeding it), open the served URL in a browser, and walk `02-UI-SPEC.md`'s affordance list: confirm channel tabs, search, per-message/per-signal toggles, staleness dimming after ~3s of no updates and reversion on resume, message-group collapse via click, and no-results copy differing from the empty/waiting state. This was performed once, live, in Chrome, during this phase's own verification pass (recorded in `02-VERIFICATION.md` and `WINDOWS.md` id=1/id=2) — it is real evidence but not a repeatable, CI-enforced test, and will not re-run itself on the next change to `dashboard.html`. |

This gap was already disclosed in `02-VERIFICATION.md` (score noted 9/9 with
this caveat named explicitly) and `02-UI-REVIEW.md`. This audit does not
introduce new disclosure — it independently re-confirms the caveat is accurate
(the file-content tests really are file-content tests; no DOM test exists in
`tests/`) and records the reason a headless-browser test was not retroactively
added: doing so would require introducing a new runtime dependency
(Playwright/Selenium + browser binaries) not currently present anywhere in
this project's pinned `requirements.txt`, which is a scope decision for a
future phase (Phase 6, Live Display, is the next phase that touches this UI
surface), not a silent gap in this one.

---

## Validation Sign-Off

- [x] All tasks have automated verify or a documented Manual-Only justification
- [x] Sampling continuity: every requirement ID (GND-02/03/04/05, CAP-01) has a passing automated test re-run this audit
- [x] Wave 0 covers all MISSING references — none were missing
- [x] No watch-mode flags in any command listed above
- [x] Feedback latency: ground-station subset ~21s, well under any reasonable threshold
- [x] `nyquist_compliant: true` set in frontmatter — true because every phase requirement ID has automated coverage; the one caveat (DOM rendering) is an explicitly disclosed, justified Manual-Only item outside any single v1 requirement ID's literal text, not an unautomated requirement

**Approval:** approved 2026-08-08

---

## Validation Audit 2026-08-08

| Metric | Count |
|--------|-------|
| Gaps found | 1 (dashboard DOM/browser behavioral coverage — no automated harness) |
| Resolved | 0 (justified SKIP — see Manual-Only table; no new browser-automation dependency added retroactively) |
| Escalated | 0 (not an implementation bug; a disclosed, accepted tooling-scope gap) |

Requirement-level result: GND-02, GND-03, GND-04, GND-05, CAP-01 all have
real, passing, behavior-discriminating automated tests, independently
re-run during this audit (`44 passed`, ground-station subset). No prose
figure in this document was transcribed from a SUMMARY without independent
re-verification against the actual test files and a live pytest run.
