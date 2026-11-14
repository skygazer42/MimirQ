"""Shared token and tenant parsing for Dify HTTP authentication."""

import hashlib
import hmac
import re
from uuid import UUID

from fastapi import HTTPException

_TOKEN_SPLIT_RE = re.compile(r"[,\s]+")


def _split_items(raw: str) -> list[str]:
    return [part for part in _TOKEN_SPLIT_RE.split(raw.strip()) if part]


def _token_matches(provided_token: str, expected_token: str) -> bool:
    if expected_token.lower().startswith("sha256:"):
        digest = expected_token.split(":", 1)[1].strip().lower()
        provided_digest = hashlib.sha256(provided_token.encode("utf-8", "ignore")).hexdigest()
        return hmac.compare_digest(provided_digest, digest)
    return hmac.compare_digest(provided_token, expected_token)


def _extract_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise HTTPException(status_code=401, detail="Invalid Dify Authorization header")
    raw = authorization.strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Dify Authorization header")
    token = raw[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid Dify Authorization header")
    return token


def _coerce_uuid(value: object, *, label: str) -> UUID:
    if value is None:
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    try:
        return UUID(str(value).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}") from exc
