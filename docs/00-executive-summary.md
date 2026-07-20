# Document 0 — Executive Summary & Go/No-Go

## Recommendation: Go, scoped down hard from the original brief, conditional on one legal check.

Proceed with Phase 0 (data collection, Kalshi-only, no live capital) immediately. Do not fund a live trading account until the state-of-residence legal check (below) clears. Do not build for in-play sports trading at all — that part of the original scope is dead, not deferred.

## What changed from the original ambition

- **In-play sports market-making is off the table, structurally, not marginally.** Official low-latency data feeds run $4,000-6,000+/month — 4-6x this entire bankroll, per month, before any trading — and Kalshi's visible sports-market-making presence is already occupied by HFT-pedigree firms (Susquehanna is a designated MM; DL Trading reportedly the largest sports MM on the venue). This isn't a probabilistic edge case, it's a different weight class of capital. The system does not quote or take positions during live game play, full stop, and revisiting that requires a separate, explicit re-authorization later, not a natural extension of what's built here.
- **Polymarket execution is out of scope; Polymarket price data is not.** Polymarket's US-access situation is unresolved (the original wallet-based venue is close-only for US persons; a new KYC'd "Polymarket US" product exists but its bot/API maturity is unconfirmed) and the platform underwent a major migration in April 2026. Rather than build execution infrastructure against a venue in flux, this plan uses Polymarket's public price data — and sportsbook consensus odds — purely as inputs to a Kalshi-only strategy's fair-value estimate. The edge thesis survives; the execution risk doesn't.
- **The primary strategy is now information-aggregation, not modeling or speed.** Buy/sell Kalshi when it diverges from a de-vigged blend of sportsbook consensus and Polymarket's price — an approach that plays to the operator's microstructure/execution strengths and doesn't require building sports-forecasting expertise from scratch. Two supporting strategies (complementary-outcome arbitrage, thin-market liquidity provision) are lower-priority and gated independently.

## Is $1,000 viable?

Marginally, and only if infra cost is treated as separate from trading capital. Kalshi's taker fee runs ~0.34¢-1.75¢/contract depending on price, meaning a directional bet at the money needs to clear a real, demonstrated edge just to break even — this is not a venue where noise trading survives. Expected data/infra spend (~$71/month: sportsbook odds API + AWS) will likely exceed or match canary-phase trading P&L, because canary size is deliberately trivial. That's expected, not a failure signal, provided it's budgeted as R&D spend going in rather than discovered as a surprise in month three.

## The single biggest risk, and it isn't a trading risk

Kalshi's legal right to offer *sports* contracts is genuinely contested as of this writing — an active, unresolved circuit split (Third Circuit favorable to Kalshi in April 2026, S.D.N.Y. against in July 2026, both under appeal), with several states having already issued cease-and-desist actions. This is state-dependent and moving month to month. **This plan is built on the assumption that this resolves favorably or is at least not adverse in the operator's home state — that assumption needs to be checked, not assumed, before a single dollar goes into a live Kalshi account.** It's the one open item that can invalidate the whole plan rather than just move a parameter (Doc 8 §2).

## What the adversarial review process caught

Two independent Opus-tier reviews of the draft architecture and risk-control design, done before any code was written, found a genuine, severe bug: as originally specified, the risk engine would have allowed a single batch of strategy-generated orders to blow through the per-game position cap by up to 6x, because in-flight (approved but not-yet-filled) orders were invisible to the exposure check until they filled. This has been fixed in the design (Doc 3 §3.5, Doc 4 §2) — every order now reserves its exposure synchronously at approval time, not at fill time. Surfacing and fixing this on paper, before it could have cost real money, is the concrete value the review pass bought; it's referenced here because it's the kind of finding that justifies the process, not because the fix itself needs restating.

## The falsifiable core

The whole plan reduces to one testable claim: **Kalshi sports prices sometimes diverge from external consensus in a way that predicts subsequent Kalshi price movement, by more than round-trip fees.** Phase 0-1 (Doc 2, Doc 7) exists to answer that question with real data before any live capital is at risk, with a pre-registered, numeric pass/fail bar (Doc 2 §2) — not to build the trading engine first and hope. If the answer is no after 8 weeks of clean data, the honest conclusion is to stop, not to lower the bar (Doc 2's kill-if conditions say this explicitly).

## Immediate next steps

1. Operator: confirm state of residence for the legal check (Doc 8 §2).
2. Operator: resolve the git/GitHub setup blocker (Doc 8 §3) or accept working without version control for now.
3. Operator: create Kalshi + AWS + Odds API accounts (Doc 8 §2).
4. Start Recorder build — Week 1 of Doc 7, the one thing on this whole roadmap that cannot be backfilled if delayed.
