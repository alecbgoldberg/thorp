# Document 14 — Pinnacle Feed + Time-Series Collector

Operator-directed (2026-07-21): build our own Pinnacle odds feed so the only
limit is our own rate limiting (not OddsPapi's 250/mo), and start collecting
dense time series for baseball on **both Kalshi and Pinnacle** into a local
directory (destined for S3). This is the data foundation for the eventual plan:
**pregame market-making on Kalshi to collect edge fills, taking when there's
edge, priced off Pinnacle (and blended books later)**, expanding toward player
props and market-maker-program qualification. Execution stays Kalshi-only
(Doc 3); nothing here places orders.

## 1. Access approach — Pinnacle's own JSON API, not HTML scraping

Pinnacle's site is a React SPA, so BeautifulSoup/Selenium (the common advice)
means rendering JS to scrape rendered HTML — heavy, brittle, and hard on their
servers. Instead we use the **same backend JSON API the site itself calls**,
`guest.api.arcadia.pinnacle.com/0.1`, with the public frontend `X-API-Key`
embedded in their JS bundle (not an account credential). Verified live
2026-07-21:

- `GET /sports` → baseball = sport **3**.
- `GET /leagues/246/matchups` → MLB games. Real games have `parentId` null and
  two `participants` with `alignment` home/away + team `name` — so **home/away
  is explicit** (cleaner than OddsPapi, which forced an orientation guess).
- `GET /leagues/246/markets/straight` → **one request returns every game's
  markets** (moneyline/spread/total/team_total). Moneyline prices are **American
  odds** tagged by `designation` home/away, with a `limits` **max stake** (a
  useful liquidity/confidence signal, e.g. $10–15k pregame).

Because the bulk endpoint covers the whole slate in one call, the entire MLB
schedule costs ~1 Pinnacle request per poll — lighter than any HTML scraper.

**Robustness / fallback.** If the frontend key rotates, re-extract it from the
site JS. If the JSON API is ever locked down, a Selenium-rendered fallback could
be added behind the same `PinnacleScraper` interface — but it isn't needed today
and would be strictly worse, so it's deliberately not built.

## 2. Respectful rate limiting + ToS

Our own rate limiting is the throttle: a configurable **minimum interval between
requests** (default 1s), a browser User-Agent (Cloudflare 1010-bans bare
clients), and 429/5xx backoff. This is polite and also keeps our IP unblocked.

**ToS note (operator has decided).** Automated access likely runs against
Pinnacle's Terms of Service; the realistic downside is an IP block, not more.
The operator has directed building this with that understood. The data is used
privately as a trading signal and **never redistributed**. This reverses the
conservative Doc 1 §1.3 / Doc 5 §8 stance *for Pinnacle specifically*, as an
explicit, informed operator decision — not a general license to scrape.

## 3. What we collect (and where)

`src/thorp/collector/` runs autonomously, pairing each Kalshi MLB game to its
Pinnacle matchup by **canonical team set + exact Eastern date** (multi-day series
repeat teams, so date disambiguation matters; Pinnacle's UTC start is converted
to ET). For every game in its active window (pregame through the game) it writes,
every ~20s:

- **Pinnacle** (`data/timeseries/pinnacle/date=…/game=…/snapshots.jsonl`):
  full moneyline both sides — American, decimal, vig-inclusive prob, **de-vigged
  prob** — plus max stake and cutoff. Raw retained.
- **Kalshi** (`data/timeseries/kalshi/…`): per-team-market best bid/offer + mid
  from the order book.
- Plus ref-team paired **observations** feeding the Doc 13 lead/lag analysis.

Partitioned `venue/date/game` exactly like Doc 5, so `aws s3 sync
data/timeseries s3://…` and a DuckDB `read_json_auto` both work unchanged when
the operator moves storage to S3.

Deployed headless via `deploy/install-collector.sh` (launchd + caffeinate,
KeepAlive) — supersedes the budget-limited OddsPapi tracker daemon.

## 4. Correction — Kalshi MLB is highly liquid (earlier "empty" was our bug)

An earlier draft of this doc claimed Kalshi MLB books were empty pregame. **That
was wrong — a schema bug on our side, caught by the operator.** The elections
host uses a dollar/fixed-point schema (`orderbook_fp` with
`yes_dollars`/`no_dollars`, market fields `yes_bid_dollars` / `volume_fp`), while
our parser read the older cents-based `orderbook.yes`/`.no` keys that don't exist
there — so every book decoded as empty. Fixed 2026-07-22.

Reality: Kalshi MLB moneylines are **deeply liquid** — e.g. a single team market
showed **~1.9M contracts of volume, ~1.3M open interest**, a 1¢-wide top of book
($0.12/$0.13), and ladders with tens of thousands of contracts several cents
deep. The bulk `/markets` response already carries BBO + volume + OI for every
market, so the whole slate's pricing comes from one request; per-market
`orderbook_fp` calls add the depth ladder. This liquidity is exactly what makes
the pregame market-making thesis worth pursuing.

**Capture windows.** Pinnacle's matchups endpoint drops games once they start, so
the collector pairs the two venues during the **pregame** window (the MM focus);
in-play pairing would need Pinnacle's live endpoint and is out of scope for now.

## 5. Forward plan (gated, not built yet)

Per the operator: once we have enough paired data to draw a **conclusion**
(does Pinnacle lead Kalshi? is there fee-clearing edge? when does Kalshi
liquidity appear?), implement it **in simulation** (Doc 3 §4 BACKTEST/SHADOW):
replay the captured Kalshi book + Pinnacle-derived fair value and measure what
market-making/taking **would have** made or lost — first with Pinnacle alone,
later with a blended book. That simulation is the next deliverable **after** the
data supports a conclusion; the stored format above is already sim-ready
(timestamped books + fair-value inputs). Player props and MM-program
qualification are follow-ons beyond that.
