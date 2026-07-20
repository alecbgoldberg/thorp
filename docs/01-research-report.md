# Document 1 — Research Report

Status: draft v1. Sportsbook-odds-API section pending one more research pass (marked below); everything else is primary-source-grounded per the citations inline. [VERIFY] tags mark claims not confirmed against a primary source within this research pass.

---

## 1. Venue Mechanics

### 1.1 Kalshi (execution venue)

**API surface.** Two product lines (Predictions / event contracts, and Perps), each with REST, WebSocket, and FIX. REST base `https://api.kalshi.com/trade-api/v2`, WS `wss://api.kalshi.com/trade-api/ws/v2`. WebSocket is market-data-only (book deltas, tickers, fills feed) — order placement/cancellation is REST-only, meaning there is no exchange-native "streaming order entry" path. FIX (FIXT.1.1 / FIX50SP2) exists but Premier-tier-and-above access is default; lower tiers must email `institutional@kalshi.com`. A full demo/sandbox environment exists at `demo.kalshi.co` with separate credentials and mock funding — demo pricing/liquidity is explicitly not representative of production. (docs.kalshi.com/welcome, docs.kalshi.com/fix, docs.kalshi.com/getting_started/demo_env)

**Auth.** API-key + RSA-PSS request signing (sign `timestamp_ms + METHOD + path`), not OAuth/JWT. [VERIFY: Developer Agreement §9.1(f) references "OAuth Token(s)" as an alternative — unconfirmed whether this is a real alternate auth path or boilerplate legal language.]

**Rate limits.** Token-bucket, separate read/write buckets, 7 tiers from Basic (200 read / 100 write tokens/sec, default on signup) up to Prestige (6,000/8,000). Advanced tier is a self-serve upgrade; Expert+ requires trailing-30-day volume share (0.05%–0.80%) or manual grant. Most requests cost 10 tokens; batch cancels cost 2/order. At $1,000 capital and low order velocity, Basic tier is not a binding constraint. (docs.kalshi.com/getting_started/rate_limits)

