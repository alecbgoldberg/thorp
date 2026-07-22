# Document 15 — Execution Microstructure, Aggregation Board, Multi-Book

Covers three operator asks: (1) the aggregation **board UI**, (2) adding **more
book sources** (FanDuel/DraftKings/BetMGM) and what's actually feasible, and (3)
**execution/microstructure strategies** (queue holding, stacking, …) for the
pregame market-making + taking plan on Kalshi. Execution stays **Kalshi-only**
(Polymarket dropped by the operator). The live MM/taking engine is **not built
yet** — it needs the risk-engine/OMS machinery (Docs 3–4) and is gated on the
lead/lag + edge conclusion from the collected data (Doc 14). This doc is the
design that work will implement.

## 1. Aggregation board (`src/thorp/board/`, built)

A read-only local UI over the collector's time series:

```sh
uv run python -m thorp.board --open
```

One card per game, sorted by largest absolute edge: each team's **book fair
value(s)** (de-vigged) and their **consensus**, the **Kalshi bid/ask/mid**, the
**edge** (fair value − Kalshi mid: positive = Kalshi cheap → buy, negative =
rich → sell), Kalshi **volume**, and the Kalshi **YES/NO ladder**. It reads
`data/timeseries/` live (polls every 2s) and treats any non-`kalshi` venue as a
book, so new books appear with no code change. Verified live: e.g. CIN-SEA showed
Pinnacle SEA 0.582 vs Kalshi 0.575 → +0.7¢ edge, with volume and depth.

This is the surface where the simulation output and the order **ladders** will
render once those exist; today it shows real pricing + edge + Kalshi depth.

## 2. More books — feasibility (important)

Direct scraping of the US recreational books is **not** like Pinnacle:

- **DraftKings** → HTTP 403 (Akamai "Access Denied"); DK has a documented history
  of C&D letters over scraping (Doc 1 §1.3).
- **FanDuel** → 400/geo-gated (per-state `sbapi`, device tokens).
- **BetMGM** → 403 bot-protection HTML.

These sit behind enterprise bot walls (Akamai sensor data, per-state geofencing,
TLS fingerprinting) that a plain HTTP client can't pass. Options, honestly:

1. **Aggregator (recommended): The Odds API** — `us` region covers
   DK/FD/MGM/Caesars, ToS-clean, $30/mo with usable limits. Cleanest path to
   dense, legal multi-book data. (OddsPapi, already integrated, also has these
   books but the 250/mo tier is too thin for dense capture.)
2. **Headless-browser stealth scraper** (Playwright + anti-detection) per book —
   technically possible, but fragile (breaks on every site change), heavy, and
   the most ToS/legally exposed given DK's posture.

**Recommendation:** keep **Pinnacle direct** (sharp, free, dense — the key
reference), and add DK/FD/MGM via **The Odds API** when you want them, at a
moderate cadence. The board and collector are already multi-book: a new source
just writes `data/timeseries/<book>/…` snapshots in the same shape. I did **not**
build fragile Akamai-bypass scrapers — say the word and I'll wire The Odds API
(needs a key) or attempt a Playwright scraper for a specific book.

**Why multiple books matter (the goal):** Pinnacle is the sharp anchor; DK/FD/MGM
are where recreational flow moves. Divergence between them, and which book moves
*first*, is the price-discovery signal — it raises confidence in fair value and
flags when one venue (often Kalshi, sometimes a slow rec book) is stale and
takeable.

## 3. Execution / microstructure strategies (design)

Target: **pregame market-making on Kalshi to earn spread + rebate/edge fills**,
**taking when Kalshi diverges from blended fair value beyond fees**, sized by the
Doc 2 §5 fractional-Kelly + fading rules and gated by the Doc 4 risk engine.
Fair value = de-vigged blend of books (Pinnacle-weighted); Kalshi is deeply
liquid (Doc 14 §4), so queue dynamics matter.

### 3.1 Fair-value-anchored quoting
Quote a bid/ask straddling blended fair value `p̂`: bid at `p̂ − h`, ask at
`p̂ + h`, where the half-spread `h` ≥ round-trip fee + a margin, widened by
fair-value **uncertainty** (book disagreement, staleness) — quote tight only when
books agree, wide when they don't. Re-center as `p̂` moves.

