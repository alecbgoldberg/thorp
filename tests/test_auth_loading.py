"""Key loading from PEM files and the entrypoint's env-based signer wiring."""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from thorp.recorder.__main__ import _build_signer
from thorp.recorder.config import RecorderConfig
from thorp.recorder.kalshi.auth import KalshiSigner

CFG = RecorderConfig(
    data_dir=Path("data/raw"),
    environment="demo",
    series_tickers=("X",),
    rest_url="https://x",
    ws_url="wss://x",
)


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CFG.api_key_id_env, raising=False)
    monkeypatch.delenv(CFG.private_key_path_env, raising=False)
    assert _build_signer(CFG) is None


def test_build_signer_loads_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "key.pem"
    path.write_bytes(pem_bytes(key))
    monkeypatch.setenv(CFG.api_key_id_env, "kid-1")
    monkeypatch.setenv(CFG.private_key_path_env, str(path))
    signer = _build_signer(CFG)
    assert signer is not None
    assert signer.headers("GET", "/x")["KALSHI-ACCESS-KEY"] == "kid-1"
