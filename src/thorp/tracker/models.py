"""Tracker data types."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from thorp.common.records import BaseRecord

Source = Literal["kalshi", "pinnacle"]


class KalshiGame(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_ticker: str
    game_date: date | None
    # canonical team abbr -> Kalshi market ticker whose YES = that team wins
    market_by_team: dict[str, str]
    name_by_team: dict[str, str]


class GameLink(BaseModel):
    """A Kalshi game matched to an OddsPapi fixture, with a fixed reference team
    both sources' probabilities are expressed for."""

    model_config = ConfigDict(frozen=True)

    game_key: str  # e.g. "2026-07-21:DET-KC"
    teams: tuple[str, str]  # canonical abbrs, sorted
    ref_team: str  # the team both probs track (P(ref_team wins))
    kalshi_event: str
    kalshi_market_by_team: dict[str, str]
    oddspapi_fixture_id: str
    oddspapi_pinnacle_id: str | None
    start_time: datetime | None = None  # first pitch, for active-window gating


class Observation(BaseRecord):
    """One probability reading of ``ref_team`` from one source at one instant."""

    record_type: Literal["tracker_obs"] = "tracker_obs"
    game_key: str
    ref_team: str
    source: Source
    prob: Decimal  # P(ref_team wins), in [0, 1]
    ts: datetime
    detail: str = ""  # e.g. kalshi ticker or pinnacle orientation
