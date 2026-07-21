"""Kalshi API-key + RSA-PSS request signing (Doc 1 §1.1).

Signs ``timestamp_ms + METHOD + path`` (path only, no query string) with
RSA-PSS/SHA-256. The private key is loaded from a file path supplied via
environment variable — never from the repo or config (Doc 8 §2).
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class KalshiSigner:
    def __init__(self, api_key_id: str, private_key: rsa.RSAPrivateKey) -> None:
        self._api_key_id = api_key_id
        self._private_key = private_key

    @classmethod
    def from_pem_bytes(cls, api_key_id: str, pem: bytes, source: str = "<inline>") -> KalshiSigner:
        key = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise TypeError(f"expected an RSA private key in {source}, got {type(key).__name__}")
        return cls(api_key_id, key)

    @classmethod
    def from_pem_file(cls, api_key_id: str, pem_path: Path) -> KalshiSigner:
        return cls.from_pem_bytes(api_key_id, pem_path.read_bytes(), source=str(pem_path))

    def headers(self, method: str, path: str, timestamp_ms: int | None = None) -> dict[str, str]:
        # Uses real system time, not CaptureClock: the server validates this
        # timestamp against its own wall clock.
        ts = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
        message = f"{ts}{method.upper()}{path}".encode()
        signature = self._private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self._api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
