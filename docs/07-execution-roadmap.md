# Document 7 — Execution Roadmap (First 8 Weeks)

Budget: ~15 hrs/week, solo. Data capture starts Week 1 per the brief's non-negotiable — every day not recorded is unrecoverable. This roadmap covers Phase 0-3 (Doc 2); Phase 4 is open-ended, gated by the reinvestment policy, not a calendar date.

## Critical Path

```
Recorder MVP (W1) → 14 days clean capture, Gate 0→1 (~end W2/early W3)
  → Backtest harness + fair-value engine + Strategy 4.1 (W3-4)
    → Phase 1 backtest, Gate 1→2 per-strategy (W5)
      → Risk engine + OMS build (W5, can start earlier in parallel if time allows)
        → ShadowVenue / Phase 2 shadow run, 10 *trading* days, Gate 2→3 (W6-7, calendar-dependent on game schedule — 10 trading days is not the same as 10 calendar days if the sport in scope doesn't play daily)
          → CANARY launch, Gate 3→4 begins accumulating toward the 100-fill threshold (W8+)
```

The Risk Engine/OMS build (§Week 5) has no code dependency on the backtest results — it can be pulled earlier if the operator has spare hours, compressing the timeline. Default plan below is serial, matching the 15hr/week constraint.

## Week-by-Week

**Week 1 — Recorder MVP + accounts.** Kalshi API account + demo-env test; AWS account + S3 bucket with lifecycle rules (Doc 5 §5); Odds API signup ($30/mo tier); Recorder v0 — Kalshi WS client capturing book deltas/trades to local JSON (Doc 5 §1-2). Also: kick off the state-of-residence legal check (Doc 1 §1.1 circuit split) now — it's not blocking for demo/data-collection work, but it's a potential project-killer and shouldn't be discovered in Week 8 right before funding a live account. *Effort: ~15h, dominated by the Recorder.* *Needs from operator: Kalshi account, AWS account, Odds API signup, state of residence.*

**Week 2 — Polymarket + compaction pipeline.** Add Polymarket public read-only capture to the Recorder; build the hourly JSON→Parquet compaction job + S3 upload with checksum verification (Doc 5 §3); daily data-quality report v0 (Doc 5 §6). Resolve the Kalshi fee-schedule and sports-series settlement-source [VERIFY] items via direct browser check (the PDF 429'd on every scripted fetch attempt). *Effort: ~15h.*

**Week 3 — Continue capture; backtest harness scaffolding.** Recorder runs unattended (low effort now). Build `BacktestVenue` + the pessimistic-by-default fill model (Doc 3 §4); build the research access layer (`load_books`, `load_matched_signals`, Doc 5 §7). **Gate 0→1 checkpoint lands here** (14 consecutive clean days) — do not proceed to backtesting on a pipeline that hasn't cleared this. *Effort: ~12h.*

**Week 4 — Fair-value engine + Strategy 4.1.** Build `SportsConsensusFairValue` (Shin de-vig + Polymarket blend, Doc 3 §3.3); implement Strategy 4.1 (external-consensus mispricing) against `BacktestVenue`. If time allows, stub Strategy 4.2 (complementary-outcome scan is largely a book-consistency check, cheaper to build than 4.1). *Effort: ~15h.*

**Week 5 — Phase 1 backtest + Risk Engine/OMS.** Run the Phase 1 backtest for 4.1 (and 4.2/4.3 if built) against Doc 2 §2's per-strategy gate criteria — this is a hard evaluation against pre-registered numbers, not a vibe check. In parallel, build `RiskEngine.check()` and the OMS state machine (Doc 3 §3.5-3.6, Doc 4's control catalog) — this code path is identical across all four run modes, so building it now unblocks both SIMULATION and CANARY later. **Gate 1→2 decision point.** *Effort: ~15h.*

**Week 6 — ShadowVenue + execution analytics + ops processes.** Build `ShadowVenue` (Doc 3 §4's SIMULATION mode) and, alongside it (not deferred), the Execution Analytics batch job (Doc 11) — shadow fills are its first input, and validating the fill-model fixes from Doc 3 §4 requires markout/pickoff analysis running from day one of shadow, not bolted on after CANARY starts. Also build the Watchdog + Control CLI processes (Doc 4 §8-9). Begin the Phase 2 shadow run. *Effort: ~18h (upgraded from the original 15h estimate to fold in Doc 11).*

**Week 7 — Shadow run continues; canary prep.** Continue accumulating the 10 required trading days (may extend past this week depending on the in-scope sport's schedule density — treat this as a scheduling risk, not a fixed date). Build the sim-vs-live divergence reporting tooling now so it's ready the moment CANARY starts (Doc 3 §4). Fund the Kalshi live account to the Phase 3 canary level only (not the full $700 — start smaller and step up, Doc 2 §3); set up secrets management for the live API key (Doc 7-ops, see Document 6/7 cross-reference — RSA private key never in plaintext in the repo or a bare env file). *Effort: ~12h.*

**Week 8 — Gate 2→3 decision; CANARY launch.** If Phase 2 gate criteria are met: launch CANARY (single-contract size, Doc 4 defaults). Confirm the state-of-residence legal check is resolved before this step — it is a hard prerequisite for sending any live order, not a formality. Begin tracking the sim-vs-live divergence report on real fills. *Effort: ~10h, shifts from building to monitoring.*

## What's Explicitly Out of Scope for These 8 Weeks

Strategy 4.3 (thin-market liquidity provision) is not on the critical path — its own Phase 1 gate (Doc 2 §2) can run whenever time allows after 4.1 is through, since Doc 2 §3 requires it to clear independently before any capital is allocated to it. In-play strategies are not scheduled at all (Doc 1 §3 kill decision) and would require a separate re-authorization, not a roadmap slot.
