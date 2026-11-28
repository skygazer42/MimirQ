from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.identity.workspaces import TenantGroup


def _build_auth_headers(cfg: dict) -> dict[str, str]:
    auth = cfg.get("auth")
    if not isinstance(auth, dict):
        return {}
    auth_type = str(auth.get("type") or "none").strip().lower()
    if auth_type == "cookie":
        cookie = auth["cookie"].strip()
        return {"Cookie": cookie} if cookie else {}
    if auth_type == "bearer":
        token = auth["token"].strip()
        return {"Authorization": f"Bearer {token}"} if token else {}
    if auth_type == "basic":
        username = auth["username"].strip()
        password = auth["password"].strip()
        return _build_basic_auth_header(username, password)
    return {}


def _build_basic_auth_header(username: str, password: str) -> dict[str, str]:
    if not username or not password:
        return {}

    import base64

    raw = f"{username}:{password}".encode("utf-8", "ignore")
    b64 = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {b64}"}


def _is_http_or_https_url(value: str | None) -> bool:
    if value is None:
        return False
    raw = value.strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    scheme = parsed.scheme.strip().lower()
    if scheme not in {"http", "https"}:
        return False
    return bool(parsed.netloc.strip())


def _is_link_href_allowed(value: str | None) -> bool:
    if value is None:
        return False
    raw = value.strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    scheme = parsed.scheme.strip().lower()
    if scheme in {"http", "https"}:
        return bool(parsed.netloc.strip())
    if scheme == "mailto":
        return bool(parsed.path.strip())
    return False


def _resolve_tenant_group_ids_by_external_id(
    db: Session,
    *,
    tenant_id: UUID,
    external_ids: list[str],
    max_items: int = 200,
) -> set[UUID]:
    ids: list[str] = []
    seen: set[str] = set()
    for raw in external_ids or []:
        ext = raw.strip()
        if not ext or ext in seen:
            continue
        seen.add(ext)
        ids.append(ext[:255])
        if max_items and len(ids) >= max_items:
            break

    if not ids:
        return set()

    rows = (
        db.query(TenantGroup.id)
        .filter(
            TenantGroup.tenant_id == tenant_id,
            TenantGroup.external_id.in_(ids),
        )
        .all()
    )
    return {row[0] for row in rows if row and row[0]}
