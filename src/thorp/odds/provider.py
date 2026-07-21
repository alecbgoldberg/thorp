"""Odds-provider interface + factory (the swap seam, Doc 13 §5).

Callers depend only on ``OddsProvider``. Swapping vendors = add a branch to
``build_provider`` and an implementation module; nothing else changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from thorp.odds.config import OddsConfig
from thorp.odds.types import Fixture, OddsQuoteRecord


class OddsProvider(Protocol):
    """A read-only odds source. No method places or affects an order —
    odds are signal-only (Kalshi-only execution stands, Doc 13 §1)."""

    @property
    def name(self) -> str: ...

    async def list_fixtures(self, sport: str, start: datetime, end: datetime) -> list[Fixture]: ...

    async def fetch_quotes(
        self, fixture_id: str, sport: str, bookmakers: list[str]
    ) -> list[OddsQuoteRecord]: ...

    async def aclose(self) -> None: ...


def build_provider(cfg: OddsConfig, api_key: str) -> OddsProvider:
    if cfg.provider == "oddspapi":
        from thorp.odds.oddspapi import OddsPapiProvider

        return OddsPapiProvider(
            api_key=api_key, base_url=cfg.base_url, odds_format=cfg.odds_format
        )
    raise ValueError(
        f"unknown odds provider {cfg.provider!r}; add it to build_provider "
        f"and PROVIDER_DEFAULTS (see src/thorp/odds/)"
    )
