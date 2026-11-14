import json
import os
import re
import tempfile
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.config import settings
from app.core.database import get_db
from app.rag.core.evidence_capsule_builder import validate_evidence_capsule
from app.services import dataset_service

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)

_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{5,127}")


class EvidenceCapsulePersistRequest(BaseModel):
    capsule: dict[str, Any]
    capsule_id: str | None = Field(default=None, min_length=6, max_length=128)
    overwrite: bool = False


class EvidenceCapsulePersistResponse(BaseModel):
    capsule_id: str
    capsule_hash: str
    path: str
    overwritten: bool = False


class EvidenceCapsuleGetResponse(BaseModel):
    capsule_id: str
    capsule_hash: str
    capsule: dict[str, Any]


class EvidenceCapsuleVerifyResponse(BaseModel):
    capsule_id: str | None = None
    valid: bool
    reason: str


def _store_dir() -> Path:
    return Path(settings.EVIDENCE_CAPSULE_STORE_DIR).resolve()


def _normalize_capsule_id(value: str) -> str:
    cid = value.strip()
    if not _SAFE_ID_RE.fullmatch(cid):
        raise HTTPException(status_code=400, detail="invalid_capsule_id")
    return cid


def _tenant_store_dir(tenant_id: UUID) -> Path:
    root = _store_dir()
    path = (root / str(tenant_id)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_tenant_id") from exc
    return path


def _capsule_path(*, tenant_id: UUID, capsule_id: str) -> Path:
    root = _tenant_store_dir(tenant_id)
    path = (root / f"{capsule_id}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_capsule_id") from exc
    return path


def _legacy_capsule_path(*, capsule_id: str) -> Path:
    root = _store_dir()
    path = (root / f"{capsule_id}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_capsule_id") from exc
    return path


def _capsule_envelope(*, capsule: dict[str, Any], tenant_id: UUID, capsule_id: str, account_id: str) -> dict[str, Any]:
    bound_tenant_id = str(tenant_id)
    existing_tenant_id = capsule.get("tenant_id")
    if existing_tenant_id is not None and existing_tenant_id != bound_tenant_id:
        raise HTTPException(status_code=400, detail="capsule_tenant_id_mismatch")
    existing_owner_account_id = capsule.get("owner_account_id")
    if existing_owner_account_id is not None and existing_owner_account_id != account_id:
        raise HTTPException(status_code=400, detail="capsule_owner_account_id_mismatch")
    return {
        "tenant_id": bound_tenant_id,
        "owner_account_id": account_id,
        "capsule_id": capsule_id,
        "capsule": capsule,
    }


def _read_capsule_payload(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"capsule_read_failed:{exc.__class__.__name__}") from exc


def _load_authorized_capsule(
    path: Path,
    *,
    tenant_id: UUID,
    account_id: str,
    allow_legacy_raw: bool,
) -> dict[str, Any]:
    payload = _read_capsule_payload(path)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="capsule_invalid_payload")

    if "capsule" in payload:
        capsule = payload["capsule"]
        if not isinstance(capsule, dict):
            raise HTTPException(status_code=500, detail="capsule_invalid_payload")
    elif allow_legacy_raw:
        capsule = payload
    else:
        raise HTTPException(status_code=500, detail="capsule_invalid_payload")
    if payload.get("tenant_id") != str(tenant_id) or payload.get("owner_account_id") != account_id:
        raise HTTPException(status_code=404, detail="capsule_not_found")
    return capsule


def _atomic_create_text(path: Path, content: str) -> bool:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        return False

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise

    return True


def _atomic_replace_text(path: Path, content: str) -> None:
    fd, temp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temp_path, path)
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


@router.post("/capsules", response_model=EvidenceCapsulePersistResponse)
def persist_evidence_capsule(
    body: EvidenceCapsulePersistRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceCapsulePersistResponse:
    if not settings.EVIDENCE_CAPSULE_PERSIST_ENABLED:
        raise HTTPException(status_code=400, detail="EVIDENCE_CAPSULE_PERSIST_ENABLED=false")

    dataset_service.ensure_member(db, tenant_id, account_id)

    strict = settings.EVIDENCE_CAPSULE_STRICT_VALIDATION_ENABLED or settings.EVIDENCE_CAPSULE_VERIFY_HASH_ON_PERSIST
    ok, reason = validate_evidence_capsule(
        body.capsule,
        strict=strict,
        verify_signature=settings.EVIDENCE_CAPSULE_REQUIRE_SIGNATURE_ON_PERSIST,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=f"invalid_capsule:{reason}")

    capsule_hash = body.capsule["capsule_hash"].strip()
    capsule_id = _normalize_capsule_id(body.capsule_id if body.capsule_id is not None else capsule_hash)
    path = _capsule_path(tenant_id=tenant_id, capsule_id=capsule_id)
    legacy_path = _legacy_capsule_path(capsule_id=capsule_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        overwrite_source_path = path
    elif legacy_path.exists():
        overwrite_source_path = legacy_path
    else:
        overwrite_source_path = None

    if overwrite_source_path is not None:
        if not body.overwrite or not settings.EVIDENCE_CAPSULE_ALLOW_OVERWRITE:
            raise HTTPException(status_code=409, detail="capsule_exists")
        _load_authorized_capsule(
            overwrite_source_path,
            tenant_id=tenant_id,
            account_id=account_id,
            allow_legacy_raw=overwrite_source_path == legacy_path,
        )

    payload = _capsule_envelope(
        capsule=body.capsule,
        tenant_id=tenant_id,
        capsule_id=capsule_id,
        account_id=account_id,
    )
    serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    if overwrite_source_path is None:
        if not _atomic_create_text(path, serialized_payload):
            raise HTTPException(status_code=409, detail="capsule_exists")
    else:
        _atomic_replace_text(path, serialized_payload)
    return EvidenceCapsulePersistResponse(
        capsule_id=capsule_id,
        capsule_hash=capsule_hash,
        path=str(path),
        overwritten=overwrite_source_path is not None,
    )


@router.get("/capsules/{capsule_id}", response_model=EvidenceCapsuleGetResponse)
def get_evidence_capsule(
    capsule_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceCapsuleGetResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)
    normalized_id = _normalize_capsule_id(capsule_id)
    path = _capsule_path(tenant_id=tenant_id, capsule_id=normalized_id)
    legacy_path = _legacy_capsule_path(capsule_id=normalized_id)

    if path.exists():
        capsule = _load_authorized_capsule(
            path,
            tenant_id=tenant_id,
            account_id=account_id,
            allow_legacy_raw=False,
        )
    elif legacy_path.exists():
        capsule = _load_authorized_capsule(
            legacy_path,
            tenant_id=tenant_id,
            account_id=account_id,
            allow_legacy_raw=True,
        )
    else:
        raise HTTPException(status_code=404, detail="capsule_not_found")

    return EvidenceCapsuleGetResponse(
        capsule_id=capsule_id,
        capsule_hash=capsule["capsule_hash"],
        capsule=capsule,
    )


@router.post("/capsules/verify", response_model=EvidenceCapsuleVerifyResponse)
def verify_evidence_capsule_payload(
    body: EvidenceCapsulePersistRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceCapsuleVerifyResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)
    ok, reason = validate_evidence_capsule(
        body.capsule,
        strict=settings.EVIDENCE_CAPSULE_STRICT_VALIDATION_ENABLED,
        verify_signature=settings.EVIDENCE_CAPSULE_REQUIRE_SIGNATURE_ON_PERSIST,
    )
    return EvidenceCapsuleVerifyResponse(
        capsule_id=body.capsule_id,
        valid=ok,
        reason=reason,
    )
