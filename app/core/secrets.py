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


def _fernet_for_secret_key(secret_key: str) -> Fernet:
    # Derive a stable 32-byte key from a SECRET_KEY string.
    raw = (secret_key or "").encode("utf-8", "ignore")
    digest = hashlib.sha256(raw).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def _fernet() -> Fernet:
    return _fernet_for_secret_key(settings.SECRET_KEY or "")


def _fallback_fernets() -> list[Fernet]:
    """
    Optional fallback keys for decrypting secrets encrypted with previous SECRET_KEY values.
    """
    raw = str(getattr(settings, "SECRET_KEY_FALLBACKS", "") or "").strip()
    if not raw:
        return []
    current = str(settings.SECRET_KEY or "").strip()
    out: list[Fernet] = []
    for item in raw.split(","):
        key = str(item or "").strip()
        if not key or key == current:
            continue
        out.append(_fernet_for_secret_key(key))
        # Keep bounded to avoid pathological configs.
        if len(out) >= 5:
            break
    return out


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
    # Try current key first, then fallbacks.
    for f in [_fernet(), *_fallback_fernets()]:
        try:
            return f.decrypt(token.encode("utf-8", "ignore")).decode("utf-8", "ignore")
        except InvalidToken:
            continue
    raise ValueError("invalid_encrypted_secret")


def redact_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Best-effort redaction for connector config fields.

    This is used for API responses; it should never raise.
    """
    if not isinstance(config, dict):
        return {}

    out: Dict[str, Any] = dict(config)
    # Common top-level secret fields (e.g. DB connectors).
    if "password" in out and out.get("password"):
        out["password"] = "<redacted>"
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
    # Common top-level secret fields (e.g. DB connectors).
    if "password" in out:
        out["password"] = encrypt_secret(out.get("password"))  # type: ignore[assignment]
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
    # Common top-level secret fields (e.g. DB connectors).
    if "password" in out:
        out["password"] = decrypt_secret(out.get("password"))  # type: ignore[assignment]
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
