"""KalshiRestClient: pagination, auth-header attachment, path signing."""

import json
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import rsa

from thorp.recorder.kalshi.auth import KalshiSigner
from thorp.recorder.kalshi.rest import KalshiRestClient

BASE = "https://api.test.example/trade-api/v2"


def make_transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_get_open_markets_follows_cursor_pagination() -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append(params)
        if params.get("cursor") == "page2":
            return httpx.Response(200, json={"markets": [{"ticker": "M3"}], "cursor": ""})
        return httpx.Response(
            200, json={"markets": [{"ticker": "M1"}, {"ticker": "M2"}], "cursor": "page2"}
        )

    client = KalshiRestClient(BASE, transport=make_transport(handler))
    markets = await client.get_open_markets("KXMLBGAME")
    await client.aclose()

    assert [m["ticker"] for m in markets] == ["M1", "M2", "M3"]
    assert len(calls) == 2
    assert calls[0]["series_ticker"] == "KXMLBGAME"
    assert calls[0]["status"] == "open"
    assert "cursor" not in calls[0]
    assert calls[1]["cursor"] == "page2"


async def test_get_orderbook_hits_market_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/trade-api/v2/markets/KXMLBGAME-T/orderbook"
        return httpx.Response(200, json={"orderbook": {"yes": [[40, 1]], "no": []}})

    client = KalshiRestClient(BASE, transport=make_transport(handler))
    payload = await client.get_orderbook("KXMLBGAME-T")
    await client.aclose()
    assert payload["orderbook"]["yes"] == [[40, 1]]


async def test_signer_headers_attached_with_full_path() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signer = KalshiSigner("kid", key)
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({k: v for k, v in request.headers.items() if k.startswith("kalshi-")})
        return httpx.Response(200, json={"orderbook": {}})

    client = KalshiRestClient(BASE, signer=signer, transport=make_transport(handler))
    await client.get_orderbook("X")
    await client.aclose()

    assert seen["kalshi-access-key"] == "kid"
    assert "kalshi-access-signature" in seen and "kalshi-access-timestamp" in seen


async def test_http_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = KalshiRestClient(BASE, transport=make_transport(handler))
    try:
        await client.get_orderbook("X")
        raise AssertionError("expected HTTPStatusError")
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 500
    finally:
        await client.aclose()


async def test_unauthenticated_requests_send_no_kalshi_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert not any(k.startswith("kalshi-") for k in request.headers)
        return httpx.Response(200, json=json.loads('{"markets": [], "cursor": ""}'))

    client = KalshiRestClient(BASE, transport=make_transport(handler))
    assert await client.get_open_markets("S") == []
    await client.aclose()
