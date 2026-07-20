# Document 5 — Data Capture & Research Corpus Design

This is a parallel project that starts first (Week 1, Doc 7) — every day not recorded is history that can never be backfilled. The Recorder (Doc 3 §2) has one job and no others: never miss data. It has zero code-level dependency on the Trading Engine and keeps running regardless of trading system state.

## 1. What Gets Captured

Three independent capture streams, one process each (or one process with three independent async tasks — see §6 for the resource-tradeoff note), none blocking the others:

1. **Kalshi** — full order-book deltas + trade prints for the sports series in scope, via WebSocket, plus periodic REST snapshots for resync safety. This is the execution-relevant data (Doc 3's Market Data client) and also research data.
2. **Polymarket** — public, read-only market-data endpoints (no auth/trading account needed — Doc 1 §1.2 confirms this is a signal-only integration). Same delta+snapshot pattern where the public API supports it.
3. **Sportsbook consensus (Odds API)** — polled, not streamed (the vendor's own update cadence is 60-90s pre-game, Doc 1 §1.3), h2h+spread+total markets across DK/FD/MGM/Caesars, `us` region, starting on the $30/mo tier.

Plus **auxiliary context**, captured alongside (Doc 1's requirement, needed for labeling and for the fair-value model's inputs, not just nice-to-have):
- Game schedules (kickoff times, team identifiers) — needed to key Kalshi/Polymarket/Odds-API observations to the same event and to know when a market should transition out of "pre-game" scope.
- Event outcomes (final score / winner) — needed to label historical signals for the Phase 1 backtest (Doc 2 §2). Source: Kalshi's own settlement data for the markets we're tracking is sufficient for labeling — no separate outcomes feed is required, since we only need outcomes for games we're already tracking on Kalshi. This avoids the ToS risk of scraping a separate sports-results site.

## 2. Schema

**Book delta record:**
```
{
  venue: "kalshi" | "polymarket",
  market_key: str,              # Kalshi ticker or Polymarket condition/token id
  seq: int,                     # venue sequence number, used for gap detection
  side: "bid" | "ask",
  price: decimal,
  size: int,
  exchange_ts: datetime | null, # venue-reported timestamp, if provided
  receive_ts: datetime,         # when our socket received the message (monotonic-corrected, see §4)
  process_ts: datetime,         # when our recorder finished handling it
}
```

**Trade print record:** same key fields (`venue`, `market_key`, `exchange_ts`, `receive_ts`, `process_ts`) plus `price`, `size`, `taker_side`.

**Snapshot record:** full book state (all price levels) at a point in time, same timestamp triple, plus the `seq` it was taken at — this is what a resync-from-gap or a from-arbitrary-point backtest replay anchors to.

**Snapshot cadence:** every 60s per actively-tracked market, plus unconditionally on (a) recorder startup and (b) any detected sequence gap. 60s bounds how much delta-replay is needed to reconstruct state at any point, without meaningfully inflating storage (Doc 1 §5's infra research: even at high-volume assumptions this stays in the low single-dollar range).

**Sportsbook odds record:** `{book: str, market_key, market_type: "h2h"|"spread"|"total", side, price(american or decimal, store as fetched), line (for spread/total), fetched_ts}`.

## 3. Wire Format → Parquet Compaction

- **On the wire / freshly captured:** append-only newline-delimited JSON per stream, written locally first (durability against a network blip to S3), rotated hourly.
- **Compaction:** an hourly batch job converts the raw JSON files to columnar Parquet with zstd compression (Doc 1 §infra research assumed 4-10x compression on this kind of data) and uploads to S3; local raw JSON is deleted only after the Parquet upload is confirmed and a row-count checksum matches.
- **Partition scheme:** `s3://<bucket>/<venue>/<data_type>/date=YYYY-MM-DD/series=<series_ticker>/` — e.g. `s3://thorp-data/kalshi/book_deltas/date=2026-09-14/series=KXNFLGAME/part-00.parquet`. Justification: `date` first because almost every research query (backtest a date range, run a daily quality report) filters on date first; `series` second because most analysis is sport-scoped (e.g., "all NFL" vs. "all NBA"), not cross-sport; `venue`/`data_type` as top-level prefixes because the Kalshi (execution-relevant) and Polymarket/Odds-API (signal-only) data have different retention/access patterns downstream and should never require a query to scan both to get one.

## 4. Timestamping Discipline

Every record carries three timestamps, never collapsed into one:

- `exchange_ts` — venue-reported, when available (Kalshi/Polymarket messages may include one; Odds API does not — the vendor's own update, not the book's true instant, so treat it as approximate).
- `receive_ts` — when the recorder's socket received the bytes, using a **monotonic clock for interval measurement** (`time.monotonic()`) mapped to wall-clock at connection start, then re-synced periodically against NTP-disciplined system time — this avoids the classic bug where a system clock adjustment (NTP correction, DST, VM pause) makes an interval calculation go negative or wildly wrong mid-session.
- `process_ts` — when the recorder finished handling the message (parsing, schema validation) — the gap between `receive_ts` and `process_ts` is itself a useful data-quality signal (recorder falling behind).

**Why this matters concretely:** the backtest fill model (Doc 3 §4) depends entirely on knowing, for a given hypothetical order, what the *true* book state was at that instant — if timestamps are sloppy, the backtest silently answers a different, easier question than "would this order have filled." This is stated as a first-class design constraint, not a nice-to-have, because a backtest built on bad timestamps produces a confident, wrong answer that Doc 2's Phase 1 gate would then wrongly pass or fail.

## 5. S3 Layout, Storage Class, and Cost

From the infra research (Doc 1 source list): even at high-volume assumptions (50 markets, high-frequency), 2-year retention costs land around $3-4/month in S3 storage+requests, well inside the "tens of dollars" budget, with egress absorbed by the 100GB/month free tier in all but the high scenario.

**Lifecycle policy:**
- 0-30 days: S3 Standard (active research access, no retrieval friction)
- 30-180 days: S3 Standard-IA (research access is infrequent by this point, still millisecond retrieval)
- 180+ days: S3 Glacier Instant Retrieval (cheap, still no multi-hour retrieval delay — Deep Archive is rejected because its retrieval delay is incompatible with "load all NBA moneyline books for March" being a casual one-liner, Deep Archive would turn that into a multi-hour operation)
- Lifecycle transitions configured via S3 bucket rules, not a manual job.

**Egress control:** researcher pulls (loading data for local analysis) should default to querying via **DuckDB directly against S3** (reads only the needed row groups/columns from Parquet, not whole-file downloads) rather than syncing whole partitions locally, keeping egress far below the 100GB/month free tier. Local caching of frequently-reused date ranges (e.g., the current Phase 1 backtest's working set) in a `~/.thorp/cache/` directory is a §7 access-layer feature, not a manual habit to remember.

**Compute for the recorder:** Hetzner CX22 (~$5/mo) or AWS Lightsail nano (~$3.50-5/mo) — recommendation from Doc 1's infra research, since latency is irrelevant for a data-only recorder and both beat EC2 t4g.micro+EBS on price. Default to Lightsail if keeping billing consolidated in AWS is preferred; Hetzner if minimizing cost is preferred. Not a consequential decision either way at this budget — flagged as a judgment call, either is fine.

## 6. Gap Detection and Daily Data-Quality Report

- Every stream's `seq` field is checked for monotonicity on ingestion; a gap triggers (a) an immediate REST snapshot fetch to resync and (b) a logged gap event `{venue, market_key, expected_seq, received_seq, gap_size, detected_at}`.
- A daily batch job (runs against the prior day's compacted Parquet) produces a data-quality report: missing intervals (periods with zero messages for a market that should have been active), total gap count and cumulative gap duration per market, message-volume anomalies (a day with 10x or 0.1x the trailing-7-day average message count for a given market flags for manual review), and snapshot-reconstruction validation (does replaying deltas from the nearest prior snapshot reproduce the next snapshot exactly — a direct correctness check, not just a completeness one).
- This report is what Doc 2's Phase 0→1 gate (`<1% sequence-gap rate over 14 consecutive days`) is measured against — the gate is not a vague intention, it's a specific number this report computes daily.

## 7. Research Access Layer

A thin query helper, not a full framework — the goal is "load all NBA moneyline books for March" being a one-liner, not building a general-purpose data platform:

```python
def load_books(venue: str, series: str, date_range: tuple[date, date],
                market_type: str | None = None) -> pl.DataFrame:
    # Builds the S3 partition-pruned path list from the venue/date/series scheme (§3),
    # queries via DuckDB (S3 Parquet, no full download), returns a Polars DataFrame.
    ...

def load_matched_signals(series: str, date_range: tuple[date, date]) -> pl.DataFrame:
    # Joins Kalshi books + Odds API consensus + Polymarket price on (game_id, timestamp-nearest),
    # the exact join the Phase 1 backtest and the FairValueEngine both need —
    # written once here, used by both the research notebook and (conceptually) the live engine's
    # equivalent real-time join, so backtest and live logic don't silently diverge.
    ...
```

## 8. ToS and Legal Constraints on Captured Data

- **Kalshi data**: per the Developer/Data Terms of Service (Doc 1 §1.1), caching beyond the operator's own trading use and any redistribution to third parties is prohibited without written consent; using Kalshi data for ML/AI training is reportedly flagged as requiring written consent in the Data ToS. **[VERIFY the exact Data ToS text before any model-training use of captured Kalshi data — the fair-value/strategy backtesting described in this plan is "facilitating your own trading," which appears to be the permitted use case, but the exact boundary of what counts as "training an AI model" vs. "computing a statistical backtest" is not defined in the source and should be read literally before scaling up.]** This corpus is never redistributed or resold under any circumstance in this plan.
- **Odds API data**: ToS permits use as an internal signal for the operator's own trading decisions; explicitly forbids reselling/redistributing as a standalone product (Doc 1 §1.3) — this plan's use (private signal input, never redistributed) fits inside the permitted use, but was not affirmatively blessed by the vendor for "informing trades on a third-party exchange" specifically. [VERIFY: worth a direct email to their support before relying on this at scale, per the sportsbook-odds research's own flag.]
- **Polymarket public market data**: read-only, no account/auth required per Doc 1 §1.2 — lowest-risk source in the corpus.
- No sportsbook website scraping anywhere in this design — explicitly rejected as a ToS/legal risk (Doc 1 §1.3), even as a cost-saving fallback.
