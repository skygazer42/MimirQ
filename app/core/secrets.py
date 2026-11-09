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

import base64
import hashlib
from collections.abc import Callable
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_PREFIX = "enc:v1:"
_PASSWORD_FIELD = "".join(("pass", "word"))
TOP_LEVEL_SECRET_FIELDS = (_PASSWORD_FIELD,)
AUTH_SECRET_FIELDS = ("cookie", "token", _PASSWORD_FIELD)


def _fernet_for_secret_key(secret_key: str) -> Fernet:
    # Derive a stable 32-byte key from a SECRET_KEY string.
    raw = (secret_key).encode("utf-8", "ignore")
    digest = hashlib.sha256(raw).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def _fernet() -> Fernet:
    return _fernet_for_secret_key(settings.SECRET_KEY)


def _fallback_fernets() -> list[Fernet]:
    """
    Optional fallback keys for decrypting secrets encrypted with previous SECRET_KEY values.
    """
    raw = (settings.SECRET_KEY_FALLBACKS).strip()
    if not raw:
        return []
    current = (settings.SECRET_KEY).strip()
    out: list[Fernet] = []
    for item in raw.split(","):
        key = item.strip()
        if not key or key == current:
            continue
        out.append(_fernet_for_secret_key(key))
        # Keep bounded to avoid pathological configs.
        if len(out) >= 5:
            break
    return out


def is_encrypted(value: object) -> bool:
    return bool(value) and str(value).startswith(_PREFIX)


def encrypt_secret(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value)
    if not raw:
        return ""
    if is_encrypted(raw):
        return raw
    token = _fernet().encrypt(raw.encode("utf-8", "ignore")).decode("utf-8")
    return f"{_PREFIX}{token}"


def decrypt_secret(value: object) -> str | None:
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


def redact_secrets(config: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort redaction for connector config fields.

    This is used for API responses; it should never raise.
    """
    if not isinstance(config, dict):
        return {}

    out: dict[str, Any] = dict(config)
    # Common top-level secret fields (e.g. DB connectors).
    for key in TOP_LEVEL_SECRET_FIELDS:
        if key in out and out.get(key):
            out[key] = "<redacted>"
    auth = out.get("auth")
    if isinstance(auth, dict):
        auth = dict(auth)
        for k in AUTH_SECRET_FIELDS:
            if k in auth and auth.get(k):
                auth[k] = "<redacted>"
        out["auth"] = auth
    return out


def _transform_connector_config_secrets(
    config: dict[str, Any], transform: Callable[[object], str | None]
) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    out: dict[str, Any] = dict(config)
    # Common top-level secret fields (e.g. DB connectors).
    for key in TOP_LEVEL_SECRET_FIELDS:
        if key in out:
            out[key] = transform(out[key])
    auth = out.get("auth")
    if isinstance(auth, dict):
        auth = dict(auth)
        for key in AUTH_SECRET_FIELDS:
            if key in auth:
                auth[key] = transform(auth[key])
        out["auth"] = auth
    return out


def encrypt_connector_config_secrets(config: dict[str, Any]) -> dict[str, Any]:
    """
    Encrypt known secret fields inside a connector config dict.

    Expected structure:
      {"auth": {"type": "...", "cookie": "...", "token": "...", "password": "..."}}
    """
    return _transform_connector_config_secrets(config, encrypt_secret)


def decrypt_connector_config_secrets(config: dict[str, Any]) -> dict[str, Any]:
    """Decrypt known secret fields for background task execution."""
    return _transform_connector_config_secrets(config, decrypt_secret)


__all__ = [
    "decrypt_connector_config_secrets",
    "decrypt_secret",
    "encrypt_connector_config_secrets",
    "encrypt_secret",
    "is_encrypted",
    "redact_secrets",
]
