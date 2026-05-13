from __future__ import annotations

import contextlib
import hashlib
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.models.tenant_group import TenantGroup

_DRIVE_FILE_ID_FROM_PATH_RE = None


def _drive_file_id_pattern():
    global _DRIVE_FILE_ID_FROM_PATH_RE
    if _DRIVE_FILE_ID_FROM_PATH_RE is None:
        import re

        _DRIVE_FILE_ID_FROM_PATH_RE = re.compile(r"/file/d/([^/]+)")
    return _DRIVE_FILE_ID_FROM_PATH_RE


def _build_auth_headers(cfg: dict) -> dict[str, str]:
    auth = cfg.get("auth") if isinstance(cfg.get("auth"), dict) else None
    if not isinstance(auth, dict):
        return {}
    auth_type = str(auth.get("type") or "none").strip().lower()
    if auth_type == "cookie":
        cookie = str(auth.get("cookie") or "").strip()
        return {"Cookie": cookie} if cookie else {}
    if auth_type == "bearer":
        token = str(auth.get("token") or "").strip()
        return {"Authorization": f"Bearer {token}"} if token else {}
    if auth_type == "basic":
        username = str(auth.get("username") or "").strip()
        password = str(auth.get("password") or "").strip()
        return _build_basic_auth_header(username, password)
    return {}


def _build_basic_auth_header(username: str, password: str) -> dict[str, str]:
    if not username or not password:
        return {}

    import base64

    raw = f"{username}:{password}".encode("utf-8", "ignore")
    b64 = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {b64}"}


