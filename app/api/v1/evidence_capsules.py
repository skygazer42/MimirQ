from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings
from app.core.database import get_db
from app.rag.core.evidence_capsule_builder import validate_evidence_capsule
from app.services.dataset_service import DatasetService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,127}$")


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
    root = Path(str(getattr(settings, "EVIDENCE_CAPSULE_STORE_DIR", "./runs/evidence_capsules") or "./runs/evidence_capsules"))
    return root.resolve()


def _normalize_capsule_id(value: str) -> str:
    cid = str(value or "").strip()
    if not _SAFE_ID_RE.match(cid):
        raise HTTPException(status_code=400, detail="invalid_capsule_id")
    return cid


def _capsule_path(capsule_id: str) -> Path:
    cid = _normalize_capsule_id(capsule_id)
    root = _store_dir()
    path = (root / f"{cid}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_capsule_id") from exc
    return path


@router.post("/capsules", response_model=EvidenceCapsulePersistResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def persist_evidence_capsule(
    body: EvidenceCapsulePersistRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    if not bool(getattr(settings, "EVIDENCE_CAPSULE_PERSIST_ENABLED", True)):
        raise HTTPException(status_code=400, detail="EVIDENCE_CAPSULE_PERSIST_ENABLED=false")

    DatasetService.ensure_member(db, tenant_id, account_id)

    strict_validation = bool(getattr(settings, "EVIDENCE_CAPSULE_STRICT_VALIDATION_ENABLED", True))
    verify_signature = bool(getattr(settings, "EVIDENCE_CAPSULE_REQUIRE_SIGNATURE_ON_PERSIST", False))
    verify_hash_on_persist = bool(getattr(settings, "EVIDENCE_CAPSULE_VERIFY_HASH_ON_PERSIST", True))
    strict = bool(strict_validation or verify_hash_on_persist)
    ok, reason = validate_evidence_capsule(
        body.capsule,
        strict=strict,
        verify_signature=verify_signature,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=f"invalid_capsule:{reason}")

    capsule_hash = str(body.capsule.get("capsule_hash") or "").strip()
    capsule_id = _normalize_capsule_id(str(body.capsule_id or capsule_hash or ""))
    path = _capsule_path(capsule_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    existed = path.exists()
    allow_overwrite = bool(getattr(settings, "EVIDENCE_CAPSULE_ALLOW_OVERWRITE", False))
    if existed and (not bool(body.overwrite) or not allow_overwrite):
        raise HTTPException(status_code=409, detail="capsule_exists")

    payload = dict(body.capsule)
    payload.setdefault("capsule_id", capsule_id)
    # capsule_id is validated and path is confined to EVIDENCE_CAPSULE_STORE_DIR in _capsule_path().
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return EvidenceCapsulePersistResponse(
        capsule_id=capsule_id,
        capsule_hash=capsule_hash,
        path=str(path),
        overwritten=bool(existed),
    )


@router.get("/capsules/{capsule_id}", response_model=EvidenceCapsuleGetResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_evidence_capsule(
    capsule_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    path = _capsule_path(capsule_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="capsule_not_found")
    try:
        capsule = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"capsule_read_failed:{exc.__class__.__name__}") from exc
    if not isinstance(capsule, dict):
        raise HTTPException(status_code=500, detail="capsule_invalid_payload")
    return EvidenceCapsuleGetResponse(
        capsule_id=capsule_id,
        capsule_hash=str(capsule.get("capsule_hash") or ""),
        capsule=capsule,
    )


@router.post("/capsules/verify", response_model=EvidenceCapsuleVerifyResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def verify_evidence_capsule_payload(
    body: EvidenceCapsulePersistRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    strict = bool(getattr(settings, "EVIDENCE_CAPSULE_STRICT_VALIDATION_ENABLED", True))
    require_sig = bool(getattr(settings, "EVIDENCE_CAPSULE_REQUIRE_SIGNATURE_ON_PERSIST", False))
    ok, reason = validate_evidence_capsule(body.capsule, strict=strict, verify_signature=require_sig)
    return EvidenceCapsuleVerifyResponse(
        capsule_id=(str(body.capsule_id or "").strip() or None),
        valid=bool(ok),
        reason=str(reason),
    )
