"""Derived dashboard view: mark-to-mid P&L and JSON-friendly projection.

Pure functions over an ``EngineStatus`` snapshot + recent events, so the P&L
math is unit-testable in isolation. Money is kept as ``Decimal`` through the
computation and converted to ``float`` only at the JSON boundary (display only;
the engine's own accounting stays Decimal).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from thorp.telemetry.events import (
    EngineStatus,
    Event,
    FillEvent,
    HaltEvent,
    MarketMark,
    PositionMark,
    RiskDecisionEvent,
)


def mid_for(mark: MarketMark) -> Decimal | None:
    """Engine-reported mid, else midpoint of bid/ask, else the one live side."""
    if mark.mid is not None:
        return mark.mid
    if mark.bid is not None and mark.ask is not None:
        return (mark.bid + mark.ask) / 2
    return mark.bid if mark.bid is not None else mark.ask


def unrealized_pnl(position: PositionMark, mid: Decimal | None) -> Decimal | None:
    """Mark-to-mid unrealized P&L in dollars for a signed YES position.

    ``net_contracts`` is signed (+ long YES, - short YES); a YES contract is
    worth ``mid`` dollars, so both long and short fall out of one formula.
    Returns None when the market has no mark (can't be valued).
    """
    if mid is None or position.net_contracts == 0:
        return None
    return Decimal(position.net_contracts) * (mid - position.avg_entry)


def _f(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def build_view(status: EngineStatus | None, events: list[Event], now: datetime) -> dict[str, Any]:
    if status is None:
        return {"connected": False, "reason": "no status file yet — engine not running"}

    marks: dict[str, Decimal | None] = {m.market_key: mid_for(m) for m in status.markets}

    positions: list[dict[str, Any]] = []
    realized_total = Decimal(0)
    unrealized_total = Decimal(0)
    for pos in status.positions:
        mid = marks.get(pos.market_key)
        unreal = unrealized_pnl(pos, mid)
        realized_total += pos.realized_pnl
        if unreal is not None:
            unrealized_total += unreal
        positions.append(
            {
                "market_key": pos.market_key,
                "group": pos.correlated_group,
                "net_contracts": pos.net_contracts,
                "avg_entry": _f(pos.avg_entry),
                "mid": _f(mid),
                "unrealized": _f(unreal),
                "realized": _f(pos.realized_pnl),
            }
        )

    open_orders = [
        {
            "order_id": o.order_id,
            "market_key": o.market_key,
            "group": o.correlated_group,
            "side": o.side,
            "price": _f(o.price),
            "size": o.size,
            "filled": o.filled,
            "remaining": o.size - o.filled,
            "state": o.state,
            "age_s": max(0.0, (now - o.submitted_at).total_seconds()),
            "reason": o.reason,
            "fill_model": o.fill_model.model_dump() if o.fill_model else None,
        }
        for o in status.open_orders
    ]

    groups = [
        {
            "group": g.correlated_group,
            "exposure": _f(g.exposure),
            "soft_cap": _f(g.soft_cap),
            "hard_cap": _f(g.hard_cap),
            "utilization": (float(g.exposure / g.hard_cap) if g.hard_cap else None),
        }
        for g in status.groups
    ]

    fills = [_fill_row(e) for e in reversed(events) if isinstance(e, FillEvent)][:50]
    alerts = [
        _alert_row(e)
        for e in reversed(events)
        if (isinstance(e, HaltEvent))
        or (isinstance(e, RiskDecisionEvent) and e.decision == "rejected")
    ][:30]

    net = realized_total + unrealized_total
    staleness = (now - status.updated_at).total_seconds()
    return {
        "connected": True,
        "mode": status.mode,
        "halted": status.halted,
        "halt_reason": status.halt_reason,
        "updated_at": status.updated_at.isoformat(),
        "staleness_s": staleness,
        "stale": staleness > 5.0,
        "uptime_s": max(0.0, (now - status.started_at).total_seconds()),
        "last_event_seq": status.last_event_seq,
        "pnl": {
            "realized": _f(realized_total),
            "unrealized": _f(unrealized_total),
            "net": _f(net),
            "fees_paid": _f(status.fees_paid),
        },
        "positions": positions,
        "open_orders": open_orders,
        "groups": groups,
        "fills": fills,
        "alerts": alerts,
    }


def _fill_row(e: FillEvent) -> dict[str, Any]:
    return {
        "ts": e.ts.isoformat(),
        "market_key": e.market_key,
        "group": e.correlated_group,
        "side": e.side,
        "price": _f(e.price),
        "size": e.size,
        "fee": _f(e.fee),
        "liquidity": e.liquidity,
        "fill_model": e.fill_model.model_dump() if e.fill_model else None,
    }


def _alert_row(e: Event) -> dict[str, Any]:
    if isinstance(e, HaltEvent):
        kind = "HALT" if e.halted else "RESUME"
        return {"ts": e.ts.isoformat(), "kind": kind, "detail": e.reason}
    assert isinstance(e, RiskDecisionEvent)
    return {
        "ts": e.ts.isoformat(),
        "kind": "REJECT",
        "detail": f"{e.market_key}: {e.reason}",
    }
