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
| B5 | Research + design doc on sharp line-movement signals (oddscreens / Pinnacle lead-lag) — `docs/13` | Direct (Fable) web research | Operator-requested research; design-level, no code | Pinnacle direct API dead (2025-07-23); Unabated $3k/OddsJam opaque both out; realistic paid = SportsGameOdds $99 or SharpAPI $399; **free research paths exist** (OddsPapi free tier [VERIFY Pinnacle claim], SharpAPI 3-day trial). Proposed falsification-first study before any spend | **Awaiting operator go-ahead** on the two free signups (Doc 13 §7) |

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