**Order types & pricing.** Single order-book model (bid=buy YES, ask=sell YES) with time-in-force flags (`fill_or_kill`, `good_till_canceled`, `immediate_or_cancel`) rather than a market/limit enum; `post_only` flag available; self-trade-prevention modes (`taker_at_cross`, `maker`). Price range $0.01–$0.99 in cents. [VERIFY: third-party sources describe sub-cent tick precision (`tapered_deci_cent`) near the 1¢/99¢ extremes via a `price_level_structure` field on the Market object — not confirmed against a live market response this pass.] [VERIFY: whether Predictions-series orders accept fractional (0.01) contract counts, or whether that's Perps-only.] (docs.kalshi.com/api-reference/orders/create-order-v2)

**Fees.** Taker fee formula: `fee = round_up(0.07 × C × P × (1−P))` per order, in dollars, where P is price in dollars and C is contract count — consistently reported across multiple secondary sources but **not confirmed against the primary PDF, which returned HTTP 429 on every fetch attempt (both by the research subagent and by me directly)**. [VERIFY before finalizing the cost model in Doc 2 — retry `kalshi.com/docs/kalshi-fee-schedule.pdf` from a browser, not a script.] Maker fee is reported as ~25% of the taker rate. A Kalshi-hosted primary page (`docs.kalshi.com/getting_started/fee_rounding`) confirms rounding happens at $0.0001 granularity internally, coarser ($0.01) only at the non-direct-member balance level — finer than the "round to the cent" simplification common in blog writeups. The Series API exposes a `fee_type` (`quadratic` / `quadratic_with_maker_fees` / `flat`) and `fee_multiplier` field, meaning **the 0.07 constant may not apply uniformly — sports series' actual multiplier is unconfirmed** [VERIFY via `GET /series/KXNFLGAME`]. A first-two-days-of-listing fee waiver exists (confirmed via CFTC filing), and a Volume Incentive Program (rolling ≤31-day rebate pool, capped $0.005/contract, running through Sept 2026) is separate from any maker rebate. A formal Market Maker program exists (invitation/application-based, reduced fees + adjusted position limits) with no published capital/volume threshold.

Worked taker-fee table (illustrative, pending PDF confirmation), 100 contracts:

| Price | Fee (100 contracts) | Per-contract |
|---|---|---|
| 5¢ / 95¢ | 34¢ | 0.34¢ |
| 10¢ / 90¢ | 63¢ | 0.63¢ |
| 25¢ / 75¢ | 132¢ | 1.32¢ |
| 50¢ | 175¢ | 1.75¢ |

**Structural implication:** fee-as-%-of-*potential-profit* is worst when buying deep favorites or selling deep longshots (thin margin, same absolute fee) and comparatively cheap on the other side of that trade. This directly intersects the favorite-longshot-bias literature below — the fee schedule itself creates a bias against exactly the side of the market that's already structurally overpriced. Round-trip taking (entering and exiting before settlement) roughly doubles the one-way figures; holding to settlement likely incurs only the entry fee — settlement/redemption itself is assumed fee-free based on standard exchange practice **[VERIFY: not explicitly confirmed by any source this pass]**.

**Contract specs / settlement.** Sports series use tickers like `KXNFLGAME` with per-game tickers appending date+teams (e.g. `KXNFLGAME-25DEC25DALWAS`). Series objects expose `settlement_sources` (official data sources, methodology in the rulebook) and settlement-timing fields (`settlement_timer_seconds`, `latest_expiration_time`), but no default numeric value was confirmed for sports specifically. [VERIFY exact settlement source and timer for a live NFL/NBA series before relying on same-day settlement assumptions.]

**Position limits.** Rule 5.14(a): standard $25,000 (max-loss basis) position limit per contract for retail-eligible contracts; some categories (election/control contracts) carry much higher limits. [VERIFY whether sports carries the standard limit or a different one, and whether it's a hard Position Limit vs. the newer "Position Accountability Level" (monitoring trigger, not hard cap) regime Kalshi has been migrating some contracts to since Nov 2024.] At $1,000 capital this is not a binding constraint regardless.

**Algo trading / ToS.** Developer Agreement (kalshi-public-docs.s3.amazonaws.com) implicitly permits automated trading — API use is "expressly limited to facilitating a member's own trading," not banned from being automated. Explicitly prohibited: caching/redistributing API data to third parties without written consent (§3.1); spoofing/wash trading (§3.3); using the API to monitor Kalshi's own service performance or for "benchmarking/competitive purposes" (§3.5); sublicensing API access (§3.7); non-HTTPS transmission (§3.8). Liability capped at $50 aggregate; Kalshi may suspend/terminate access at its sole discretion without notice. A separate Data Terms of Service reportedly restricts data to non-commercial personal use and requires written consent for building software on top of it, including ML/AI training — **full text not fetched this pass; re-read directly before any model-training use of captured Kalshi data.** [VERIFY]

**Cancel-on-disconnect.** Confirmed to exist for FIX sessions (`CancelOrdersOnDisconnect=Y` tag) but the specific docs page 404'd for the research agent; not independently re-confirmed. **No REST or WebSocket-native cancel-on-disconnect was found** — since WebSocket is market-data-only and REST is stateless, there is no exchange-side "pull quotes if my connection drops" mechanism outside FIX. This is architecturally significant: **the system's own heartbeat/watchdog is the only thing standing between a dropped connection and resting orders staying live** (see Doc 4 §Data-staleness kill / dead-man switch).

### 1.2 Polymarket (signal source only — not an execution venue in this plan)

Polymarket is being used here exclusively as a **read-only fair-value/reference-price input**, not a trading venue, for reasons detailed in Document 8 and ADR-002. Mechanics relevant to that role:

- Hybrid architecture: off-chain order matching, on-chain settlement on Polygon via an audited Exchange contract; gasless for end users via a relayer. (docs.polymarket.com/trading/overview)
- **Major platform migration, April 28, 2026**: Polymarket moved from bridged USDC.e collateral to its own token, **pUSD**, with new smart contracts and a rewritten order book; all open orders were cleared during the migration. Treat pre-April-2026 blog/forum descriptions of Polymarket mechanics as potentially stale. (docs.polymarket.com/concepts/pusd, help.polymarket.com Exchange Upgrade Apr 28 2026)
- **US accessibility, confirmed directly this pass**: the original international Polymarket.com is **"close-only" for US persons** — can exit existing positions, cannot open new ones, on both frontend and API (docs.polymarket.com/api-reference/geoblock, fetched directly). A separate Polymarket-owned help-center page reportedly describes a full block with no exceptions — **the two Polymarket-owned pages disagree; do not build compliance assumptions on either alone.** [VERIFY]
- A **separate, KYC'd, CFTC-regulated "Polymarket US" product** (operated by QCX LLC, acquired by Polymarket for a reported $112M) launched for US residents Dec 3, 2025, settling in USD via FCMs rather than on-chain. API/bot access maturity on this product is unconfirmed and its docs (`docs.polymarket.us`) are thin. This product is **not** what this plan proposes to integrate with (see below) — read-only price consumption from the international CLOB's public market-data endpoints is the intended integration, which does not require an account, KYC, or trading access, only public price/orderbook read access. **[VERIFY that public read-only market-data endpoints are actually accessible without authentication/geoblock restrictions that apply to trading — geoblock language above is framed around opening/closing positions, not necessarily reading public prices, but this needs direct confirmation before building the ingestion pipeline.]**
- UMA optimistic-oracle resolution: proposer bond (~$750 pUSD), 2-hour challenge window, disputed resolutions can run 4-6 days via UMA token-holder voting. Irrelevant to this plan's use of Polymarket (we're not holding Polymarket positions), but relevant color on why Polymarket prices can occasionally reflect resolution uncertainty/dispute risk rather than pure event probability near settlement — a caveat for the fair-value model, not a custody risk to us.
- Fees: maker $0, taker `shares × categoryFeeRate × price × (1−price)`, sports category rate 0.05 (vs. crypto 0.07). Irrelevant to this plan since we don't trade there, but relevant to interpreting Polymarket's own price quality — a 5% taker vig at the money means Polymarket's displayed price also embeds a cost wedge, not a pure probability.

### 1.3 Sportsbook consensus odds (signal source)

**Recommendation: The Odds API, 100K-credit plan, $59/month** (fallback: 20K plan, $30/month, at a slower poll cadence — still fine since this feeds pre-game, not in-play). Billing is credits = markets × regions per request; polling h2h+spread+total (3 markets) in the `us` region every 60-90s during active pre-game windows only (not 24/7) lands in the 40K-100K credit/month range. `us`-region coverage includes DraftKings, FanDuel, BetMGM, Caesars, Bovada, MyBookie. ToS forbids reselling/redistributing the raw feed as a standalone product but does not forbid using it as an internal signal for the operator's own trading decisions; liability for trading outcomes is fully disclaimed by the vendor either way. (the-odds-api.com, the-odds-api.com/terms-and-conditions.html)

**Pinnacle** (the standard "sharp line" reference in the devig literature) closed its public API to new signups July 23, 2025 and is now bespoke-deal-only — not obtainable at this budget. Third-party Pinnacle resellers exist (PinnOdds ~$99/mo, SportsGameOdds Pro $299/mo) but both exceed the "tens of dollars" ceiling. **Practical consequence: the de-vig consensus in §4.1's fair-value model will be built from DK/FD/MGM/Caesars only, not Pinnacle — a real quality gap vs. the academic literature's assumed sharp-book reference, and worth stating explicitly as a limitation of the fair-value model rather than glossing over.** [VERIFY current PinnOdds/SportsGameOdds pricing before ruling this out permanently — resale pricing moves independently of Pinnacle's own policy.]

Directly scraping DraftKings/FanDuel as a free alternative is a clear ToS/legal risk (explicit anti-bot clauses, documented history of DraftKings cease-and-desist letters over scraping) — not a viable fallback if budget tightens; degrade to fewer books via The Odds API rather than scraping.

OddsJam and Odds-API.io were evaluated and rejected: OddsJam's API pricing is gated behind sales contact and reportedly runs $499-$5,000+/month (secondhand); Odds-API.io starts at £99/month with weaker book coverage than The Odds API. Neither improves on the recommendation above at this budget.

---

## 2. Strategy & Academic Literature

### 2.1 Avellaneda-Stoikov: why it doesn't transfer cleanly

AS (2008) assumes continuous Brownian mid-price diffusion (unbounded support), quadratic/CARA utility over continuous terminal wealth, unconstrained inventory, and Poisson order arrivals decaying exponentially with distance from mid. Three assumptions break for a Kalshi sports contract:

1. **Bounded [0,1] support vs. unbounded diffusion.** Price compressed near 0.97 cannot diffuse like an equity; true "volatility" in probability units must shrink near the boundary or the model prescribes absurd quote geometry. A 2025 arXiv paper (*"Toward Black-Scholes for Prediction Markets,"* arXiv:2510.15205) explicitly builds a bounded-martingale kernel with jumps to handle this, and shows standard GBM-style diffusion creates mathematical singularities near the boundary — direct confirmation this is a real, known modeling gap, not a hypothetical concern.
2. **Continuous diffusion vs. discrete event jumps.** A touchdown moves win probability 5–15 points instantaneously. AS has no native jump term; the dominant source of variance late in a sports market is jumps, not diffusion.
3. **Smoothly-hedgeable inventory vs. a binary terminal payoff with no tradeable underlying.** Options-market-making-near-expiry is the closer analogy (gamma risk spikes near expiry, dealers skew hard against inventory) — but even that analogy is imperfect because an options MM can delta-hedge against a continuous underlying; a Kalshi sports contract MM cannot (there's no continuously-tradeable "NFL win probability" instrument to hedge against — the position can only be closed by trading the same contract, at a resolution-dependent price).

**Practical takeaway:** AS-style formulas (reservation price shifting linearly with inventory, spread scaling with vol×time-remaining) are usable as a *skeleton* for inventory-skewing logic, not as a literal pricing model. The reservation-price-shift concept survives; the vol/diffusion assumptions underneath it do not. This plan uses an AS-*inspired* skew (Doc 4 fading parameters), explicitly not a full AS solve.

### 2.2 Inventory skew / adverse selection near event catalysts

Direct prediction-market literature is thin; the closest rigorous analogue is options-MM-near-earnings. Adverse-selection measures (PIN, spread decomposition) rise measurably around scheduled information events, and MMs respond by widening spreads and skewing pre-emptively rather than reactively (ScienceDirect, informed options trading around earnings). Guéant-Lehalle-Fernandez-Tapia (arXiv:1105.3115) formalizes reservation-price skew as proportional to `position × variance × time-remaining` — portable to sports if "variance" is replaced with a state-dependent, game-clock-conditioned jump-intensity estimate (higher near known high-leverage moments). **Practical takeaway for this plan: known catalyst windows (two-minute warning, end of quarter, etc.) should trigger pre-emptive size reduction and quote widening, not just reactive post-jump skewing** — but per the in-play kill decision below, this plan does not quote *through* live catalyst windows at all in Phase 0-3, so this is mainly relevant if in-play is ever revisited.

### 2.3 Sports betting market efficiency

**Favorite-longshot bias (FLB).** Well-replicated (Snowberg & Wolfers 2010, NBER w15923; Shin 1992/93 insider-trading model; a 2021 MDPI review of ~70 years of evidence across sports finds direction/magnitude is sport- and market-structure-dependent, not universal). Magnitude on liquid modern lines (NFL/NBA moneylines at major books) is small — a few percentage points, concentrated at extreme longshots (<10% implied probability) where liquidity is thinnest. **My read: on Kalshi/Polymarket specifically, this is plausibly already priced by market makers replicating sharp-book closing lines in flagship markets; more likely exploitable in thin, less-modeled markets than in NFL/NBA game-winner markets.** This is informed speculation, not a validated backtest.

**Closing line value (CLV).** Widely treated (mostly in practitioner literature, weaker academic support) as the best available skill proxy — beating the closing line more consistently than chance implies forecasting edge. One academic NFL-lines paper (arXiv:1211.4000) found no significant opening-vs-closing predictive difference, cutting against a strong version of the claim. Treat CLV as a useful *evaluation metric* for this plan's own strategy (Doc 2 success criteria), not as a proven standalone signal.

**De-vigging methods:**

| Method | Formula | Notes |
|---|---|---|
| Multiplicative | pᵢ = πᵢ / Σπⱼ | Naive; degrades on skewed lines |
| Additive | pᵢ = πᵢ − (Σπⱼ−1)/n | Naive; degrades on skewed lines |
| Power | pᵢ = πᵢ^(1/k), solve k s.t. Σpᵢ=1 | Accounts for FLB |
| Shin | pᵢ = (√(z²+4(1−z)πᵢ²) − z) / (2(1−z)), solve z s.t. Σpᵢ=1 | Insider-fraction model, academically preferred for skewed lines |

(πᵢ = 1/decimal odds.) Shin and Power are preferred over multiplicative/additive specifically because they correct for FLB rather than assuming a flat vig — relevant since this plan's fair-value engine will de-vig sportsbook consensus as a primary input.

### 2.4 Prediction market efficiency and anomalies

- **Longshot bias in prediction markets** is structurally distinct from sports-book FLB: Wolfers & Zitzewitz show it can arise purely from risk-aversion preferences (CRRA >1) without any informed insiders, unlike Shin's insider-trading explanation for sportsbooks. Two different mechanisms, same directional symptom.
- **Complementary-outcome / cross-market arbitrage**: a 2025 arXiv paper (arXiv:2508.03474) estimates **~$40M extracted by arbitrage bots from Polymarket, April 2024–April 2025**, concentrated in fast-resolving crypto markets (latency arb, not sports). A companion NBA-specific paper (arXiv:2605.00864) quantifies single-market (YES+NO ≠ 100%) and cross-market combinatorial arbitrage in Polymarket NBA markets specifically — the closest direct evidence this mechanism exists in sports contracts on these exact platforms.
- **Time-to-resolution effects**: >500,000 Intrade transactions analysis found markets well-calibrated near expiration but biased farther out, attributed to opportunity-cost-of-capital participation constraints (arXiv:2602.21091). A 2025 study across 2,500+ political markets found arbitrage opportunities peaked in the final two weeks pre-resolution and calibration differed sharply by platform: **Kalshi 78%, Polymarket 67%, PredictIt 93%** (via DL News summary of Clinton & Huang). This is real evidence of a persistent, platform-specific calibration gap — structurally driven by capital cost and platform liquidity, not pure speed, making it a better fit for a slow, capital-constrained operator than the crypto-latency-arb niche above.

### 2.5 Existing open-source prediction-market bots (architecture patterns, not code reuse)

| Repo | Pattern | License |
|---|---|---|
| nikhilnd/kalshi-market-making | WS book streaming + REST execution, centralized state object, Cauchy-distribution fair value | Unspecified |
| orangejuicetin/kalshi_market_maker | asyncio, one coroutine per market | Unspecified |
| ImMike/polymarket-arbitrage | Cross-platform + complementary-outcome arb detection, explicit risk module (position/loss limits, kill switch) | MIT |
| Polymarket/agents (official) | Modular: market-metadata client, vector-DB news context, signing/execution layer, LLM decision layer | MIT |
| warproxxx/poly-maker (1.4k★, most mature) | In-memory book per token, SQLite for positions/orders/PnL, raw events journaled to files for replay | MIT |

**Pattern observed across all repos**: (1) data-ingestion layer, (2) stateful current-market/position object, (3) strategy function producing target quotes, (4) order-manager reconciling desired-vs-live orders. None implement full AS stochastic control — all use fair-value + heuristic (often inventory-linear) spread. This validates the architecture direction in Document 3 rather than motivating a more exotic design. `poly-maker`'s "journal raw events to files + indexed store" pattern is the direct model for this plan's recorder (Document 5), adapted to S3 + Parquet.

---

## 3. In-Play Latency Economics — Why In-Play Is Killed

- Official real-time sports data (Sportradar, Genius Sports): even conservative estimates put a modest in-game package at **$4,000–6,000/month** (Sports Handle reporting, citing sportsbook-industry sources), with the NFL's exclusivity deal with Genius Sports reportedly requiring "at least a five-fold increase" over prior Sportradar pricing for the same content — a rare quantified admission of the multiples involved. This is 4-6x the *entire* starting bankroll, per month, before any trading — categorically disqualifying, not a marginal disadvantage.
- Latency gap between official feeds and free/broadcast data is real and precedented: courtsiding literature (tennis/exchange betting) documents exploitable windows as tight as 1-2 seconds; broadcast-only delay runs 7-40 seconds depending on medium. [VERIFY: magnitudes sourced from sports-betting media and forums, not formal engineering benchmarks — directionally credible, not rigorously measured.]
- **Concrete, non-anecdotal evidence the adverse-selection risk is real on Kalshi specifically**: Susquehanna International Group is Kalshi's first official designated market maker (reduced fees, higher position limits, dedicated prediction-markets desk since 2023); DL Trading (ex-Chicago HFT) is reported as one of the largest sports-focused market makers on Kalshi. Sophisticated, feed-armed capital has already claimed the visible sports-liquidity-providing role on this exact venue.
- "Slow corner" niche-sports hypothesis is plausible but unproven — the same thinness that repels fast capital may mean official data barely exists there either, folding any edge into "better modeling," not "faster reaction," which collapses the distinction back into the pre-game strategy.
- Pre-game pricing, by contrast, is repeatedly framed (both in an EMH-sports-forecasting arXiv preprint and general market commentary) as a *modeling-quality* problem — injuries, lineups, weather, public consensus — not a reaction-speed problem. Nothing in the official-feed cost structure is a barrier here.

**Conclusion carried into Doc 2/4: this plan does not quote or take positions during live game play in Phase 0-3. Any future in-play work is gated behind a separate, explicit re-authorization, not a default extension of the pre-game strategy.**

---

## 4. Ranked Strategy Shortlist

All four assume **Kalshi-only execution**; Polymarket and sportsbook prices are inputs, never counterparties.

### 4.1 [PRIMARY] Kalshi mispricing vs. external consensus fair value

**Edge thesis:** Kalshi sports prices occasionally diverge from a de-vigged blend of (a) sportsbook consensus (Shin/Power de-vig across 4-5 books) and (b) Polymarket's own price (a second, independently-arrived-at probability estimate, itself imperfect per its 67% calibration figure above, but cheap and orthogonal information). Divergence can come from Kalshi-specific liquidity thinness rather than informed order flow, since Kalshi sports markets are newer and thinner than mainstream sportsbook lines. This requires no proprietary sports model — it's an information-aggregation strategy, matching the operator's stated inexperience with sports modeling while leveraging strong microstructure/execution skills.

**Falsifiable test:** On captured data (Doc 5), compute a rolling de-vigged consensus fair value and Polymarket price for the same game/market at matched timestamps; measure the distribution of (Kalshi price − blended external fair value) and whether that gap predicts subsequent Kalshi price movement toward the external estimate, net of the round-trip fee threshold from §1.1. A positive, fee-covering, statistically-significant relationship across a large enough sample (Doc 2 defines the sample-size gate) is the pass condition.

**Kill-if:** the gap doesn't predict movement (Kalshi is already efficiently arbitraged to the external consensus by other participants — plausible, since Kalshi's designated MMs are sophisticated), or the gap exists but is smaller than round-trip fees at the price levels where it appears.

### 4.2 [SECONDARY] Complementary-outcome / related-contract arbitrage

**Edge thesis:** YES+NO (or a full mutually-exclusive outcome set) on Kalshi occasionally doesn't sum to 100¢, or a series-vs-game-market pair is inconsistent — a near-riskless capture when found, requiring no market view. Precedented (~$40M extracted on Polymarket in one 12-month window, some directly in NBA markets).

**Falsifiable test:** scan captured Kalshi order books for complementary-set sum deviations exceeding round-trip fees, log frequency/size/duration of such windows.

**Kill-if:** deviations are rare, sub-fee, or close within one message (meaning a bot would need sub-100ms reaction to capture them — a different, faster-capital game this plan explicitly opts out of per §3).

### 4.3 [TERTIARY] Structural liquidity provision in thin, non-marquee markets

**Edge thesis:** wide spreads in low-volume sports/prop markets reflect absence of participants, not fast-moving information — a slower, patient quoter can earn the spread with acceptable adverse selection, avoiding the marquee-market MM presence identified in §3.

**Falsifiable test:** for markets below a volume/open-interest threshold (defined in Doc 5's research access layer), measure realized spread capture vs. adverse-selection cost (price move against the fill in the following N minutes) from captured data, before any live capital is risked.

**Kill-if:** adverse selection cost exceeds realized spread even in thin markets (i.e., "thin" doesn't actually mean "uninformed," it just means the same informed flow with less competition among MMs). This condition is made concretely computable, not just aspirational, by Doc 11's pickoff-rate and realized-spread-capture metrics.

### 4.4 [DEMOTED — monitor, don't trade] Cross-venue calibration arbitrage

Originally a candidate to trade directly (buy cheap on one venue, sell on the other). **Demoted to signal-only under the Kalshi-only execution decision** (ADR-002) — Polymarket's US-access situation (§1.2) makes it unsuitable as an execution counterparty for now. The underlying calibration-gap evidence (Kalshi 78% vs Polymarket 67%) is still useful as a component of the §4.1 blended fair value, just not as a standalone tradeable arb.

---

## 5. Source List

Kalshi: docs.kalshi.com (welcome, fix, getting_started/*, api-reference/*), kalshi.com/regulatory/rulebook, kalshi-public-docs.s3.amazonaws.com (Developer Agreement, Data ToS), CFTC.gov filings (order022123kexdcm002, rules0627242994).

Polymarket: docs.polymarket.com (trading/overview, developers/CLOB/introduction, concepts/pusd, concepts/resolution, trading/fees, api-reference/geoblock), help.polymarket.com, github.com/Polymarket (py-clob-client, agents), CFTC Letter 25-48.

Literature: Avellaneda & Stoikov (2008); arXiv:2510.15205; arXiv:1105.3115; Snowberg & Wolfers NBER w15923; MDPI 2021 FLB review; arXiv:1211.4000; Wolfers & Zitzewitz (NBER); arXiv:2508.03474; arXiv:2605.00864; arXiv:2602.21091; Clinton & Huang 2025 (via DL News); arXiv:2604.17194.

In-play economics: Sports Handle ("Here's How Much 'Official' League Data Actually Costs"; "Sportradar Letter On NFL's Data"), lsports.eu, Sportico ("Prediction Market Oddsmaking Battle"), sig.com/predictions.

OSS repos: github.com/nikhilnd/kalshi-market-making, github.com/orangejuicetin/kalshi_market_maker, github.com/ImMike/polymarket-arbitrage, github.com/Polymarket/agents, github.com/warproxxx/poly-maker.

Infra: aws.amazon.com/s3/pricing, aws.amazon.com/s3/glacier/pricing, instances.vantage.sh, hetzner.com/cloud.

Full [VERIFY] list consolidated in Document 8.
