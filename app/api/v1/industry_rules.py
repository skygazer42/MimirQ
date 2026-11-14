from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.pipelines import (
    IndustryRulesetDetail,
    IndustryRulesetDetailResponse,
    IndustryRulesetListResponse,
    IndustryRulesetSummary,
    IndustryRulesGlossaryUpdateRequest,
    IndustryRulesIntentsUpdateRequest,
    IndustryRulesPatternsUpdateRequest,
    IndustryRulesRewritePreviewRequest,
    IndustryRulesRewritePreviewResponse,
    IndustryRulesUpdateResponse,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.config import settings
from app.core.constants import UserRoles
from app.core.database import get_db
from app.rag.industry_rules.appliers.query_rewrite import expand_query_terms
from app.rag.industry_rules.loaders import (
    list_rulesets,
    load_ruleset,
    replace_ruleset_glossary,
    replace_ruleset_intents,
    replace_ruleset_patterns,
    ruleset_exists,
)
from app.rag.industry_rules.schema import IndustryRuleset
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)

_INDEX_SCHEMA = "mimirq.industry_rules_index.v1"
_RULESET_SCHEMA = "mimirq.industry_rules_ruleset.v1"
_PREVIEW_SCHEMA = "mimirq.industry_rules_preview.v1"
_UPDATE_SCHEMA = "mimirq.industry_rules_update.v1"


def _ensure_write(db: Session, tenant_id: UUID, account_id: str) -> None:
    try:
        system_tenant_id = UUID(settings.DEFAULT_TENANT_ID)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="DEFAULT_TENANT_ID is invalid") from exc
    if tenant_id != system_tenant_id:
        raise HTTPException(status_code=403, detail="No permission to manage industry rules")
    member = ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.SETTINGS_WRITE,
        detail="No permission to manage industry rules",
    )
    if member.role.strip().lower() != UserRoles.OWNER:
        raise HTTPException(status_code=403, detail="No permission to manage industry rules")


def _ruleset_summary(ruleset: IndustryRuleset) -> IndustryRulesetSummary:
    return IndustryRulesetSummary(
        name=ruleset.name,
        glossary_count=len(ruleset.glossary),
        pattern_count=len(ruleset.patterns),
        intent_count=len(ruleset.intents),
    )


def _require_ruleset(name: str) -> str:
    candidate = name.strip()
    if not ruleset_exists(candidate):
        raise HTTPException(status_code=404, detail=f"Unknown industry ruleset: {candidate or '<empty>'}")
    return candidate


@router.get(
    "/rulesets",
    dependencies=[Depends(get_current_account_id)],
    response_model=IndustryRulesetListResponse,
    summary="列出行业规则集",
    description=(
        "返回当前租户全部行业规则集(industry rulesets)的摘要列表,每条含术语映射、"
        "问题模式、意图分类三个 section 的条目数。用于治理后台的规则集总览。"
        "返回体的 `schema` 字段是版本化的 payload 标记。"
    ),
)
def get_industry_rulesets() -> IndustryRulesetListResponse:
    rows = [_ruleset_summary(load_ruleset(name)) for name in list_rulesets()]
    return IndustryRulesetListResponse(schema_=_INDEX_SCHEMA, count=len(rows), rulesets=rows)


@router.get(
    "/rulesets/{name}",
    dependencies=[Depends(get_current_account_id)],
    response_model=IndustryRulesetDetailResponse,
    summary="获取单个行业规则集详情",
    description=(
        "按规则集名称返回完整内容,包含 glossary(术语映射:规范词→同义/变体列表)、"
        "patterns(问题模式)、intents(意图分类)三个 section 的全量数据。"
        "规则集不存在时返回 404。"
    ),
)
def get_industry_ruleset(name: str) -> IndustryRulesetDetailResponse:
    ruleset = load_ruleset(_require_ruleset(name))
    return IndustryRulesetDetailResponse(
        schema_=_RULESET_SCHEMA,
        ruleset=IndustryRulesetDetail(
            **_ruleset_summary(ruleset).model_dump(),
            glossary=ruleset.glossary,
            patterns=ruleset.patterns,
            intents=ruleset.intents,
        ),
    )


@router.put(
    "/rulesets/{name}/glossary",
    response_model=IndustryRulesUpdateResponse,
    summary="整体替换术语映射表",
    description=(
        "用请求体中的 glossary 全量替换指定规则集的术语映射表(非增量合并)。返回写入条目数。规则集不存在时返回 404。"
    ),
)
def put_industry_ruleset_glossary(
    name: str,
    body: IndustryRulesGlossaryUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> IndustryRulesUpdateResponse:
    _ensure_write(db, tenant_id, account_id)
    candidate = _require_ruleset(name)
    result = replace_ruleset_glossary(candidate, body.glossary)
    return IndustryRulesUpdateResponse(schema_=_UPDATE_SCHEMA, **result)


@router.put(
    "/rulesets/{name}/patterns",
    response_model=IndustryRulesUpdateResponse,
    summary="整体替换问题模式",
    description=(
        "用请求体中的 patterns 全量替换指定规则集的问题模式列表(非增量合并)。返回写入条目数。规则集不存在时返回 404。"
    ),
)
def put_industry_ruleset_patterns(
    name: str,
    body: IndustryRulesPatternsUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> IndustryRulesUpdateResponse:
    _ensure_write(db, tenant_id, account_id)
    candidate = _require_ruleset(name)
    result = replace_ruleset_patterns(candidate, body.patterns)
    return IndustryRulesUpdateResponse(schema_=_UPDATE_SCHEMA, **result)


@router.put(
    "/rulesets/{name}/intents",
    response_model=IndustryRulesUpdateResponse,
    summary="整体替换意图分类",
    description=(
        "用请求体中的 intents 全量替换指定规则集的意图分类列表(非增量合并)。返回写入条目数。规则集不存在时返回 404。"
    ),
)
def put_industry_ruleset_intents(
    name: str,
    body: IndustryRulesIntentsUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> IndustryRulesUpdateResponse:
    _ensure_write(db, tenant_id, account_id)
    candidate = _require_ruleset(name)
    result = replace_ruleset_intents(candidate, body.intents)
    return IndustryRulesUpdateResponse(schema_=_UPDATE_SCHEMA, **result)


@router.post(
    "/preview-rewrite",
    dependencies=[Depends(get_current_account_id)],
    response_model=IndustryRulesRewritePreviewResponse,
    summary="预览查询改写效果",
    description=(
        "用指定规则集的术语映射对输入 query 做术语展开,返回展开前后的查询及是否发生变化。"
        "用于治理后台实时预览 glossary 对检索查询改写的影响,不落库。规则集不存在时返回 404。"
    ),
)
def preview_industry_rules_rewrite(body: IndustryRulesRewritePreviewRequest) -> IndustryRulesRewritePreviewResponse:
    candidate = _require_ruleset(body.ruleset)
    ruleset = load_ruleset(candidate)
    original_query = body.query.strip()
    expanded_query = expand_query_terms(original_query, ruleset.glossary)
    return IndustryRulesRewritePreviewResponse(
        schema_=_PREVIEW_SCHEMA,
        ruleset=candidate,
        original_query=original_query,
        expanded_query=expanded_query,
        changed=expanded_query != original_query,
    )


__all__ = [
    "router",
    "get_industry_rulesets",
    "get_industry_ruleset",
    "put_industry_ruleset_glossary",
    "put_industry_ruleset_patterns",
    "put_industry_ruleset_intents",
    "preview_industry_rules_rewrite",
]
