# Document 11 — Execution Analytics: Markouts, Adverse Selection, and Edge Attribution

Doc 2 §1 named the metrics ("realized edge per contract vs. modeled edge," "fill-rate vs. adverse-selection decomposition," "fair-value model calibration") without specifying how they're computed. This document specifies them. It also generalizes and subsumes the narrower "sim-vs-live divergence report" from Doc 3 §4 / Doc 6 §7 — that report and this framework are the same computation applied to different fill sources (shadow fills in SIMULATION, real fills in CANARY/PRODUCTION), and should share one implementation, not two.

## 1. Where This Lives

A **batch/offline analytics component**, not part of the live hot path — consistent with Doc 3's "safety, then clarity, then speed" ordering, and with the precedent already set for CPU-bound work (Doc 3 §5's separate-batch-process pattern for backtest sweeps). It reads the event log (Doc 3 §3.8) and the Recorder's captured book/price data (Doc 5), and writes its own Parquet output table alongside the research corpus, queryable the same way (Doc 5 §7). It runs daily during any phase that produces fills (SIMULATION onward), plus on-demand via the research access layer.

## 2. The Core Decomposition

For any fill, at contract price `P`, side `s` (+1 buy_yes / −1 sell_yes), with `FV` = the fair-value estimate the strategy acted on (Doc 3 §3.3) and `O` = the eventual settlement outcome (0 or 1):

```
realized_pnl_per_contract = entry_edge + calibration_error − fee

entry_edge        = s × (FV_at_trade − P)         # did we trade cheap/rich relative to OUR OWN model
calibration_error = s × (O − FV_at_trade)         # was our model's belief actually right
```

This is the full attribution: **entry_edge measures execution quality against the model; calibration_error measures whether the model itself was correct.** A strategy can have great execution (always trading at favorable prices relative to its own fair value) and still lose money if the fair-value model is miscalibrated — this decomposition is what makes that distinguishable instead of collapsing into one opaque P&L number. `calibration_error`, aggregated across many fills and compared against `FV_at_trade`, is exactly the Brier-score-style calibration metric Doc 2 §1 already named as a 3-month success criterion — this document gives it a concrete formula tied to per-fill data rather than leaving it as a named-but-undefined concept.

## 3. Markouts

For a fill at time `t`, price `P`, side `s`, define the markout at horizon `Δ` against a reference price series `ref(·)`:

```
markout(Δ) = s × (ref(t + Δ) − ref(t))
```

Positive = price moved in our favor after the fill. Negative = we got picked off (§4).

**Two reference series are tracked in parallel, not one**, because they answer different questions:
- **Market markout** — `ref = Kalshi mid-price`. Answers "did the market move our way after we traded," independent of whether our model was right — this isolates microstructure/adverse-selection effects from model correctness.
- **Model markout** — `ref = our own fair-value estimate`. Answers "did our belief keep moving in our favor after we traded" — a strategy whose model markout is persistently negative even when its entry edge looked positive is a sign the fair-value engine itself is noisy/mean-reverting rather than tracking something real.

**Horizons**, chosen for a pre-game, non-latency strategy (not HFT tick horizons, which would be meaningless here): **1 minute, 5 minutes, 30 minutes, at Kalshi market close (kickoff), and at settlement.** The settlement-horizon market markout is, by construction, equal to `realized_pnl_per_contract` before fees — it's included in the same table for continuity, not as a separate concept.

## 4. Pickoff Detection (Adverse Selection)

A fill is flagged as a **pickoff** if its 1-minute *market* markout is negative and exceeds a threshold: `market_markout(1m) < -pickoff_threshold`, default `pickoff_threshold = 1¢` (tunable once Phase 1/2 data shows the actual noise floor of 1-minute Kalshi price movement — 1¢ is a starting default, not a validated figure).

