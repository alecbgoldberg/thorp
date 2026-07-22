"""Kalshi REST client — market-data reads only.

This module exposes market discovery and orderbook snapshots. It deliberately
has no order-placement capability of any kind; execution goes exclusively
through the Trading Engine's ``ExecutionVenue`` (Doc 3 §2, §4), which does not
exist in the Recorder process at all.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from thorp.common.records import JsonDict

from .auth import KalshiSigner


class KalshiRestClient:
    def __init__(
        self,
        base_url: str,
        signer: KalshiSigner | None = None,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_path = urlsplit(base_url).path.rstrip("/")
        self._signer = signer
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s, transport=transport)

    async def get_open_markets(self, series_ticker: str) -> list[JsonDict]:
        """All open markets for a series, following cursor pagination."""
        markets: list[JsonDict] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "series_ticker": series_ticker,
                "status": "open",
                "limit": 1000,
            }
            if cursor:
                params["cursor"] = cursor
            payload = await self._get("/markets", params=params)
            markets.extend(payload.get("markets") or [])
            cursor = payload.get("cursor") or None
            if not cursor:
                return markets

    async def get_orderbook(self, market_ticker: str, depth: int = 10) -> JsonDict:
        return await self._get(f"/markets/{market_ticker}/orderbook", params={"depth": depth})

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> JsonDict:
        headers = (
            self._signer.headers("GET", f"{self._base_path}{path}") if self._signer else None
        )
        response = await self._client.get(path, params=params, headers=headers)
        response.raise_for_status()
        result: JsonDict = response.json()
        return result
