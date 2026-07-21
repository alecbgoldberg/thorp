# research/

Offline research studies and their outputs. **Not part of the live trading
engine** — nothing here places orders or runs in production. Each study is a
runnable script that reads captured data (or, until capture exists, synthetic
data) and writes a report under its own `output/` directory (gitignored).

The reusable, unit-tested analysis code these scripts import lives in the
installed package under `src/thorp/research/` — so the math is covered by
`make check`, while the runnable studies and their artifacts live here where
they're clearly research, not production.

## Studies

### `lead_lag/` — do sharp books lead Kalshi? (Doc 13 §6)

Tests whether a sharp sportsbook (Pinnacle) line *moves before* Kalshi does —
the falsification-first question that gates any spend on a paid sharp feed.

```sh
uv run python research/lead_lag/study.py            # synthetic self-validation
uv run python research/lead_lag/study.py --help     # options
```

Right now it runs on **synthetic** data (a sharp series with a known injected
lead), which validates that the method recovers the lag it was given. Once the
Recorder is capturing Kalshi and the odds capture is pulling Pinnacle
(`python -m thorp.odds`), point the study at that captured data to run the real
test against the pre-registered bar in Doc 13 §6 (sharp leads by ≥5s, correlation
significant, implied edge > round-trip Kalshi fees).
