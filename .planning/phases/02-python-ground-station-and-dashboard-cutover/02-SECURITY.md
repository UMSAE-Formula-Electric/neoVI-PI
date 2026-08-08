---
phase: 02
slug: python-ground-station-and-dashboard-cutover
status: secured
verdict: SECURED
threats_total: 13
threats_closed: 13
threats_open: 0
asvs_level: 1
block_on: high
audited: 2026-08-08
retroactive: true
---

# Phase 02 — Security Verification

> Retroactive audit (`/gsd-secure-phase`-equivalent) run at the Phase 2 boundary. This is the
> **first-ever** security pass on this project, so this file also becomes the accepted-risks log
> that later phases verify against. Threats are deduplicated across the four plan `<threat_model>`
> blocks — T-02-01, T-02-04 and T-02-06 are restated identically in later plans and counted once.
>
> Config: `security_asvs_level: 1` (mitigation-presence verification at the cited location),
> `security_block_on: high`.

## Verdict: SECURED

**13/13 threats closed. 0 open.**

Phase 2 introduced this project's **first listening network service** — a stdlib `http.server`
serving a dashboard over HTTP plus an SSE stream, intended to run on a pit-lane laptop at a
racing event (untrusted nearby devices, shared/ad-hoc networks). That makes this boundary the
right place for the first audit.

## Threat Register

| ID | Category | Severity | Disposition | Evidence |
|----|----------|----------|-------------|----------|
| T-02-01 | Tampering / Info Disclosure — static route path traversal | high | mitigate | `server.py:53-65,221-238,263-280`: fixed route constants; `do_GET` does literal `==` comparison; `DASHBOARD_HTML_PATH` built from `Path(__file__).parent`, never from `self.path`. Tests `test_traversal_style_path_is_404_not_a_file_read`, `test_unknown_path_returns_404` pass. |
| T-02-02 | DoS — per-client SSE queue growth | medium | mitigate | `server.py:50,148-183`: `SSE_CLIENT_QUEUE_MAXSIZE=256`, check-then-evict-then-count drop-oldest. Tests `test_slow_client_loses_oldest_not_newest`, `test_broadcast_never_blocks_on_a_full_client` pass. |
| T-02-03 | DoS — unbounded concurrent SSE clients | low | accept | Loopback-default bind, single-engineer tool; counts genuinely maintained (`SseHubCounters.clients_connected/clients_peak`, `server.py:103-104,131-135`). |
| T-02-04 | Info Disclosure — HTTP bind address | medium | mitigate | `cli.py:184-194`: `--http-host` defaults to `127.0.0.1`, help text warns of exposure. `server.py:370-378`: warning logged naming the address for any non-loopback host. |
| T-02-05 | DoS — oversized/malformed request line | low | accept | `DashboardRequestHandler` overrides only `log_message`/`do_GET`; stdlib request-line/header parsing (65536-byte cap, 414/`HTTPException`) is left intact. |
| T-02-06 | Tampering — dependency supply chain | low | accept | `requirements.txt` unchanged since Phase 1 (last touched at `5e2eb33`, before this phase). `dashboard.html` has no CDN/font/script src — the only external-looking reference is an SVG XML namespace URI. |
| T-02-07 | Info Disclosure — stale value shown as current | medium | mitigate | `SignalState.update()` takes explicit `now_ms`; `cli.py:497` passes the ground station's own wall clock, never `frame.timestamp_us`. `test_update_ts_is_wall_clock_not_frame_timestamp` passes. |
| T-02-08 | Tampering / injection — unescaped `innerHTML` | low | accept | See "Accepted risk in detail" below. |
| T-02-09 | Spoofing — UDP telemetry ingress via simulator | low | accept | `simulate.py` adds no capability beyond the link's existing unauthenticated-by-design posture; frames still pass CRC (`Deframer`) and DBC decode (`cli.py::_decode_frame`) before display. |
| T-02-10 | DoS — simulator saturating ground station | low | accept | `simulate.py:327` narrows to `config.telemetry.allowlist`; real-time pacing in `feed_frames`; downstream bound is the drop-oldest queue verified under T-02-02. |
| T-02-11 | DoS / self-inflicted — deletion of still-referenced module | medium | mitigate | `tests/test_legacy_cutover.py` 4/4 passing; grep for any remaining import of the four removed modules across `src/` and `tests/` returns zero hits. Full suite 323 passed. |
| T-02-12 | Repudiation / Tampering — stale docs describing removed code | medium | mitigate | Actual on-disk `.claude/CLAUDE.md` read directly: Python-only, describes the real `telemetry` tree, zero Node/npm/WebSocket/pipe references. `test_instruction_file_does_not_document_removed_code` passes. |
| T-02-13 | Info Disclosure — abandoned unauthenticated Node server left in tree | low | mitigate | `can-dashboard/` confirmed absent from the working tree and untracked in git (deleted at `1df5d76`). |

## Accepted Risk in Detail — T-02-08 (unescaped `innerHTML`)

`channel` / `id` / `name` / `signal` / `unit` are interpolated unescaped into `innerHTML`
(`dashboard.html:512,555-563,604-610`). The data flow was traced rather than assumed: every one
of those strings originates from `message.name` / `signal.name` / `signal.unit` (the DBC, via
`cantools`) or from `config/logger.json` channel names. Wire-carried signal **values** — the only
attacker-influenceable data on this path — go through `el.textContent` (line 628), which is safe.

**Stated plainly:** this holds only while the DBC and `config/logger.json` remain locally-authored,
trusted build assets. It is a real latent injection primitive that a future phase would reopen if
either were sourced from an untrusted or networked origin. Matches code review's IN-01, correctly
left unmitigated by design for now.

## Newly Registered — Found by Code Inspection, Not by Any Plan

Neither raises `threats_open` above zero, but both were previously unregistered and are recorded
here so they are not rediscovered from scratch later.

### T-02-14 — Connection-level slow-loris / thread exhaustion (low, accept)

**Genuinely unmitigated in code.** `DashboardRequestHandler` sets no `timeout` class attribute,
and `ThreadingHTTPServer` spawns one unbounded thread per accepted TCP connection with no cap. A
client that opens a connection and never completes sending a request line holds that thread
indefinitely.

This is distinct from T-02-02 (bounds an *already-registered* SSE client's queue) and T-02-05
(bounds a *complete* oversized request line) — it is the pre-registration connection-accept phase,
and it applies to every route, not just `/events`.

Accepted at **low** on the same reasoning as T-02-03/T-02-05: loopback-default bind, single-operator
diagnostic tool, restart-recoverable, and no data-loss impact — the durable archive path is entirely
untouched by this server. Revisit if the bind address ever defaults to non-loopback.

### T-02-15 — `GET /state` had no threat entry (low, mitigate)

The `/state` route was added post-hoc during the code-review fix pass (WR-02) and so never passed
through a plan's threat model. Verified after the fact: it is read-only (`server.py` defines only
`do_GET`; other verbs fall through to `BaseHTTPRequestHandler`'s default 501), returns exactly the
same payload shape the SSE snapshot event already sends to any connected client, and is gated by
the same fixed-string route allowlist (T-02-01) and loopback-default bind (T-02-04) as the other
two routes. It introduces no disclosure beyond what `/events` already gives the same trust boundary.

Functionally covered; registered here to close the procedural gap.

## Scope Note

Drop-oldest fan-out on the SSE path is **by design** — a slow browser must never block the decode
thread — and is not a defect. Only the archive path carries a zero-drop obligation, and it is not
in this phase's scope.
