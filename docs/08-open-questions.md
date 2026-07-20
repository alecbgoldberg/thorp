# Document 8 — Open Questions, Assumptions, and Access Needed

## 1. Consolidated [VERIFY] List

Grouped by topic, each with what to check and how.

### Kalshi mechanics (Doc 1 §1.1)
- **Fee schedule exact constant/rounding** — the primary PDF (`kalshi.com/docs/kalshi-fee-schedule.pdf`) returned HTTP 429 on every scripted fetch attempt, including a direct manual retry. *Verify: open it in a regular browser (not a script) before Doc 2's cost model is treated as final — the 0.07 constant and worked fee table are load-bearing for the breakeven-edge math.*
- **Sports-series `fee_multiplier`** — unconfirmed whether `KXNFLGAME`-style series use the default 0.07 quadratic formula or a different multiplier. *Verify: `GET /series/KXNFLGAME` via the API, check the `fee_multiplier`/`fee_type` fields on a live response.*
- **Sub-cent tick structure near 1¢/99¢** and **whether Predictions-series orders accept fractional (0.01) contract counts**. *Verify: `GET /markets/{ticker}` on a live sports market, check `price_level_structure`; test a fractional-size order against the demo environment.*
- **Settlement source and `settlement_timer_seconds`** for a live sports series. *Verify: `GET /events/{event_ticker}` on a live NFL/NBA event.*
- **Position limit regime for sports** — standard $25K Position Limit vs. the newer Position Accountability Level regime. *Verify: current `kalshi.com/regulatory/rulebook` plus the series' `contract_terms_url`. Not urgent at $1,000 capital (not a binding constraint either way), but worth confirming before Phase 4 scaling.*
- **FIX cancel-on-disconnect** — the docs page 404'd. *Verify: browse from `docs.kalshi.com/fix` to find the current session-management page. Currently assumed unavailable outside FIX, making the Watchdog (Doc 4 §8) the sole safety net — if this turns out to be available via REST/WS after all, it becomes a valuable second layer, not a replacement for the Watchdog.*
- **Full Kalshi Data Terms of Service text**, specifically the ML/AI-training restriction and exactly where "backtesting my own trading" ends and a restricted use begins. *Verify: read `kalshi-public-docs.s3.amazonaws.com/kalshi-data-terms-of-service.pdf` directly before scaling any model-training use of captured data beyond simple statistical backtesting.*
- **Settlement/redemption fee-free assumption** — assumed no fee is charged at contract settlement, only on trades. *Verify: confirm in the fee schedule PDF alongside the constant check above.*

### Polymarket / reference data (Doc 1 §1.2)
- **Geoblock language discrepancy** — `docs.polymarket.com/api-reference/geoblock` (confirmed directly this session) says US is "close-only"; a separate Polymarket-owned help-center page reportedly says full block with no exceptions. *Verify both pages directly before assuming public, read-only market-data access is unaffected by either policy — the plan's Polymarket integration is read-only and doesn't require an account, but this should be confirmed, not assumed, before building the ingestion pipeline.*
- **Public market-data endpoint accessibility** — whether Polymarket's public price/orderbook read endpoints require any authentication or are subject to the same geoblock language as trading. *Verify directly against the API before Week 2 (Doc 7) when Polymarket capture is added to the Recorder.*

### Legal/regulatory/tax (Doc 1 §1.1, §1.3 combined)
- **State-of-residence legality of Kalshi sports contracts** — this is the single most important open item and the only one that could invalidate the whole plan. As of the July 2026 research pass, Kalshi's right to offer sports contracts is contested with an emerging circuit split (Third Circuit favorable, S.D.N.Y. unfavorable, both under appeal), and several states (NV, NJ, MD, CT, NY, MA) have taken action. *This needs the operator's state of residence to check current status — not resolvable generically. Flagged as a hard prerequisite in Doc 7 (Week 1 start, Week 8 hard gate before any live order).*
- **§1256 vs. ordinary tax treatment** — genuinely unresolved, no IRS guidance found. *For a CPA, not resolvable from public sources.*
- **Whether Kalshi's Data ToS blocks caching sportsbook/Polymarket-derived signals** alongside Kalshi data in the same corpus — likely fine since the restriction is on *Kalshi's* data specifically, but worth a literal read alongside the ML-training question above.

