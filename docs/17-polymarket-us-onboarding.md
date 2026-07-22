# Document 17 — Polymarket US: Onboarding + Cross-Venue Plan

Operator decision (2026-07-22): add **Polymarket US** as a second **execution**
venue alongside Kalshi, keeping the sportsbooks (Pinnacle sharp, DraftKings via
ESPN) as **pricing** venues. Goal: market-make both Kalshi and Polymarket and
**arb when they cross**, entering the *same* contract on both via an event
matcher. This reverses the earlier Kalshi-only stance — a deliberate, informed
change now that Polymarket US is a legal, CFTC-regulated, API-accessible venue
(Doc 16 §3.3).

## What I need from you (onboarding steps)

Polymarket US is the **QCX**-operated, CFTC-regulated product (not the
international CLOB). API access is gated behind KYC + an application:

1. **Account + KYC.** Finish identity verification on Polymarket US (you're off
   the waitlist). Fund it only when we're ready to trade live.
2. **Apply for API access.** Trading API access needs an application +
   integration testing (compliance). Start it via the developer portal or email
   **onboarding@qcex.com**. Ask for **market-data + trading** scope and note you
   want **preprod/dev** access too (so we can integration-test without real money).
3. **Generate an Ed25519 API key** in the developer portal (Polymarket US uses
   **Ed25519**, not Kalshi's RSA). You'll get:
   - a **participant id**,
   - an **API key id** (the key's identifier / `kid`),
   - an **Ed25519 private key** (download the PEM).
4. **Give them to me** by editing `secrets/polymarket.env` (gitignored):
   - `THORP_POLYMARKET_PARTICIPANT_ID`, `THORP_POLYMARKET_API_KEY_ID`,
   - save the private key as `secrets/polymarket-ed25519.pem`,
   - set `THORP_POLYMARKET_ENV` to `preprod` first (then `prod` when live).
5. **Point me at the docs** if you can: the exact **token-exchange endpoint**,
   the **instruments** and **order-book** paths, and the **order payload** — a
   few things in `src/thorp/polymarket/client.py` are marked `[VERIFY]` because
   the public docs excerpt didn't include them and `/v1/markets` needs auth.

With preprod credentials I can finish and integration-test the client
(market-data reads first), verify the event matcher against **real MLB symbols**,
and capture Polymarket prices into the collector alongside Kalshi + the books.

## Two Polymarket APIs — public (sim) vs Polymarket US (execution)

There are two distinct APIs, and we use them for two different things:

- **Public international Gamma API** (`gamma-api.polymarket.com`, **no auth**):
  read-only market data — best bid/ask, condition/token ids — verified live.
  This is the **sim/reference** data source (`polymarket/public.py`). It's a
  *different order book* from Polymarket US, so treat it as a reference price,
  not the exact execution price.
- **Polymarket US (QCX) API** (`api.prod.polymarketexchange.com/v1`, **Ed25519
  auth + KYC**): the CFTC-regulated venue we'd actually **execute** on. This is
  the one that needs onboarding (below) and stays gated on the risk engine.

So the public API covers "give me Polymarket prices for the sim" with no
credentials; the onboarding steps below are only for **live execution**.

## What's built now (no key needed)

- **API client skeleton** (`src/thorp/polymarket/client.py`): base URL verified
  live (`/health` 200, `/markets` 401), Ed25519 private-key-JWT auth flow
  (real signing; token endpoint/claims `[VERIFY]`), market-data read methods.
  **Order placement is gated** — it raises, because live cross-venue execution
  must route through the risk-engine/OMS (Docs 3-4), which isn't built yet.
- **Event matcher** (`src/thorp/polymarket/matching.py`): reduces a Kalshi
  market ticker and a Polymarket symbol to a canonical `EventOutcome`
  (sport, date, outcome team) and confirms they're the **same contract** before
  we'd ever cross them. Tested. `[VERIFY]` the Polymarket MLB symbol format
  against a real instrument (the parser is tolerant of the event segment).
- **Secrets slot** (`secrets/polymarket.env`).

## Cross-venue plan (gated on the risk/OMS engine)

Once credentials + the risk engine exist:

1. **Match** every tradeable outcome across venues (event matcher) so a cross is
   provably the same contract — never assume by name.
2. **Price** off the sharp/blended book fair value (Pinnacle-led, Doc 16 §3.1).
3. **Make** two-sided quotes on both Kalshi and Polymarket around fair value
   (Doc 15 §3), and **arb** when Kalshi and Polymarket cross each other
   (YES_kalshi + NO_polymarket < $1 net of both venues' fees, or vice versa) —
   execute both legs together, sized by the risk engine.
4. **Risk** stays central: the same `RiskEngine`/OMS gate (Docs 3-4) fronts
   *both* venues; per-venue and per-correlated-group caps; the in-flight
   reservation ledger already handles concurrent legs (Doc 3 §3.5).

Fee sensitivity is decisive for cross-venue edges (Doc 16 §3.2), so getting to
low fee tiers on both venues (volume / MM programs) is part of the plan, not an
afterthought.

## Safety note

Adding a second execution venue widens the surface the Kalshi-only stance
avoided (Doc 3 §3.1). Live order placement on **either** venue stays gated on the
Docs 3-4 risk-engine/OMS build + a validated edge — this document sets up the
data + matching foundation, not live trading.
