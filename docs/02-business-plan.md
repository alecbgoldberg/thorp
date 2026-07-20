# Document 2 — Business Plan

## 1. Objectives and Success Criteria

Sharpe is meaningless on the trade counts this plan will generate in its first 6 months. The metrics below replace it.

| Horizon | What "shows promise" means, numerically |
|---|---|
| 1 month (end Phase 0/1) | Data pipeline uptime ≥99% over the measurement window; ≥30 settled games captured end-to-end with full pre-game price history (Kalshi + sportsbook consensus + Polymarket); an initial per-strategy edge-per-contract estimate computed from backtest (not yet gated on profitability) |
| 3 months (end Phase 3 canary) | Realized edge per contract vs. modeled edge, ratio in **0.5x-1.5x** (tracking the model, not wildly off); fill-rate vs. adverse-selection decomposed and reported; fair-value model calibration (Brier score against actual outcomes) computed and compared against the Doc 1 benchmark range (Kalshi 78% / Polymarket 67% / PredictIt 93% in the reference study); directional hit-rate vs. Kalshi's own closing price ≥50% on a sample large enough for a binomial test to be informative (≥100 independent signals) |
| 6 months | Cumulative realized P&L net of fees and infra costs; strategy-level comparison (did 4.1 outperform 4.2/4.3 as the research hypothesized); explicit reinvestment decision made against the policy in §5 |

## 2. Phase Gates

Each gate's criteria are pre-registered here, before any results exist. A gate that isn't met is not renegotiated after the fact.

### Phase 0 — Data Collection (Weeks 1-3, no trading)
**Gate 0→1:**
- ≥14 consecutive days of Kalshi book/trade capture with <1% sequence-gap rate (Doc 5 quality report)
- ≥14 days of matched sportsbook-consensus + Polymarket price capture for the same games
- Zero missed days in the daily data-quality report
- ≥30 completed (settled) games captured with full pre-game price history

**Fail action:** extend Phase 0 and fix recorder reliability. Do not backtest on a pipeline that hasn't proven it captures cleanly — a backtest built on a leaky recorder produces a confident, wrong answer.

### Phase 1 — Backtest (Weeks 3-5, overlapping continued capture)
**Gate 1→2**, evaluated per-strategy (4.1/4.2/4.3 from Doc 1 each get their own pass/fail, not a shared bar):
- Positive expected edge per contract, net of fees, under the **pessimistic** fill model (Doc 3), significant at p<0.05 across ≥200 independent signal instances (correlated same-game signals count as partially dependent, not 1:1 as independent trials — the backtest harness must account for this or the significance claim is inflated)
- Edge magnitude exceeds round-trip fee by ≥2x at the median trade price level (safety margin for model/estimation error)
- Edge remains positive under both "pessimistic" and "very pessimistic" fill-model settings

**Kill-if:** no strategy clears this bar after the full captured sample. If still negative after 8 weeks of data, treat this as evidence the pre-game edge thesis is wrong, not as a reason to lower the bar — reopen Doc 1's shortlist instead.

### Phase 2 — Live-Book Simulation / Shadow (Weeks 5-7)
**Gate 2→3:**
- ≥10 trading days in SIMULATION mode (real feed, real strategy, no orders sent)
- Simulated fill rate falls within a plausible range of the pessimistic backtest assumption — large deviation means the backtest fill model was wrong, not that the strategy is ready
- Simulated realized edge stays within 30% of the Phase 1 backtested figure
- Zero unhandled exceptions/crashes over the run; every risk control (Doc 4) exercised at least once (synthetic triggers allowed) with correct behavior

### Phase 3 — Canary (Weeks 7-8+, live orders, trivial size)
**Gate 3→4:**
- ≥100 live fills accumulated
- Sim-vs-live divergence report (Doc 3) shows fill rate and slippage within pre-registered tolerance (realized slippage within 1.5x of shadow-predicted slippage)
- No risk-control breach requiring manual intervention beyond controls that were expected/designed to fire
- Realized P&L is not *significantly* negative, adjusting for small-sample noise — the bar is "no red flags," not "profitable at N=100," because profitability isn't statistically resolvable at that sample size

### Phase 4 — Scaled (ongoing)
Sizing governed by §5 (fading parameters) and reinvestment governed by §7, not a one-time gate.

### Hard shutdown criteria (stop the whole project, not just a phase)
- Cumulative realized loss exceeds **$300 (30% of starting capital)** at any point from Phase 3 onward — no exceptions, no "let it run one more week."
- No strategy clears the Phase 1 fee-hurdle bar after 8 weeks of captured data — the core edge thesis is falsified.
- Kalshi sports contracts become illegal/restricted in the operator's state of residence (Doc 1 §1.1 circuit split) — halt pending legal resolution.
- A reconciliation break (Doc 4) that cannot be explained/resolved within 24 hours — halt pending investigation, never trade through it.

