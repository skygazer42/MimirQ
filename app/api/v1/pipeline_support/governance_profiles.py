"""Governance-profile row mapping, resolution, and import helpers.

Extracted verbatim from ``app/api/v1/pipeline.py`` (built-in profile lookups are
passed in via ``builtin_by_key`` instead of reading the pipeline module's
import-time snapshot). Submodules must not import ``app.api.v1.pipeline``.
"""
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas.governance_profile import (
    GovernanceProfileOut,
    GovernanceProfilePayload,
    GovernanceProfileSummary,
)
from app.core.regex_safety import RegexRulesValidationError
from app.models.governance_profile import GovernanceProfile as DBGovernanceProfile
from app.services.governance_profiles import (
    builtin_profile_to_out,
    validate_and_normalize_payload,
    validate_profile_key,
)

GOVERNANCE_PROFILE_NOT_FOUND_DETAIL = "Governance profile not found"


def _profile_key_for_row(row: DBGovernanceProfile) -> str:
    raw = str(getattr(row, "key", "") or "").strip()
    if raw:
        return raw
    return f"custom:{str(row.id)}"


def _profile_summary_from_row(row: DBGovernanceProfile) -> GovernanceProfileSummary:
    return GovernanceProfileSummary(
        id=row.id,
        key=_profile_key_for_row(row),
        name=str(getattr(row, "name", "") or ""),
        description=getattr(row, "description", None),
        is_system=bool(getattr(row, "is_system", False)),
    )


def _profile_out_from_row(row: DBGovernanceProfile) -> GovernanceProfileOut:
    payload_raw = getattr(row, "payload", None)
    if not isinstance(payload_raw, dict):
        payload_raw = {}
    payload = GovernanceProfilePayload(**payload_raw)
    return GovernanceProfileOut(
        id=row.id,
        key=_profile_key_for_row(row),
        name=str(getattr(row, "name", "") or ""),
        description=getattr(row, "description", None),
        is_system=bool(getattr(row, "is_system", False)),
        payload=payload,
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


def _resolve_profile_ref(
    *,
    db: Session,
    tenant_id: UUID,
    profile_ref: str,
    builtin_by_key: dict[str, Any],
) -> GovernanceProfileOut:
    ref = str(profile_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="profile_ref is required")

    if ref in builtin_by_key:
        return builtin_profile_to_out(builtin_by_key[ref])

    # Allow UUID lookup.
    try:
        ref_uuid = UUID(ref)
    except Exception:
        ref_uuid = None

    q = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    if ref_uuid is not None:
        row = q.filter(DBGovernanceProfile.id == ref_uuid).first()
        if row is not None:
            return _profile_out_from_row(row)
    # Allow key lookup (tenant-scoped).
    row = q.filter(DBGovernanceProfile.key == ref).first()
    if row is not None:
        return _profile_out_from_row(row)

    raise HTTPException(status_code=404, detail=GOVERNANCE_PROFILE_NOT_FOUND_DETAIL)


def _resolve_custom_profile_row(
    *,
    db: Session,
    tenant_id: UUID,
    profile_ref: str,
    builtin_by_key: dict[str, Any],
) -> DBGovernanceProfile:
    ref = str(profile_ref or "").strip()
    if ref in builtin_by_key:
        raise HTTPException(status_code=403, detail="built-in profiles are read-only")

    try:
        ref_uuid = UUID(ref)
    except Exception:
        ref_uuid = None

    q = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    row = q.filter(DBGovernanceProfile.id == ref_uuid).first() if ref_uuid else q.filter(DBGovernanceProfile.key == ref).first()
    if row is None:
        raise HTTPException(status_code=404, detail=GOVERNANCE_PROFILE_NOT_FOUND_DETAIL)
    return row


@dataclass
class _GovernanceProfileImportRecord:
    name: str
    key: str | None
    description: str | None
    payload: GovernanceProfilePayload


async def _read_governance_profile_import_json(file: UploadFile) -> object:
    max_bytes = 256 * 1024
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Profile script too large (max={max_bytes} bytes)")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON file") from exc


def _raw_governance_profile_import_items(data: object) -> list[object]:
    if isinstance(data, dict) and isinstance(data.get("profiles"), list):
        return list(data.get("profiles") or [])
    return [data]


def _reject_unknown_import_keys(item: dict[str, object], allowed: set[str], *, label: str) -> None:
    unknown_keys = set(item.keys()) - allowed
    if unknown_keys:
        unknown_sorted = ", ".join(sorted(map(str, unknown_keys))[:20])
        raise HTTPException(status_code=400, detail=f"Unknown {label} fields: {unknown_sorted}")


def _normalize_governance_profile_import_record(item: object) -> _GovernanceProfileImportRecord:
    if not isinstance(item, dict):
        raise HTTPException(status_code=400, detail="Invalid profile item (expected object)")

    _reject_unknown_import_keys(item, {"name", "description", "key", "payload"}, label="profile")
    name = str(item.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")

    try:
        key = validate_profile_key(item.get("key"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload_raw = item.get("payload")
    if not isinstance(payload_raw, dict):
        raise HTTPException(status_code=400, detail="payload is required and must be an object")

    _reject_unknown_import_keys(
        payload_raw,
        {"version", "extends", "input_formats", "pipeline_patch", "regex_rules", "processing_scripts"},
        label="payload",
    )
    try:
        payload = GovernanceProfilePayload(**payload_raw)
        payload = validate_and_normalize_payload(payload)
    except RegexRulesValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(exc)[:200]}") from exc

    description = item.get("description")
    desc = str(description or "").strip()[:2000] if description is not None else None
    return _GovernanceProfileImportRecord(name=name, key=key, description=desc, payload=payload)


def _find_existing_governance_profile(
    db: Session,
    tenant_id: UUID,
    key: str | None,
) -> DBGovernanceProfile | None:
    if not key:
        return None
    return (
        db.query(DBGovernanceProfile)
        .filter(DBGovernanceProfile.tenant_id == tenant_id, DBGovernanceProfile.key == key)
        .first()
    )


def _upsert_governance_profile_import_record(
    *,
    db: Session,
    tenant_id: UUID,
    record: _GovernanceProfileImportRecord,
    overwrite: bool,
) -> tuple[int, int, GovernanceProfileSummary]:
    existing = _find_existing_governance_profile(db, tenant_id, record.key)
    if existing is not None:
        if not overwrite:
            raise HTTPException(status_code=409, detail=f"Profile key already exists: {record.key}")
        existing.name = record.name[:200]
        existing.description = record.description
        existing.payload = record.payload.model_dump()
        return 0, 1, _profile_summary_from_row(existing)

    row = DBGovernanceProfile(
        tenant_id=tenant_id,
        key=record.key,
        name=record.name[:200],
        description=record.description,
        is_system=False,
        payload=record.payload.model_dump(),
    )
    db.add(row)
    db.flush()
    return 1, 0, _profile_summary_from_row(row)
