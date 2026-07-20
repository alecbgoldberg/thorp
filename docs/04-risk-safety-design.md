# Document 4 — Risk & Safety Design

Status: draft v1, pending Opus adversarial red-team review (in progress) before final sign-off. Every control below states default value, enforcement point (referencing Doc 3's components), and escalation behavior (warn / block orders / flatten / halt).

## 1. Per-Order Controls

| Control | Default (Canary) | Default (Tier 1) | Enforcement point | Escalation |
|---|---|---|---|---|
| Max order size | 1 contract | 10 contracts | `RiskEngine.check()` | Block — reject the intent, log reason |
| Price sanity band vs. fair value | reject if \|price − fv.probability\| > 0.15 | same | `RiskEngine.check()` | Block |
| Price sanity band vs. last trade | reject if \|price − last_trade\| > 0.10 | same | `RiskEngine.check()` | Block |
| Hard price bound | reject outside [$0.02, $0.98] (tighter than Kalshi's own [$0.01,$0.99] — margin against our own fat-finger) | same | `RiskEngine.check()` | Block |
| Fat-finger notional cap | reject single order notional > $50 | reject > $150 | `RiskEngine.check()` | Block |

**Test approach:** every row above gets a negative unit test that constructs an `OrderIntent` violating exactly that bound and asserts `RiskDecision` is `RejectedIntent` — not merely "the strategy shouldn't produce this," but "if it did, the engine refuses it." Doc 6 §2 elaborates.

## 2. Per-Market (Correlated-Group) Controls

Correlated grouping, defined once here and used everywhere else: **every Kalshi market referencing the same game (moneyline, spread, total, and any related props) is one correlated group**, keyed by a stable game identifier derived from the series ticker's date+teams. This is not a per-contract limit dressed up — it is enforced by summing signed exposure across every market in the group before checking any cap.

| Control | Default (Canary) | Default (Tier 1) | Enforcement point |
|---|---|---|---|
| Max position per correlated group (`hard_cap`, Doc 2 §5) | $50 | min($150, 15% of balance) | `RiskEngine.check()`, summed across the group |
| Fade threshold (`soft_cap`) | $25 | 50% of `hard_cap` | `RiskEngine.check()` — modifies size, doesn't reject, below `hard_cap` |
| Max open orders per group | 4 | 6 | `RiskEngine.check()` |
| Max notional at risk per group | = `hard_cap` (binary contracts: position ≈ notional at risk) | = `hard_cap` | `RiskEngine.check()` |

At `hard_cap`, any `OrderIntent` that would increase \|group position\| is a hard `RejectedIntent` — this is the Doc 2 §5 fading design's enforcement backstop, independent of whether the strategy layer's own hurdle logic worked correctly. The risk engine does not trust the strategy layer to have already applied the fade; it re-derives group exposure from `RiskState` and re-checks unconditionally.

**Revised after Opus adversarial review — the in-flight-order race.** The reviewer constructed a concrete breach: `RiskState` group exposure, if derived only from *reconciled, filled* positions (reconciled every 5s per §7), is blind to orders that have already been approved and are resting-but-unfilled. A strategy returning a batch of intents in one signal (e.g. 6 intents at $150 each against a $150 group cap) has each one individually checked against the *same* stale exposure figure, since none of the earlier approvals in the batch have filled yet — all 6 pass, and the group can end up filled to 6x its cap. This also silently disables the fade itself, since `size_multiplier`/`required_edge` (Doc 2 §5) are functions of the same stale `position` read — the anti-accumulation mechanism goes quiet exactly when it's needed most.

**Fix, now part of the design:** `RiskState.group_exposure(group)` = reconciled filled position **+ notional of every approved-but-not-yet-terminal order** (an in-flight reservation ledger, not a fill-derived sum), updated synchronously at approval time — before the coroutine that approved it yields control via `await venue.place_order(...)` (Doc 3 §3.5's revised design). A second intent evaluated during that `await` sees the first intent's reservation even though it hasn't filled yet. The reservation is released and reconciled against the eventual fill/cancel when the order reaches a known-terminal state (Doc 3 §3.6's revised state machine).

## 3. Portfolio Controls

| Control | Default (Canary) | Default (Tier 1) | Enforcement point |
|---|---|---|---|
| Max gross exposure (Σ\|position\| across all groups) | $100 | 40% of current balance (~$280 at $700) | `RiskEngine.check()` |
| Max correlated exposure | = per-group `hard_cap` (§2) | same | `RiskEngine.check()` |
| Max total capital deployed | = Kalshi funded balance | = Kalshi funded balance | **Operational control, not code**: the Kalshi account is never funded above the current phase's trading-balance figure (Doc 2 §3). Reserve and held-back capital physically never touch the Kalshi account. This is deliberately a human/banking control, not a software one — software controls cannot protect against a human wiring the wrong amount, but keeping the exchange account itself underfunded relative to total capital bounds the blast radius of *any* software bug, including ones this document failed to anticipate. |

## 4. Rate Controls

Kalshi Basic tier gives 100 write tokens/sec, most requests costing 10 tokens (Doc 1 §1.1) — an effective ~10 writes/sec ceiling. This project's own budget is set well below that so a bug never gets close to exchange-imposed throttling, let alone triggers it.

| Control | Default | Enforcement point | Escalation |
|---|---|---|---|
| Max orders/sec | 2 | Local token bucket in OMS, checked before every submit | Block — queue or drop, never burst through |
| Max cancel-replace/sec | 5 | Same bucket, separate budget | Block |
| Max order-to-fill ratio (rolling 10 min) | 20:1 | OMS, computed from event log | Warn at 15:1, block new non-reducing orders at 20:1 — a strategy that's spamming without getting filled is either mispricing badly or the venue moved; either way, stop adding |
| Cumulative message budget vs. exchange limit | proactively throttle at 80% of tier limit | OMS-level local counter, mirrors Kalshi's token-bucket model | Block before the exchange would 429, never rely on the 429 as the first signal |

## 5. P&L Controls

Tied directly to Doc 2's $300 total hard-shutdown threshold — these are sub-limits designed so no single day or single strategy can burn through that budget before the operator has a chance to react.

| Control | Default (Canary) | Default (Tier 1) | Enforcement point | Escalation |
|---|---|---|---|---|
| Intraday max loss | $20 | $75 (25% of the $300 total shutdown budget) | `RiskEngine`, checked against `PositionAccounting` realized+unrealized | Hard halt — cancel all resting orders, block new non-reducing orders, alert |
| Drawdown from session high | 50% of intraday max loss | same ratio | Same | Warn + reduce size to 50% (does not yet halt) |
| Per-strategy loss limit | $10/day per strategy | $30/day per strategy | Same, scoped per `strategy_name` | Halt that strategy only, others continue |

**Clarification after Opus adversarial review:** per-strategy limits are a narrower, additional control layered on top of the §2 correlated-group cap — they are not a substitute for it and do not compose the way a first read might suggest. The reviewer noted that 4.1/4.2/4.3 can all hold positions in the same correlated group (same game) simultaneously; halting one strategy for hitting its own daily loss limit does nothing to reduce a group-level position the *other* strategies keep adding to. The §2 group `hard_cap`/fade logic is the authoritative, strategy-agnostic backstop on any single game's aggregate exposure regardless of how many strategies contributed to it — per-strategy loss limits exist to isolate which strategy is misbehaving for debugging/kill purposes, not to bound correlated risk, which is already §2's job.

**Explicitly not a code enforcement point, stated here for completeness:** the Doc 2 $300 *cumulative* (not daily) shutdown threshold is a project-level decision requiring operator action — the system should alert loudly on approach (e.g. at $250 cumulative realized loss) but the actual project shutdown is a human decision, not an automated one, consistent with reinvestment also being manual (Doc 2 §7). Automating a irreversible "stop trading forever" decision inside the risk engine is a judgment call this plan deliberately avoids — automate the halt, not the abandonment.

## 6. Data Staleness Kill — the most important control given Doc 1's findings

Kalshi's own docs show no confirmed REST/WebSocket-native cancel-on-disconnect (Doc 1 §1.1) — this makes staleness detection and the watchdog (§8) the *primary* safety mechanism, not a backup to an exchange feature.

| Input | Staleness budget | Warn at | Action at breach |
|---|---|---|---|
| Kalshi book WS (market data) | 5s without a message | 3s | Cancel all resting quotes in affected market(s), block new non-reducing orders on that market until fresh |
| Sportsbook consensus (Odds API) | 180s (matches ~90-180s poll cadence) | 90s | `FairValueEngine` drops the stale input, recomputes with wider `uncertainty` (Doc 3 §3.3) — automatically raises the Kelly/hurdle bar rather than needing a separate flag |
| Polymarket reference price | 30s | 15s | Same graceful-degradation path as above |
| All fair-value inputs stale simultaneously | — | — | Full halt on new position-adding orders across all strategies; reducing orders remain allowed |

This is a graduated response, not a single trigger: individual stale inputs degrade the fair-value estimate (wider uncertainty → smaller size, per Doc 2 §5) before anything halts outright. Only a market-data staleness breach (which threatens order-placement correctness directly, not just signal quality) triggers an immediate cancel.

**Fix after Opus adversarial review — the degenerate single-input case.** The "all inputs stale → full halt" rule (last row above) correctly handles zero surviving inputs, but the reviewer identified a worse, uncaught case in between: if `uncertainty` is computed as a function of *both* input count and the *spread of disagreement* among de-vigged estimates (Doc 3 §3.3), then as inputs decay from several down to exactly one, the disagreement/spread term collapses to zero (nothing left to disagree with) — `uncertainty` can move **down**, not up, right before the all-stale halt would otherwise fire. A single fresh-but-unvalidated input (one sportsbook line, or a lone Polymarket price sitting at Doc 1's 67%-calibration quality) then produces a falsely *confident* estimate, which raises the Kelly fraction and lowers the fading hurdle (Doc 2 §5) — a larger position taken on the least-validated signal available, at the exact moment input diversity is lowest. **Fix, now part of the design:** `uncertainty` must be provably monotonic non-increasing in input count — enforced by construction (e.g., compute a floor term from input count alone, independent of the spread term, and take the estimate's uncertainty as at least that floor) rather than emerging incidentally from the spread calculation. In addition, a **minimum-live-inputs floor of 2** is set: with exactly one live input, sizing is forced toward the canary-minimum regardless of what the raw uncertainty formula would otherwise produce, and with zero, the existing full-halt rule applies unchanged.

## 7. Reconciliation Break

- On every heartbeat cycle (5s) and unconditionally on startup, fetch actual Kalshi positions and open orders via REST and diff against `RiskState`'s internal view.
- Any divergence beyond a rounding tolerance (0 contracts — this is a binary-contract exchange, fractional-contract divergence should never legitimately occur) → **immediate halt**: block all new order submission, alert (Doc 7), and require explicit manual operator acknowledgment before resuming. The engine does not attempt to auto-correct its internal state and resume — a divergence means something is already wrong in a way this document didn't anticipate, and continuing to trade on an unverified state is the failure mode this control exists to prevent. **Never trade through a break.**
- **Fix after Opus adversarial review:** the halt sequence is **cancel every resting order first, then block new submissions and alert** — not block-new-submissions-only. The original design blocked new orders but left existing resting orders working on the exchange; the reviewer pointed out this is exactly backwards for the one state where the engine has admitted its position view might be wrong — resting orders can keep filling and drive the true position further from the already-diverged internal view for as long as the halt sits unacknowledged, and the watchdog's dead-man switch won't catch this because the engine is alive and heartbeating normally. Cancel-all-then-halt closes that gap.
- Startup is a special case of this same path with a stronger constraint: the engine's internal state starts genuinely empty (no cached last-known-position file is trusted) and is populated *only* from a fresh reconciliation fetch before the engine is allowed to transition out of a `STARTING` state into `ACTIVE`.

## 8. Heartbeat / Dead-Man Switch (Watchdog process)

- Trading Engine writes a heartbeat timestamp to a local file, fsync'd and atomically renamed into place (Doc 3 §5), on a 1s cadence.
- Watchdog (separate OS process, deliberately minimal — the brief's instinct to keep this simple is correct: a complex watchdog is a watchdog that can itself fail) polls that file every 2s.
- Heartbeat stale >10s → Watchdog independently calls Kalshi's cancel-all-orders REST endpoint directly, using its own code path that does not depend on the Trading Engine process being responsive in any way.
- **This is the primary safety net, not a backup**, given Doc 1's finding that Kalshi has no confirmed REST/WS-native cancel-on-disconnect. [VERIFY: re-check `docs.kalshi.com/fix/session-management` directly — if FIX cancel-on-disconnect is confirmed available and the project ever moves to FIX for order entry, that becomes a genuine second layer; until then, the Watchdog is the only layer.]

**Three gaps fixed after Opus adversarial review:**

1. **Heartbeat proved process-alive, not logic-alive.** If the heartbeat write ran on its own free-running timer task, a deadlock or livelock in the risk/OMS logic could leave that task ticking merrily while the actual trading loop was stuck — the watchdog would see a fresh file and never fire, despite the thing it exists to protect against having already happened. **Fix:** the heartbeat is written **only as the last step of each completed core-loop iteration** (market data processed → fair value updated → strategies evaluated → risk-checked → submitted), capped at once per second, not by an independent timer. A stuck loop stops producing heartbeats, full stop — this is what makes the 10s threshold actually mean "the loop is stuck," not just "the process didn't segfault."
2. **The cancel-all action was fire-once with no verification.** If the Watchdog's REST call itself failed (auth error, 5xx, transient network issue), nothing retried it and nothing alerted — the one action the entire switch exists to perform could silently fail. **Fix:** the Watchdog retries the cancel-all call with backoff, then re-fetches open orders to verify the count is actually zero; if orders are still open after N retries, it escalates to the phone/log alert (Doc 7) as a distinct, louder failure mode ("dead-man switch fired but could not confirm flatten") rather than treating "I sent the cancel request" as equivalent to "I confirmed it worked."
3. **No watchdog-of-the-watchdog.** If the Watchdog process itself crashes, nothing notices, and the dead-man switch is silently gone. At this project's scale, full redundancy for the Watchdog (e.g., a second independent monitor) is judged not worth the added complexity — **the pragmatic mitigation is a process supervisor (systemd/supervisord) configured to auto-restart the Watchdog and to alert on repeated-crash-loop**, which is a few lines of config, not a new component. Full external redundancy is deferred as a Phase 4+ enhancement if scaled size ever justifies it — noted here as a judgment call, not solved.

## 9. Reconciliation Break + Manual Kill Switch

- CLI command (`thorp kill`) writes a halt flag the Trading Engine's risk engine polls every cycle **and independently** calls Kalshi's cancel-all/flatten REST endpoints directly — belt-and-suspenders, works even if the Engine process is fully wedged and never reads the flag.
- Phone/mobile-accessible physical trigger: **explicitly deferred to Phase 4**, judgment call. At $1,000 capital and 15 hrs/week, building a mobile-triggerable kill switch (e.g., an authenticated webhook or bot command) before the Watchdog + CLI kill exist and are tested is solving a problem this project doesn't have yet — the Watchdog's automatic dead-man trigger covers the "operator is asleep/unreachable" case without needing a phone in hand. Revisit once Phase 4 sizing makes a faster manual response meaningfully valuable.

## 10. Startup Safety

The Trading Engine's state machine has an explicit `STARTING` state that cannot transition to `ACTIVE` without a successful reconciliation fetch (§7) — this is not a "best practice" note, it is a literal blocking state transition in the Engine's own code, tested by a startup integration test that fails if any code path reaches `ACTIVE` without having called the reconciliation fetch first (Doc 6 §3).

## 11. Summary Table — Where Each Control Lives

| Layer | Controls enforced there |
|---|---|
| `RiskEngine.check()` (Doc 3 §3.5) | Per-order, per-group, portfolio, fading/hurdle logic |
| OMS (Doc 3 §3.6) | Rate controls, idempotency, order state machine |
| `FairValueEngine` (Doc 3 §3.3) | Staleness-driven uncertainty widening |
| Trading Engine top-level loop | Data-staleness hard cancels, reconciliation, startup gating |
| Watchdog process (separate) | Dead-man switch |
| Control CLI (separate) | Manual kill |
| Operational (human/banking) | Max total capital deployed |

No single strategy bug can bypass this because every layer below the Strategy layer re-derives and re-checks state from `RiskState`/reconciled exchange data rather than trusting what the strategy or even the risk engine's own prior decision claimed — this redundancy (e.g., the risk engine re-summing group exposure rather than trusting a running counter the strategy maintains) is deliberate, not an oversight.
