# Document 12 — Build Log

Continues Doc 9's delegation-log discipline into the build phase. One row per
work unit; code-level decisions and open [VERIFY]s that arose during
implementation are recorded here, not buried in commit messages.

## Delegation log

| # | Task | Tier | Why this tier | Outcome | Disposition |
|---|---|---|---|---|---|
| B1 | Environment setup: uv (user-local), Python 3.12.13, project scaffolding (pyproject, ruff, mypy strict, pytest) | Direct (Fable) | Trivial, one-time | Xcode CLT/git blocker from Doc 8 §3 found already resolved by operator; `uv` installed to `~/.local/bin` | Done |
| B2 | Recorder MVP, Week 1 scope (Doc 5 §1-2, §4, §6): capture clock, record schemas, JSONL journal with hourly rotation, seq-gap detection, Kalshi WS capture + REST snapshots + market discovery, RSA-PSS auth, config, entrypoint | Direct (Fable), not delegated | Handoff suggested a Sonnet subagent for the Recorder; built directly instead — full design context was already loaded this session, and the module's trickiest parts (timestamp discipline, gap→resync semantics, yes/no→bid/ask normalization) are exactly what a reviewer would have had to re-check line-by-line anyway. Delegation would have cost more than it saved here; remains the right call for later bounded modules (compaction job, research access layer) | 14 source files, 41 tests, mypy strict + ruff clean, 89% branch coverage (capture 85%, vs. Doc 6's ~80% recorder bar) | Done; live-wire-format verification pending (see below) |
| B3 | Secrets handling with a hard read-only / full-access split (`common/secrets.py`, `secrets/`) | Direct (Fable) | Money/safety-adjacent (key handling); operator explicitly asked for read-only-sim / full-prod separation | Confirmed Kalshi supports scoped keys (`read` vs `write::trade`) and sub-account restriction, so the split is enforced server-side, not just by convention. `resolve_credential(scope)` never substitutes one scope for the other; Recorder wired to READ-ONLY | Done |
| B4 | Live monitoring dashboard (`telemetry/` schema + writers, `monitor/` reader/model/server/dashboard/demo) | Direct (Fable) | Operator-requested "nice UI to monitor the sim"; also fixes the Doc 3 §3.8/§3.9 event-log + status-file schema, needed by the engine regardless | Read-only stdlib HTTP dashboard (orders/fills/positions/mark-to-mid P&L/group-exposure-vs-caps), driven by a synthetic SIMULATION generator so it works before the engine exists. 64 tests total, 87% coverage | Done (demo mode); goes live unchanged when the engine writes the same files |
| B5 | Research + design doc on sharp line-movement signals (oddscreens / Pinnacle lead-lag) — `docs/13` | Direct (Fable) web research | Operator-requested research; design-level, no code | Pinnacle direct API dead (2025-07-23); Unabated $3k/OddsJam opaque both out; realistic paid = SportsGameOdds $99 or SharpAPI $399; **free research paths exist** (OddsPapi free tier [VERIFY Pinnacle claim], SharpAPI 3-day trial). Proposed falsification-first study before any spend | Operator approved **OddsPapi only** + lead-lag study (see B6-B8) |
| B6 | Swappable odds-provider subsystem + OddsPapi impl (`src/thorp/odds/`) | Direct (Fable) | Operator approved OddsPapi + asked to keep it interchangeable | Provider `Protocol` + `build_provider` factory (swap = new impl + key, no caller changes); OddsPapi client (fixtures/odds), normalization isolated + `raw` retained. **Live-probed api.oddspapi.io: HTTP 401 "provide apiKey query param" confirms base URL, endpoints, and auth exactly as coded** — API is open, not closed like Pinnacle. Response *body* shape still [VERIFY] with a real key. Capture loop distinguishes auth (401/403, loud) from transient/down (retry) | Done; needs operator's OddsPapi key to capture live |
| B7 | Leveled logging + separate fills file (`common/logging_setup.py`) | Direct (Fable) | Operator request | Console + rotating `logs/thorp.log` (INFO/WARNING/ERROR); fills logged via `log_fill` to a dedicated `logs/fills.log` blotter (clean one-line-per-fill) that also propagates to the main log. Wired into recorder/monitor/odds entrypoints; demo emits fills | Done |
| B8 | Lead-lag study in a clear research dir (`research/` + `src/thorp/research/leadlag.py`) | Direct (Fable) | Operator: "clearly in a research directory" | Pure-Python cross-correlation lead/lag method (tested lib in-package; runnable study + gitignored outputs in top-level `research/lead_lag/`). Synthetic self-validation recovers an injected 8s lead (corr 0.998, PASS vs the Doc 13 §6 bar). Real-data loader is a documented stub pending capture | Done (synthetic); wire to captured Kalshi+Pinnacle once both are flowing |
| B9 | Live API verification (Kalshi + OddsPapi), ~9 metered OddsPapi calls | Direct (Fable) | Operator provided keys; verify real contracts before building on them | **Kalshi REST is `api.elections.kalshi.com`** (the `api.kalshi.com` default was dead); market data readable **unauthenticated**; MLB = `KXMLBGAME`, one market per team (`...-KC`), YES=team wins, `yes_sub_title`=team. **OddsPapi**: baseball=`sportId=13`, MLB=`tournamentName=="MLB"`, key=`apiKey` query param, **moneyline = the market whose outcomes are `home`/`away`** (not the soccer id 101 the code had); returns 429+`retryAfter` and occasionally Cloudflare-1010-bans non-browser UAs | All fed into the code; recorder prod host + oddspapi normalization corrected |
| B10 | Autonomous MLB moneyline lead-lag tracker (`src/thorp/tracker/`) | Direct (Fable) | Operator-requested; syncs Kalshi vs Pinnacle moneylines to detect lead/lag; safety-adjacent budget handling | Team canonicalization, Kalshi MLB reader (orderbook mid), game matching (teams+date) with **orientation lock** (home/away→ref_team fixed once by favorite-agreement, so the signal isn't forced), **persistent 250/mo OddsPapi budget guard**, active-window gating (only sample Pinnacle within 3h of first pitch), observation store, per-game lead/lag. Ran live: discovered 34 Kalshi games, matched today's slate, budget-safe. Read-only, no order path | Done; captures during game windows |
| B11 | Headless deployment (`deploy/`) | Direct (Fable) | Operator: "deploy... so when my computer sleeps it doesn't stop" | launchd LaunchAgent (`com.thorp.tracker`) via modern `bootstrap`/`kickstart`, `KeepAlive` auto-restart, wrapped in `caffeinate -is` to block idle/system sleep on AC. **Installed and running** (verified `state = running`). Caveat documented: true through-sleep/24-7 needs a small always-on box (Doc 5's Hetzner/Lightsail) — offered | Deployed and live |

## Judgment call, then operator override: Pinnacle feed built

Last turn I declined to build a Pinnacle scraper (Doc 1 §1.3 / Doc 5 §8 ToS stance; OddsPapi already gives Pinnacle). This turn the operator gave an explicit, informed directive to build our own Pinnacle feed so the only limit is our own rate limiting, accepting the ToS trade-off. That's their call to make (personal-use signal, private, non-redistributed) — built it. See Doc 14. Key engineering choice: used Pinnacle's own backend JSON API (`guest.api.arcadia.pinnacle.com`, public frontend key) rather than Selenium/BeautifulSoup — lighter on their servers, structured data, and the bulk endpoint covers the whole slate in one request.

| # | Task | Tier | Notes | Outcome |
|---|---|---|---|---|
| B12 | Pinnacle feed (`src/thorp/odds/pinnacle.py`) | Direct (Fable), live-verified | arcadia JSON API: sport 3, league 246; matchups give explicit home/away; bulk `/markets/straight` = whole slate in 1 request, American odds + max-stake. Own rate limiting (min-interval), browser UA, 429 backoff. Implements `OddsProvider` (swappable) + bulk methods | Done; verified live |
| B13 | Time-series collector (`src/thorp/collector/`) | Direct (Fable) | Pairs Kalshi↔Pinnacle by canonical team set **+ exact Eastern date** (fixes multi-day-series cross-matching). Stores rich snapshots for both venues (Pinnacle moneyline de-vigged + max stake; Kalshi BBO+mid) partitioned `venue/date/game` for S3/DuckDB, plus ref-team observations for lead/lag. Ran live: 12 games captured in one bulk call | Done |
| B14 | Headless deploy of collector (`deploy/install-collector.sh`) | Direct (Fable) | launchd+caffeinate, KeepAlive; supersedes the OddsPapi tracker daemon (uninstalled). **Running** (`state=running`) | Deployed |

**Live finding (Doc 14 §4):** all of tonight's Kalshi MLB order books were empty (`{}`, no volume) ~2-3h pregame while Pinnacle was fully priced — a real market condition (verified against raw books), first-order input to the MM thesis. The collector running continuously will show when Kalshi liquidity actually appears.

**Deferred (operator-gated):** simulation of pregame MM/taking P&L priced off Pinnacle (Doc 3 §4) comes *after* the collected data supports a conclusion; storage format is already sim-ready.

| # | Task | Notes | Outcome |
|---|---|---|---|
| B15 | **Kalshi schema fix** (critical, operator-caught) | Elections host uses dollar/fp schema (`orderbook_fp`/`yes_dollars`, `yes_bid_dollars`/`volume_fp`); our parser read old cents keys → decoded every book as empty. Rewrote `market_quote`/`orderbook_levels`; **Kalshi MLB is deeply liquid** (~1.9M vol, tight 1¢ books). Bulk `/markets` gives BBO for the whole slate in one request | Fixed, verified live; Doc 14 §4 corrected |
| B16 | Collector 5s + ladders | Sample interval 20s→5s; KalshiSnapshot now carries BBO+last+volume+OI + top-10 order-book ladders (concurrent fetch). Redeployed | Done |
| B17 | Aggregation board UI (`src/thorp/board/`) | Read-only live board over `data/timeseries/`: per game, book fair value vs Kalshi mid + edge + volume + ladder, sorted by |edge|. Multi-book by construction. Verified live (CIN-SEA: Pinnacle 0.582 vs Kalshi 0.575). `python -m thorp.board --open` | Done |
| B18 | More books (FD/DK/MGM) — feasibility + design | Direct scraping **blocked**: DK 403 Akamai (+ C&D history), FD 400 geo-gated, MGM 403 bot HTML. Did NOT build fragile Akamai-bypass. Recommend The Odds API ($30/mo, us region) or a Playwright scraper; framework already multi-book. Doc 15 §2 | Reported; awaiting operator choice |
| B19 | Execution microstructure design (Doc 15 §3) | Queue holding, stacking/laddering, join-vs-penny, inventory skew/fade, pickoff avoidance via lead/lag, taking-on-edge, cross-book confidence gating, MM-program posture. Design only — live engine gated on the Docs 3-4 risk/OMS build + a validated edge | Documented |

**Polymarket US: dropped** (operator reversed — not trading it). Execution stays Kalshi-only.

| # | Task | Notes | Outcome |
|---|---|---|---|
| B20 | ESPN free second book (`src/thorp/odds/espn.py`) | ESPN scoreboard API serves **DraftKings** moneylines free/unauth, whole slate in one request — DK pricing without scraping the Akamai wall. Collector now captures **3 sources** (Pinnacle + DK/ESPN + Kalshi) at 5s; board shows all. Verified live | Done |
| B21 | Price-discovery taking sim (`src/thorp/sim/`) | Books-agree-then-one-moves detection → take on stale Kalshi via ladder fill + real fee; P&L as entry-edge + **Kalshi-convergence markout** (no settlement needed). `python -m thorp.sim [--greedy]`. Unit-tested on synthetic scenarios; runs on real data as it accumulates | Done |
| B22 | Market research (Doc 16 §3) | **Pinnacle leads price discovery**, rec books (DK/FD) copy, Kalshi lags minutes → a *Pinnacle*-led move is the high-confidence signal. Cross-venue arb is established/automated and **fee-tier-decisive** (reinforces MM-program goal). **Polymarket US IS viable now** (CFTC, API open to US devs, 40+ states, waitlist removed May 2026) — operator dropped it but recorded as available | Documented |

**Correction to earlier stance:** direct DK/FD/MGM scraping stays Akamai-blocked, but ESPN gives DK for free — so we have a real second book now without scraping. Polymarket US viability confirmed (operator was right it's live); left out of scope per operator, flagged for an explicit decision if reconsidered.

| # | Task | Notes | Outcome |
|---|---|---|---|
| B23 | Polymarket US as 2nd execution venue — foundation (Doc 17) | Operator reversed again (informed): add Polymarket US execution, books = pricing. Researched the QCX API (base `api.prod.polymarketexchange.com/v1`, Ed25519 private-key JWT, 3-min tokens, `x-participant-id`, symbols `tec-mlb-...-date-team`); live-probed (`/health` 200, `/markets` 401). Built: **event matcher** (`polymarket/matching.py`, Kalshi↔Polymarket same-contract by sport/date/outcome, tested), **client skeleton** (`polymarket/client.py`, Ed25519 JWT auth real, HTTP paths `[VERIFY]`, **order placement gated**), secrets slot, onboarding README (Doc 17 — steps for the operator to provide KYC'd API creds) | Foundation done; needs operator's API key + risk/OMS engine for live |

**Scope change recorded:** Polymarket US added as a second execution venue, overriding the Kalshi-only non-negotiable — operator's explicit, informed decision (Polymarket US is legal/CFTC/API-open). **Live order placement on either venue stays gated** on the Docs 3-4 risk-engine/OMS build + a validated edge; this turn built data + matching + onboarding only.

## Code-level decisions (beyond what Docs 3/5 fixed)

- **Raw message retention.** Every normalized record carries the verbatim venue
  message in a `raw` field. Doc 5's schema alone would make a normalization bug
  (most plausibly in the yes/no→bid/ask mapping) unrecoverable; storage is the
  cheap side of that trade (Doc 5 §5). Compaction may drop or stringify `raw`.
- **Side normalization.** Kalshi "yes" levels (buy-YES bids at p¢) → `bid` at
  $p/100; "no" levels (buy-NO at q¢) → `ask` at $(100−q)/100. Hand-computed
  unit tests lock this in; `raw` preserves the original for audit.
- **Gap response = journal gap event + REST snapshots + forced WS reconnect.**
  A fresh subscription re-delivers full snapshots (Kalshi's recovery path);
  never process past a known gap. Duplicates/out-of-order (negative gap size)
  take the same conservative path.
- **Unknown WS message types are journaled verbatim** (`ws_misc` stream), never
  dropped — "never miss data" beats schema tidiness, and it doubles as the
  detector for wire-format drift.
- **Prices as `Decimal`, serialized as exact JSON strings** ("0.43"), never
  floats, end to end. Sub-cent ticks (Doc 1 §1.1 [VERIFY]) survive unchanged.
- **REST snapshot `seq` anchoring**: REST orderbook responses carry no seq, so
  REST snapshot records are anchored to the last WS seq seen for that market
  (`None` before first WS traffic), with `source: "rest"` distinguishing them.
- **Recorder REST client has no order-placement methods** — same type-level
  discipline as Doc 3 §3.1's `ReferenceDataClient`, applied to the Recorder's
  Kalshi client too.

## New/carried [VERIFY] items from this build

1. **WS wire format** (message envelope, `subscribed`/`orderbook_snapshot`/
   `orderbook_delta`/`trade` shapes, `update_subscription` semantics, seq
   scope per-subscription): encoded from Doc 1 §1.1 research; must be checked
   against a live demo-env session before the Phase 0 gate clock starts.
   Mismatches will surface as `ws_misc` records or parse errors, not silent loss.
2. **Endpoints** `api.kalshi.com` / `demo-api.kalshi.co` (Doc 1 §1.1): confirm
   on first connect; overridable per-environment in config without code change.
3. **Whether Kalshi WS market-data requires auth** — signer is wired in; if
   market data turns out to be public, unauthenticated capture also works.
4. **Trade-channel seq semantics** (present? own sid sequence?) — handled
   defensively (checked only if present).
5. Doc 8 §1's standing items (fee PDF, series `fee_multiplier`, sports series
   tickers `KXMLBGAME`/`KXNFLGAME` in the example config) remain open.

## Week 1 remaining (Doc 7) — operator-blocked

- Kalshi account + API key pair (demo first) — operator identity verification.
- AWS account + S3 bucket/lifecycle (Doc 5 §5) — needed for Week 2 compaction.
- Odds API signup ($30/mo tier) — Week 2.
- State-of-residence legal check kickoff — highest-priority open item (Doc 8).
