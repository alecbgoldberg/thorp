"""Build the aggregation-board view: per game, book fair values vs the Kalshi
market, the edge between them, and the Kalshi ladder.

Fair value = a book's de-vigged P(team). Edge for a team = book fair value minus
the Kalshi mid for that team's YES market: positive means Kalshi looks cheap
(a buy), negative means rich (a sell). With multiple books this also surfaces
book disagreement, the raw material for detecting where price discovery happens.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from thorp.board.reader import GameSnapshots


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _staleness_s(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    try:
        return (now - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return None


def _book_probs(snap: dict[str, Any]) -> dict[str, float]:
    """team -> de-vigged prob from a book snapshot (moneyline home/away)."""
    out: dict[str, float] = {}
    for side in ("home", "away"):
        team = snap.get(f"{side}_team")
        prob = _f((snap.get(side) or {}).get("prob_devig"))
        if team and prob is not None:
            out[str(team)] = prob
    return out


def _kalshi_by_team(snap: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(m["team"]): m for m in snap.get("markets", [])}


def build_board(games: list[GameSnapshots], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for gs in sorted(games, key=lambda g: g.game_key):
        book_probs = {venue: _book_probs(snap) for venue, snap in gs.books.items()}
        kalshi = _kalshi_by_team(gs.kalshi) if gs.kalshi else {}
        teams = sorted({t for probs in book_probs.values() for t in probs} | set(kalshi))
        if not teams:
            continue

        team_rows = []
        best_abs_edge = 0.0
        for team in teams:
            fair_by_book = {v: probs.get(team) for v, probs in book_probs.items()}
            fair_vals = [p for p in fair_by_book.values() if p is not None]
            consensus = sum(fair_vals) / len(fair_vals) if fair_vals else None
            km = kalshi.get(team, {})
            kmid = _f(km.get("mid"))
            edge = (consensus - kmid) if (consensus is not None and kmid is not None) else None
            if edge is not None:
                best_abs_edge = max(best_abs_edge, abs(edge))
            team_rows.append({
                "team": team,
                "fair_by_book": {v: (round(p, 4) if p is not None else None)
                                 for v, p in fair_by_book.items()},
                "consensus": round(consensus, 4) if consensus is not None else None,
                "kalshi_bid": _f(km.get("yes_bid")),
                "kalshi_ask": _f(km.get("yes_ask")),
                "kalshi_mid": kmid,
                "kalshi_last": _f(km.get("last")),
                "kalshi_volume": _f(km.get("volume")),
                "edge": round(edge, 4) if edge is not None else None,
                "yes_levels": [[_f(p), _f(s)] for p, s in (km.get("yes_levels") or [])[:6]],
                "no_levels": [[_f(p), _f(s)] for p, s in (km.get("no_levels") or [])[:6]],
            })

        book_ts = next((s.get("ts") for s in gs.books.values()), None)
        rows.append({
            "game_key": gs.game_key,
            "books": sorted(gs.books),
            "teams": team_rows,
            "best_abs_edge": round(best_abs_edge, 4),
            "pinnacle_stale_s": _staleness_s(book_ts, now),
            "kalshi_stale_s": _staleness_s(gs.kalshi.get("ts") if gs.kalshi else None, now),
            "has_kalshi": bool(kalshi),
        })
    rows.sort(key=lambda r: r["best_abs_edge"], reverse=True)
    return {"generated_at": now.isoformat(), "games": rows}
