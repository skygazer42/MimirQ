from __future__ import annotations

from collections import Counter
from typing import Any

from app.rag.evaluation.poc_runner.query_pattern_miner import mine_query_patterns
from app.rag.industry_rules.schema import IndustryRuleset

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


def _safe_query(row: dict[str, Any]) -> str:
    return str(row.get("original_query") or "").strip()


def _build_glossary_suggestions(rows: list[dict[str, Any]], *, ruleset: IndustryRuleset | None, top_k: int) -> list[dict[str, Any]]:
    pattern_summary = mine_query_patterns(rows, abbreviation_min_frequency=1, top_k_keywords=max(1, int(top_k or 1)))
    existing = set((ruleset.glossary or {}).keys()) if ruleset is not None else set()
    out: list[dict[str, Any]] = []
    for item in pattern_summary.get("glossary_candidates") or []:
        token = str((item or {}).get("token") or "").strip()
        if not token or token in existing:
            continue
        out.append({"token": token, "count": int((item or {}).get("count") or 0), "source": (item or {}).get("source")})
    out.sort(key=lambda item: (-int(item["count"]), len(str(item["token"])), str(item["token"])))
    out = out[: max(1, int(top_k or 1))]
    return out


def _build_pattern_suggestions(rows: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for pattern_key, spec in _PATTERN_LIBRARY.items():
        matches = [query for row in rows if (query := _safe_query(row)) and any(marker in query for marker in spec["markers"])]
        if not matches:
            continue
        suggestions.append(
            {
                "pattern_key": pattern_key,
                "count": int(len(matches)),
                "sample_queries": matches[:3],
                "followup_template": spec["followup"],
            }
        )
    suggestions.sort(key=lambda item: (-int(item["count"]), str(item["pattern_key"])))
    return suggestions[: max(1, int(top_k or 1))]


def _build_intent_suggestions(rows: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    for row in rows:
        query = _safe_query(row)
        if not query:
            continue
        for intent, markers in _INTENT_LIBRARY.items():
            if any(marker in query for marker in markers):
                counts[intent] += 1
                samples.setdefault(intent, []).append(query)
                break
    out = [
        {"intent": intent, "count": int(count), "sample_queries": samples.get(intent, [])[:3]}
        for intent, count in counts.most_common(max(1, int(top_k or 1)))
    ]
    return out


def build_ruleset_suggestions(
    rows: list[dict[str, Any]],
    *,
    ruleset: IndustryRuleset | None,
    top_k: int = 10,
) -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "ruleset": str(getattr(ruleset, "name", "") or "") or None,
        "glossary_suggestions": _build_glossary_suggestions(rows, ruleset=ruleset, top_k=top_k),
        "pattern_suggestions": _build_pattern_suggestions(rows, top_k=top_k),
        "intent_suggestions": _build_intent_suggestions(rows, top_k=top_k),
    }
