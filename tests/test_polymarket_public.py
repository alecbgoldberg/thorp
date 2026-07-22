"""Polymarket public (Gamma) market-data client parsing."""

from decimal import Decimal

import httpx

from thorp.polymarket.public import PolymarketPublicClient, parse_markets


def test_parse_markets() -> None:
    payload = {"data": [
        {"conditionId": "0xabc", "question": "Yankees beat Pirates?", "slug": "nyy-pit",
         "bestBid": "0.62", "bestAsk": "0.64", "endDate": "2026-07-22T22:40:00Z"},
        {"question": "no id -> skipped"},
    ]}
    markets = parse_markets(payload)
    assert len(markets) == 1
    m = markets[0]
    assert m.condition_id == "0xabc"
    assert m.best_bid == Decimal("0.62") and m.best_ask == Decimal("0.64")


async def test_list_markets_hits_gamma() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        assert request.url.path.endswith("/markets")
        return httpx.Response(200, json=[
            {"conditionId": "0x1", "question": "q", "slug": "s",
             "bestBid": "0.5", "bestAsk": "0.51"},
        ])

    client = PolymarketPublicClient(transport=httpx.MockTransport(handler))
    markets = await client.list_markets(tag="mlb", limit=10)
    await client.aclose()
    assert seen["tag"] == "mlb" and seen["closed"] == "false"
    assert markets[0].condition_id == "0x1"
