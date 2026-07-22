# thorp — project rules

## RULE #1 (HIGHEST PRIORITY): SIM / PROD SEPARATION

**Simulation must never be able to place a real order. This is the number-one
rule and overrides convenience, speed, and every other consideration.**

Concretely, and non-negotiably:

1. **The SIMULATION path uses `ShadowVenue` only** — a pure in-memory fill model
   with zero network I/O. No simulation code may import, construct, or call any
   live-execution venue or any order-placement API.
2. **Read-only clients on the sim path.** `KalshiRestClient` has no
   order-placement method (market data only). Polymarket data on the sim path
   uses the read-only public client (`polymarket/public.py`), never the
   execution client.
3. **Live execution is gated and explicit.** Any live `ExecutionVenue`
   (Kalshi/Polymarket US) and `place_order` stays gated behind the RiskEngine +
   OMS + Watchdog (Docs 3–4) and an explicit operator go-ahead. Today,
   `PolymarketUsClient.place_order` raises; there is no `KalshiLiveVenue`.
4. **Credentials enforce it too.** The read-only Kalshi key (`read` scope) cannot
   place orders server-side; the full-access key is never loaded by a sim/data
   path (`common/secrets.CredentialScope`).
5. **Run mode is explicit in telemetry.** The engine stamps `RunMode` on the
   status file; a sim run is `SIMULATION` and can never silently be `CANARY`/
   `PRODUCTION`.

**Before adding or changing anything that touches order flow, verify at the code
level that no sim path can reach a live order** (grep for live venues /
`place_order` / order POSTs), and keep that separation obvious in the types, not
just in comments. When in doubt, gate it.

## Environment

- Use `uv`: `uv run python -m thorp.<module>` (uv auto-uses `.venv`; no manual
  activation). `uv` is at `~/.local/bin/uv` on this machine.
- Local pre-deploy gate: `make check` (ruff + mypy strict + pytest). Keep it green.
- Design docs live in `docs/`; append build decisions to `docs/12-build-log.md`.
