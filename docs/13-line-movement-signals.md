# Document 13 — Sharp Line-Movement Signals (Research + Design, awaiting go-ahead)

**Status: proposal.** This document researches whether an oddscreen-style feed of
*sharp* sportsbook line movement (Pinnacle in particular) can act as a *leading*
indicator for Kalshi price moves, and designs how it would integrate. **No code
is written and no external API is integrated yet** — per the operator's
instruction, integration of any (even free) API waits for explicit go-ahead
(§7). This extends, and does not replace, the Doc 1 §4.1 primary strategy.

## 1. The idea, and how it differs from what's already planned

Doc 1 §4.1 already uses de-vigged sportsbook **consensus** and Polymarket price
as a fair-value **level** — "where should Kalshi be right now." The operator's
proposal adds two things that the current plan does not have:

1. **A sharp reference, not just a consensus.** Pinnacle is the canonical
   sharp book (low margin, high limits, moves first); the academic de-vig
   literature treats it as the reference line (Doc 1 §2.3). The current plan
   explicitly lacks it (Doc 1 §1.3: "a real quality gap vs. the literature's
   assumed sharp-book reference"). A Pinnacle input directly closes that gap.
2. **Movement / velocity as a signal, not just the level.** The hypothesis is
   temporal: a sharp line *moving* (e.g. Pinnacle steaming from -110 to -130)
   **leads** Kalshi's adjustment, opening a short window to take (cross the
   Kalshi book ahead of its repricing) or to make (skew/pull quotes before
   getting picked off). This is a *lead/lag* claim, distinct from the
   *level-divergence* claim 4.1 already tests.

Both are Kalshi-only execution. This is a **read-only signal source** — it maps
onto the existing `ReferenceDataClient` (Doc 3 §3.1), which by type *cannot place
an order*. No new execution surface, no change to the Kalshi-only invariant.

## 2. Why this is worth testing (and the honest caveats)

- **Mechanism is plausible.** Kalshi sports markets are newer/thinner than
  Pinnacle's; if Kalshi's own MMs (Susquehanna, DL Trading — Doc 1 §3) key off
  sharp books, Kalshi will *track* Pinnacle with a lag, and the lag is the edge.
- **But the fast version is already someone else's game.** The same Doc 1 §3
  logic that killed in-play applies here in miniature: if the lead/lag window is
  sub-second, it's a latency race against HFT-pedigree MMs and we lose. This is
  only viable if the window is **seconds-to-minutes**, which is plausible for
  *pre-game* line moves (our scope) but must be measured, not assumed.
- **No direct academic confirmation found** that sharp-book moves lead Kalshi
  specifically (§8 sources). This is therefore a **falsifiable research
  question first**, funded like everything else in this plan by a pre-registered
  test, not a paid feed bought on faith.

## 3. Data-source landscape (July 2026 research)

Pinnacle **shut its public API to new signups on 2025-07-23** (consistent with
Doc 1 §1.3); direct access is bespoke-deal-only now. So Pinnacle data means a
third-party aggregator. What's actually available at/near this budget:

| Source | Free tier | Pinnacle? | Latency | Cost for Pinnacle | Notes |
|---|---|---|---|---|---|
| **Unabated** | none | yes | push/WS | **$3,000/mo** | 3× the entire bankroll. Out. |
| **OddsJam** | consumer only | unclear | n/a | "contact sales" ($99–499+/mo consumer) | Opaque API pricing; no self-serve dev tier. Out. |
| **SharpAPI** | DK+FD only, 17,280 req/day | **only on paid** | 60s window | **$399/mo (Sharp tier)**; **3-day Sharp free trial, no CC** | Generous free reqs but free tier has no sharp books. Trial gives a real Pinnacle burst. |
| **SportsGameOdds** | 9 books, 10-min delay | yes (paid) | 3-min min delay | **$99/mo** | Cheapest steady Pinnacle, but ≥3-min delay likely too slow for a *movement* signal. |
| **OddsPapi** | 250 req/mo, no CC | **claims yes + historical on free** | REST (WS on paid) | free tier / "custom" paid | Free tier reportedly includes Pinnacle **and** historical — but this is the vendor's own marketing; **[VERIFY] directly.** 250 req/mo is study-only, not live. |
| **The Odds API** | 500 credits/mo | **no** | 60–90s | already in plan ($30/mo) | Current planned consensus source; DK/FD/MGM/Caesars, no Pinnacle. |

**Takeaways:**
- Nothing gives cheap, *low-latency*, *steady-state* Pinnacle. The realistic
  steady-state options are SportsGameOdds ($99, but ≥3-min delayed) or SharpAPI
  Sharp ($399, 60s). Both are real money and both should be **gated on a
  positive research result**, not bought first.
- For the **research spike**, two genuinely-free paths exist: OddsPapi's free
  tier (small Pinnacle sample, if the claim verifies) and a SharpAPI 3-day Sharp
  trial (a bounded Pinnacle capture window, no credit card). Either is enough to
  answer "does Pinnacle movement lead Kalshi?" against Recorder-captured Kalshi
  data, for $0.
- **The Odds API remains the workhorse consensus source** regardless; this
  proposal is additive (a sharp reference + a movement signal), not a
  replacement.

