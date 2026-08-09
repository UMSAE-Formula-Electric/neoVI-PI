# Phase 3: Unattended On-Car Operation - Context

**Gathered:** 2026-08-09
**Status:** Ready for planning
**Mode:** mvp (declared in ROADMAP.md — plan as a vertical slice)

<domain>
## Phase Boundary

The car logs every run without anyone touching a keyboard, and anyone on the team can tell whether
it is working. Concretely this phase delivers four things and nothing else:

1. **Automatic start on power-up** (OPS-01) — no screen, no keyboard, no login.
2. **A heartbeat that says alive *and* capturing** (OPS-02) — legible to someone standing at the car.
3. **Disk-space monitoring surfaced early** (OPS-03) — while there is still time to act.
4. **A written runbook** (OPS-07) — usable by someone who did not build the system.

**Explicitly NOT in this phase:**
- Remote/link-borne health reporting. Distinguishing "steady" from "we stopped hearing from it"
  over the radio is **Phase 6** scope, and Phase 2 already deferred its amber/red link-health
  states there on the same reasoning. Do not reopen that boundary here.
- Wire-protocol recovery behaviour (Phase 4) and transmit shaping (Phase 5).
- Automated off-car data retrieval. The runbook documents retrieval *manually*; automated
  retrieval and interchange formats are **Phase 8**.
- Any change to the capture, archive, or telemetry data paths themselves. Phase 1 owns those and
  they are code-complete; this phase observes them, it does not modify them.

</domain>

<decisions>
## Implementation Decisions

### Boot & Supervision (OPS-01)

- **A systemd service unit starts the logger at power-up.** The deployment target is Linux on the
  Raspberry Pi CM4, so systemd is already there and gives ordering, restart policy, and journal
  capture without new machinery. Not cron `@reboot` (no restart semantics, no dependency ordering)
  and not a hand-rolled init script.
- **Restart policy is `Restart=always` with a bounded rate limit** (`StartLimitIntervalSec` /
  `StartLimitBurst`). A crash mid-session must recover unattended, but a crash-loop must remain
  *visible* rather than silently absorbed — consistent with Phase 1's "a hard, visible stop is the
  honest failure mode" decision.
- **If the neoVI hardware is not present at boot, the logger stays alive, retries with backoff, and
  reports `waiting-for-hardware`.** The CM4 will frequently finish booting before the CAN bus is
  powered, so exiting would turn a completely normal power-sequencing race into a failure requiring
  a restart. This state is distinct from an error state and must be visible in the heartbeat.
- **The unit file ships in-repo under `deploy/`, with an install script.** Version-controlled and
  reproducible, matching the config-driven precedent (`config/logger.json` + typed loader). A unit
  file that exists only as prose in a runbook drifts from reality — this project's single most
  recorded failure mode.

### Heartbeat & Liveness (OPS-02)

- **The primary indicator is a heartbeat status file (JSON) plus a `telemetry-status` CLI that
  renders it.** Any physical LED sits behind a thin, optional abstraction.
  **Rationale, stated as an open question rather than an assumption:** it is not established what
  GPIO or status LED the neoVI PI actually exposes. Committing LED-first would bake in an
  unverified hardware claim, which is exactly the failure class this project has hit five times.
  Planning/research MUST confirm the real LED/GPIO surface before any LED code is written; if a
  usable LED exists, it is driven *through* the abstraction, not instead of the status file.
- **Five distinguishable states:** `booting`, `waiting-for-hardware`, `capturing`, `degraded`,
  `stopped-error`. Success criterion 2 asks whether the logger is "alive **and** capturing" — a
  binary alive/dead signal cannot answer that.
- **Heartbeat is written at 1 Hz and considered stale after 5 s.** Mirrors the staleness discipline
  already shipped in Phase 2's dashboard (3 s threshold there), scaled to a slower on-car cadence.
- **No remote readout this phase.** Local status file and CLI only. Pushing the heartbeat over the
  link is Phase 6's job and would prejudge its design.

### Disk Space (OPS-03)

- **Two-stage thresholds — `warn` and `critical` — both configurable in `config/logger.json`.**
  Follows the existing typed, fail-closed config loader pattern (`telemetry/logger/config.py`
  raising a named `LoggerConfigError` on malformed input, never silently defaulting).
- **At critical: refuse to START a new session, warn loudly during a run in progress, and NEVER
  auto-delete.** Automatically pruning session data would directly contradict the project's core
  value — "no run's data is ever lost." Stopping a run already in progress is also rejected: a
  partially-written session is more valuable than no session, and Phase 1's archive is crash-safe
  by design, so letting a run continue until the disk genuinely fills loses less than pre-emptively
  killing it.
- **Surfaced in three places:** the heartbeat state, a startup log line, and an explicit runbook
  check step. Criterion 3 requires it be visible *while there is still time to act*, which a log
  line alone does not achieve for someone standing at the car.
- **Measured with stdlib `shutil.disk_usage` against the archive root.** Keeps `requirements.txt`
  at its current 8 exact pins and avoids re-triggering the package legitimacy gate (the 01-01
  blocking-checkpoint precedent). Not `psutil`, not shelling out to `df`.

### Runbook & Verifiability (OPS-07)

- **The runbook lives at `docs/runbook.md`,** joining the existing `docs/power-pull-test.md`.
- **Audience is explicitly someone who did not build the system.** It must cover: starting a
  session, confirming health, retrieving the data, and what to do for each bad heartbeat state.
  Criterion 4 states this almost verbatim, so it is an acceptance condition, not a nicety.
