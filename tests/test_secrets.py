"""Credential scope resolution and the read-only / full-access split."""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from thorp.common.secrets import (
    CredentialScope,
    load_env_file,
    require_credential,
    resolve_credential,
)

RO_ID = "THORP_KALSHI_READONLY_KEY_ID"
RO_KEY = "THORP_KALSHI_READONLY_PRIVATE_KEY"
FULL_ID = "THORP_KALSHI_FULL_KEY_ID"
FULL_KEY = "THORP_KALSHI_FULL_PRIVATE_KEY"
ALL_VARS = (RO_ID, RO_KEY, FULL_ID, FULL_KEY)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)


def pem_file(tmp_path: Path, name: str = "k.pem") -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / name
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path


def test_load_env_file_sets_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / "kalshi.env"
    env.write_text(
        '# a comment\n\nTHORP_KALSHI_READONLY_KEY_ID="ro-123"\n'
        "THORP_KALSHI_READONLY_PRIVATE_KEY = secrets/ro.pem\n"
    )
    assert load_env_file(env) == 2
    import os

    assert os.environ[RO_ID] == "ro-123"
    assert os.environ[RO_KEY] == "secrets/ro.pem"


def test_load_env_file_does_not_override_real_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(RO_ID, "from-real-env")
    env = tmp_path / "kalshi.env"
    env.write_text('THORP_KALSHI_READONLY_KEY_ID="from-file"\n')
    load_env_file(env)
    import os

    assert os.environ[RO_ID] == "from-real-env"  # real env wins


def test_load_env_file_missing_is_noop(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "nope.env") == 0


def test_resolve_none_when_unset() -> None:
    assert resolve_credential(CredentialScope.READ_ONLY) is None


def test_resolve_readonly_from_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = pem_file(tmp_path)
    monkeypatch.setenv(RO_ID, "ro-key")
    monkeypatch.setenv(RO_KEY, str(path))
    cred = resolve_credential(CredentialScope.READ_ONLY)
    assert cred is not None
    assert cred.scope is CredentialScope.READ_ONLY
    assert cred.api_key_id == "ro-key"
    assert b"PRIVATE KEY" in cred.private_key_pem
    assert cred.source == str(path)


def test_resolve_inline_pem(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pem = pem_file(tmp_path).read_bytes().decode()
    monkeypatch.setenv(FULL_ID, "full-key")
    monkeypatch.setenv(FULL_KEY, pem.replace("\n", "\\n"))  # single-line inline form
    cred = resolve_credential(CredentialScope.FULL_ACCESS)
    assert cred is not None
    assert cred.source == "<inline>"
    assert b"BEGIN" in cred.private_key_pem and b"\n" in cred.private_key_pem


def test_scopes_are_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RO_ID, "ro")
    monkeypatch.setenv(RO_KEY, str(pem_file(tmp_path, "ro.pem")))
    # Full-access is NOT configured, so a full-access request yields nothing
    # even though a read-only key is present — they never substitute.
    assert resolve_credential(CredentialScope.FULL_ACCESS) is None
    assert resolve_credential(CredentialScope.READ_ONLY) is not None


def test_half_configured_credential_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RO_ID, "ro")  # id set, key material missing
    with pytest.raises(ValueError, match="incomplete"):
        resolve_credential(CredentialScope.READ_ONLY)


def test_missing_pem_path_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RO_ID, "ro")
    monkeypatch.setenv(RO_KEY, "/no/such/key.pem")
    with pytest.raises(FileNotFoundError):
        resolve_credential(CredentialScope.READ_ONLY)


def test_require_credential_raises_when_absent() -> None:
    with pytest.raises(ValueError, match="no full_access"):
        require_credential(CredentialScope.FULL_ACCESS)
