"""Polymarket US (QCX) API client — SKELETON pending live access (Doc 17).

Verified from docs.polymarket.us + a live probe (2026-07-22):
- Base URL ``https://api.prod.polymarketexchange.com/v1`` (``/health`` -> 200,
  ``/markets`` -> 401 without a token). Preprod/dev hosts exist too.
- Auth: **Ed25519 private-key JWT** -> short-lived access token (**expires every
  3 minutes**), sent as ``Authorization: Bearer <token>`` plus ``x-participant-id``.
- Symbols like ``tec-mlb-...-2026-07-23-kc``; integer prices divided by the
  instrument ``price_scale`` (e.g. 550/1000 = $0.55).

**[VERIFY] once credentials exist:** the exact token-exchange endpoint and JWT
claims (``aud``/``sub``), the instrument-list and order-book paths, and the order
payload. The Ed25519 JWT construction here is real; the HTTP paths are marked.

**Execution is gated.** ``place_order``/``cancel_order`` deliberately raise —
live cross-venue order placement must go through the risk-engine/OMS (Docs 3-4),
which is not built yet. This client is wired for **market data** first.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

logger = logging.getLogger("thorp.polymarket")

PROD_BASE_URL = "https://api.prod.polymarketexchange.com/v1"
_TOKEN_PATH = "/auth/token"  # [VERIFY] exact path in the authentication guide
_TOKEN_TTL_S = 170.0  # tokens expire at 180s; refresh a little early


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def build_client_assertion(
    private_key: Ed25519PrivateKey, api_key_id: str, participant_id: str, audience: str
) -> str:
    """A signed EdDSA JWT used as the client assertion for the token exchange."""
    header = {"alg": "EdDSA", "typ": "JWT", "kid": api_key_id}
    now = int(time.time())
    claims = {
        "iss": api_key_id,
        "sub": participant_id,
        "aud": audience,
        "iat": now,
        "exp": now + 60,
        "jti": f"{participant_id}-{now}",
    }
    signing_input = f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(claims).encode())}"
    signature = private_key.sign(signing_input.encode())
    return f"{signing_input}.{_b64url(signature)}"


class PolymarketUsClient:
    def __init__(
        self,
        participant_id: str,
        api_key_id: str,
        private_key: Ed25519PrivateKey,
        base_url: str = PROD_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._participant_id = participant_id
        self._api_key_id = api_key_id
        self._private_key = private_key
        self._base_url = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=15.0, transport=transport)
        self._token: str | None = None
        self._token_at = 0.0

    @classmethod
    def from_secrets(
        cls, participant_id: str, api_key_id: str, pem_path: Path, base_url: str = PROD_BASE_URL
    ) -> PolymarketUsClient:
        key = load_pem_private_key(pem_path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise TypeError(f"expected an Ed25519 private key in {pem_path}")
        return cls(participant_id, api_key_id, key, base_url)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _access_token(self) -> str:
        if self._token is not None and (time.monotonic() - self._token_at) < _TOKEN_TTL_S:
            return self._token
        assertion = build_client_assertion(
            self._private_key, self._api_key_id, self._participant_id, self._base_url
        )
        resp = await self._client.post(
            _TOKEN_PATH,
            json={
                "grant_type": "client_credentials",
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": assertion,
            },
        )
        resp.raise_for_status()
        token = str(resp.json()["access_token"])
        self._token, self._token_at = token, time.monotonic()
        return token

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = await self._access_token()
        resp = await self._client.get(
            path,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "x-participant-id": self._participant_id,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def list_instruments(self, sport: str | None = None) -> Any:
        return await self._get("/markets", params={"sport": sport} if sport else None)

    async def orderbook(self, symbol: str) -> Any:
        return await self._get("/orderbook", params={"symbol": symbol})

    async def place_order(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(
            "Polymarket order placement is gated: live cross-venue execution must "
            "route through the risk-engine/OMS (Docs 3-4), which is not built yet."
        )

    async def cancel_order(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("gated — see place_order")
