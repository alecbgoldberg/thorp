"""Provider-neutral odds types.

These are the interchange types every odds provider maps onto (Doc 13 §5): the
rest of the system depends on *these*, never on a vendor's response shape, so
swapping OddsPapi for another vendor later is a new provider implementation plus
its key — no caller changes.

Odds are normalized to **decimal odds** and an **implied probability**
(1/decimal, still vig-inclusive — de-vigging to a fair probability happens
downstream in the FairValueEngine, Doc 1 §2.3). ``OddsQuoteRecord`` is what the
capture loop journals, keeping the verbatim vendor payload in ``raw`` (Doc 5
discipline) so a normalization bug is recoverable.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from thorp.common.records import BaseRecord, JsonDict


class Fixture(BaseRecord):
    record_type: Literal["fixture"] = "fixture"
    provider: str
    fixture_id: str
    sport: str
    start_time: datetime | None
    home: str | None
    away: str | None
    raw: JsonDict | None = None


class OddsQuoteRecord(BaseRecord):
    """One bookmaker's price for one outcome of one fixture at one instant."""

    record_type: Literal["odds_quote"] = "odds_quote"
    provider: str
    bookmaker: str  # e.g. "pinnacle"
    fixture_id: str
    sport: str
    market: str  # normalized label, e.g. "moneyline"; vendor id kept in raw
    outcome: str  # normalized label, e.g. "home"/"away"/"draw"
    decimal_odds: Decimal
    implied_prob: Decimal  # 1/decimal_odds, vig-inclusive
    start_time: datetime | None = None
    fetched_ts: datetime
    raw: JsonDict | None = None
