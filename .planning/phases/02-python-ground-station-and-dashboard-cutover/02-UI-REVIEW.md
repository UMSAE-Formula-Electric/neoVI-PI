# Phase 2 — UI Review

**Audited:** 2026-08-08
**Baseline:** `.planning/phases/02-python-ground-station-and-dashboard-cutover/02-UI-SPEC.md` (approved contract — explicitly designates `dashboard.html` a "frozen legacy exception zone": a port of `can-dashboard/dashboard.html`, not a redesign)
**Screenshots:** not captured this session (no dev server probed independently — see note below). Scoring instead relies on (a) direct source read of `src/telemetry/ground/static/dashboard.html` against the UI-SPEC's explicit rules and (b) the orchestrator's real-Chrome observations supplied verbatim in the task prompt, which are treated as verified fact per the honesty requirement. Anything not covered by either source is flagged as unverified rather than scored optimistically.

**Scope note:** Per the UI-SPEC's frozen legacy exception zone, inherited spacing/radii/toggle geometry/badge padding are NOT findings here (36×20/28×16 toggles, 2px 7px/1px 6px badge padding, 50px signal-row padding, 5–10px radii are all accepted exceptions). Only genuinely new chrome (the staleness indicator) is held to the 4/8/16 scale, and only contract deviations are scored down.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 4/4 | Empty state, error state, and no-results state all match the contract's copy verbatim, including the resolved `--serve` flag (no leftover `{SERVING_FLAG}` placeholder) |
| 2. Visuals | 3/4 | Hierarchy matches the contract on paper (`.sig-value` is the only 600-weight/monospace/right-aligned element), but CR-01's now-fixed collapse/toggle bug shipped in the first pass, and `--channel-colors` is dead CSS the spec doesn't mention either way |
| 3. Color | 3/4 | 60/30/10 split and accent-only-on-declared-elements rule are respected in the CSS; the `--red` reuse for connection-error status matches the spec's own carve-out, but `--channel-colors` (6 raw hex values) sits unused and unaudited against the accent-restriction rule |
| 4. Typography | 4/4 | `.sig-value` rule (14px monospace/600, right-aligned, fixed min-width) is intact and unweakened; new/changed text (empty state body, no-results copy) all uses 400 or 600 only, per contract |
| 5. Spacing | 4/4 | The one new-chrome element this phase adds — the staleness indicator — is a color-only rule (`.sig-value.stale { color: var(--dim); }`) with zero new spacing values, so there is nothing to audit against the 4/8/16 scale; everything else is the accepted legacy exception zone |
| 6. Experience Design | 3/4 | All 9 "covered" states in the spec's UI-considerations table are implemented and now verified live (staleness dim/undim, reconnect copy, no-results, snapshot-on-connect); the one 🧪 backstop item (per-signal staleness) has no automated DOM test, only the live-observed manual check reported in this session |

**Overall: 21/24**

---

## Top 3 Priority Fixes

