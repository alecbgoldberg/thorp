# Handoff Brief — Build Phase

Paste this to Fable to kick off implementation. Fable has no memory of the planning conversation that produced this — everything it needs is either in this brief or in `docs/`.

## Context

`~/thorp/docs/00` through `10` (11 markdown files) is a finalized planning package for a solo-operator algorithmic trading system on Kalshi, sports contracts, $1,000 starting capital. It went through a research phase (6+ parallel primary-source research passes) and two independent Opus-tier adversarial reviews of the risk-control and architecture design — several real, severe bugs were found and fixed at the design level before any code existed (most notably: an in-flight-order race that would have let the risk engine's own position caps be breached by up to 6x; see Doc 3 §3.5, Doc 4 §2, and Doc 9 for the full history). Read `docs/00-executive-summary.md` first, then `docs/09-delegation-log.md` for how this was built, then the rest as needed per the task at hand — don't re-derive decisions that are already made and justified in these docs.

**You are authorized to write code now.** The planning-only constraint from the prior phase is lifted.

## Non-negotiables — do not relitigate these

1. **Kalshi-only execution.** Polymarket and sportsbook odds (The Odds API) are read-only signal inputs. No code path may place an order on Polymarket — this is enforced at the type level per Doc 3 §3.1 (`ReferenceDataClient` has no order-placement method), and that type-level enforcement must be preserved, not "temporarily" bypassed for convenience.
2. **No in-play trading.** The system does not quote or take positions during live game play. This isn't a flag to toggle later — see Doc 1 §3 / ADR-009 for why.
3. **Phase gates are real, not aspirational.** Doc 2 §2 has pre-registered numeric pass/fail criteria for Phase 0→1→2→3→4. Do not let "the code works" substitute for "the gate criteria are met." Do not proceed to Phase 1 backtesting on a Recorder that hasn't cleared its Phase 0 data-quality gate.
4. **The risk-engine/OMS design fixes from the adversarial review are load-bearing, implement them as specified, not as a simplified first pass "to get something working":** the in-flight exposure reservation ledger (Doc 3 §3.5), the revised OMS state machine with `PENDING_CANCEL` as a legal pre-fill state (Doc 3 §3.6), cancel-all-before-halt ordering on a reconciliation break (Doc 4 §7), and the watchdog's heartbeat-tied-to-loop-completion + verified-cancel-all (Doc 4 §8). These exist because a reviewer found concrete ways to lose money or blow through limits without them.
5. **Doc 2's $300 cumulative hard-shutdown threshold and the per-phase P&L/loss limits (Doc 4 §5) are not soft suggestions.** If the code doesn't enforce them, it isn't done, regardless of whether the "happy path" strategy logic works.

## Suggested build order (matches Doc 7's critical path)

1. Recorder (Doc 5) — start here, no dependency on anything else. This is also the best candidate for delegating to a bounded coding subagent: it's fully specified (schema, partition scheme, timestamping discipline all fixed in Doc 5), low ambiguity, and not safety-critical in the same sense as the risk/OMS path.
2. Backtest harness + `BacktestVenue` + fair-value engine + Strategy 4.1 (Doc 3 §3.3-3.4, §4).
3. `RiskEngine` + OMS (Doc 3 §3.5-3.6, Doc 4) — build this one yourself or under close, line-by-line review; don't hand the safety-critical path to a subagent without an adversarial review pass on the resulting code, mirroring what was done at the design level. Every control in Doc 4's tables needs its negative test (Doc 6 §2) before this is considered done.
4. `ShadowVenue` (SIMULATION mode) — pay specific attention to the four fill-model fixes in Doc 3 §4 (latency modeling, print-allocation exclusivity, self-exclusion, the assumptions-vector tagging). These were the highest-severity findings from the architecture review; an implementation that skips them silently reintroduces the exact optimism bug that was caught on paper.
5. Watchdog + Control CLI (Doc 3 §2, Doc 4 §8-9).
6. Test suite alongside every component above, not after — Doc 6 specifies which tests are direct regressions for specific adversarial-review findings; those are not optional/deferred-to-later tests.

## Orchestration guidance for you (Fable)

Apply the same tiering discipline that built this plan, now for code:
- Delegate bounded, well-specified, non-safety-critical modules (Recorder, research access layer, backtest data loaders) to Sonnet-tier subagents.
- Do not delegate the risk engine, OMS state machine, or the in-flight exposure ledger to a subagent without personally reviewing the result against Doc 4's control catalog line by line, and get an Opus-tier adversarial code review on that specific code (not just the design) before it's trusted with real orders, even in CANARY.
- Keep a delegation log the same way Doc 9 does — it's cheap to maintain and it's what made the design-phase review process auditable.

## First blocking item

Git/GitHub isn't set up yet — `git` is non-functional on this machine until Xcode Command Line Tools are properly installed (Doc 8 §3). Confirm this is resolved before writing meaningful code, or at minimum don't lose work to the lack of version control — check with the operator on status before proceeding past the Recorder MVP.

## Where to stop and ask

Per Doc 2 §2's hard shutdown criteria and Doc 8 §2's "what I need from you" list — funding a live Kalshi account (Phase 3 canary) requires the state-of-residence legal check to have cleared first. If that hasn't been confirmed, build through Phase 0-2 (data, backtest, shadow) freely, but treat sending a live order as gated on explicit operator confirmation that this check is done, not just on the code being ready.