## 3. Capital Allocation

$1,000 starting capital, split:

| Bucket | Amount | Purpose |
|---|---|---|
| Kalshi trading balance | $700 | Live capital at risk, all phases |
| Reserve (uncommitted) | $150 | Buffer against settlement timing, margin, emergency |
| Held back / not deployed initially | $150 | Deliberately idle — do not feel compelled to deploy 100% of capital on day one |

**Data/infra spend is treated as a separate operating budget, not drawn from the $700 trading balance** (consistent with the operator's stated willingness to pay tens of $/month for this as an R&D investment, distinct from trading risk capital — see §4).

**Per-strategy caps within the $700** (Phase 3 canary, before Phase 4 scaling):
- 4.1 (external-consensus mispricing, primary): full canary allocation, scaling toward majority allocation in Phase 4 once its own Phase 1 gate is cleared.
- 4.2 (complementary-outcome arbitrage): capped at $100 concurrent exposure — unproven at this venue even though the mechanism is precedented on Polymarket.
- 4.3 (thin-market liquidity provision): capped at $150 concurrent, and only activated once its *own* Phase 1 backtest (adverse-selection-vs-spread-capture) clears independently — do not fund it on the strength of 4.1's gate.

## 4. Cost Model

| Item | Low | Expected | High |
|---|---|---|---|
| AWS (S3 + compute) | $5/mo | $12/mo | $25/mo |
| Sportsbook odds API | $30/mo | $59/mo | $99+/mo |
| **Total infra/data (excl. exchange fees)** | **$35/mo** | **$71/mo** | **$124/mo** |
| Kalshi exchange fees (canary-size activity, ~100 trades over Phase 3) | ~$10 | ~$15 | ~$25 |

**The flag the brief asked for, stated plainly: expected infra spend (~$71/mo) will very likely exceed or match canary-phase trading P&L.** At deliberately trivial Phase 3 position sizes, a real, positive-edge strategy can easily produce single-digit-to-low-double-digit dollar P&L over a few weeks — smaller than one month of Odds API + AWS spend. **This is expected and should not be read as evidence of failure.** Budget $400-700 of pure infra/data spend as a sunk R&D cost over the first 6 months, independent of trading P&L, and judge the strategy on the Phase 1/Phase 3 gate criteria (§2), not on whether canary-phase trading revenue covers the AWS bill.

Recommendation to control this: start on the Odds API's $30/mo tier (5-minute poll cadence, still fine for pre-game-only signal), not the $59/mo tier, until Phase 1 backtesting shows poll-frequency is actually a binding constraint on signal quality.

## 5. Position Sizing and Fading Parameters

**Base sizing: fractional Kelly.** For a binary contract bought at price P with model probability estimate p̂, full-Kelly stake fraction is approximately `f* = p̂ - (1-p̂)·P/(1-P)` (derived from the standard Kelly formula for a bet costing P per unit, paying 1 on success). **This plan uses 10% of full Kelly during Phase 3 canary (`f_used = 0.10 × f*`), not full or half Kelly.** Justification: full Kelly is only optimal if p̂ is known exactly; here p̂ is itself a noisy estimate (a de-vigged blend of 4 sportsbooks without a Pinnacle reference, plus an imperfectly-calibrated Polymarket price per Doc 1's 67% figure). Betting full Kelly against an *uncertain* edge estimate systematically overbets relative to true optimal sizing under parameter uncertainty — this is a model-uncertainty argument, not just a variance-reduction one. `f_used` may rise to 0.25× full Kelly (quarter-Kelly) only after a full Phase 4 track record validates the calibration claims in §1's 3-month metrics — this is a Phase 4 decision, not automatic.

**Fading parameters (explicit anti-accumulation control).** Position is tracked and capped **per correlated group**, not per individual contract — every market referencing the same game (moneyline, spread, total) is one risk unit, per Doc 4's correlation-grouping definition.

- `hard_cap` = min($150, 15% of current Kalshi trading balance) per correlated group — floor $50 so the cap doesn't become meaningless if the trading balance shrinks.
- `soft_cap` = 50% of `hard_cap` — this is the fade *trigger*, not the limit.
- Below `soft_cap`: quote/order size follows `f_used` sizing unmodified.
- Between `soft_cap` and `hard_cap`: size on the side that would **increase** |position| is linearly reduced to zero as position approaches `hard_cap`; size on the side that **reduces** |position| is unaffected. This is the "fade."
- At `hard_cap`: the risk engine (Doc 4) hard-blocks any order that would increase |position| further, independent of what the strategy layer requests — this is the enforcement backstop, not just a strategy-layer suggestion.
- **Taking-strategy variant** (applies to 4.1/4.2, which take liquidity rather than post resting quotes): instead of skewing a resting quote, the required edge threshold to justify *adding* to an existing position scales up with inventory: `min_edge_required = base_edge × (1 + inventory_ratio × hurdle_multiplier)`, with `base_edge` set from the Phase 1 backtest's fee-hurdle-plus-margin figure and `hurdle_multiplier = 2` as a starting default (so at 50% of `soft_cap`, the required edge is 1.5x base; at `soft_cap`, 2x base). This makes it progressively harder, not impossible, to keep adding to a position that's already sized up — exactly the "help us not accumulate too much position" behavior requested, implemented as a continuous fade rather than a binary cutoff below `hard_cap`.

Illustrative interface (pseudocode, not implementation):

```
def size_multiplier(position, hard_cap, soft_cap, side_increases_position: bool) -> float:
    if not side_increases_position:
        return 1.0
    ratio = abs(position) / hard_cap
    if ratio <= soft_cap / hard_cap:
        return 1.0
    if ratio >= 1.0:
        return 0.0
    # linear fade between soft_cap and hard_cap
    return 1.0 - (ratio - soft_cap / hard_cap) / (1.0 - soft_cap / hard_cap)

def required_edge(position, soft_cap, base_edge, hurdle_multiplier=2.0) -> float:
    inventory_ratio = min(abs(position) / soft_cap, 1.0)
    return base_edge * (1.0 + inventory_ratio * hurdle_multiplier)
```

Doc 4 specifies where this is enforced (strategy layer proposes, risk engine enforces the hard cap independent of strategy correctness) and how it's tested (negative tests proving the hard cap cannot be bypassed).

## 6. Risk Register

| # | Risk | Likelihood | Impact | Control |
|---|---|---|---|---|
| 1 | Fee formula/sports fee_multiplier assumption wrong (unconfirmed primary source) | Medium | Medium — changes breakeven edge calc | [VERIFY] against primary PDF before finalizing Phase 1 backtest; fee model is a parameter, not a hardcoded constant |
| 2 | Kalshi sports contracts ruled illegal/restricted in operator's state | Medium (active litigation) | High — forced shutdown | State-of-residence legal check before Phase 3; monitor CFTC/court dockets; hard shutdown criterion already defined (§2) |
| 3 | Core edge thesis wrong — Kalshi's designated MMs already price external consensus efficiently | Medium-High | High — kills the primary strategy | Phase 1 falsification gate; Doc 1 §4.1 kill-if condition |
| 4 | Strategy 4.3 (thin markets) — thin ≠ uninformed, adverse selection eats the spread | Medium | Medium | Phase 1 backtest explicitly measures adverse-selection cost vs. spread capture before any live capital touches 4.3 |
| 5 | Data recorder gaps/downtime silently corrupting backtest conclusions | Medium (single points of failure at this budget) | High — garbage-in-garbage-out for the whole validation | Doc 5 daily quality report; Phase 0 gate blocks progression on unclean capture |
| 6 | Runaway loop / duplicate orders (operational bug) | Low-Medium | High | OMS idempotency keys, rate controls, manual + automatic kill switch (Doc 4) |
| 7 | Stale reference-data feed (sportsbook/Polymarket) corrupting fair value | Low-Medium | Medium-High | Data-staleness kill switch (Doc 4) — pulls quotes/blocks new orders if inputs are stale, even though we don't quote in-play |
| 8 | Kalshi API key compromise | Low | High | Secrets management (Doc 7); position/loss limits bound the damage even if compromised |
| 9 | Exchange outage / API degradation mid-position | Low-Medium | Medium | Reconciliation-on-reconnect (Doc 4); conservative sizing caps max loss even in a bad outage |
| 10 | Infra/data cost bleed exceeds canary-phase P&L, operator loses patience before the sample is large enough to judge the strategy | Medium-High | Medium (opportunity loss, not trading loss) | Explicit cost-model framing (§4) sets expectations in advance; infra is a sunk R&D cost, not a trading P&L input |

## 7. Reinvestment Policy

A rule, not a vibe:

1. **Canary → Tier 1 (within existing $700):** unlocked automatically once Phase 3 gate (§2) is cleared. No new capital, just permission to size up to the fading-parameter caps in §5 instead of trivial canary size.
2. **Tier 1 → new capital injection:** unlocked only after **3 consecutive profitable months** (net of fees + infra) at Tier 1 size, with realized edge tracking modeled edge within the 0.5x-1.5x band from §1. Any single new-capital addition is capped at 50% of current capital — do not double the book on the strength of a 3-month track record.
3. **Any hard shutdown criterion (§2) breach freezes reinvestment immediately**, regardless of prior track record, until the operator explicitly re-authorizes.
4. Reinvestment decisions are manual (operator-approved), never automatic — the system can recommend, per the metrics in §1, but must not self-scale capital.
