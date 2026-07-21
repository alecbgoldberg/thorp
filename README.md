# thorp

Solo-operator algorithmic trading system for Kalshi sports contracts. The full
design — strategy, risk controls, phase gates, architecture — lives in `docs/`
(start with `docs/00-executive-summary.md`). Build history and code-level
decisions: `docs/12-build-log.md`.

**Non-negotiables** (see `HANDOFF-TO-FABLE.md`): Kalshi-only execution;
no in-play trading; pre-registered phase gates (Doc 2 §2) decide progression,
not "the code works"; the adversarial-review risk/OMS fixes are load-bearing.

## Layout

- `src/thorp/common/` — shared primitives: capture clock (Doc 5 §4), record
  schemas (Doc 5 §2)
- `src/thorp/recorder/` — the Recorder process (Doc 5): Kalshi WS/REST capture
  to local append-only JSONL. Runs independently of everything else, by design.
- `src/thorp/telemetry/` — the engine's event-log + status-file schema and
  writers (Doc 3 §3.8–3.9), the regression/replay backbone
- `src/thorp/monitor/` — read-only live dashboard (orders, fills, mark-to-mid
  P&L, group exposure). Separate process; observes files, never engine memory.
- `src/thorp/odds/` — swappable odds-provider capture (Doc 13); OddsPapi today,
  interchangeable via a provider `Protocol` + factory.
- `src/thorp/research/` — tested offline analysis (lead/lag); runnable studies
  live in the top-level `research/` dir.
- `src/thorp/odds/pinnacle.py` — our own Pinnacle feed via its backend JSON API
  (no vendor API-key limit; own rate limiting). Doc 14.
- `src/thorp/collector/` — autonomous Kalshi + Pinnacle time-series collector
  (the primary data collector); `deploy/install-collector.sh` runs it headless.
- `src/thorp/tracker/` — earlier OddsPapi lead/lag pilot (budget-limited).
- `tests/` — pytest suite; `make check` is the local pre-deploy gate (Doc 6 §1)

## Credentials

Two Kalshi keys, never interchangeable (see `secrets/README.md`): a **read-only**
key for the Recorder and every SIMULATION/BACKTEST path, and a **full-access**
key used only for live trading. Paste yours into `secrets/kalshi.env`
(gitignored) — the read-only key is all you need to start.

## Monitoring dashboard

```sh
uv run python -m thorp.monitor --demo --open   # synthetic sim, opens a browser
uv run python -m thorp.monitor --session-dir data/live   # a real engine session
```

The `--demo` session is a stand-in until the sim engine exists (Doc 7 Week 6);
it writes the real telemetry schema, so the same dashboard lights up unchanged
once the engine runs. Logs go to `logs/thorp.log` (leveled) and fills to their
own `logs/fills.log` blotter.

## Odds capture (signal source, read-only)

Sharp/consensus odds for the fair-value model and the lead/lag study (Doc 13).
The provider is swappable; OddsPapi is wired up today. Put your key in
`secrets/odds.env`, then:

```sh
cp config/odds.example.toml config/odds.toml   # then edit sports/bookmakers
uv run python -m thorp.odds --config config/odds.toml
```

## Research studies

```sh
uv run python research/lead_lag/study.py   # does a sharp book lead Kalshi? (Doc 13 §6)
```

Runs on synthetic data until real capture exists; see `research/README.md`.

## MLB moneyline tracker (Kalshi vs Pinnacle lead/lag)

Autonomously syncs each MLB game's win probability on Kalshi with Pinnacle (via
OddsPapi), storing paired observations the lead/lag study consumes. It samples
Kalshi densely (free) and Pinnacle sparingly — only within a few hours of first
pitch, under a hard 250-call/month budget guard.

```sh
uv run python -m thorp.tracker --once      # one discover/sample/analyze round
deploy/install-tracker.sh install          # run headless (launchd + caffeinate)
deploy/install-tracker.sh status | logs | uninstall
```

See `deploy/README.md` for the headless/sleep details.

## Time-series collector (Kalshi + Pinnacle, primary)

Collects dense time series for MLB on **both venues** — Kalshi order-book BBO and
Pinnacle moneyline (de-vigged, via Pinnacle's own JSON API, no vendor limit) —
into `data/timeseries/<venue>/date=…/game=…/` (S3/DuckDB-ready). This is the data
foundation for the pregame market-making study (Doc 14).

```sh
uv run python -m thorp.collector --once        # one discover/sample/analyze round
deploy/install-collector.sh install            # run headless (launchd + caffeinate)
deploy/install-collector.sh status | logs | uninstall
```

## Setup

Requires [uv](https://docs.astral.sh/uv/) (installs its own Python 3.12):

```sh
uv sync
make check          # ruff + mypy strict + pytest
```

## Running the Recorder

```sh
cp config/recorder.example.toml config/recorder.toml   # then edit
export THORP_KALSHI_API_KEY_ID=...                     # from the Kalshi dashboard
export THORP_KALSHI_PRIVATE_KEY_PATH=~/path/to/key.pem # never committed
uv run python -m thorp.recorder --config config/recorder.toml
```

Captured data lands under `data/raw/<venue>/<data_type>/date=YYYY-MM-DD/HH.jsonl`
(gitignored). Parquet compaction + S3 upload is the Week 2 deliverable (Doc 7).
