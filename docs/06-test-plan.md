# Document 6 — Test Plan

Written against the finalized (post-Opus-review) Doc 3/Doc 4 designs — several test cases below are direct regressions for specific bugs the adversarial review found, called out explicitly rather than folded anonymously into a generic matrix.

## 1. Tooling

- **pytest** for unit/integration; **Hypothesis** for property-based tests.
- **Mock Kalshi exchange server** implementing the real REST/WS protocol and schema as confirmed in Doc 1 §1.1 (order endpoints, book delta format, fee rounding behavior) — used for integration and fault-injection tests so they exercise the real wire format, not a hand-simplified stand-in.
- **coverage.py**, branch coverage mode.
- No CI infrastructure is assumed at this budget/scale (Doc 7 doesn't provision one) — the deterministic-replay and full test suite run as a local pre-deploy gate (`make check` or equivalent) before any code reaches CANARY/PRODUCTION, not on every commit to a remote CI service.

## 2. Unit Tests

| Area | Cases |
|---|---|
| Book maintenance (Doc 3 §3.2) | Crossed book rejected as hard error; negative size rejected; sequence gap triggers resync-from-snapshot, never silent skip; replaying deltas from a snapshot reproduces a fresh snapshot |
| Fee calculation (Doc 1 §1.1) | Every value in the worked fee table is a golden test case, locked in once the primary PDF [VERIFY] is confirmed; fee formula tested at boundary prices (1¢, 99¢, 50¢) |
| Order state machine (Doc 3 §3.6, revised) | Every legal transition in the revised machine; `PENDING_CANCEL → FILLED` explicitly tested as **legal**, not a break (direct regression for the Opus-found mis-flagged race); a late/duplicate terminal message that agrees with known state is a no-op; one that disagrees raises a reconciliation break |
| De-vigging math (Doc 1 §2.3) | Shin and Power methods against hand-computed examples; multiplicative/additive included for comparison even though not used in production, to document why they were rejected |
| PnL accounting | Realized/unrealized computed correctly against known fill sequences, including a sequence with partial fills reconciled via cumulative-filled-quantity (not delta-summing — direct regression for the Opus dedup fix) |
| Every risk control (Doc 4 §1-7 tables) | One negative test per control: construct an `OrderIntent`/`RiskState` that violates exactly that bound, assert the result is `RejectedIntent` (or the correct `ModifiedIntent` for fade-range cases) — not "the strategy shouldn't do this," but "if it did, the engine refuses it" |

## 3. Property-Based Tests (Hypothesis)

- **Book invariants under arbitrary update sequences**: for any generated sequence of deltas/snapshots/gaps, best bid < best ask always holds after processing, and reconstructed state from snapshot+deltas matches an independently-fetched snapshot.
- **Position accounting always reconciles**: for any generated sequence of fills (including duplicates, out-of-order delivery, and partial fills), running `PositionAccounting` state matches a from-scratch recomputation over the same fill set — this must hold even when the input sequence is adversarially reordered or duplicated.
- **No sequence of strategy-proposed intents can breach a risk limit — the direct regression test for the Opus-found in-flight-order race.** Generate arbitrary sequences of `OrderIntent` batches (including the exact shape that broke the original design: multiple intents against the same correlated group in one batch, before any fill lands) and assert that `RiskState.group_exposure(group)` — computed from the in-flight reservation ledger (Doc 3 §3.5's fix) — never exceeds `hard_cap` at any point during processing, regardless of batch size or `await` interleaving. This property is the single most important test in the suite: it's testing the exact mechanism the reviewer found broken, not a proxy for it.
- **Fee formula properties**: fee is always ≥ 0, symmetric around 50¢, monotonically increasing from 1¢ to 50¢ and decreasing from 50¢ to 99¢.
- **Fair-value uncertainty is monotonic non-increasing in live input count** (Doc 4 §6's fix) — generated input sets of varying size/staleness must never produce a *lower* uncertainty from *fewer* live inputs.

## 4. Integration Tests

Against the mock Kalshi exchange server, exercising the full path market data → fair value → strategy → risk → OMS → fill → position update:

- Standard signal-to-fill happy path, all four run modes, asserting identical `OrderIntent`/`RiskDecision` sequences across BACKTEST/SIMULATION/CANARY for the same input event stream (modulo the fill-model differences that are supposed to differ, per Doc 3 §4).
- **The exact in-flight-race scenario, end to end**: a strategy emits a batch of 6 intents against one correlated group in a single signal, submitted with artificial network latency against the mock exchange; assert final reconciled position never exceeds `hard_cap`, using the real async submission path (not a synchronous test harness that would hide the race the unit-level property test above already covers in isolation — this test specifically exercises the `await` interleaving with the mock exchange's own async responses).
- Startup reconciliation: engine boots against a mock exchange with a nonzero existing position, asserts internal state is populated from the fetch (not from any cached file) before transitioning out of `STARTING` (Doc 4 §10).

## 5. Deterministic Replay Tests

A captured SIMULATION or CANARY session's event log (Doc 3 §3.8), replayed through BACKTEST mode against the same recorded inputs, produces a **bit-identical decision sequence** — same `OrderIntent`s, same `RiskDecision`s, same fill-model-assumption tags. This is the regression backbone: any code change that alters this output for a previously-captured session must be an intentional, reviewed change, not a silent behavior drift. Run as part of the local pre-deploy gate (§1) before any change reaches CANARY.

## 6. Fault Injection

The highest-priority category — this is what actually costs money in production, and several cases here are direct regressions for specific Opus-review findings:

| Scenario | Assertion |
|---|---|
| WebSocket disconnect mid-order (after send, before ack) | Order resolves correctly on reconnect via reconciliation, never double-submitted (idempotency key, Doc 3 §3.6's `nonce` fix) |
| Duplicate fill delivery (same exchange fill-id twice) | Deduplicated by fill-id; position not double-counted (direct regression for the Opus dedup finding) |
| Out-of-order messages (fill arrives before its order's ack) | Handled without raising a spurious reconciliation break |
| Book delta sequence gap | Triggers resync-from-snapshot within one cycle, no silent processing of a known-incomplete book |
| Exchange reject after acknowledgment (self-match, market closed) | `REJECTED` transition from `ACKNOWLEDGED` handled per the revised state machine, not treated as an illegal/undefined transition |
| Partial fills, multiple, summing via cumulative quantity | Final position matches the exchange's own cumulative-filled figure even if individual delta messages were lossy or reordered |
| Clock jump mid-session (NTP correction, DST) | Monotonic-clock-based interval measurement (Doc 5 §4) is unaffected; wall-clock-mapped timestamps re-sync without producing negative intervals |
| **Fill arriving for an order believed cancelled** | Treated as legal (`PENDING_CANCEL → FILLED`) unless quantity exceeds known resting size — direct regression for the Opus-found mis-flagged-race finding |
| Watchdog: kill the Engine process outright mid-session | Watchdog detects heartbeat staleness within the 10s+2s+RTT bound, cancel-all succeeds and is *verified* (re-fetch open orders = 0) before the incident is considered resolved — direct regression for the Opus-found silent-failure gap |
| Reconciliation break: desync internal state from a mocked exchange position | Cancel-all fires **before** the halt-and-alert (not after, not instead of) — direct regression for the Opus-found ordering bug |
| Disk full on the bulk event-log volume | Heartbeat/halt-flag writes (separate volume, Doc 3 §5's fix) remain unaffected; engine degrades (or halts) gracefully rather than silently losing its control-plane channel |

## 7. Sim-vs-Live Divergence Reporting (standing, not one-time)

During CANARY, every signal that fired is logged with both `ShadowVenue`'s prediction (fill/no-fill, price, slippage, and the full fill-model-assumptions vector — Doc 3 §4's fix) and `KalshiLiveVenue`'s actual outcome. Regenerated after every CANARY session as an automated report, not eyeballed manually: any strategy whose realized slippage exceeds 1.5x the shadow-predicted figure (Doc 2 §2 Phase 3 gate) is flagged automatically. This report is also the tool for diagnosing *which* fill-model assumption (queue position, latency, print-allocation, self-exclusion) is driving a given divergence, per Doc 3 §4.

## 8. Coverage Targets

| Component | Target | Why |
|---|---|---|
| `RiskEngine`, in-flight exposure ledger, OMS state machine | ~95%+ branch coverage | This is exactly the code the Opus review found the worst, highest-severity bugs in — it gets the highest bar in the project, not a uniform default |
| Reconciliation, Watchdog, kill-switch paths | ~95%+ branch coverage | Safety-critical, low-frequency-but-high-consequence code paths are exactly where undertested edge cases hide |
| Recorder / data pipeline | ~80%+ | Doc 5's "never miss data" mandate justifies a high bar, though slightly below the risk/OMS tier since a recorder bug is recoverable (gap detection catches it) in a way a risk-engine bug is not |
| Strategy / fair-value implementations | ~70-80%, deliberately not higher | These are exploratory and tunable by design (Phase 1 backtesting iterates on them) — chasing near-100% coverage here produces brittle tests that fight against legitimate parameter iteration rather than catching real bugs |