### 3.2 Queue holding (queue-position value)
Kalshi is price-time priority per level. Posting **early** at a level earns queue
priority; the queue-ahead is a real asset (you fill first when the level trades).
**Hold** a resting order through small, noise-level `p̂` moves rather than
cancel/replace — cancelling forfeits queue position and pays the
adverse-selection cost of re-joining at the back. Only reprice when `p̂` moves
past a hysteresis band (e.g. > the tick + a buffer) or a **sharp** move fires the
pickoff guard (§3.6). This directly trades off queue value vs. staleness risk.

### 3.3 Stacking / laddering
Post **multiple resting orders at several price levels** (a ladder) rather than a
single top-of-book quote: e.g. bids at `p̂ − h`, `p̂ − h − tick`, `p̂ − h − 2·tick`
with sizes shaped by edge (more size where cheaper vs fair value). Benefits:
captures more fill volume, builds queue priority across levels ahead of moves,
and earns better average edge on a sweep. Total ladder exposure is bounded by the
per-correlated-group cap (Doc 2 §5); inventory skew (§3.5) shifts the ladder.

### 3.4 Joining vs pennying
At a level, **join** the existing queue (same price, take time priority behind)
when the level is already at/through fair value — cheap queue position. **Penny**
(improve by one tick) only when the edge justifies giving up queue priority to
guarantee top-of-book — i.e. when `p̂` is far enough from the touch that a one-tick
improvement is still profitable and fill probability materially rises. Default to
joining (Kalshi's tick is 1¢, meaningful relative to edges).

### 3.5 Inventory skew (fading — already specified)
As inventory in a correlated group grows, skew quotes to reduce it: widen/pull
the adding side, keep/improve the reducing side; and raise the required edge to
*add* (`required_edge = base·(1 + inventory_ratio·k)`, Doc 2 §5). Hard cap
enforced by the risk engine regardless of strategy (Doc 4). This is the
anti-accumulation backstop for both making and taking.

### 3.6 Adverse selection / pickoff avoidance
The core MM risk: a sharp move (Pinnacle steams) makes our resting quote stale
and we get picked off. Mitigation: the **lead/lag signal** (Doc 13) — when
Pinnacle/blended fair value jumps, **pull or reprice** the now-stale side before
Kalshi catches up, faster than the hysteresis used for noise. Pre-emptively widen
around known catalysts (lineup posts, weather) pregame. Track realized
**markouts/pickoff rate** (Doc 11) to tune how aggressively to hold vs pull.

### 3.7 Taking on edge
When Kalshi's price diverges from blended fair value by **more than round-trip
fees + margin** (the Doc 2 §1 falsifiable edge), cross to take — especially right
after a sharp move Kalshi hasn't absorbed (the lead/lag window). Size by
fractional Kelly on the edge; respect the fade/hard cap. Taking and making share
the same fair value and risk gate.

### 3.8 Cross-book confidence gating
Only quote tight / size up when books **agree** on `p̂`. Wide disagreement =
uncertain fair value or a book in transition → widen, shrink, or stand aside.
This is the concrete use of the multi-book data (§2): confidence and
price-discovery timing, not just a level.

### 3.9 Market-maker-program posture
Kalshi's MM program rewards continuous two-sided quoting + volume. The above
(tight two-sided quotes when confident, laddered, held for queue priority) is
also what accrues the uptime/volume to **qualify** — a byproduct of good MM, not
a separate mode. Track quoting uptime and volume share as program metrics.

## 4. Validation path (unchanged, gated)
None of §3 goes live before: (a) the collected time series shows a fee-clearing
edge / exploitable lead-lag (Doc 14, Doc 13 bar), and (b) it's **simulated**
(Doc 3 §4 BACKTEST/SHADOW) against the captured Kalshi ladders + blended fair
value to measure realized P&L, fill rate, and pickoff — first Pinnacle-only, then
blended. The stored data (Kalshi BBO+ladder+volume, Pinnacle moneyline, both at
5s) is already in the shape that simulation needs.