- **OS-touching code sits behind thin abstractions with fakes, so the logic is unit-testable on the
  Windows dev box; the unit file gets a parse/lint test; real boot behaviour becomes ONE explicit
  Pi UAT item.** This is the decision that keeps Phase 3 from stranding the way Phase 1 did (three
  hardware-only items, still unverified). systemd ordering and actual power-up genuinely cannot run
  on Windows — the goal is to confine that irreducible part to a single named item rather than let
  it swallow the whole phase.
- **Ops logic lives inside the existing logger process, in a new `src/telemetry/ops/` module.** The
  logger process already owns the counters and the archive root; a separate supervisor process
  would have to duplicate both and would introduce a second thing that can die silently.

### Claude's Discretion

No "you decide" answers were recorded — all 16 questions across the 4 areas were accepted as
recommended. Discretion remains for: heartbeat file format details and exact field names, backoff
curve for hardware retry, the specific default threshold values (must be config-driven regardless),
install-script mechanics, and `telemetry-status` output formatting.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets

- **Typed fail-closed config loader** — `src/telemetry/logger/config.py` builds frozen dataclasses
  (`LoggerConfig`, `ChannelConfig`, `TelemetryConfig`) and raises a named `LoggerConfigError`
  identifying the offending key and value. A new `ops` section in `config/logger.json` should
  extend this exact pattern, not introduce a second config mechanism.
- **Per-subsystem counter dataclasses** — `TelemetryPipelineCounters` (`logger/pipeline.py:98`),
  `FanOutCounters` (`capture/fanout.py:88`), `HardwareSourceCounters` (`capture/hardware_source.py:115`).
  The heartbeat should *read* these rather than invent a parallel accounting of the same events.
- **Archive session lifecycle** — `ArchiveWriter` with `records_written`, `flush_count`,
  `is_closed`, and the `.done` sidecar marker written only after close-and-flush returns. The
  heartbeat's "capturing" state and the disk check's archive root both hang off this.
- **Existing CLI/signal discipline** — `logger/cli.py` installs signal handlers before any resource
  construction and supports a `--duration-s` bound via an independent `threading.Timer`
  (`HardwareFrameSource` blocks internally between polls). Any new supervision must not break that
  ordering.
- **Health-line precedent** — `ground/cli.py` already has `--health-interval-s` emitting periodic
  link-health lines to stderr. The car-side heartbeat should feel like a sibling of that, not a
  different idiom.

### Established Patterns

- Absolute imports rooted at the `telemetry` package; `pythonpath = src` via `pytest.ini`,
  `PYTHONPATH=src` for direct runs. Never a relative import across subpackages.
- Repo-relative paths resolved from `Path(__file__).resolve()` walking up a fixed number of
  `.parent`s — never a hardcoded absolute path.
- One `logger = logging.getLogger(__name__)` per module at module scope; only CLI entry points
  configure logging.
- Interchangeable implementations declared as `typing.Protocol` with a minimal method surface
  (`FrameSource`, `Link` — three methods each), not ABCs. **The LED/GPIO abstraction should follow
  this exact shape.**
- **Catch the SDK's own exception type, never the builtin it shadows.** `ics.RuntimeError` does not
  subclass `builtins.RuntimeError` (verified live). Applies to any hardware-presence probing added
  for `waiting-for-hardware`.

### Integration Points

- `config/logger.json` — gains a new `ops` section (thresholds, heartbeat path and cadence).
- `src/telemetry/logger/cli.py` — the process that must publish the heartbeat and run the disk check
  at startup; this is where supervision hooks in.
- `src/telemetry/archive/` — `archive.root_dir` (`sessions`) is the path the disk check measures.
- `deploy/` — new directory for the systemd unit and install script.
- `docs/` — new `runbook.md` alongside `power-pull-test.md`.
- New `src/telemetry/ops/` package — heartbeat, disk monitor, LED abstraction, status CLI.

</code_context>

<specifics>
## Specific Ideas

- The CM4 has **no RTC battery**, so the wall clock can be epoch-garbage at boot. Phase 1 already
  handles this for session naming (UTC `YYYYMMDD-HHMMSS` with a monotonic counter fallback, and a
  sanity floor treating a UTC year before 2020 as implausible). The heartbeat's timestamps and the
  5 s staleness comparison must use a **monotonic** clock, not wall time, or a clock jump at boot
  will make a healthy logger look stale — or a dead one look fresh.
- `Restart=always` must be paired with a rate limit specifically so a boot-time crash-loop is
  observable rather than an infinite silent retry.
- The `waiting-for-hardware` state exists because of a real power-sequencing race, not as a generic
  error bucket — keep it semantically distinct from `stopped-error` in both the state machine and
  the runbook.

</specifics>

<deferred>
## Deferred Ideas

- **Remote/link-borne heartbeat** → Phase 6 (Live Plots and Link Health), which owns distinguishing
  "steady" from "we stopped hearing from it" and the reserved `--amber`/`--red` states Phase 2
  deliberately left unused.
- **Automated off-car data retrieval** → Phase 8 (Archive Retrieval and Interchange). Phase 3's
  runbook covers manual retrieval only.
- **Auto-pruning or rotation of old sessions** → rejected outright for this phase as contrary to
  the core value; if it is ever wanted it needs its own explicit decision, not a disk-threshold
  side effect.
- **`psutil` for richer system metrics** → not needed for OPS-03 and would re-trigger the package
  legitimacy gate. Revisit only if a later phase needs metrics stdlib cannot provide.

</deferred>