### Sportsbook odds vendor (Doc 1 §1.3)
- **The Odds API's "no resale as standalone product" clause**, whether it's understood by the vendor to cover a private, non-redistributed trading signal. *Not explicitly addressed in their ToS. Worth a direct email to their support before relying on it at Phase 4 scale — low risk at Phase 0-3 given the private/non-redistributed use, but cheap to confirm early.*
- **Current PinnOdds/SportsGameOdds pricing**, if a Pinnacle reference line is ever revisited — moves independently of Pinnacle's own policy.

## 2. What I Need From You

None of these block starting Doc 7's Week 1 activities except where noted, but they need answers before the corresponding roadmap step:

1. **State of residence** — needed to run the legal check above. This is the highest-priority item; happy to do the research once you provide it, or you can do it directly since it's specific to your personal situation.
2. **Kalshi account** — sign-up requires your own identity verification; I can't do this for you. Once you have an account, generate an API key pair from the Kalshi dashboard (Doc 1 §1.1's RSA-PSS flow) — the private key should go into a local secrets file you control, never shared with me or committed to the repo (Doc 7-ops practice).
3. **AWS account** — either an existing one or a new sign-up. If you want me to help provision the S3 bucket/lifecycle rules (Doc 5 §5) programmatically, I'll need either console access or CLI credentials scoped to just S3 for this project (not root/admin) — your call on how you want to hand that off.
4. **Odds API account** ($30/mo tier recommended to start, Doc 1 §1.3) — needs a payment method on your end.
5. **GitHub** — see §3 below, this is currently blocked on your machine's Xcode Command Line Tools being broken.
6. **Confirmation of the $700 Kalshi trading balance funding timeline** — Doc 7 has this landing around Week 7-8; let me know if that timeline needs to shift.
7. **Any pushback on the Kalshi-only / Polymarket-as-signal-only framing** — this plan was built on that basis per your last message; flagging once more here since it's a foundational assumption every other document depends on.

## 3. Git/GitHub Setup — Blocked, Needs Your Action

`git` is non-functional on this machine: `xcode-select -p` reports `/Library/Developer/CommandLineTools` but the actual tools are broken/incomplete, and there's no Homebrew or `gh` CLI installed as a fallback. This requires an interactive step I can't perform:

- Run `xcode-select --install` (pops a GUI installer, takes a few minutes), **or**
- Install Homebrew (`https://brew.sh`, also requires an interactive sudo step) then `brew install git gh`.

Once either is done, tell me and I'll: `git init` this directory, create the initial commit of the 11 planning docs, and either (a) run `gh repo create` if the `gh` CLI is available and authenticated, or (b) you create an empty repo on github.com and give me the remote URL to wire up with `git remote add`. Given this repo will eventually hold trading strategy code and (indirectly, via config) reference your account setup, **recommend a private repo**, not public.

## 4. Assumptions Made, and What Changes If Wrong

| Assumption | If wrong, what changes |
|---|---|
| Kalshi's 0.07 fee formula and worked table are approximately correct | Doc 2's breakeven-edge math and the Phase 1 gate's "2x fee hurdle" threshold need recomputation — directionally the strategy shortlist doesn't change, but the required edge magnitude might |
| Settlement/redemption itself is fee-free | If a settlement fee exists, "hold to resolution" strategies (4.1 in particular) become relatively less attractive vs. exiting early — recheck once confirmed |
| Kalshi sports contracts are legal in your state | This is the one assumption that, if wrong, halts the entire plan rather than adjusting a parameter — see Doc 2's hard shutdown criteria, already written to trigger on this |
| Polymarket's public market-data endpoints are accessible read-only without geoblock restriction | If wrong, Strategy 4.1's fair-value blend loses the Polymarket input and falls back to sportsbook-consensus-only, which Doc 1 already flags as a real quality gap (no Pinnacle reference) — the strategy doesn't die, but its edge thesis weakens and the Phase 1 gate becomes a harder bar to clear |
| The Odds API's ToS permits this private-signal use case | Low risk given the use is genuinely private and non-redistributed, but if the vendor disagrees on inquiry, fall back to a lower-tier/fewer-books plan or find an alternative — doesn't change the architecture, just the specific vendor |
| 15 hrs/week is a stable budget for 8 weeks | Doc 7's week-by-week plan compresses or stretches proportionally; the critical-path dependency order (recorder → clean capture → backtest → risk/OMS → shadow → canary) doesn't change regardless of pace |
