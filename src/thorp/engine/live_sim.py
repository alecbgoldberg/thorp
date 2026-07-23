"""Live SIMULATION engine — the full path, no real orders (Doc 3 §2, §4).

Reuses the collector for 4-source data (Kalshi + Pinnacle + DraftKings/ESPN +
Polymarket) and the board reader for aggregation, then runs the real safety
path: blended fair value -> price-discovery/edge strategy -> **RiskEngine.check**
-> **OMS** -> **ShadowVenue** fills -> **PositionAccounting** -> telemetry the
monitor renders (event log + status file). One process feeds the whole UI: it
writes the time series (board tab) and the engine status/events (trading tab).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from thorp.board.reader import GameSnapshots, read_latest
from thorp.collector.collector import Collector
from thorp.common.clock import CaptureClock
from thorp.common.logging_setup import log_fill
from thorp.engine.accounting import PositionAccounting
from thorp.engine.heartbeat import HeartbeatWriter
from thorp.engine.limits import RiskLimits
from thorp.engine.oms import OMS, RateLimited, ReconciliationBreak
from thorp.engine.risk import RiskEngine
from thorp.engine.shadow import ShadowVenue
from thorp.engine.state import MarketPosition, RiskState
from thorp.engine.types import ApprovedIntent, OrderIntent, RejectedIntent, decision_size
from thorp.telemetry.events import (
    EngineStatus,
    FillEvent,
    FillModelTags,
    GroupExposure,
    MarketMark,
    OpenOrder,
    OrderIntentEvent,
    OrderState,
    PositionMark,
    RiskDecisionEvent,
    RunMode,
    Side,
)
from thorp.telemetry.writer import EventLog, StatusWriter

logger = logging.getLogger("thorp.engine")

# Sim limits: bounded but big enough that trades are visible on the UI.
SIM_LIMITS = RiskLimits(
    max_order_size=100,
    fat_finger_notional=Decimal("100"),
    hard_cap=Decimal("150"),
    soft_cap=Decimal("75"),
    max_open_orders_group=20,
    max_gross_exposure=Decimal("600"),
    intraday_max_loss=Decimal("200"),
    drawdown_from_high=Decimal("100"),
    per_strategy_max_loss=Decimal("100"),
)

# Signal on blended fair vs Kalshi *mid*; execute at the ask (crossing the
# spread). Kept modest so genuine divergences trade and are visible on the UI —
# fees are charged honestly, so marginal takes show their true (often thin) P&L.
EDGE_THRESHOLD = Decimal("0.01")
STRATEGY = "pricedisc"


def _dec(v: object) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (ArithmeticError, ValueError):
        return None


def _levels(raw: object) -> list[tuple[Decimal, Decimal]]:
    out: list[tuple[Decimal, Decimal]] = []
    if isinstance(raw, list):
        for row in raw:
            p, s = _dec(row[0]), _dec(row[1])
            if p is not None and s is not None:
                out.append((p, s))
    return out


class LiveSimEngine:
    def __init__(
        self,
        collector: Collector,
        data_dir: Path,
        clock: CaptureClock,
        sample_interval_s: float = 5.0,
        discover_interval_s: float = 300.0,
    ) -> None:
        self._collector = collector
        self._data_dir = data_dir
        self._clock = clock
        self._sample_interval_s = sample_interval_s
        self._discover_interval_s = discover_interval_s
        self._state = RiskState()
        self._risk = RiskEngine(SIM_LIMITS)
        self._oms = OMS(self._state, SIM_LIMITS.max_orders_per_sec, SIM_LIMITS.max_cancels_per_sec)
        self._acct = PositionAccounting()
        self._shadow = ShadowVenue()
        session = data_dir / "live"
        self._events = EventLog(session / "events.jsonl")
        self._status = StatusWriter(session / "status.json")
        self._heartbeat = HeartbeatWriter(session / "heartbeat")
        self._halt_flag = session / "halt.flag"
        self._halt_flag.unlink(missing_ok=True)  # fresh session
        self._started = datetime.now(UTC)
        self._seq = 0
        self._intent_n = 0
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def close(self) -> None:
        self._events.close()

    def _check_halt(self) -> None:
        """Manual-kill / watchdog dead-man flag (Doc 4 §8-9): halt = no new
        position-adding orders (reducing still allowed via the RiskEngine)."""
        if self._halt_flag.exists() and not self._state.halted:
            self._state.halt("kill flag / watchdog dead-man")
            logger.error("HALT FLAG detected — engine halted, no new position-adding orders")

    # -- one trading cycle over the freshest snapshots ---------------------
    def trade_cycle(self) -> None:
        self._check_halt()
        games = read_latest(self._data_dir)
        mids: dict[str, Decimal | None] = {}
        for gs in games:
            self._trade_game(gs, mids)
        self._write_status(games, mids)

    def _trade_game(self, gs: GameSnapshots, mids: dict[str, Decimal | None]) -> None:
        if gs.kalshi is None or not gs.books:
            return
        group = gs.game_key
        by_team = {str(m["team"]): m for m in gs.kalshi.get("markets", [])}
        # blended de-vigged fair value per team across books
        fair: dict[str, list[Decimal]] = {}
        for snap in gs.books.values():
            for side in ("home", "away"):
                team = snap.get(f"{side}_team")
                prob = _dec((snap.get(side) or {}).get("prob_devig"))
                if team and prob is not None:
                    fair.setdefault(str(team), []).append(prob)
        for team, market in by_team.items():
            ticker = str(market["ticker"])
            self._state.market_to_group[ticker] = group
            self._acct.group_by_market[ticker] = group
            mid = _dec(market.get("mid"))
            mids[ticker] = mid
            if mid is not None:
                self._state.fair_value[ticker] = mid  # sanity band anchor
            last = _dec(market.get("last"))
            if last is not None:
                self._state.last_trade[ticker] = last
            probs = fair.get(team)
            ask = _dec(market.get("yes_ask"))
            if not probs or ask is None or mid is None:
                continue
            consensus = sum(probs, Decimal(0)) / len(probs)
            # Signal on divergence from the Kalshi mid; execute at the ask.
            if consensus - mid > EDGE_THRESHOLD:
                self._try_trade(group, ticker, "buy_yes", ask, consensus, market)

    def _try_trade(
        self, group: str, ticker: str, side: Side, price: Decimal, fair: Decimal,
        market: dict[str, Any]
    ) -> None:
        self._intent_n += 1
        intent = OrderIntent(
            strategy_name=STRATEGY, market_ticker=ticker, correlated_group=group,
            side=side, price=price, size=SIM_LIMITS.max_order_size,
            reason=f"edge {float(fair - price):.3f} vs blended fair",
            intent_id=f"int-{self._intent_n}",
        )
        now = self._clock.now()
        self._events.append(OrderIntentEvent(
            seq=self._next_seq(), ts=now, intent_id=intent.intent_id, market_key=ticker,
            side=side, price=price, size=intent.size, reason=intent.reason, correlated_group=group,
        ))
        decision = self._risk.check(intent, self._state)
        approved_size = decision_size(decision)
        self._events.append(RiskDecisionEvent(
            seq=self._next_seq(), ts=now, intent_id=intent.intent_id,
            decision="rejected" if isinstance(decision, RejectedIntent) else (
                "approved" if isinstance(decision, ApprovedIntent) else "modified"),
            market_key=ticker, original_size=intent.size, approved_size=approved_size,
            reason=decision.reason if isinstance(decision, RejectedIntent) else "ok",
        ))
        if isinstance(decision, RejectedIntent):
            return
        try:
            record = self._oms.submit(decision)
        except RateLimited:
            self._state.release(intent.intent_id)
            return
        fill = self._shadow.fill(decision, _levels(market.get("yes_levels")),
                                 _levels(market.get("no_levels")))
        self._oms.on_ack(record.client_order_id)
        if fill is None:
            self._oms.on_cancelled(record.client_order_id)  # unfilled -> release reservation
            return
        try:
            self._oms.on_fill(record.client_order_id, fill.fill_id, fill.size)
        except ReconciliationBreak as exc:
            logger.error("reconciliation break: %s", exc)
            self._state.halt(str(exc))
            return
        self._acct.apply_fill(ticker, group, side, fill.price, fill.size, fill.fee)
        self._sync_position(ticker)
        self._events.append(FillEvent(
            seq=self._next_seq(), ts=now, fill_id=fill.fill_id, order_id=record.client_order_id,
            market_key=ticker, correlated_group=group, side=side, price=fill.price, size=fill.size,
            fee=fill.fee, liquidity="taker",
            fill_model=FillModelTags(queue_position="taker", modeled_latency_ms=0,
                                     print_allocation="exclusive", self_excluded=False),
        ))
        log_fill(market_key=ticker, side=side, price=fill.price, size=fill.size, fee=fill.fee,
                 liquidity="taker", mode="SIMULATION", order_id=record.client_order_id, ts=now)

    def _sync_position(self, ticker: str) -> None:
        pos = self._acct.positions.get(ticker)
        if pos is not None:
            self._state.positions[ticker] = MarketPosition(net_contracts=pos.net, avg_price=pos.avg)

    def _write_status(self, games: list[GameSnapshots], mids: dict[str, Decimal | None]) -> None:
        now = self._clock.now()
        open_orders = [
            OpenOrder(order_id=o.client_order_id, market_key=o.intent.market_ticker,
                      correlated_group=o.intent.correlated_group, side=o.intent.side,
                      price=o.intent.price, size=o.resting_size, filled=o.filled_qty,
                      state=OrderState(o.state), submitted_at=now, reason=o.intent.reason)
            for o in self._oms.open_orders()
        ]
        positions = [
            PositionMark(market_key=m, correlated_group=self._acct.group_by_market.get(m, "?"),
                         net_contracts=p.net, avg_entry=p.avg, realized_pnl=p.realized)
            for m, p in self._acct.positions.items() if p.net != 0 or p.realized != 0
        ]
        groups_seen = {self._acct.group_by_market.get(m) for m in self._acct.positions}
        groups = [
            GroupExposure(correlated_group=str(g), exposure=self._state.group_exposure(str(g)),
                          soft_cap=SIM_LIMITS.soft_cap, hard_cap=SIM_LIMITS.hard_cap)
            for g in groups_seen if g
        ]
        marks = [
            MarketMark(market_key=m, bid=None, ask=None, mid=mid)
            for m, mid in mids.items() if mid is not None
        ]
        status = EngineStatus(
            mode=RunMode.SIMULATION, updated_at=now, started_at=self._started,
            halted=self._state.halted, halt_reason=self._state.halt_reason,
            last_event_seq=self._seq, markets=marks, open_orders=open_orders,
            positions=positions, groups=groups, fees_paid=self._acct.fees_paid,
        )
        self._status.write(status)

    async def run(self) -> None:
        await self._collector.discover()
        last_discover = self._clock.now()
        while not self._stop.is_set():
            await self._collector.sample_all()
            self.trade_cycle()
            self._heartbeat.beat()  # last step of a completed loop (Doc 4 §8 gap-1)
            now = self._clock.now()
            if (now - last_discover).total_seconds() >= self._discover_interval_s:
                await self._collector.discover()
                last_discover = now
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._sample_interval_s)
                break
            except TimeoutError:
                pass
