# Document 10 — Architecture Decision Records

## ADR-001: Python, multi-process, over C++/Rust hot path or pure single-process

**Context:** operator has strong C++ background, no Rust; strategy shortlist (Doc 1) explicitly excludes latency-sensitive in-play trading, so no strategy-driven need for sub-millisecond decisioning.

**Options considered:** (a) pure Python single-process/threaded; (b) Python research + C++/Rust hot path; (c) all-Rust; (d) Python, multi-process, asyncio within each process.

**Decision:** (d). Multi-process for fault isolation (recorder/watchdog survive engine crashes), asyncio within the Engine process for I/O concurrency, no hot-path language given no latency-sensitive strategy exists in scope.

**Consequences:** slower absolute execution speed than (b)/(c), irrelevant given the strategy profile. Lower engineering complexity for a solo 15hr/week operator. The `ExecutionVenue` and `FairValueEngine` interfaces (Doc 3 §1) are left as seams for a future hot-path swap if a latency-sensitive strategy is ever explicitly re-authorized (Doc 1 §3).

## ADR-002: Kalshi-only execution; Polymarket and sportsbook odds as read-only signal inputs

**Context:** original strategy shortlist included cross-venue Polymarket execution arbitrage. Research (Doc 1 §1.2) found Polymarket's US-access situation is actively unresolved (original CLOB is close-only for US persons; a separate KYC'd "Polymarket US" product exists but its bot/API maturity is unconfirmed) and its platform underwent a major migration (pUSD, rewritten book) in April 2026.

**Decision:** execute only on Kalshi. Use Polymarket's public read-only price data and sportsbook consensus odds (via The Odds API) purely as inputs to the fair-value engine (Doc 3 §3.3).

**Consequences:** the cross-venue arbitrage strategy (Doc 1 §4.4) is demoted from tradeable to signal-only. This removes an entire class of execution risk (custody, KYC, on-chain settlement, geoblock compliance) at the cost of a strategy candidate whose underlying edge is preserved as an input to the primary strategy (4.1) rather than lost. Revisit if Polymarket US's bot/API access is confirmed mature (Doc 8 §1).

## ADR-003: Single injected `ExecutionVenue`, not mode-branching in strategy code

**Context:** brief requires one strategy codebase across BACKTEST/SIMULATION/CANARY/PRODUCTION.

**Options considered:** (a) `if mode == "sim"` branches inside strategy/OMS code; (b) a single `ExecutionVenue` protocol with four implementations, injected once at startup.

**Decision:** (b).

**Consequences:** strategy code cannot accidentally diverge in behavior between modes because it has no branch to diverge on — it only ever calls the injected venue's interface. CANARY and PRODUCTION are the literal same `KalshiLiveVenue` class, differing only in risk-engine-enforced size caps, which is what makes the CANARY→PRODUCTION validation meaningful (Doc 3 §4).

## ADR-004: Correlated risk grouping is per-game, not per-contract

**Context:** a single game can have several Kalshi markets (moneyline, spread, total) that are not independent risks.

**Decision:** all markets referencing the same game are one correlated group for position-cap, fading, and exposure-check purposes (Doc 2 §5, Doc 4 §2).

**Consequences:** prevents a strategy (or three strategies, per the Opus-review finding in Doc 4 §5) from building an effectively-single large directional bet across three "separate" markets that each individually look small. Requires a stable game-identifier derivation from series tickers, a small but load-bearing piece of code.

## ADR-005: 10% fractional Kelly at canary, with a continuous inventory-based fade rather than a hard binary cutoff

**Context:** brief specifically requested position-fading parameters to prevent over-accumulation; full Kelly is provably wrong under estimated (not known) probabilities.

**Decision:** base sizing at 10% of full Kelly during canary (Doc 2 §5), rising to 25% only after a validated Phase 4 track record; a continuous linear fade between `soft_cap` and `hard_cap` per correlated group, plus a scaling required-edge hurdle for taking strategies, rather than a strategy that sizes freely up to a hard wall.

**Consequences:** more conservative sizing than a professional desk might use, deliberately — justified by model uncertainty (noisy fair-value estimate), not just variance. A continuous fade produces smoother, more predictable behavior near the cap than a binary cutoff, and is enforced redundantly at the risk-engine layer (Doc 4 §2) regardless of whether the strategy layer's own hurdle logic is correct.