Tracked as:
- **Pickoff rate** = pickoffs / total fills, computed per strategy, per correlated group, and per a market-thinness bucket (volume/open-interest tier, Doc 5's research access layer).
- **Pickoff severity** = mean/median markout magnitude among pickoff events.

This is most relevant to Strategy 4.3 (thin-market liquidity provision, Doc 1 §4.3), whose entire viability question — *is thin liquidity actually uninformed, or just less-competed-for informed flow?* — is precisely "does resting-quote pickoff rate exceed what the captured spread justifies." **This document is what makes Doc 1 §4.3's kill-if condition ("adverse selection cost exceeds realized spread") computable rather than aspirational**, and it directly extends Doc 1 §4.3's own falsifiable test. Taking strategies (4.1/4.2) are less exposed to this specific failure mode since they choose their own entry timing, but pickoff rate is still computed for them — a persistently high pickoff rate on a taking strategy is a sign its signal is stale by the time it acts (ties to the data-staleness controls in Doc 4 §6).

## 5. Fill-Quality / Quote Metrics (market-making strategies specifically)

For Strategy 4.3 and any future resting-quote strategy:
- **Quote uptime** — % of in-scope time the strategy had a live two-sided quote, vs. paused (e.g., due to staleness degradation or fading, Doc 4 §6/§2).
- **Realized spread capture** — `s × (P − mid_at_fill)`, i.e. how much of the quoted half-spread was actually captured at the instant of the fill, before any subsequent drift — the pre-markout component, isolated from what happens after.
- **Fill rate** — fraction of quoted size that ever gets hit within its resting lifetime.

## 6. Data Model

```python
@dataclass(frozen=True)
class FillAnalytics:
    fill_id: str
    strategy: str
    correlated_group: str
    side: Literal["buy_yes", "sell_yes"]
    trade_price: Decimal
    fair_value_at_trade: Decimal
    mid_at_trade: Decimal
    entry_edge: Decimal                      # §2
    market_markouts: dict[str, Decimal]      # {"1m":..., "5m":..., "30m":..., "close":..., "settlement":...}
    model_markouts: dict[str, Decimal]       # same horizons, model-reference series
    is_pickoff: bool                         # §4
    settlement_outcome: Optional[Decimal]    # filled in once known (0 or 1)
    calibration_error: Optional[Decimal]     # §2, null until settlement
    realized_pnl: Optional[Decimal]          # §2, null until settlement
    fee: Decimal
    fill_model_assumptions: Optional[dict]   # populated for SIMULATION fills only, Doc 3 §4's tagging
```

One table, one schema, whether the fill came from `ShadowVenue` or `KalshiLiveVenue` — this is what makes the sim-vs-live divergence report (Doc 3 §4, Doc 6 §7) a special case of this table rather than a separate pipeline: it's the same `FillAnalytics` rows, grouped by venue-mode and diffed. **A shadow fill's predicted markouts vs. a real CANARY fill's realized markouts, for matched signals, is a more informative divergence check than fill-rate/slippage alone** (which is all the original Doc 3 §4 design compared) — it tells you not just *whether* sim and live disagree but *in which direction the adverse-selection profile differs*, which is exactly the kind of gap the Opus review's shadow-mode findings (Doc 3 §4, Doc 9) were about.

## 7. Reporting

Daily batch job (same cadence as the Doc 5 §6 data-quality report) produces:
- Per-strategy, per-correlated-group summary: mean/median entry edge, markout curve (all 5 horizons), pickoff rate and severity, realized P&L (for fills old enough to have settled).
- A rolling calibration check: bucket fills by `fair_value_at_trade` (e.g. deciles) and compare mean `settlement_outcome` within each bucket to the bucket's mean `fair_value_at_trade` — a direct, visual calibration curve, the same shape as the Kalshi-78%/Polymarket-67%/PredictIt-93% figures cited in Doc 1 §2.4, now computed for this system's own fair-value engine instead of just cited from someone else's study.
- Flags: any strategy whose 30-day pickoff rate exceeds a configurable threshold, or whose entry-edge-to-realized-P&L ratio falls outside the Doc 2 §1 0.5x–1.5x band, surfaces in the report header, not buried in a table.

## 8. Tests (extends Doc 6)

- Unit: `entry_edge`/`calibration_error`/`realized_pnl` formulas against hand-computed examples, including sign conventions for both sides (buy_yes and sell_yes must produce symmetric, correctly-signed results).
- Property-based: for any fill where `settlement_outcome` is known, `realized_pnl == entry_edge + calibration_error − fee` holds exactly (this is an algebraic identity, not a statistical claim, and should be tested as one — a violation means a bug, not noise).
- Integration: a synthetic sequence of fills with known subsequent price paths produces the expected markout values at each horizon, including the pickoff flag triggering correctly at the threshold boundary.
- The two-sided-quote print-allocation fix (Doc 3 §4) is directly exercised here too: a synthetic scenario with a shadow strategy quoting both sides must not produce `FillAnalytics` rows implying the same real print filled both a hypothetical buy and a hypothetical sell.

## 9. Roadmap Placement (extends Doc 7)

Not on the Week 1-5 critical path (no fills exist to analyze until SIMULATION is running). Build in **Week 6, alongside `ShadowVenue`** — the two should land together, since shadow fills are this framework's first real input and validating the fill-model fixes from Doc 3 §4 *requires* markout/pickoff analysis to be running, not something bolted on after the fact once CANARY starts. Doc 7's Week 6 effort estimate (~15h) should be read as covering both, not `ShadowVenue` alone.
