"""Credential loading with a hard read-only / full-access split.

Two Kalshi API keys, never interchangeable (see secrets/README.md):

- ``READ_ONLY``   — Kalshi ``read`` scope only. Cannot place orders at the
  venue level (no ``write::trade``). Used by the Recorder and every SIMULATION
  / BACKTEST path. Even a bug that tries to submit an order gets a 403 from
  Kalshi, on top of the type-level ``ShadowVenue`` guarantee (Doc 3 §4).
- ``FULL_ACCESS`` — ``read`` + ``write::trade`` (never ``write::transfer`` /
  withdraw). Used only by ``KalshiLiveVenue`` in CANARY / PRODUCTION.

``require_credential`` is the enforcement point: SIMULATION asking for
``FULL_ACCESS`` (or vice versa) is a programming error, and the caller passes
the scope its run mode is allowed to use — so the wrong key can never be loaded
by accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class CredentialScope(Enum):
    READ_ONLY = "read_only"
    FULL_ACCESS = "full_access"


# Env var names per scope: (key-id var, private-key var). The private-key var
# may hold either a filesystem path to a .pem or the PEM text itself.
_ENV_VARS: dict[CredentialScope, tuple[str, str]] = {
    CredentialScope.READ_ONLY: (
        "THORP_KALSHI_READONLY_KEY_ID",
        "THORP_KALSHI_READONLY_PRIVATE_KEY",
    ),
    CredentialScope.FULL_ACCESS: (
        "THORP_KALSHI_FULL_KEY_ID",
        "THORP_KALSHI_FULL_PRIVATE_KEY",
    ),
}

DEFAULT_SECRETS_FILE = Path("secrets/kalshi.env")


@dataclass(frozen=True)
class KalshiCredential:
    scope: CredentialScope
    api_key_id: str
    private_key_pem: bytes
    source: str  # for error messages / logging (path or "<inline>"), never the key itself


def load_env_file(path: Path, override: bool = False) -> int:
    """Load ``KEY=VALUE`` lines into ``os.environ``. Returns count set.

    Real environment variables win over the file unless ``override`` is set, so
    a CI/host-provided secret is never silently shadowed by a checked-out file.
    Missing file is a no-op (returns 0) — credentials may come from the real
    environment instead.
    """
    if not path.exists():
        return 0
    count = 0
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or (not override and key in os.environ):
            continue
        os.environ[key] = value
        count += 1
    return count


def resolve_credential(scope: CredentialScope) -> KalshiCredential | None:
    """Build the credential for ``scope`` from the environment, or None.

    Returns None only when neither env var is set (unconfigured). A half-set
    pair — id without key, or key without id — is a configuration error and
    raises, because silently running unauthenticated would be worse.
    """
    id_var, key_var = _ENV_VARS[scope]
    key_id = os.environ.get(id_var)
    key_material = os.environ.get(key_var)
    if not key_id and not key_material:
        return None
    if not key_id or not key_material:
        missing = id_var if not key_id else key_var
        raise ValueError(
            f"incomplete {scope.value} Kalshi credential: {missing} is unset. "
            f"Set both {id_var} and {key_var} (see secrets/README.md)."
        )
    pem, source = _read_key_material(key_material)
    return KalshiCredential(scope=scope, api_key_id=key_id, private_key_pem=pem, source=source)


def require_credential(scope: CredentialScope) -> KalshiCredential:
    cred = resolve_credential(scope)
    if cred is None:
        id_var, key_var = _ENV_VARS[scope]
        raise ValueError(
            f"no {scope.value} Kalshi credential found. Set {id_var} and {key_var} "
            f"(see secrets/README.md); this run mode requires it."
        )
    return cred


def _read_key_material(value: str) -> tuple[bytes, str]:
    """Interpret a private-key env value as inline PEM or a file path."""
    if "BEGIN" in value and "PRIVATE KEY" in value:
        # Inline PEM. A single-line env value uses literal "\n" for newlines.
        return value.replace("\\n", "\n").encode(), "<inline>"
    path = Path(value).expanduser()
    if not path.exists():
        raise FileNotFoundError(
            f"Kalshi private key path does not exist: {path}. "
            f"Point the env var at your .pem file or paste the PEM text directly."
        )
    return path.read_bytes(), str(path)
