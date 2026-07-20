"""RSA-PSS request signing (Doc 1 §1.1): message format and verifiability."""

import base64

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from thorp.recorder.kalshi.auth import KalshiSigner


def test_headers_sign_timestamp_method_path() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signer = KalshiSigner("key-id-123", key)

    headers = signer.headers("get", "/trade-api/v2/markets", timestamp_ms=1_789_000_000_000)

    assert headers["KALSHI-ACCESS-KEY"] == "key-id-123"
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1789000000000"
    # Signature verifies against exactly timestamp + upper-cased method + path.
    key.public_key().verify(
        base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
        b"1789000000000GET/trade-api/v2/markets",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_default_timestamp_is_current_millis() -> None:
    import time

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signer = KalshiSigner("k", key)
    before = int(time.time() * 1000)
    ts = int(signer.headers("GET", "/x")["KALSHI-ACCESS-TIMESTAMP"])
    after = int(time.time() * 1000)
    assert before <= ts <= after
