"""Key loading from PEM files and the entrypoint's env-based signer wiring."""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from thorp.recorder.__main__ import _build_signer
from thorp.recorder.config import RecorderConfig
from thorp.recorder.kalshi.auth import KalshiSigner


def make_cfg(tmp_path: Path) -> RecorderConfig:
    # Point secrets_file at a nonexistent path so _build_signer reads only the
    # real (monkeypatched) environment, not a checked-out secrets file.
    return RecorderConfig(
        data_dir=Path("data/raw"),
        environment="demo",
        series_tickers=("X",),
        rest_url="https://x",
        ws_url="wss://x",
        secrets_file=tmp_path / "absent.env",
    )


READONLY_ID = "THORP_KALSHI_READONLY_KEY_ID"
READONLY_KEY = "THORP_KALSHI_READONLY_PRIVATE_KEY"


def pem_bytes(key: rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def test_from_pem_file_loads_rsa_key(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "key.pem"
    path.write_bytes(pem_bytes(key))
    signer = KalshiSigner.from_pem_file("kid", path)
    assert "KALSHI-ACCESS-SIGNATURE" in signer.headers("GET", "/x")


def test_from_pem_file_rejects_non_rsa_key(tmp_path: Path) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "ec.pem"
    path.write_bytes(pem_bytes(key))
    with pytest.raises(TypeError, match="RSA"):
        KalshiSigner.from_pem_file("kid", path)


def test_build_signer_returns_none_without_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(READONLY_ID, raising=False)
    monkeypatch.delenv(READONLY_KEY, raising=False)
    assert _build_signer(make_cfg(tmp_path)) is None


def test_build_signer_loads_readonly_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "key.pem"
    path.write_bytes(pem_bytes(key))
    monkeypatch.setenv(READONLY_ID, "kid-1")
    monkeypatch.setenv(READONLY_KEY, str(path))
    signer = _build_signer(make_cfg(tmp_path))
    assert signer is not None
    assert signer.headers("GET", "/x")["KALSHI-ACCESS-KEY"] == "kid-1"