def _is_http_or_https_url(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        return False
    return bool(str(parsed.netloc or "").strip())


def _is_link_href_allowed(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme in {"http", "https"}:
        return bool(str(parsed.netloc or "").strip())
    if scheme == "mailto":
        return bool(str(parsed.path or "").strip())
    return False


def _extract_drive_file_id(url: str) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None

    host = (parsed.netloc or "").strip().lower()
    if host not in {"drive.google.com", "docs.google.com"}:
        return None

    qs = parse_qs(parsed.query or "")
    if "id" in qs and qs["id"]:
        fid = str(qs["id"][0] or "").strip()
        return fid or None

    match = _drive_file_id_pattern().search(parsed.path or "")
    if match:
        fid = str(match.group(1) or "").strip()
        return fid or None
    return None


def _drive_direct_download_url(file_id: str) -> str:
    fid = str(file_id or "").strip()
    if not fid:
        raise ValueError("drive_file_id_required")
    return f"https://drive.google.com/uc?export=download&id={fid}"


def _drive_source_ref(*, file_id: str | None, source_url: str) -> str:
    fid = str(file_id or "").strip()
    if fid:
        return fid

    raw_url = str(source_url or "").strip()
    digest = hashlib.sha256(raw_url.encode("utf-8", "ignore")).hexdigest()
    return f"url:{digest}"


def _drive_fallback_sync_token(*, file_id: str | None, source_url: str) -> str:
    fid = str(file_id or "").strip()
    raw_url = str(source_url or "").strip()
    seed = f"file_id:{fid}|url:{raw_url}"
    digest = hashlib.sha256(seed.encode("utf-8", "ignore")).hexdigest()
    return f"hash:{digest}"


async def _drive_fetch_file_sync_token(
    *,
    client: httpx.AsyncClient | None,
    file_id: str,
    source_url: str,
    headers: dict[str, str] | None = None,
) -> str:
    fid = str(file_id or "").strip()
    fallback = _drive_fallback_sync_token(file_id=fid, source_url=source_url)
    if not fid or client is None:
        return fallback

    url = f"https://www.googleapis.com/drive/v3/files/{quote(fid, safe='')}"
    params = {
        "fields": "id,version,modifiedTime",
        "supportsAllDrives": "true",
    }
    try:
        resp = await client.get(url, params=params, headers=dict(headers or {}))
        if int(resp.status_code or 0) >= 400:
            return fallback
        payload = resp.json() if callable(getattr(resp, "json", None)) else {}
    except Exception:
        return fallback

    data = payload if isinstance(payload, dict) else {}
    version = str(data.get("version") or "").strip()
    modified_time = str(data.get("modifiedTime") or "").strip()
    resolved_file_id = str(data.get("id") or fid).strip() or fid
    if not version and not modified_time:
        return fallback

    parts: list[str] = []
    if version:
        parts.append(f"version:{version}")
    if modified_time:
        parts.append(f"modified_time:{modified_time}")
    parts.append(f"file_id:{resolved_file_id}")
    return "|".join(parts)


def _drive_group_principal_key(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized:
        return ""
    return f"drive:group:{normalized}"[:255]


def _drive_permission_external_ids_and_anyone(
    perms: object,
) -> tuple[list[str], bool]:
    ext_ids: list[str] = []
    has_anyone = False
    seen_ext: set[str] = set()

    for permission in perms or []:
        if not isinstance(permission, dict):
            continue
        if bool(permission.get("deleted", False)):
            continue

        permission_type = str(permission.get("type") or "").strip().lower()
        if permission_type == "anyone":
            has_anyone = True
            continue
        if permission_type != "group":
            continue

        key = _drive_group_principal_key(str(permission.get("emailAddress") or ""))
        if key and key not in seen_ext:
            seen_ext.add(key)
            ext_ids.append(key)
            if len(ext_ids) >= 200:
                break

    return ext_ids, has_anyone


async def _drive_fetch_file_permissions(
    *,
    client: httpx.AsyncClient,
    file_id: str,
    headers: dict[str, str],
    max_items: int = 500,
) -> list[dict[str, Any]]:
    fid = str(file_id or "").strip()
    if not fid:
        return []

    url = f"https://www.googleapis.com/drive/v3/files/{quote(fid, safe='')}/permissions"
    params = {
        "fields": "permissions(type,role,emailAddress,domain,deleted)",
        "supportsAllDrives": "true",
    }
    resp = await client.get(url, params=params, headers=headers)
    if int(resp.status_code or 0) >= 400:
        raise RuntimeError(f"drive api failed (status={resp.status_code})")

    data = resp.json()
    perms = data.get("permissions") if isinstance(data, dict) else None
    items = perms if isinstance(perms, list) else []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(dict(item))
        if max_items and len(out) >= max_items:
            break
    return out


def _github_raw_url(*, owner: str, repo: str, branch: str, path: str) -> str:
    org = str(owner or "").strip()
    repo_name = str(repo or "").strip()
    branch_name = str(branch or "").strip() or "main"
    file_path = str(path or "").lstrip("/").strip()
    if not org or not repo_name or not file_path:
        raise ValueError("invalid_github_raw_url_parts")
    return (
        f"https://raw.githubusercontent.com/{org}/{repo_name}/"
        f"{quote(branch_name, safe='')}/{quote(file_path, safe='/')}"
    )


def _github_team_principal_key(*, org: str, team_slug: str) -> str:
    normalized_org = str(org or "").strip()
    normalized_slug = str(team_slug or "").strip()
    if not normalized_org or not normalized_slug:
        return ""
    return f"github:team:{normalized_org.lower()}/{normalized_slug.lower()}"[:255]


def _parse_link_header_next(link_header: str | None) -> str | None:
    raw = str(link_header or "").strip()
    if not raw:
        return None
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        if 'rel="next"' not in candidate and "rel=next" not in candidate:
            continue
        if "<" in candidate and ">" in candidate:
            start = candidate.find("<")
            end = candidate.find(">", start + 1)
            if start >= 0 and end > start:
                next_url = candidate[start + 1 : end].strip()
                return next_url or None
    return None


def _github_team_principal_key_from_repo_team_item(
    item: object,
    *,
    owner: str,
) -> str:
    if not isinstance(item, dict):
        return ""

    slug = str(item.get("slug") or "").strip()
    if not slug:
        return ""

    org_login = ""
    org_obj = item.get("organization")
    if isinstance(org_obj, dict):
        org_login = str(org_obj.get("login") or "").strip()
    if not org_login:
        org_login = str(owner or "").strip()

    return _github_team_principal_key(org=org_login, team_slug=slug)


async def _github_fetch_repo_team_principal_keys(
    *,
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    headers: dict[str, str],
    max_pages: int = 3,
    max_items: int = 200,
) -> list[str]:
    org = str(owner or "").strip()
    repo_name = str(repo or "").strip()
    if not org or not repo_name:
        return []

    url = (
        f"https://api.github.com/repos/{quote(org, safe='')}/"
        f"{quote(repo_name, safe='')}/teams?per_page=100"
    )
    out: list[str] = []
    seen: set[str] = set()

    for _page in range(max(1, min(int(max_pages or 0), 10))):
        resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            return out
        data = resp.json()
        items = data if isinstance(data, list) else []
        for item in items:
            key = _github_team_principal_key_from_repo_team_item(item, owner=org)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
            if max_items and len(out) >= max_items:
                return out

        link = None
        with contextlib.suppress(Exception):
            link = resp.headers.get("Link")
        next_url = _parse_link_header_next(link)
        if not next_url:
            break
        url = next_url

    return out


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
        ext = str(raw or "").strip()
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
