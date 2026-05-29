from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.schemas.industry_rules import (
    IndustryRulesetDetailResponse,
    IndustryRulesetListResponse,
    IndustryRulesGlossaryUpdateRequest,
    IndustryRulesIntentsUpdateRequest,
    IndustryRulesPatternsUpdateRequest,
    IndustryRulesRewritePreviewRequest,
    IndustryRulesRewritePreviewResponse,
    IndustryRulesUpdateResponse,
)
from app.rag.industry_rules.appliers.query_rewrite import expand_query_terms
from app.rag.industry_rules.loaders import (
    list_rulesets,
    load_ruleset,
    replace_ruleset_glossary,
    replace_ruleset_intents,
    replace_ruleset_patterns,
    ruleset_exists,
)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_INDEX_SCHEMA = "mimirq.industry_rules_index.v1"
_RULESET_SCHEMA = "mimirq.industry_rules_ruleset.v1"
_PREVIEW_SCHEMA = "mimirq.industry_rules_preview.v1"
_UPDATE_SCHEMA = "mimirq.industry_rules_update.v1"


def _ruleset_summary(name: str) -> dict[str, Any]:
    ruleset = load_ruleset(name)
    return {
        "name": ruleset.name,
        "glossary_count": int(len(ruleset.glossary)),
        "pattern_count": int(len(ruleset.patterns)),
        "intent_count": int(len(ruleset.intents)),
    }


def _ruleset_detail(name: str) -> dict[str, Any]:
    ruleset = load_ruleset(name)
    return {
        "name": ruleset.name,
        "glossary_count": int(len(ruleset.glossary)),
        "pattern_count": int(len(ruleset.patterns)),
        "intent_count": int(len(ruleset.intents)),
        "glossary": dict(ruleset.glossary),
        "patterns": list(ruleset.patterns),
        "intents": list(ruleset.intents),
    }


def _require_ruleset(name: str) -> str:
    candidate = str(name or "").strip()
    if not ruleset_exists(candidate):
        raise HTTPException(status_code=404, detail=f"Unknown industry ruleset: {candidate or '<empty>'}")
    return candidate


@router.get(
    "/rulesets",
    response_model=IndustryRulesetListResponse,
    summary="列出行业规则集",
    description=(
        "返回当前租户全部行业规则集(industry rulesets)的摘要列表,每条含术语映射、"
        "问题模式、意图分类三个 section 的条目数。用于治理后台的规则集总览。"
        "返回体的 `schema` 字段是版本化的 payload 标记。"
    ),
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_industry_rulesets() -> dict[str, Any]:
    names = list_rulesets()
    rows = [_ruleset_summary(name) for name in names]
    return {
        "schema": _INDEX_SCHEMA,
        "count": int(len(rows)),
        "rulesets": rows,
    }


@router.get(
    "/rulesets/{name}",
    response_model=IndustryRulesetDetailResponse,
    summary="获取单个行业规则集详情",
    description=(
        "按规则集名称返回完整内容,包含 glossary(术语映射:规范词→同义/变体列表)、"
        "patterns(问题模式)、intents(意图分类)三个 section 的全量数据。"
        "规则集不存在时返回 404。"
    ),
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_industry_ruleset(name: str) -> dict[str, Any]:
    candidate = _require_ruleset(name)
    return {
        "schema": _RULESET_SCHEMA,
        "ruleset": _ruleset_detail(candidate),
    }


@router.put(
    "/rulesets/{name}/glossary",
    response_model=IndustryRulesUpdateResponse,
    summary="整体替换术语映射表",
    description=(
        "用请求体中的 glossary 全量替换指定规则集的术语映射表(非增量合并)。"
        "返回写入条目数。规则集不存在时返回 404。"
    ),
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def put_industry_ruleset_glossary(name: str, body: IndustryRulesGlossaryUpdateRequest) -> dict[str, Any]:
    candidate = _require_ruleset(name)
    result = replace_ruleset_glossary(candidate, body.glossary)
    return {"schema": _UPDATE_SCHEMA, **result}


@router.put(
    "/rulesets/{name}/patterns",
    response_model=IndustryRulesUpdateResponse,
    summary="整体替换问题模式",
    description=(
        "用请求体中的 patterns 全量替换指定规则集的问题模式列表(非增量合并)。"
        "返回写入条目数。规则集不存在时返回 404。"
    ),
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def put_industry_ruleset_patterns(name: str, body: IndustryRulesPatternsUpdateRequest) -> dict[str, Any]:
    candidate = _require_ruleset(name)
    result = replace_ruleset_patterns(candidate, body.patterns)
    return {"schema": _UPDATE_SCHEMA, **result}


@router.put(
    "/rulesets/{name}/intents",
    response_model=IndustryRulesUpdateResponse,
    summary="整体替换意图分类",
    description=(
        "用请求体中的 intents 全量替换指定规则集的意图分类列表(非增量合并)。"
        "返回写入条目数。规则集不存在时返回 404。"
    ),
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def put_industry_ruleset_intents(name: str, body: IndustryRulesIntentsUpdateRequest) -> dict[str, Any]:
    candidate = _require_ruleset(name)
    result = replace_ruleset_intents(candidate, body.intents)
    return {"schema": _UPDATE_SCHEMA, **result}


@router.post(
    "/preview-rewrite",
    response_model=IndustryRulesRewritePreviewResponse,
    summary="预览查询改写效果",
    description=(
        "用指定规则集的术语映射对输入 query 做术语展开,返回展开前后的查询及是否发生变化。"
        "用于治理后台实时预览 glossary 对检索查询改写的影响,不落库。规则集不存在时返回 404。"
    ),
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def preview_industry_rules_rewrite(body: IndustryRulesRewritePreviewRequest) -> dict[str, Any]:
    candidate = _require_ruleset(body.ruleset)
    ruleset = load_ruleset(candidate)
    original_query = str(body.query or "").strip()
    expanded_query = expand_query_terms(original_query, ruleset.glossary)
    return {
        "schema": _PREVIEW_SCHEMA,
        "ruleset": candidate,
        "original_query": original_query,
        "expanded_query": expanded_query,
        "changed": bool(expanded_query != original_query),
    }


__all__ = [
    "router",
    "get_industry_rulesets",
    "get_industry_ruleset",
    "put_industry_ruleset_glossary",
    "put_industry_ruleset_patterns",
    "put_industry_ruleset_intents",
    "preview_industry_rules_rewrite",
]
