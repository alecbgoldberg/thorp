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
- `tests/` — pytest suite; `make check` is the local pre-deploy gate (Doc 6 §1)

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
