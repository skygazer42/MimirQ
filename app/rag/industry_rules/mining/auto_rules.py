from collections import Counter
from typing import Any

from app.rag.evaluation.poc_runner.query_pattern_miner import mine_query_patterns
from app.rag.industry_rules.schema import IndustryRuleset
from app.types.document_metadata import metadata_text

_SCHEMA = "mimirq.industry_rules_suggestions.v1"

_PATTERN_LIBRARY = {
    "no_data": {"markers": ("没数据",), "followup": "请补软件名 / 设备名 / 故障表现"},
    "crash": {"markers": ("闪退", "崩溃"), "followup": "请提供版本、系统和崩溃前操作"},
    "licensing": {"markers": ("授权", "加密锁", "许可证"), "followup": "请说明软授权/硬件锁以及错误提示"},
}

_INTENT_LIBRARY = {
    "authorization": ("授权", "加密锁", "许可证"),
    "fault_troubleshooting": ("报错", "故障", "闪退", "没数据", "异常"),
    "configuration_guidance": ("怎么配置", "如何配置", "怎么设置", "如何设置"),
    "product_consultation": ("支持什么", "功能", "介绍"),
    "data_storage": ("历史库", "数据库", "存储"),
    "web_client": ("web", "浏览器", "客户端", "发布"),
}


def _build_glossary_suggestions(
    rows: list[dict[str, Any]], *, ruleset: IndustryRuleset | None, top_k: int
) -> list[dict[str, Any]]:
    pattern_summary = mine_query_patterns(rows, abbreviation_min_frequency=1, top_k_keywords=top_k)
    existing = set(ruleset.glossary) if ruleset is not None else set()
    out: list[dict[str, Any]] = []
    for item in pattern_summary["glossary_candidates"]:
        token = item["token"]
        if token in existing:
            continue
        out.append({"token": token, "count": item["count"], "source": item["source"]})
    out.sort(key=lambda item: (-item["count"], len(item["token"]), item["token"]))
    return out[:top_k]


def _build_pattern_suggestions(queries: list[str], *, top_k: int) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for pattern_key, spec in _PATTERN_LIBRARY.items():
        matches = [query for query in queries if any(marker in query for marker in spec["markers"])]
        if not matches:
            continue
        suggestions.append(
            {
                "pattern_key": pattern_key,
                "count": len(matches),
                "sample_queries": matches[:3],
                "followup_template": spec["followup"],
            }
        )
    suggestions.sort(key=lambda item: (-item["count"], item["pattern_key"]))
    return suggestions[:top_k]


def _build_intent_suggestions(queries: list[str], *, top_k: int) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    for query in queries:
        for intent, markers in _INTENT_LIBRARY.items():
            if any(marker in query for marker in markers):
                counts[intent] += 1
                matched = samples.setdefault(intent, [])
                if len(matched) < 3:
                    matched.append(query)
                break
    return [
        {"intent": intent, "count": count, "sample_queries": samples[intent]}
        for intent, count in counts.most_common(top_k)
    ]


def build_ruleset_suggestions(
    rows: list[dict[str, Any]],
    *,
    ruleset: IndustryRuleset | None,
    top_k: int = 10,
) -> dict[str, Any]:
    if top_k < 0:
        raise ValueError("Rule suggestion limit must not be negative")
    if top_k == 0:
        return {
            "schema": _SCHEMA,
            "ruleset": ruleset.name if ruleset is not None else None,
            "glossary_suggestions": [],
            "pattern_suggestions": [],
            "intent_suggestions": [],
        }
    queries = [query for row in rows if (query := metadata_text(row, "original_query"))]
    return {
        "schema": _SCHEMA,
        "ruleset": ruleset.name if ruleset is not None else None,
        "glossary_suggestions": _build_glossary_suggestions(rows, ruleset=ruleset, top_k=top_k),
        "pattern_suggestions": _build_pattern_suggestions(queries, top_k=top_k),
        "intent_suggestions": _build_intent_suggestions(queries, top_k=top_k),
    }