## 4. ToS / legal posture

Same posture as the existing Odds API integration (Doc 5 §8, Doc 8 §1): use as a
**private, non-redistributed** trading signal, never resold or republished.
Aggregator ToS generally forbid *redistribution as a standalone product*, which
this is not. Two caveats to confirm before any paid commitment:
- **[VERIFY]** each aggregator's ToS permits private signal use for trading on a
  third-party venue (Kalshi), same open question flagged for The Odds API.
- **[VERIFY]** whether the aggregator's own Pinnacle-sourcing has redistribution
  limits that touch us as a downstream consumer. Low risk for private use, but a
  one-line support email before paying is cheap insurance.
No sportsbook scraping anywhere (Doc 1 §1.3 rejected it; unchanged here).

## 5. Design (if validated)

Minimal, and deliberately inside the existing seams:

- **New `ReferenceDataClient` source** `"sharp"` (alongside `"polymarket"` /
  `"oddsapi"`), returning the same `PriceObservation` type (Doc 3 §3.1). Still
  no `place_order` method anywhere on the type — read-only by construction.
- **Recorder captures it** as a fourth stream (Doc 5 §1), same
  delta/snapshot/timestamp discipline, partitioned `venue=sharp`. Poll cadence
  matched to the vendor's real update rate; three-timestamp discipline (Doc 5
  §4) so lead/lag can actually be measured — a movement signal is worthless if
  our own timestamps are sloppy.
- **Two derived features** feed the `FairValueEngine` (Doc 3 §3.3):
  1. *Sharp level* → add Pinnacle to the de-vig blend (closes the Doc 1 §1.3
     gap), with weight a Phase-1-tunable parameter.
  2. *Sharp velocity* → `d(sharp_devigged_prob)/dt` over a short window, as a
     directional signal that raises `required_edge` on the wrong side and can
     trigger a pre-emptive quote pull (the "make" use) or justify a take.
- **Enforcement unchanged.** The velocity signal only ever *proposes* via a
  Strategy; the Risk Engine still gates every order (Doc 3 §3.5). A bad signal
  can't breach caps or bypass the fade.

## 6. Validation plan (falsification first, matching Doc 2)

Pre-registered, before paying for anything:

1. **Capture spike (free):** for a set of ~20–30 pre-game windows, capture
   Pinnacle (via OddsPapi free tier and/or a SharpAPI 3-day trial) *alongside*
   the Kalshi book the Recorder already captures.
2. **Lead/lag study:** measure the cross-correlation between sharp-line moves and
   subsequent Kalshi mid moves. **Pass bar (pre-registered):** sharp moves lead
   Kalshi by a window ≥ **5 seconds** (so it's not an HFT race we lose) with a
   predictive relationship significant at p<0.05, and the implied edge exceeds
   round-trip Kalshi fees at the relevant price levels (same fee hurdle as Doc 2
   §2 Phase 1).
3. **Decision:** only if it passes, buy a steady-state feed (SportsGameOdds $99
   if the lead window tolerates ≥3-min delay — likely only for slow pre-game
   drift; SharpAPI Sharp $399 if seconds-scale) and promote it to a live
   `ReferenceDataClient` source. If it fails, we've spent $0 and learned the
   consensus-level approach (4.1) is the right ceiling.

This keeps the discipline the rest of the plan uses: **spend research effort and
free/trial data to falsify before spending monthly dollars.**

## 7. What I need a go-ahead on

Nothing here is built or signed up for yet. Specifically requesting approval to:

1. **OddsPapi free tier** (no credit card) — wire a read-only capture source to
   pull a small Pinnacle sample for the §6 study. *[Pending §4 [VERIFY] that the
   free tier actually includes Pinnacle as their blog claims.]*
2. **SharpAPI 3-day Sharp free trial** (no credit card upfront) — a bounded
   Pinnacle capture window for the same study. Time-boxed; nothing recurring.

Both are **read-only signal capture for a backtest**, not connected to any
order path, fully inside the Kalshi-only-execution invariant. **No paid
subscription** ($99 SportsGameOdds / $399 SharpAPI) would be purchased without a
separate go-ahead *after* the §6 study passes its pre-registered bar.

## 8. Sources

- OddsPapi, "Best Odds APIs in 2026" and "Odds API Pricing 2026" —
  oddspapi.io/blog (vendor; free-tier Pinnacle/historical claims flagged
  [VERIFY]).
- SharpAPI pricing, free-tier, and Pinnacle pages — sharpapi.io (Sharp tier
  $399/mo; free tier DK+FD only, 17,280 req/day; 3-day Sharp trial).
- Unabated API — unabated.com/get-unabated-api ($3,000/mo personal).
- SportsGameOdds — sportsgameodds.com/bookmakers/pinnacle-odds-api ($99/mo
  paid tiers include Pinnacle; free tier 9 books, 10-min delay).
- Pinnacle public-API shutdown (2025-07-23) — corroborates Doc 1 §1.3.
- Kalshi API-key scopes — docs.kalshi.com/api-reference/api-keys/create-api-key
  (relevant to the read-only/full-access split; see secrets/README.md).
