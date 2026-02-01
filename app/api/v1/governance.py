"""
Governance helper endpoints.

This is primarily used by the UI for rule-pack discovery and profile editors.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.rag.preprocessing.rule_packs import list_governance_rule_packs
from app.services.dataset_service import DatasetService

router = APIRouter()


class GovernanceRulePackListResponse(BaseModel):
    items: list[str] = Field(default_factory=list)


@router.get("/rule-packs", response_model=GovernanceRulePackListResponse)
async def list_rule_packs(
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    return {"items": list_governance_rule_packs()}

