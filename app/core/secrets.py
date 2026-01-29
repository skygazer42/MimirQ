"""
Small symmetric encryption helpers for storing short-lived secrets in DB JSON fields.

Use-cases:
- Connector configs that require cookies/tokens/passwords for authenticated crawling.

Security notes:
- Secrets are encrypted at rest using a key derived from settings.SECRET_KEY.
- This is best-effort: it avoids storing plaintext secrets in JSONB and prevents
  accidental leaks via API responses/logging.
- Rotating SECRET_KEY will make previously stored encrypted secrets undecryptable.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any, Dict

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    # Derive a stable 32-byte key from SECRET_KEY.
    raw = (settings.SECRET_KEY or "").encode("utf-8", "ignore")
    digest = hashlib.sha256(raw).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def is_encrypted(value: str | None) -> bool:
    return bool(value) and str(value).startswith(_PREFIX)


def encrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value)
    if not raw:
        return ""
    if is_encrypted(raw):
        return raw
    token = _fernet().encrypt(raw.encode("utf-8", "ignore")).decode("utf-8")
    return f"{_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value)
    if not raw:
        return ""
    if not is_encrypted(raw):
        return raw
    token = raw[len(_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("utf-8", "ignore")).decode("utf-8", "ignore")
    except InvalidToken as exc:
        raise ValueError("invalid_encrypted_secret") from exc


def redact_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Best-effort redaction for connector config fields.

    This is used for API responses; it should never raise.
    """
    if not isinstance(config, dict):
        return {}

    out: Dict[str, Any] = dict(config)
    auth = out.get("auth")
    if isinstance(auth, dict):
        auth = dict(auth)
        for k in ("cookie", "token", "password"):
            if k in auth and auth.get(k):
                auth[k] = "<redacted>"
        out["auth"] = auth
    return out


def encrypt_connector_config_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Encrypt known secret fields inside a connector config dict.

    Expected structure:
      {"auth": {"type": "...", "cookie": "...", "token": "...", "password": "..."}}
    """
    if not isinstance(config, dict):
        return {}
    out: Dict[str, Any] = dict(config)
    auth = out.get("auth")
    if isinstance(auth, dict):
        auth = dict(auth)
        if "cookie" in auth:
            auth["cookie"] = encrypt_secret(auth.get("cookie"))  # type: ignore[assignment]
        if "token" in auth:
            auth["token"] = encrypt_secret(auth.get("token"))  # type: ignore[assignment]
        if "password" in auth:
            auth["password"] = encrypt_secret(auth.get("password"))  # type: ignore[assignment]
        out["auth"] = auth
    return out


def decrypt_connector_config_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decrypt known secret fields inside a connector config dict.

    This is used at runtime in background tasks.
    """
    if not isinstance(config, dict):
        return {}
    out: Dict[str, Any] = dict(config)
    auth = out.get("auth")
    if isinstance(auth, dict):
        auth = dict(auth)
        if "cookie" in auth:
            auth["cookie"] = decrypt_secret(auth.get("cookie"))  # type: ignore[assignment]
        if "token" in auth:
            auth["token"] = decrypt_secret(auth.get("token"))  # type: ignore[assignment]
        if "password" in auth:
            auth["password"] = decrypt_secret(auth.get("password"))  # type: ignore[assignment]
        out["auth"] = auth
    return out


__all__ = [
    "decrypt_connector_config_secrets",
    "decrypt_secret",
    "encrypt_connector_config_secrets",
    "encrypt_secret",
    "is_encrypted",
    "redact_secrets",
]

