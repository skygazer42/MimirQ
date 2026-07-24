import secrets
import threading
import time
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.schemas.auth import SamlExchangeResponse, TokenResponse, UserPublic
from app.core.config import settings
from app.core.redis_client import LazyRedisClient

_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={"decode_responses": False},
    enabled=lambda: bool(getattr(settings, "SAML_REPLAY_REDIS_ENABLED", False)),
    skip_empty_url=True,
    strip_url=True,
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate
_memory_lock = threading.Lock()
_memory_bridges: dict[str, tuple[float, bytes]] = {}
_BRIDGE_TTL_SEC = 60
_REDIS_POP_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if value then
  redis.call('DEL', KEYS[1])
end
return value
"""


class SamlBridgeSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    expires_in: int
    token_type: str = "bearer"
    user: dict[str, Any]
    return_to: str = "/"


def saml_bridge_session_from_exchange(response: SamlExchangeResponse) -> SamlBridgeSession:
    return SamlBridgeSession(
        access_token=response.token.access_token,
        expires_in=int(response.token.expires_in),
        token_type=str(response.token.token_type or "bearer"),
        user=response.user.model_dump(mode="json"),
        return_to=str(response.return_to or "/") or "/",
    )


def saml_bridge_session_to_exchange(session: SamlBridgeSession) -> SamlExchangeResponse:
    return SamlExchangeResponse(
        user=UserPublic.model_validate(session.user),
        token=TokenResponse(
            access_token=session.access_token,
            expires_in=int(session.expires_in),
            token_type=str(session.token_type or "bearer"),
        ),
        return_to=str(session.return_to or "/") or "/",
    )


def _ttl_sec_for(session: SamlBridgeSession) -> int:
    expires_in = max(1, int(session.expires_in or 0))
    return max(1, min(_BRIDGE_TTL_SEC, expires_in))


def _bridge_key(code: str) -> str:
    return f"saml:bridge:{code}"


def _issue_in_memory(code: str, payload: bytes, ttl_sec: int) -> None:
    now = time.monotonic()
    with _memory_lock:
        expired = [key for key, (expires_at, _payload) in _memory_bridges.items() if expires_at <= now]
        for key in expired:
            _memory_bridges.pop(key, None)
        _memory_bridges[_bridge_key(code)] = (now + float(ttl_sec), payload)


def _consume_in_memory(code: str) -> bytes | None:
    now = time.monotonic()
    key = _bridge_key(code)
    with _memory_lock:
        expired = [expired_key for expired_key, (expires_at, _payload) in _memory_bridges.items() if expires_at <= now]
        for expired_key in expired:
            _memory_bridges.pop(expired_key, None)
        stored = _memory_bridges.pop(key, None)
    if stored is None:
        return None
    expires_at, payload = stored
    if expires_at <= now:
        return None
    return payload


def issue_saml_bridge_session(session: SamlBridgeSession) -> str:
    payload = session.model_dump_json().encode("utf-8")
    ttl_sec = _ttl_sec_for(session)
    redis_enabled = bool(getattr(settings, "SAML_REPLAY_REDIS_ENABLED", False))

    for _ in range(4):
        code = secrets.token_urlsafe(24)
        if not redis_enabled:
            _issue_in_memory(code, payload, ttl_sec)
            return code

        client = _get_redis_client()
        if client is None:
            raise HTTPException(status_code=503, detail="SAML bridge unavailable")
        try:
            stored = client.set(_bridge_key(code), payload, ex=ttl_sec, nx=True)
        except Exception as exc:  # noqa: BLE001
            _invalidate_redis_client()
            raise HTTPException(status_code=503, detail="SAML bridge unavailable") from exc
        if stored:
            return code

    raise HTTPException(status_code=503, detail="SAML bridge unavailable")


def consume_saml_bridge_session(code: str) -> SamlBridgeSession:
    normalized = str(code or "").strip()
    if not normalized:
        raise HTTPException(status_code=401, detail="Invalid SAML bridge session")

    redis_enabled = bool(getattr(settings, "SAML_REPLAY_REDIS_ENABLED", False))
    if not redis_enabled:
        payload = _consume_in_memory(normalized)
    else:
        client = _get_redis_client()
        if client is None:
            raise HTTPException(status_code=503, detail="SAML bridge unavailable")
        try:
            payload = client.eval(_REDIS_POP_SCRIPT, 1, _bridge_key(normalized))
        except Exception as exc:  # noqa: BLE001
            _invalidate_redis_client()
            raise HTTPException(status_code=503, detail="SAML bridge unavailable") from exc

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid SAML bridge session")

    raw = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
    try:
        return SamlBridgeSession.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid SAML bridge session") from exc


__all__ = [
    "SamlBridgeSession",
    "consume_saml_bridge_session",
    "issue_saml_bridge_session",
    "saml_bridge_session_from_exchange",
    "saml_bridge_session_to_exchange",
]
