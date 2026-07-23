"""Collector data types: matched games and the rich time-series snapshots.

Snapshots keep enough to price and to later *simulate* market-making/taking on
Kalshi against Pinnacle-derived fair value (Doc 14): full moneyline (both sides,
American + decimal + vig-inclusive + de-vigged prob) with Pinnacle's max stake,
and Kalshi best bid/offer + mid per team market. Stored as JSONL partitioned by
venue/date/game so it drops straight into S3 + DuckDB later.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from thorp.common.records import BaseRecord, JsonDict


class CollectorGame(BaseModel):
    model_config = ConfigDict(frozen=True)

    game_key: str  # "YYYY-MM-DD:AWAY-HOME" (canonical abbrs, sorted)
    teams: tuple[str, str]
    ref_team: str  # both venues' probability is expressed as P(ref_team wins)
    kalshi_event: str
    kalshi_market_by_team: dict[str, str]  # canonical abbr -> Kalshi market ticker
    pinnacle_matchup_id: int
    pinnacle_ref_side: Literal["home", "away"]  # which Pinnacle side is ref_team
    start_time: datetime | None = None


class MoneylineSide(BaseModel):
    model_config = ConfigDict(frozen=True)

    american: int
    decimal_odds: Decimal
    prob_vig: Decimal  # 1/decimal, vig-inclusive
    prob_devig: Decimal  # after two-way de-vig


class PinnacleSnapshot(BaseRecord):
    record_type: Literal["pinnacle_snapshot"] = "pinnacle_snapshot"
    ts: datetime
    game_key: str
    matchup_id: int
    home_team: str
    away_team: str
    home: MoneylineSide
    away: MoneylineSide
    max_stake: int | None = None
    raw: JsonDict | None = None


class BookSnapshot(BaseRecord):
    """Generic book moneyline snapshot (ESPN/DraftKings and future books).

    Same core fields as ``PinnacleSnapshot`` (home/away team + de-vigged
    moneyline) so the board and sim read every book uniformly.
    """

    record_type: Literal["book_snapshot"] = "book_snapshot"
    venue: str  # e.g. "espn" (DraftKings via ESPN)
    ts: datetime
    game_key: str
    home_team: str
    away_team: str
    home: MoneylineSide
    away: MoneylineSide
    source_provider: str | None = None  # e.g. "DraftKings"


Level = tuple[Decimal, Decimal]  # (price_dollars, size)


class KalshiMarketBook(BaseModel):
    model_config = ConfigDict(frozen=True)

    team: str
    ticker: str
    yes_bid: Decimal | None
    yes_ask: Decimal | None
    mid: Decimal | None
    last: Decimal | None = None
    volume: float | None = None
    open_interest: float | None = None
    # Top ladder levels (best first): resting buy-YES and buy-NO orders in
    # dollars, for the ladder UI and fill simulation.
    yes_levels: list[Level] = []
    no_levels: list[Level] = []


class KalshiSnapshot(BaseRecord):
    record_type: Literal["kalshi_snapshot"] = "kalshi_snapshot"
    ts: datetime
    game_key: str
    event_ticker: str
    markets: list[KalshiMarketBook]


class LinesSnapshot(BaseRecord):
    """Matched Kalshi<->Pinnacle spread/total lines at an instant (Doc: line
    shifts). Each pair: kind, line, selection, kalshi_prob, pinnacle_prob, edge."""

    record_type: Literal["lines_snapshot"] = "lines_snapshot"
    ts: datetime
    game_key: str
    pairs: list[JsonDict]