1. **`--channel-colors` custom property is declared but never wired to anything (`dashboard.html:24`)** — no user-visible impact today (channel tabs render with no color distinction, which the spec doesn't call for either), but it's dead code sitting inside `:root` alongside the spec's actual color contract, making a future reader unsure whether it's an intentional reserved token or an abandoned feature. Either delete the declaration or wire `.ch-tab` to cycle through it — this was flagged as IN-02 in the code review and explicitly left unfixed (out of scope for that pass), so it's still open. Low priority, but it is the only genuinely unresolved item touching Pillar 2/3 scoring.

2. **Per-signal staleness (the spec's one 🧪 backstop item) has no committed automated check, only this session's manual live observation** — the UI-SPEC itself calls this out as needing "a snapshot/DOM assertion in the phase's test suite or manual UAT, per the honest-verifier rule (no silent pass)." That manual UAT happened this session (36/36 sig-values gained `.stale` after 3s, cleared on resume), which is real evidence, but it is not committed as a repeatable test — a future regression to the staleness sweep (`sweepStaleness()`, `dashboard.html:660`) would not be caught by CI. Given the code-review's own admission that this file "has no automated interaction coverage," consider at minimum a Playwright/Puppeteer smoke test that asserts `.sig-value.stale` appears after `STALE_THRESHOLD_MS` and clears on the next update — the WR/CR fixes for other bugs (CR-01, WR-01) already show this codebase's test-writers are willing to add narrowly-scoped regression tests when a real defect is found; staleness deserves the same treatment given it's a domain-critical requirement ("a frozen number must never be mistaken for a current one").

3. **Two of the file's IN-01/IN-02 code-review findings (unescaped `innerHTML` interpolation, dead `--channel-colors`) remain unfixed by explicit scope decision** — not a UI-contract violation today (all interpolated strings originate from the trusted local DBC/config, not the wire), but worth tracking so it doesn't silently become exploitable if a future phase sources channel names or signal metadata from something less trusted (e.g., a network-supplied config). Not urgent for this phase's ship gate, but should not be forgotten — recommend a lightweight backlog item rather than blocking phase closure.

---

## Detailed Findings

### Pillar 1: Copywriting (4/4)

- Empty state heading/body match the contract exactly, including the corrected invocation `python -m telemetry.ground.cli --serve` (`dashboard.html:387-390`) — confirmed the `--serve` flag is real (`cli.py:175`), so the `{SERVING_FLAG}` placeholder the spec calls a "failed contract" if shipped literally is correctly resolved. No occurrence of the literal string `{SERVING_FLAG}` anywhere in the shipped file.
- Error-state copy pairing (`"Live"` / `"Reconnecting…"`, not "Error") is implemented exactly as specified (`dashboard.html:441,445`) and confirmed live by the orchestrator's observation (server-kill → `.error` + "Reconnecting…"; restart → auto-return to `.live` + "Live" with no page reload).
- No-results state (`dashboard.html:392-397,753-761`) correctly uses distinct copy from the "no data at all" empty state — `'No signals match "{query}"'` plus a "Clear search" button — never the "Waiting for CAN data…" string that would falsely suggest the link is down. This was the spec's explicitly-called-out probe-surfaced requirement (the form-element axis "hidden by the aggregated category rows"), and it is correctly implemented.
- No generic/unresolved placeholder strings, no leftover `node server.js` reference anywhere in the shipped file (grepped — none found).

### Pillar 2: Visuals (3/4)

- The spec's visual-hierarchy tie-breaker (`.sig-value` as sole primary focal point: right-aligned, monospace, 600-weight, fixed min-width, nothing else competing) is intact in the shipped CSS (`dashboard.html:275-283`) — no other element uses that combination of properties.
- Connection status dot/text (secondary focal point) remains in the sticky header, visible at all viewport widths per the existing `position: sticky` header rule (`dashboard.html:36-46`) — unchanged from the ported file, consistent with spec.
- Deduction: CR-01 (message-group collapse/visibility toggle completely non-functional due to a `CSS.escape`/`getElementById` id mismatch) shipped in the reviewed code and was only caught by a subsequent code-review pass, not this UI process — meaning the pillar's "must never out-weight a signal value" hierarchy contract was technically fine on paper, but a core piece of the tertiary-chrome interaction layer (collapse/expand, message-level show/hide) was broken end-to-end until the fix landed (`02-REVIEW-FIX.md`, commit `c015acf`). It is now fixed and the orchestrator's live-browser evidence confirms "message collapse and per-message visibility toggle both work (CR-01 fixed and re-verified live)" — but a full 4/4 would require this class of defect not shipping past the phase's own review loop in the first place. Scoring 3/4 to reflect that the contract is met now, not that it was met throughout the phase.
- `--channel-colors` (`dashboard.html:24`) is declared but never consumed anywhere in CSS or JS — a half-finished visual-hierarchy feature (channel-tab color coding) that the spec neither requires nor forbids, but which sits as visible clutter in the token list for anyone reading the color contract.

### Pillar 3: Color (3/4)

- 60/30/10 split: `--bg` (`#0d0d0f`) as page background, `--surface`/`--surface2` for header/search/tabs/cards/stats bar, `--accent` (`#4f8ef7`) restricted to active-tab underline, `.msg-id` badge, toggle "on" fill, mini range-bar fill, search-focus border, and logo icon background — grep confirms `var(--accent)` appears only at those declared sites (`dashboard.html:59,116,141,146→actually --dim,203-204,254,310`; no stray usage on body text or borders).
- `--red` is correctly repurposed only for the connection-error status dot (`dashboard.html:78`), matching the spec's explicit carve-out that this is a status color, not a destructive-action color, for this phase.
- New staleness color (`--dim`, reused rather than a new token) is implemented exactly as specified: `.sig-value.stale { color: var(--dim); }` (`dashboard.html:292`), declared before `.flash` so a fresh update's flash color wins on class overlap, and the render path explicitly does `el.classList.remove('stale')` before applying `.flash` (`dashboard.html:633-638`) — this ordering detail from the spec's rationale is correctly implemented, not just approximately followed. Live evidence confirms all 36 `.sig-value` elements gained `.stale` after 3s and none showed row-opacity change (correctly distinct from `.hidden`'s `opacity: 0.35`).
- `--amber` is declared (`dashboard.html:21-22`) but correctly left unused in markup, matching the spec's "reserved, do not repurpose it for staleness" instruction.
- Deduction: `--channel-colors` (`dashboard.html:24`) declares 6 raw hex values in a single CSS custom property that is never read by any selector or script — this is a second color surface, alongside the audited 60/30/10 set, that was never brought under any accent-restriction discipline because nothing consumes it. It doesn't currently violate anything (unused code can't violate a usage rule), but it means the color pillar's real surface area is not fully accounted for by the spec's token table, and a reviewer auditing "is the accent used only on declared elements" would need to separately confirm this property does nothing rather than trusting the token list is exhaustive.

### Pillar 4: Typography (4/4)

- `.sig-value` retains its full declared rule set (14px monospace stack, weight 600, right-aligned, fixed `min-width: 80px`, `dashboard.html:275-283`) — the spec's "domain-specific hard rule" that this must not be weakened when porting is met; nothing in the diff between the ported file and this implementation touches that rule.
- Font-weight audit: grepping the stylesheet's `font-weight` declarations shows only `500` (`.msg-name`, `.ch-tab` — the spec's named inherited exception, explicitly not to be expanded), `600` (`.logo`, `.sig-value`, `.msg-toggle`... via inheritance), and `400` (implicit body default) — no new weight was introduced by this phase's changes (empty-state copy, no-results copy, staleness rule are all color-only or reuse existing text rules).
- Font-size audit: all sizes present in the file (11px–16px range) match the ported file's existing distribution; nothing new was added outside that range by this phase's changes.

### Pillar 5: Spacing (4/4)

- The only genuinely new chrome this phase adds to the UI (per the spec's own framing: "if Phase 2 adds any genuinely new chrome... it must use the 4/8/16 scale") is the staleness indicator, and it is implemented as a pure color-state class with zero spacing properties: `.sig-value.stale { color: var(--dim); }` (`dashboard.html:292`). There is no new padding, margin, gap, or dimension introduced anywhere in this phase's diff — the no-results state and updated empty-state copy reuse the existing `.empty`/`.btn-small` rules verbatim.
- Everything else in the file (toggle geometry, badge padding, signal-row padding, card radii) is the spec's explicitly accepted frozen legacy exception zone and is correctly out of scope for this audit, per the task's scope constraint.

### Pillar 6: Experience Design (3/4)

- All 9 "✅ covered" rows in the spec's UI-considerations table are implemented in source and independently confirmed by the orchestrator's live-browser pass this session: empty state (waiting-for-data), loading ("Connecting…" default status text before first SSE event), error (`.error`/"Reconnecting…" on `EventSource.onerror`, auto-recovers with no reload), populated (snapshot-on-connect via `rebuildAll()`), partial (lazy `ensureSignalRow`), overflow (search filter + horizontal-scrolling tabs), zero-one-many (empty/single-tab/many-with-search all present), long-text (ellipsis truncation retained), and the no-results form-element case.
- The 🧪 backstop item — per-signal staleness — is implemented correctly in source (`sweepStaleness()`, `dashboard.html:660-673`, polling every 1000ms independent of update cadence, specifically designed to catch the "message went quiet" case that would otherwise never re-render) and is now verified by live observation (36/36 signals staled after 3s, 36/36 cleared on resume) rather than by an automated test. The spec itself flagged this as needing either "a snapshot/DOM assertion in the phase's test suite or manual UAT" — manual UAT happened, satisfying the letter of that requirement, but there is still no committed regression test for this domain-critical behavior (see Top 3 Fix #2). Scoring 3/4 rather than 4/4 because the spec's own bar for this item was explicitly lower-confidence ("backstop," not "covered"), and that lower confidence is still true after this session — the behavior works today, verified by a human this once, but nothing in CI will catch a future regression to `sweepStaleness()` or the `STALE_THRESHOLD_MS` constant.
- CR-01's shipped-then-fixed collapse/toggle bug is also relevant here: it broke two of the "existing, unchanged behavior" interactions the spec assumed would port cleanly (collapse-all toggling individual groups, message-level visibility). It's fixed now and re-verified live, but the fact that a full-file port of "just change the transport" scope introduced a functional regression in unrelated interaction code is worth naming in this pillar rather than only in Pillar 2, since it's fundamentally an interaction-state defect, not a purely visual one.

---

## Files Audited

- `src/telemetry/ground/static/dashboard.html` (full file, 804 lines — CSS and JS)
- `.planning/phases/02-python-ground-station-and-dashboard-cutover/02-UI-SPEC.md` (design contract)
- `.planning/phases/02-python-ground-station-and-dashboard-cutover/02-CONTEXT.md` (locked decisions)
- `.planning/phases/02-python-ground-station-and-dashboard-cutover/02-REVIEW.md` (code review findings — CR-01, WR-01..05, IN-01/02)
- `.planning/phases/02-python-ground-station-and-dashboard-cutover/02-REVIEW-FIX.md` (fix verification — all 6 in-scope findings fixed, IN-01/02 left open by explicit scope decision)
- `src/telemetry/ground/cli.py` (confirmed `--serve` flag matches the empty-state copy's invocation string)

**Screenshot note:** No independent screenshot capture was performed this session — the orchestrator's live-Chrome observations (supplied in the task prompt) are treated as verified fact per the honesty requirement and are cited throughout the findings above wherever they inform a score. Anything not covered by either the source read or those observations (e.g., exact pixel-level channel-tab horizontal-scroll behavior at extreme viewport widths, mobile `@media (max-width: 500px)` layout) was not independently verified and is not scored as if it had been.
