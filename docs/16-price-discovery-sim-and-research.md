# Document 16 — Price-Discovery Simulation, ESPN Source, Market Research

Covers: a second free book source (ESPN/DraftKings), the price-discovery taking
**simulation**, and **market-microstructure research** (who moves first, what
others do, Polymarket US viability). Execution stays Kalshi-only.

## 1. ESPN — a free, unauthenticated second book (`src/thorp/odds/espn.py`)

Direct DK/FD/MGM scraping is Akamai-walled (Doc 15 §2), but **ESPN's public
scoreboard API serves DraftKings moneylines for free**, no key, no geoblock:

    GET site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=YYYYMMDD

One request returns the whole slate's DK moneylines (home/away American). The
collector now captures **three sources** — Pinnacle (sharp, direct), DraftKings
(via ESPN), Kalshi — every 5s, and the board shows them side by side. Verified
live: MIL-NYM had ESPN 0.5716 and Pinnacle 0.5697 (agree within 0.2¢) vs Kalshi
0.585 — books agree, Kalshi is the outlier.

## 2. Price-discovery taking simulation (`src/thorp/sim/`)

Implements the operator's strategy: monitor multiple books; when they **agree**
and one **moves sharply**, treat it as price discovery and **take** on Kalshi if
Kalshi is stale — capturing the edge before Kalshi converges, and not getting
picked off the other way.

- **Detection:** at each Kalshi tick, compute the cross-book consensus P(team)
  and dispersion. A *discovery* fires when books were in agreement (dispersion <
  `agree_threshold`) and the consensus moved > `move_threshold` over
  `move_window_s`. Takes are gated on discovery (or `--greedy` for any edge).
- **Take + fill:** when the blended fair beats the Kalshi ask by more than
  fee + margin, lift the Kalshi ladder (`take_yes_fill` walks `no_levels`;
  YES ask = 1 − buy-NO price), size-capped, with the real Kalshi taker fee.
- **P&L, two honest measures** (no settlement outcome needed):
  - *entry edge* = (blended fair − fill) − fee: the theoretical edge at fill.
  - *markout* = (Kalshi mid at t+`horizon` − fill) − fee: did Kalshi actually
    **converge** toward the book fair after we took? This is the did-it-work
    number and the primary validation.

Run: `python -m thorp.sim` (discovery-gated) or `--greedy`. It reports per-game
evals / discoveries / takes / entry-edge / markout / hit-rate over the collected
time series. It becomes meaningful as the collector accumulates real 5s series
(tomorrow's slate); the logic is unit-tested against synthetic
books-agree-then-move scenarios.

## 3. Research — who moves first, what others do, Polymarket US

### 3.1 Price discovery: Pinnacle leads, rec books copy, Kalshi lags
Pinnacle is the market **originator** — sharpest mainstream book (2–3% vig,
doesn't limit winners), so sharp money corrects its lines first; retail books
(DraftKings/FanDuel) **copy** Pinnacle and let soft prices linger because they
restrict winners; prediction markets like Kalshi **lag by minutes**. Concrete
implication for us: **a Pinnacle-led move is the high-confidence signal**; our
ESPN/DraftKings feed is a *lagging confirmation*, not a leader. The sim should
(next iteration) weight books by sharpness — a Pinnacle move away from the DK
consensus is more predictive than a DK-only move (which may be public money).
This refines §2's "one moves" into "the *sharp* one moves."

### 3.2 Similar strategies (what others do)
Cross-venue arbitrage — convert sportsbook moneyline → implied prob → find the
Kalshi contract → trade when Kalshi is meaningfully cheaper — is an established,
**automated** strategy (there are off-the-shelf Kalshi/Polymarket arb bots).
Manual is impossible; edges close in seconds, so it's an infra/latency game.
**Fee tier is decisive:** at Kalshi's ~1% tier most cross-venue edges clear,
at ~7% only >5% edges survive. Spreads are compressing as capital enters.
Takeaways for the plan: (a) our approach is validated and known — the moat is
execution quality + fair-value quality, not novelty; (b) **getting to a low
Kalshi fee tier (volume / MM program) is not optional — it's what makes the edge
survive fees**, reinforcing the MM-program goal (Doc 15 §3.9); (c) speed matters,
but the *pregame* window (our scope) is minutes-scale, not the sub-second
in-play race — a good fit for our infra.

### 3.3 Polymarket US — it *is* viable now (operator was right)
Polymarket US (QCX LLC, **CFTC-regulated**) launched 2025-12-03; the **waitlist
was removed ~May 2026**; the **API is open to US developers** (23 REST + 2 WS
endpoints); it's legal in **40+ states** as of July 2026 (Minnesota ban Aug 1
2026 under CFTC challenge; ~11 states with C&D). So it is a viable, legal,
API-accessible venue today — the earlier "unresolved US access" (Doc 1 §1.2) is
resolved via this separate regulated product. The operator dropped Polymarket
from scope this session; **this is recorded as available if reconsidered** — it
would add a third *executable* venue (market-make both, arb crossings) but also
re-opens the multi-venue execution/risk surface the Kalshi-only stance avoids.
No action taken; flagged for an explicit decision, not assumed.

## 4. Status
Collector deployed capturing 3 sources at 5s (Pinnacle + DraftKings/ESPN +
Kalshi); board shows them; sim implemented + tested. Next: let tomorrow's slate
accumulate, run `python -m thorp.sim` on real data, and read the markout numbers
before building any live execution (still gated on the Docs 3–4 risk/OMS build).
