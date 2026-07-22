"""Polymarket public market data (no auth) — for SIM/reference only.

This is the **international** Polymarket public Gamma API (docs.polymarket.com),
which serves market data — best bid/ask, condition/token ids — without any
credentials. It's a read-only pricing/reference source for the sim, distinct
from the KYC'd **Polymarket US** (QCX) execution client in ``client.py``. Note
the two are different order books, so international prices are a *reference*, not
the exact prices we'd execute against on Polymarket US.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class PmMarket:
    condition_id: str
    question: str
    slug: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    end_date: str | None
    raw: dict[str, Any]


def _dec(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def parse_markets(payload: Any) -> list[PmMarket]:
    items = payload if isinstance(payload, list) else payload.get("data", [])
    out: list[PmMarket] = []
    for m in items:
        cid = m.get("conditionId") or m.get("condition_id")
        if not cid:
            continue
        out.append(
            PmMarket(
                condition_id=str(cid),
                question=str(m.get("question", "")),
                slug=str(m.get("slug", "")),
                best_bid=_dec(m.get("bestBid")),
                best_ask=_dec(m.get("bestAsk")),
                end_date=m.get("endDate"),
                raw=m,
            )
        )
    return out


class PolymarketPublicClient:
    def __init__(
        self, base_url: str = GAMMA_BASE, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=15.0,
            transport=transport,
            headers={"User-Agent": _BROWSER_UA, "Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_markets(
        self, tag: str | None = None, limit: int = 100, closed: bool = False
    ) -> list[PmMarket]:
        params: dict[str, Any] = {"limit": limit, "closed": str(closed).lower()}
        if tag:
            params["tag"] = tag
        r = await self._client.get("/markets", params=params)
        r.raise_for_status()
        return parse_markets(r.json())