## ADR-006: Parquet on S3, partitioned by venue/data_type/date/series, tiered lifecycle

**Context:** budget is "tens of dollars/month," research access pattern is "load all NBA moneyline books for March" as a one-liner.

**Decision:** columnar Parquet, partitioned `venue/data_type/date=.../series=...`, S3 Standard → Standard-IA (30d) → Glacier Instant Retrieval (180d), queried via DuckDB directly against S3 rather than bulk local sync (Doc 5 §3, §5).

**Consequences:** Doc 1's infra research shows this stays in the low single-dollar range even at 2-year/high-volume assumptions. Glacier Instant Retrieval (not Deep Archive) is chosen specifically to preserve the "casual one-liner" research-access requirement — Deep Archive's multi-hour retrieval would violate that even though it's cheaper.

## ADR-007: In-flight order exposure is a synchronously-updated reservation ledger, not derived solely from reconciled fills

**Context:** the original design derived `RiskState` group/portfolio exposure purely from reconciled, filled positions (Doc 4 §7's 5s reconciliation cadence). An Opus adversarial review (Doc 9) found this allows a batch of approved-but-unfilled orders to blow through a position cap by up to 6x, since none of them are visible to the check until they fill.

**Decision:** `RiskState` exposure = reconciled filled position + notional of every approved-but-not-yet-terminal order, reserved synchronously at approval time, before the approving coroutine yields via `await` (Doc 3 §3.5).

**Consequences:** this is the single most consequential fix produced by the adversarial review pass — without it, the entire per-group/portfolio control catalog in Doc 4 §2-3 is enforceable in appearance only. It requires the risk engine to track reservations as first-class state, released and reconciled against actual fills/cancels at order terminus, adding real implementation complexity that is judged clearly worth it given what it prevents.

## ADR-008: The Watchdog process is the primary dead-man switch, not a backup to an exchange-native feature

**Context:** Doc 1's Kalshi research found no confirmed REST/WebSocket-native cancel-on-disconnect; only FIX has a documented (but unverified this session — 404'd page) cancel-on-disconnect tag, and FIX access requires Premier tier or an institutional request this project doesn't currently have.

**Decision:** build and rely on a standalone Watchdog process (Doc 3 §2, Doc 4 §8) as the primary mechanism, not a secondary layer.

**Consequences:** more engineering effort up front (a correctly-designed dead-man switch, hardened per the Opus review's findings on heartbeat semantics and verified cancel-all) than would be needed if the exchange handled disconnect-driven cancellation natively. If FIX cancel-on-disconnect is later confirmed and the project moves to FIX for order entry, it becomes a genuine second layer, not a replacement for the Watchdog — never remove the Watchdog on the strength of an exchange-side feature alone.

## ADR-009: In-play sports trading is out of scope for this plan entirely

**Context:** Doc 1 §3's research found official low-latency sports data feeds cost 4-6x the entire starting capital per month, and Kalshi's visible sports-market-making presence is already dominated by HFT-pedigree firms (Susquehanna, reportedly DL Trading).

**Decision:** the system does not quote or take positions during live game play in Phase 0-3. This is not a parameter that gets relaxed as the project matures — it requires a separate, explicit re-authorization decision, structurally distinct from scaling the pre-game strategy.

**Consequences:** simplifies the risk design considerably (no need for sub-second data-staleness handling of live game state, no jump-risk inventory management for in-play catalysts) and removes the project's single largest identified way to lose money to structurally better-resourced competitors.

## ADR-010: Sportsbook consensus fair value uses DK/FD/MGM/Caesars, not Pinnacle

**Context:** Pinnacle (the academic literature's preferred "sharp" reference line, Doc 1 §2.3) closed public API access in July 2025; third-party resellers exceed budget.

**Decision:** build the de-vig consensus from the four books available on The Odds API's `us` region ($30-59/mo tier), accepting the quality gap this creates versus the literature's assumed reference.

**Consequences:** the fair-value model's calibration ceiling is lower than an idealized version with Pinnacle access — stated explicitly as a known limitation (Doc 1 §1.3) rather than glossed over, and factored into why Polymarket's independent price is included as a second, orthogonal input rather than relying on sportsbook consensus alone.
