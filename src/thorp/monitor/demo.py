"""Synthetic SIMULATION session generator — drives the monitor before the
engine exists (Phase 2, Doc 7 Week 6).

It writes the *real* telemetry files via the *real* writers, so the dashboard is
exercised against the genuine schema and write path, not a bespoke fixture. Not
a strategy and not a backtest — just plausible motion so the cockpit can be seen
working. Deterministic given a seed.
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from thorp.common.logging_setup import log_fill
from thorp.telemetry.events import (
    EngineStatus,
    FillEvent,
    FillModelTags,
    GroupExposure,
    HaltEvent,
    MarketMark,
    OpenOrder,
    OrderState,
    OrderStateEvent,
    PositionMark,
    RiskDecisionEvent,
    RunMode,
    Side,
)
from thorp.telemetry.writer import EventLog, StatusWriter

_CENT = Decimal("0.01")
_MARKETS = {
    "KXMLBGAME-26JUL20-NYYBOS": "MLB-NYYBOS",
    "KXMLBGAME-26JUL20-LADSF": "MLB-LADSF",
    "KXNBA-26JUL20-BOSMIA": "NBA-BOSMIA",
}


def _fee(price: Decimal, size: int) -> Decimal:
    # Kalshi taker fee ~ round_up(0.07 * C * P * (1-P)) (Doc 1 §1.1, [VERIFY]).
    raw = Decimal("0.07") * size * price * (Decimal(1) - price)
    return raw.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass
class _Pos:
    net: int = 0
    avg: Decimal = Decimal(0)
    realized: Decimal = Decimal(0)


@dataclass
class DemoEngine:
    session_dir: Path
    seed: int = 7
    _rng: random.Random = field(init=False)
    _mids: dict[str, Decimal] = field(init=False)
    _pos: dict[str, _Pos] = field(init=False)
    _orders: list[OpenOrder] = field(default_factory=list)
    _fees: Decimal = Decimal(0)
    _seq: int = 0
    _order_n: int = 0
    _fill_n: int = 0
    _started: datetime = field(init=False)
    _halted: bool = False
    _halt_reason: str | None = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._mids = {
            m: Decimal(str(self._rng.uniform(0.35, 0.65))).quantize(_CENT) for m in _MARKETS
        }
        self._pos = {m: _Pos() for m in _MARKETS}
        self._started = datetime.now(UTC)
        self._log = EventLog(self.session_dir / "events.jsonl")
        self._status = StatusWriter(self.session_dir / "status.json")

    # -- event helpers ----------------------------------------------------
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _tags(self) -> FillModelTags:
        return FillModelTags(
            queue_position="back_of_queue",
            modeled_latency_ms=self._rng.randint(40, 120),
            print_allocation=self._rng.choice(["exclusive", "shared_denied"]),
            self_excluded=False,
        )

    # -- one simulation tick ---------------------------------------------
    def tick(self) -> None:
        now = datetime.now(UTC)
        self._drift_mids()
        self._maybe_place(now)
        self._maybe_fill(now)
        self._maybe_cancel(now)
        self._maybe_noise(now)
        self._write_status(now)

    def _drift_mids(self) -> None:
        for m in _MARKETS:
            step = Decimal(str(self._rng.uniform(-0.03, 0.03))).quantize(_CENT)
            nxt = min(Decimal("0.98"), max(Decimal("0.02"), self._mids[m] + step))
            self._mids[m] = nxt

    def _maybe_place(self, now: datetime) -> None:
        if self._halted or len(self._orders) >= 6 or self._rng.random() > 0.6:
            return
        market = self._rng.choice(list(_MARKETS))
        mid = self._mids[market]
        side: Side = self._rng.choice(["buy_yes", "sell_yes"])
        offset = Decimal(str(self._rng.uniform(0.01, 0.04))).quantize(_CENT)
        price = (mid - offset) if side == "buy_yes" else (mid + offset)
        price = min(Decimal("0.98"), max(Decimal("0.02"), price))
        size = self._rng.choice([1, 2, 3, 5])
        self._order_n += 1
        order = OpenOrder(
            order_id=f"ord-{self._order_n}",
            market_key=market,
            correlated_group=_MARKETS[market],
            side=side,
            price=price,
            size=size,
            filled=0,
            state=OrderState.ACKNOWLEDGED,
            submitted_at=now,
            reason="4.1 consensus-mispricing (demo)",
            fill_model=self._tags(),
        )
        self._orders.append(order)
        self._log.append(
            OrderStateEvent(
                seq=self._next_seq(),
                ts=now,
                order_id=order.order_id,
                market_key=market,
                state=OrderState.ACKNOWLEDGED,
                resting_qty=size,
            )
        )

    def _maybe_fill(self, now: datetime) -> None:
        for order in list(self._orders):
            mid = self._mids[order.market_key]
            crosses = (order.side == "buy_yes" and mid <= order.price) or (
                order.side == "sell_yes" and mid >= order.price
            )
            if not crosses or self._rng.random() > 0.7:
                continue
            self._fill_n += 1
            fee = _fee(order.price, order.size)
            self._fees += fee
            self._apply_fill(order.market_key, order.side, order.price, order.size)
            log_fill(
                market_key=order.market_key,
                side=order.side,
                price=order.price,
                size=order.size,
                fee=fee,
                liquidity="maker",
                mode="SIMULATION",
                order_id=order.order_id,
                ts=now,
            )
            self._log.append(
                FillEvent(
                    seq=self._next_seq(),
                    ts=now,
                    fill_id=f"fill-{self._fill_n}",
                    order_id=order.order_id,
                    market_key=order.market_key,
                    correlated_group=order.correlated_group,
                    side=order.side,
                    price=order.price,
                    size=order.size,
                    fee=fee,
                    liquidity="maker",
                    fill_model=order.fill_model,
                )
            )
            self._log.append(
                OrderStateEvent(
                    seq=self._next_seq(),
                    ts=now,
                    order_id=order.order_id,
                    market_key=order.market_key,
                    state=OrderState.FILLED,
                    filled_qty=order.size,
                )
            )
            self._orders.remove(order)

    def _maybe_cancel(self, now: datetime) -> None:
        for order in list(self._orders):
            age = (now - order.submitted_at).total_seconds()
            if age > 20 and self._rng.random() < 0.3:
                self._log.append(
                    OrderStateEvent(
                        seq=self._next_seq(),
                        ts=now,
                        order_id=order.order_id,
                        market_key=order.market_key,
                        state=OrderState.CANCELLED,
                    )
                )
                self._orders.remove(order)

    def _maybe_noise(self, now: datetime) -> None:
        r = self._rng.random()
        if r < 0.05:
            self._log.append(
                RiskDecisionEvent(
                    seq=self._next_seq(),
                    ts=now,
                    intent_id=f"int-{self._seq}",
                    decision="rejected",
                    market_key=self._rng.choice(list(_MARKETS)),
                    original_size=5,
                    approved_size=0,
                    reason="hard_cap: would breach per-group exposure limit",
                )
            )
        elif r < 0.07:
            self._halted = not self._halted
            self._halt_reason = "manual kill (demo)" if self._halted else None
            self._log.append(
                HaltEvent(
                    seq=self._next_seq(),
                    ts=now,
                    halted=self._halted,
                    reason=self._halt_reason or "resumed",
                )
            )

    def _apply_fill(self, market: str, side: Side, price: Decimal, size: int) -> None:
        pos = self._pos[market]
        q = size if side == "buy_yes" else -size
        if pos.net == 0 or (pos.net > 0) == (q > 0):
            total = abs(pos.net) + abs(q)
            pos.avg = (pos.avg * abs(pos.net) + price * abs(q)) / total
            pos.net += q
            return
        closing = min(abs(q), abs(pos.net))
        sign = 1 if pos.net > 0 else -1
        pos.realized += Decimal(closing) * (price - pos.avg) * sign
        remainder = abs(q) - abs(pos.net)
        if remainder > 0:  # flipped through zero
            pos.net = (1 if q > 0 else -1) * remainder
            pos.avg = price
        else:
            pos.net += q
            if pos.net == 0:
                pos.avg = Decimal(0)

    def _write_status(self, now: datetime) -> None:
        groups: dict[str, Decimal] = {}
        for market, g in _MARKETS.items():
            pos = self._pos[market]
            groups[g] = groups.get(g, Decimal(0)) + abs(Decimal(pos.net)) * self._mids[market]
        for order in self._orders:
            g = order.correlated_group
            groups[g] = groups.get(g, Decimal(0)) + order.price * order.size

        status = EngineStatus(
            mode=RunMode.SIMULATION,
            updated_at=now,
            started_at=self._started,
            halted=self._halted,
            halt_reason=self._halt_reason,
            last_event_seq=self._seq,
            markets=[
                MarketMark(
                    market_key=m,
                    bid=(self._mids[m] - _CENT),
                    ask=(self._mids[m] + _CENT),
                    mid=self._mids[m],
                )
                for m in _MARKETS
            ],
            open_orders=list(self._orders),
            positions=[
                PositionMark(
                    market_key=m,
                    correlated_group=_MARKETS[m],
                    net_contracts=self._pos[m].net,
                    avg_entry=self._pos[m].avg,
                    realized_pnl=self._pos[m].realized,
                )
                for m in _MARKETS
            ],
            groups=[
                GroupExposure(
                    correlated_group=g,
                    exposure=exp,
                    soft_cap=Decimal("75"),
                    hard_cap=Decimal("150"),
                )
                for g, exp in sorted(groups.items())
            ],
            fees_paid=self._fees,
        )
        self._status.write(status)

    def close(self) -> None:
        self._log.close()


def run_demo(
    session_dir: Path, stop: threading.Event, interval_s: float = 1.0, seed: int = 7
) -> None:
    engine = DemoEngine(session_dir=session_dir, seed=seed)
    engine._write_status(datetime.now(UTC))
    try:
        while not stop.wait(interval_s):
            engine.tick()
    finally:
        engine.close()
