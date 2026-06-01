"""
TAG (Table Augmented Generation) helpers: NL->SQL + answer drafting.

This is intentionally conservative:
- The SQL produced must be SELECT-only and is validated again by the SQL executor.
- Result size is strictly bounded (rows/cols/bytes) before being passed back to the model.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.rag.core.code_fence import extract_first_code_fence
from app.services.table_join_stats import build_join_statistics_snapshot
from app.services.table_schema_graph import (
    infer_schema_relationships_for_tables as infer_schema_relationships_from_graph,
)
from app.services.table_schema_graph import (
    score_join_plan_candidates,
    score_multi_join_plan_candidates,
)
from app.services.table_sql_fingerprint import fingerprint_sql

_SCHEMA_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?")
_QUOTED_LITERAL_RE = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{1,80})[\"“”'‘’]")
_NUMERIC_LITERAL_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_NON_IDENT_RE = re.compile(r"[^a-z0-9]+")
_TABLE_PICK_SUM_INTENT_RE = re.compile(r"(?i)\b(sum|total|amount|gmv|revenue)\b|合计|总和|求和|金额|销售额")
_TABLE_PICK_COUNT_INTENT_RE = re.compile(r"(?i)\b(count|how many)\b|多少|几条|几行|总数|数量")
_QUESTION_REQUIRED = "question is required"
_GENERIC_NON_KEY_COLUMNS = {
    "name",
    "title",
    "type",
    "status",
    "state",
    "value",
    "amount",
    "price",
    "date",
    "time",
    "timestamp",
    "region",
    "category",
}


def _build_llm(*, temperature: float = 0.0) -> ChatOpenAI:
    model_name = (getattr(settings, "LLM_MODEL_FAST", None) or getattr(settings, "LLM_MODEL", None) or "").strip()
    if not model_name:
        model_name = "gpt-5.4-mini"
    return ChatOpenAI(
        model=model_name,
        api_key=getattr(settings, "LLM_API_KEY", None),
        base_url=normalize_openai_compatible_base_url(getattr(settings, "LLM_API_BASE", None)),
        temperature=float(temperature),
        timeout=float(getattr(settings, "LLM_TIMEOUT", 60) or 60),
        max_retries=int(getattr(settings, "LLM_MAX_RETRIES", 2) or 2),
        streaming=False,
    )


def extract_sql(text: str) -> str:
    """
    Extract best-effort SQL from LLM output (handles fenced code blocks).
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    inner = extract_first_code_fence(raw, allowed_info_strings={"", "sql"})
    if inner:
        raw = inner
    # Strip leading/trailing junk.
    raw = raw.strip().strip(";").strip()
    # Keep a sane max length (defense-in-depth).
    if len(raw) > 20_000:
        raw = raw[:20_000]
    return raw


def _quote_ident(name: str) -> str:
    s = str(name or "").strip()
    if not s:
        return '"_"'
    return f'"{s.replace(chr(34), chr(34) * 2)}"'


def _quote_literal(value: str) -> str:
    s = str(value or "").strip()
    if _NUMERIC_LITERAL_RE.match(s):
        return s
    return "'" + s.replace("'", "''") + "'"


def _norm_key(value: str) -> str:
    s = str(value or "").strip()
    return s.casefold() if s.isascii() else s


def _match_text(hay: str, needle: str) -> bool:
    hs = str(hay or "").strip()
    nd = str(needle or "").strip()
    if not hs or not nd:
        return False
    if nd.isascii():
        return nd.casefold() in hs.casefold()
    return nd in hs


def _unique_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        s = str(raw or "").strip()
        if not s:
            continue
        key = _norm_key(s)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _extract_schema_terms(question: str, *, max_terms: int = 18) -> list[str]:
    q = str(question or "").strip()
    if not q:
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for m in _SCHEMA_TERM_RE.finditer(q):
        t = str(m.group(0) or "").strip()
        if not t:
            continue
        key = _norm_key(t)
        if key in seen:
            continue
        seen.add(key)
        terms.append(t)
        if len(terms) >= max(1, int(max_terms or 0)):
            break
    return terms


def _extract_quoted_literals(question: str, *, max_values: int = 8) -> list[str]:
    q = str(question or "")
    if not q:
        return []
    out: list[str] = []
    for m in _QUOTED_LITERAL_RE.finditer(q):
        s = str(m.group(1) or "").strip()
        if s:
            out.append(s)
        if len(out) >= max(1, int(max_values or 0)):
            break
    return _unique_keep_order(out)


def score_schema_link_diagnostics(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]] | None = None,
    table_aliases: list[str] | None = None,
) -> dict[str, Any]:
    """
    Heuristic schema-link scorer for TAG requests.

    Diagnostics are intentionally compact and PII-safe: only matched schema/value signals,
    score, strategy, and reason.
    """
    q = " ".join((question or "").strip().split())
    col_names = [
        str(c.get("name") or "").strip()
        for c in (columns or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    ]
    table_names = _unique_keep_order([str(sql_table or "").strip(), *list(table_aliases or [])])
    terms = _extract_schema_terms(q, max_terms=20)

    matched_columns: list[str] = []
    matched_tables: list[str] = []
    for t in terms:
        for cn in col_names:
            if _match_text(cn, t):
                matched_columns.append(cn)
        for tn in table_names:
            if _match_text(tn, t):
                matched_tables.append(tn)

    matched_columns = _unique_keep_order(matched_columns)
    matched_tables = _unique_keep_order(matched_tables)

    sample_values: list[str] = []
    for row in (sample_rows or [])[:12]:
        if not isinstance(row, dict):
            continue
        for v in list(row.values())[:40]:
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            sample_values.append(s)
            if len(sample_values) >= 400:
                break
        if len(sample_values) >= 400:
            break
    sample_values = _unique_keep_order(sample_values)

    value_candidates = _extract_quoted_literals(q, max_values=8)
    for t in terms:
        # Keep short ASCII tokens only when clearly informative (all-caps codes like US/EU).
        if t.isascii() and len(t) < 3 and not t.isupper():
            continue
        if t not in value_candidates and t not in {"count", "sum", "avg", "group", "order", "where", "limit"}:
            value_candidates.append(t)
    value_candidates = _unique_keep_order(value_candidates)[:12]

    matched_values: list[str] = []
    for cand in value_candidates:
        if sample_values and any(_match_text(v, cand) for v in sample_values):
            matched_values.append(cand)
            continue
        # Even without sample rows, quoted literals are useful filter hints.
        if cand in _extract_quoted_literals(q, max_values=8):
            matched_values.append(cand)
    matched_values = _unique_keep_order(matched_values)

    raw_score = int(len(matched_columns) * 3 + len(matched_tables) * 2 + len(matched_values))
    score = round(min(float(raw_score) / 10.0, 1.0), 3)

    strategy = "none"
    reason = "no_schema_overlap"
    if matched_columns and matched_values:
        strategy = "column_value_overlap"
        reason = "matched_columns_and_values"
    elif matched_columns:
        strategy = "column_overlap"
        reason = "matched_columns"
    elif matched_tables and matched_values:
        strategy = "table_value_overlap"
        reason = "matched_tables_and_values"
    elif matched_tables:
        strategy = "table_overlap"
        reason = "matched_tables"
    elif matched_values:
        strategy = "value_overlap"
        reason = "matched_values"

    if strategy == "none":
        q_fold = q.casefold()
        has_table_intent = any(
            k in q_fold
            for k in ("select", "where", "group by", "order by", "limit", "sum", "avg", "count", "min", "max", "top", "前")
        ) or any(k in q for k in ("统计", "汇总", "求和", "平均", "最大", "最小", "筛选", "过滤", "分组", "多少", "几条"))
        if has_table_intent and (col_names or table_names):
            strategy = "intent_hint"
            reason = "table_intent_without_explicit_match"
            raw_score = max(raw_score, 1)
            score = 0.1
        else:
            score = 0.0

    return {
        "matched_columns": matched_columns[:12],
        "matched_values": matched_values[:12],
        "matched_tables": matched_tables[:8],
        "score": score,
        "raw_score": raw_score,
        "strategy": strategy,
        "reason": reason,
    }


def _normalize_ident(value: str) -> str:
    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    return _NON_IDENT_RE.sub("_", raw).strip("_")


def _singularize(token: str) -> str:
    t = str(token or "").strip()
    if not t:
        return ""
    if t.endswith("ies") and len(t) > 3:
        return t[:-3] + "y"
    if t.endswith("ses") and len(t) > 3:
        return t[:-2]
    if t.endswith("s") and len(t) > 3 and not t.endswith("ss"):
        return t[:-1]
    return t


def _alias_bases(table_name: str, aliases: list[str] | None) -> set[str]:
    out: set[str] = set()
    for raw in [table_name, *list(aliases or [])]:
        s = str(raw or "").strip()
        if not s:
            continue
        # Remove extensions and schema prefixes.
        s = s.split(".")[0] if s.count(".") == 1 and s.lower().endswith((".csv", ".xls", ".xlsx")) else s
        s = s.split(".")[-1]
        norm = _normalize_ident(s)
        if not norm:
            continue
        parts = [p for p in norm.split("_") if p]
        for p in parts:
            out.add(p)
            out.add(_singularize(p))
        out.add(norm)
        out.add(_singularize(norm))
    return {v for v in out if v}


def _is_likely_key_column(col_name: str) -> bool:
    n = _normalize_ident(col_name)
    if not n:
        return False
    if n in {"id", "uuid"}:
        return True
    if n.endswith("_id"):
        return True
    if n.startswith("id_"):
        return True
    return False


def _pick_best_relationship_between(
    *,
    left_table: str,
    left_aliases: list[str] | None,
    left_columns: list[dict[str, Any]],
    right_table: str,
    right_aliases: list[str] | None,
    right_columns: list[dict[str, Any]],
) -> dict[str, Any] | None:
    left_col_names = [
        str(c.get("name") or "").strip()
        for c in (left_columns or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    ]
    right_col_names = [
        str(c.get("name") or "").strip()
        for c in (right_columns or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    ]
    if not left_col_names or not right_col_names:
        return None

    left_bases = _alias_bases(left_table, left_aliases)
    right_bases = _alias_bases(right_table, right_aliases)

    best: dict[str, Any] | None = None

    def _update(candidate: dict[str, Any]) -> None:
        nonlocal best
        if best is None or float(candidate.get("confidence") or 0.0) > float(best.get("confidence") or 0.0):
            best = candidate

    for l_raw in left_col_names:
        for r_raw in right_col_names:
            ln = _normalize_ident(l_raw)
            rn = _normalize_ident(r_raw)
            if not ln or not rn:
                continue

            # 1) Exact key column overlap (id / order_id / user_id, etc.).
            if ln == rn and _is_likely_key_column(ln):
                _update(
                    {
                        "left_table": left_table,
                        "left_column": l_raw,
                        "right_table": right_table,
                        "right_column": r_raw,
                        "confidence": 0.96,
                        "reason": "same_key_name",
                    }
                )
                continue

            # Ignore generic non-key overlaps (status/name/type/etc.).
            if ln == rn and ln in _GENERIC_NON_KEY_COLUMNS:
                continue

            # 2) FK -> id pattern (left fk points to right table).
            if ln.endswith("_id"):
                base = ln[: -len("_id")]
                if base and rn in {"id", f"{base}_id"}:
                    conf = 0.90
                    reason = "fk_to_id"
                    if base in right_bases:
                        conf = 0.95
                        reason = "fk_to_table_id"
                    _update(
                        {
                            "left_table": left_table,
                            "left_column": l_raw,
                            "right_table": right_table,
                            "right_column": r_raw,
                            "confidence": conf,
                            "reason": reason,
                        }
                    )
                    continue

            # 3) FK -> id pattern in reverse orientation (right fk points to left table).
            if rn.endswith("_id"):
                base = rn[: -len("_id")]
                if base and ln in {"id", f"{base}_id"}:
                    conf = 0.90
                    reason = "fk_to_id"
                    if base in left_bases:
                        conf = 0.95
                        reason = "fk_to_table_id"
                    _update(
                        {
                            "left_table": right_table,
                            "left_column": r_raw,
                            "right_table": left_table,
                            "right_column": l_raw,
                            "confidence": conf,
                            "reason": reason,
                        }
                    )

    return best


def infer_schema_relationships_for_tables(*, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Best-effort relationship inference for multi-table TAG planning.

    Output is intentionally compact and deterministic to keep traces auditable.
    """
    return infer_schema_relationships_from_graph(tables=tables)


def _pick_join_group_column(question: str, tables: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    q = str(question or "")
    if not q:
        return None, None
    for t in tables:
        tname = str(t.get("table_name") or "").strip()
        for c in (t.get("columns") or []):
            if not isinstance(c, dict):
                continue
            cname = str(c.get("name") or "").strip()
            if not cname:
                continue
            dtype = str(c.get("dtype") or "").lower()
            if any(k in dtype for k in ("int", "float", "double", "decimal", "number", "numeric", "real")):
                continue
            if _match_text(q, cname):
                return tname, cname
    return None, None


def _pick_join_metric_column(question: str, tables: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    q = str(question or "")
    # Prefer explicitly mentioned numeric columns first.
    for t in tables:
        tname = str(t.get("table_name") or "").strip()
        for c in (t.get("columns") or []):
            if not isinstance(c, dict):
                continue
            cname = str(c.get("name") or "").strip()
            if not cname:
                continue
            dtype = str(c.get("dtype") or "").lower()
            if not any(k in dtype for k in ("int", "float", "double", "decimal", "number", "numeric", "real")):
                continue
            if _match_text(q, cname):
                return tname, cname
    # Fallback: first numeric column.
    for t in tables:
        tname = str(t.get("table_name") or "").strip()
        for c in (t.get("columns") or []):
            if not isinstance(c, dict):
                continue
            cname = str(c.get("name") or "").strip()
            if not cname:
                continue
            dtype = str(c.get("dtype") or "").lower()
            if any(k in dtype for k in ("int", "float", "double", "decimal", "number", "numeric", "real")):
                return tname, cname
    return None, None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _build_join_plan_risk_contract(
    *,
    selected_candidate: dict[str, Any] | None,
    dry_run_cardinality: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate = selected_candidate if isinstance(selected_candidate, dict) else {}
    cost_signals = candidate.get("cost_signals") if isinstance(candidate.get("cost_signals"), dict) else {}
    fanout_ratio = _to_float(cost_signals.get("fanout_ratio"), 0.0)
    left_sel = cost_signals.get("left_selectivity")
    right_sel = cost_signals.get("right_selectivity")
    selectivity_unknown = left_sel is None or right_sel is None
    fanout_explosive = bool(fanout_ratio >= 20.0 or bool((dry_run_cardinality or {}).get("explosive")))

    reason_codes: list[str] = []
    if fanout_explosive:
        reason_codes.append("fanout_explosive")
    if selectivity_unknown:
        reason_codes.append("selectivity_unknown")

    return {
        "schema": "mimirq.tag_join_plan_risk.v1",
        "fanout_explosive": bool(fanout_explosive),
        "selectivity_unknown": bool(selectivity_unknown),
        "reason_codes": reason_codes,
    }


def _dry_run_join_cardinality(
    *,
    selected_candidate: dict[str, Any] | None,
    max_rows: int,
) -> dict[str, Any]:
    candidate = selected_candidate if isinstance(selected_candidate, dict) else {}
    join = candidate.get("join") if isinstance(candidate.get("join"), dict) else {}
    left_rows = max(0, _to_int(join.get("left_row_count"), 0))
    right_rows = max(0, _to_int(join.get("right_row_count"), 0))
    cost_signals = candidate.get("cost_signals") if isinstance(candidate.get("cost_signals"), dict) else {}
    fanout_ratio = _to_float(cost_signals.get("fanout_ratio"), 1.0)
    left_sel = cost_signals.get("left_selectivity")
    right_sel = cost_signals.get("right_selectivity")
    left_sel_v = _to_float(left_sel, -1.0)
    right_sel_v = _to_float(right_sel, -1.0)
    selectivity_known = left_sel_v >= 0.0 and right_sel_v >= 0.0
    min_sel = min(left_sel_v, right_sel_v) if selectivity_known else 0.1
    min_sel = min(1.0, max(0.001, float(min_sel)))

    base_rows = max(left_rows, right_rows, int(max_rows or 1))
    estimated_upper_rows = int(max(1.0, float(base_rows) * max(1.0, fanout_ratio) / float(min_sel)))
    explosive = bool(estimated_upper_rows > int(max(1, int(max_rows or 1))) * 10)

    return {
        "schema": "mimirq.tag_join_cardinality_dryrun.v1",
        "left_row_count": int(left_rows),
        "right_row_count": int(right_rows),
        "fanout_ratio": round(float(fanout_ratio), 6),
        "left_selectivity": (round(float(left_sel_v), 6) if left_sel_v >= 0.0 else None),
        "right_selectivity": (round(float(right_sel_v), 6) if right_sel_v >= 0.0 else None),
        "estimated_upper_rows": int(estimated_upper_rows),
        "max_rows_budget": int(max(1, int(max_rows or 1))),
        "explosive": bool(explosive),
    }


def plan_join_query_for_tables(
    *,
    question: str,
    tables: list[dict[str, Any]],
    max_rows: int,
) -> dict[str, Any]:
    """
    Deterministic bounded JOIN planner for multi-table TAG.

    Returns: {"sql": "...", "planner": {...}}.
    """
    max_rows_i = max(1, int(max_rows or 1))
    limit = min(max_rows_i, _extract_question_limit(question, default_limit=min(max_rows_i, 20)))

    valid_tables: list[dict[str, Any]] = []
    for raw in tables or []:
        if not isinstance(raw, dict):
            continue
        tname = str(raw.get("table_name") or "").strip()
        cols = raw.get("columns")
        if not tname or not isinstance(cols, list):
            continue
        try:
            row_count = int(raw.get("row_count") or 0)
        except Exception:
            row_count = 0
        sample_rows_raw = raw.get("sample_rows")
        sample_rows = [r for r in sample_rows_raw if isinstance(r, dict)] if isinstance(sample_rows_raw, list) else []
        valid_tables.append(
            {
                "table_name": tname,
                "table_aliases": [str(v) for v in (raw.get("table_aliases") or []) if str(v).strip()],
                "columns": [c for c in cols if isinstance(c, dict)],
                "row_count": max(0, int(row_count)),
                "sample_rows": sample_rows[:50],
            }
        )

    if len(valid_tables) < 2:
        raise ValueError("at least two tables are required for join planning")

    top_n = max(1, int(getattr(settings, "TABLE_TAG_PLAN_CANDIDATES_TOP_N", 3) or 3))
    ambiguity_gap = float(getattr(settings, "TABLE_TAG_AMBIGUITY_SCORE_GAP", 0.03) or 0.03)
    strict_ambiguity = bool(getattr(settings, "TABLE_TAG_AMBIGUITY_STRICT_ENABLED", True))
    plan_candidates = score_join_plan_candidates(
        tables=valid_tables,
        top_n=top_n,
        ambiguity_score_gap=ambiguity_gap,
    )
    max_join_tables = max(2, int(getattr(settings, "TABLE_QUERY_MAX_JOIN_TABLES", 4) or 4))
    multi_plan_candidates = score_multi_join_plan_candidates(
        tables=valid_tables,
        top_n=top_n,
        ambiguity_score_gap=ambiguity_gap,
        max_states=max(8, max_join_tables * 8),
    )
    candidate_rows = [c for c in (plan_candidates.get("candidates") or []) if isinstance(c, dict)]
    multi_candidate_rows = [
        c for c in (multi_plan_candidates.get("candidates") or []) if isinstance(c, dict)
    ]
    if not candidate_rows:
        raise ValueError("no_join_relationship_found")
    selected_candidate = (
        plan_candidates.get("selected") if isinstance(plan_candidates.get("selected"), dict) else candidate_rows[0]
    )
    selected_from_multi = False
    if len(valid_tables) > 2 and multi_candidate_rows:
        multi_selected = (
            multi_plan_candidates.get("selected")
            if isinstance(multi_plan_candidates.get("selected"), dict)
            else multi_candidate_rows[0]
        )
        if isinstance(multi_selected, dict):
            multi_tables = [str(v) for v in (multi_selected.get("selected_tables") or []) if str(v).strip()]
            pair_score = float(selected_candidate.get("score") or 0.0) if isinstance(selected_candidate, dict) else 0.0
            multi_score = float(multi_selected.get("score") or 0.0)
            if len(multi_tables) >= 3 and multi_score >= (pair_score * 0.9):
                selected_candidate = multi_selected
                selected_from_multi = True

    if strict_ambiguity:
        if selected_from_multi and bool(multi_plan_candidates.get("ambiguous")):
            raise ValueError("ambiguous_join_plan")
        if (not selected_from_multi) and bool(plan_candidates.get("ambiguous")):
            raise ValueError("ambiguous_join_plan")

    selected_score = float(selected_candidate.get("score") or 0.0) if isinstance(selected_candidate, dict) else 0.0
    low_confidence_threshold = float(
        getattr(settings, "TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD", 0.55) or 0.55
    )
    low_confidence_threshold = min(1.0, max(0.0, float(low_confidence_threshold)))
    low_confidence = float(selected_score) < float(low_confidence_threshold)
    low_confidence_strict = bool(getattr(settings, "TABLE_TAG_PLAN_LOW_CONFIDENCE_STRICT_ENABLED", False))
    if low_confidence and low_confidence_strict:
        raise ValueError("low_confidence_join_plan")
    selected_join = selected_candidate.get("join") if isinstance(selected_candidate, dict) else None
    if not isinstance(selected_join, dict):
        joins_path = selected_candidate.get("joins") if isinstance(selected_candidate, dict) else None
        joins_path = [j for j in (joins_path or []) if isinstance(j, dict)]
        selected_join = joins_path[0] if joins_path else {}
    if not isinstance(selected_join, dict):
        selected_join = {}

    relationships: list[dict[str, Any]] = []
    if isinstance(selected_candidate, dict) and isinstance(selected_candidate.get("joins"), list):
        relationships = [j for j in (selected_candidate.get("joins") or []) if isinstance(j, dict)]
    for c in candidate_rows:
        join = c.get("join") if isinstance(c, dict) else None
        if isinstance(join, dict):
            relationships.append(join)
    dedupe_keys: set[str] = set()
    unique_relationships: list[dict[str, Any]] = []
    for rel in relationships:
        key = (
            f"{str(rel.get('left_table') or '').strip()}."
            f"{str(rel.get('left_column') or '').strip()}->"
            f"{str(rel.get('right_table') or '').strip()}."
            f"{str(rel.get('right_column') or '').strip()}"
        )
        if key in dedupe_keys:
            continue
        dedupe_keys.add(key)
        unique_relationships.append(rel)
    relationships = unique_relationships

    rel = selected_join
    left_table = str(rel.get("left_table") or "").strip()
    right_table = str(rel.get("right_table") or "").strip()
    left_column = str(rel.get("left_column") or "").strip()
    right_column = str(rel.get("right_column") or "").strip()
    if not left_table or not right_table or not left_column or not right_column:
        raise ValueError("invalid_join_relationship")

    table_map = {str(t.get("table_name") or ""): t for t in valid_tables}
    selected_tables = [
        str(v)
        for v in ((selected_candidate or {}).get("selected_tables") or [left_table, right_table])
        if str(v).strip()
    ]
    if not selected_tables:
        selected_tables = [left_table, right_table]

    alias_map = {left_table: "t0", right_table: "t1"}
    left_alias = alias_map[left_table]
    right_alias = alias_map[right_table]

    group_table, group_col = _pick_join_group_column(question, [table_map[left_table], table_map[right_table]])
    metric_table, metric_col = _pick_join_metric_column(question, [table_map[left_table], table_map[right_table]])

    q_fold = str(question or "").casefold()
    is_count = bool(_TABLE_PICK_COUNT_INTENT_RE.search(question or ""))
    is_sum = bool(_TABLE_PICK_SUM_INTENT_RE.search(question or ""))
    is_avg = any(k in q_fold for k in ("avg", "average", "均值", "平均"))
    is_min = any(k in q_fold for k in (" min", "minimum", "最小"))
    is_max = any(k in q_fold for k in (" max", "maximum", "最大"))

    sql = (
        f"SELECT {right_alias}.{_quote_ident(group_col or right_column)} AS {_quote_ident(group_col or right_column)} "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
        f"FROM {_quote_ident(left_table)} AS {left_alias} "
        f"JOIN {_quote_ident(right_table)} AS {right_alias} "
        f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
        f"LIMIT {int(limit)}"
    )
    reason = "join_projection"
    aggregation: str | None = None
    aggregation_column: str | None = None
    order_by: dict[str, Any] | None = None

    if metric_table and metric_col:
        metric_expr = f"{alias_map.get(metric_table, left_alias)}.{_quote_ident(metric_col)}"
        aggregation_column = metric_col
        if is_sum or (group_col is not None and "金额" in str(question or "")):
            aggregation = "sum"
            if group_table and group_col:
                group_expr = f"{alias_map.get(group_table, right_alias)}.{_quote_ident(group_col)}"
                sql = (
                    f"SELECT {group_expr} AS {_quote_ident(group_col)}, SUM({metric_expr}) AS total "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                    f"FROM {_quote_ident(left_table)} AS {left_alias} "
                    f"JOIN {_quote_ident(right_table)} AS {right_alias} "
                    f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
                    f"GROUP BY {group_expr} ORDER BY total DESC LIMIT {int(limit)}"
                )
                reason = "join_aggregation_group"
                order_by = {"column": "total", "direction": "desc"}
            else:
                sql = (
                    f"SELECT SUM({metric_expr}) AS total "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                    f"FROM {_quote_ident(left_table)} AS {left_alias} "
                    f"JOIN {_quote_ident(right_table)} AS {right_alias} "
                    f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
                    "LIMIT 1"
                )
                reason = "join_aggregation"
                order_by = None
        elif is_avg:
            aggregation = "avg"
        elif is_min:
            aggregation = "min"
        elif is_max:
            aggregation = "max"

    if aggregation in {"avg", "min", "max"} and metric_table and metric_col:
        metric_expr = f"{alias_map.get(metric_table, left_alias)}.{_quote_ident(metric_col)}"
        agg_sql = aggregation.upper()
        alias_name = "value"
        if group_table and group_col:
            group_expr = f"{alias_map.get(group_table, right_alias)}.{_quote_ident(group_col)}"
            sql = (
                f"SELECT {group_expr} AS {_quote_ident(group_col)}, {agg_sql}({metric_expr}) AS {alias_name} "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                f"FROM {_quote_ident(left_table)} AS {left_alias} "
                f"JOIN {_quote_ident(right_table)} AS {right_alias} "
                f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
                f"GROUP BY {group_expr} ORDER BY {alias_name} DESC LIMIT {int(limit)}"
            )
            reason = "join_aggregation_group"
            order_by = {"column": alias_name, "direction": "desc"}
        else:
            sql = (
                f"SELECT {agg_sql}({metric_expr}) AS {alias_name} "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                f"FROM {_quote_ident(left_table)} AS {left_alias} "
                f"JOIN {_quote_ident(right_table)} AS {right_alias} "
                f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
                "LIMIT 1"
            )
            reason = "join_aggregation"
            order_by = None

    if is_count and group_table and group_col:
        group_expr = f"{alias_map.get(group_table, right_alias)}.{_quote_ident(group_col)}"
        sql = (
            f"SELECT {group_expr} AS {_quote_ident(group_col)}, COUNT(*) AS count "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            f"FROM {_quote_ident(left_table)} AS {left_alias} "
            f"JOIN {_quote_ident(right_table)} AS {right_alias} "
            f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
            f"GROUP BY {group_expr} ORDER BY count DESC LIMIT {int(limit)}"
        )
        reason = "join_count_group"
        aggregation = "count"
        aggregation_column = None
        order_by = {"column": "count", "direction": "desc"}
    elif is_count:
        sql = (
            f"SELECT COUNT(*) AS count "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            f"FROM {_quote_ident(left_table)} AS {left_alias} "
            f"JOIN {_quote_ident(right_table)} AS {right_alias} "
            f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
            "LIMIT 1"
        )
        reason = "join_count"
        aggregation = "count"
        aggregation_column = None
        order_by = None

    sql_fingerprint = fingerprint_sql(sql, length=16)
    dry_run_cardinality = _dry_run_join_cardinality(
        selected_candidate=(selected_candidate if isinstance(selected_candidate, dict) else None),
        max_rows=max_rows_i,
    )
    join_plan_risk = _build_join_plan_risk_contract(
        selected_candidate=(selected_candidate if isinstance(selected_candidate, dict) else None),
        dry_run_cardinality=dry_run_cardinality,
    )
    join_statistics_snapshot = build_join_statistics_snapshot(
        tables=valid_tables,
        top_n=top_n,
        ambiguity_score_gap=ambiguity_gap,
        max_states=max(8, max_join_tables * 8),
    )
    planner = {
        # Keep strategy stable for downstream compatibility; expose beam usage via mode.
        "strategy": "deterministic_join",
        "planner_mode": ("beam" if selected_from_multi else "pairwise"),
        "reason": reason,
        "joins": relationships[: max(1, int(max_join_tables) - 1)],
        "selected_tables": selected_tables,
        "candidates": candidate_rows[:top_n],
        "multi_candidates": multi_candidate_rows[:top_n],
        "selected_candidate_id": str((selected_candidate or {}).get("candidate_id") or ""),
        "selected_score": round(float(selected_score), 6),
        "ambiguous": (
            bool(multi_plan_candidates.get("ambiguous"))
            if selected_from_multi
            else bool(plan_candidates.get("ambiguous"))
        ),
        "ambiguity_gap": (
            multi_plan_candidates.get("ambiguity_gap")
            if selected_from_multi
            else plan_candidates.get("ambiguity_gap")
        ),
        "strict_ambiguity": bool(strict_ambiguity),
        "low_confidence": bool(low_confidence),
        "low_confidence_threshold": round(float(low_confidence_threshold), 6),
        "strict_low_confidence": bool(low_confidence_strict),
        "fail_reason": ("low_confidence_join_plan" if low_confidence else None),
        "join_plan_risk": join_plan_risk,
        "dry_run_cardinality": dry_run_cardinality,
        "join_statistics_snapshot": join_statistics_snapshot,
        "aggregation": aggregation,
        "aggregation_column": aggregation_column,
        "group_by": (
            {
                "table": str(group_table),
                "column": str(group_col),
            }
            if group_table and group_col
            else None
        ),
        "order_by": order_by,
        "limit": int(limit),
        "sql_fingerprint": sql_fingerprint,
    }
    return {"sql": sql, "planner": planner}


def _extract_question_limit(question: str, *, default_limit: int) -> int:
    q = str(question or "").strip()
    if not q:
        return max(1, int(default_limit or 1))

    patterns = [
        re.compile(r"(?i)\btop\s*(\d{1,4})\b"),
        re.compile(r"前\s*(\d{1,4})\s*[条行个]?"),
        re.compile(r"(?i)\blimit\s*(\d{1,4})\b"),
    ]
    for p in patterns:
        m = p.search(q)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if n > 0:
            return max(1, n)
    return max(1, int(default_limit or 1))


def _pick_numeric_column(columns: list[dict[str, Any]]) -> str | None:
    numeric_hints = ("int", "float", "double", "decimal", "number", "numeric", "real")
    for c in (columns or []):
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        dtype = str(c.get("dtype") or "").strip().lower()
        if any(h in dtype for h in numeric_hints):
            return name
    return None


def _pick_mentioned_column(question: str, columns: list[dict[str, Any]]) -> str | None:
    q = str(question or "")
    q_fold = q.casefold()
    for c in (columns or []):
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        key = name.casefold() if name.isascii() else name
        if key and key in q_fold:
            return name
    return None


def _pick_group_column(question: str, columns: list[dict[str, Any]], *, exclude: str | None = None) -> str | None:
    q = str(question or "")
    if not q:
        return None
    q_fold = q.casefold()

    explicit_terms: list[str] = []
    m_en = re.search(r"(?i)\bgroup\s+by\s+(\w+)", q)
    if m_en:
        explicit_terms.append(str(m_en.group(1) or "").strip())
    m_zh = re.search(r"按\s*([A-Za-z0-9_\u4e00-\u9fff]+)\s*分组", q)
    if m_zh:
        explicit_terms.append(str(m_zh.group(1) or "").strip())

    for t in explicit_terms:
        if not t:
            continue
        for c in (columns or []):
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            if not name or (exclude and _norm_key(name) == _norm_key(exclude)):
                continue
            if _match_text(name, t) or _match_text(t, name):
                return name

    group_requested = any(k in q_fold for k in ("group by", "分组", "每个", "各"))
    if not group_requested:
        return None

    for c in (columns or []):
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name or (exclude and _norm_key(name) == _norm_key(exclude)):
            continue
        key = name.casefold() if name.isascii() else name
        if key and key in (q_fold if name.isascii() else q):
            return name
    return None


def _infer_filter_predicate(
    *,
    question: str,
    columns: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]] | None = None,
    preferred_column: str | None = None,
) -> tuple[str | None, str | None, str]:
    q = str(question or "").strip()
    if not q:
        return None, None, "none"

    col_names = [
        str(c.get("name") or "").strip()
        for c in (columns or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    ]

    # Explicit predicate: `region = US` / `region 为 US` / `region is US`.
    for col in col_names:
        pat = re.compile(
            rf"{re.escape(col)}\s*(?:=|==|is|equals?|eq|为|是|等于)\s*['\"“”]?([A-Za-z0-9_./:\-]+|[\u4e00-\u9fff]{{1,40}})",
            re.IGNORECASE,
        )
        m = pat.search(q)
        if not m:
            continue
        val = str(m.group(1) or "").strip().strip(".,，。;；")
        if val:
            return col, val, "explicit_predicate"

    # Quoted literals can be used when a target column is already mentioned.
    quoted_vals = _extract_quoted_literals(q, max_values=6)
    if quoted_vals and preferred_column:
        return preferred_column, quoted_vals[0], "quoted_literal"

    # Sample-value match fallback for unquoted values.
    for row in (sample_rows or [])[:12]:
        if not isinstance(row, dict):
            continue
        for k, v in list(row.items())[:40]:
            col = str(k or "").strip()
            if not col or (col_names and col not in col_names):
                continue
            if preferred_column and _norm_key(preferred_column) != _norm_key(col):
                if preferred_column in col_names:
                    continue
            if v is None:
                continue
            sval = str(v).strip()
            if not sval:
                continue
            if _match_text(q, sval):
                return col, sval, "sample_value_match"

    return None, None, "none"


def _infer_order_hint(
    *,
    question: str,
    default_column: str | None,
) -> tuple[str | None, str | None]:
    q_fold = str(question or "").casefold()
    has_order = any(k in q_fold for k in ("order by", "排序", "排名", "top", "前"))
    if not has_order:
        return None, None

    is_asc = any(k in q_fold for k in (" asc", "ascending", "升序", "最低", "最小", "least"))
    is_desc = any(k in q_fold for k in (" desc", "descending", "降序", "最高", "最大", "最多", "top", "前"))
    direction = "asc" if is_asc and not is_desc else "desc"
    return default_column, direction


def _generate_deterministic_sql_with_diagnostics(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    max_rows: int,
    sample_rows: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    q = " ".join((question or "").strip().split())
    if not q:
        raise ValueError(_QUESTION_REQUIRED)

    q_fold = q.casefold()
    max_rows_i = max(1, int(max_rows or 0))
    limit = min(max_rows_i, _extract_question_limit(q, default_limit=min(max_rows_i, 20)))

    table_q = _quote_ident(sql_table)
    mentioned_col = _pick_mentioned_column(q, columns)
    numeric_col = _pick_numeric_column(columns)
    selected_col = mentioned_col or numeric_col
    selected_col_q = _quote_ident(selected_col) if selected_col else "*"
    group_col = _pick_group_column(q, columns, exclude=selected_col)
    group_col_q = _quote_ident(group_col) if group_col else None

    filter_col, filter_val, filter_source = _infer_filter_predicate(
        question=q,
        columns=columns,
        sample_rows=sample_rows,
        preferred_column=group_col or mentioned_col,
    )
    where_clause = ""
    if filter_col and filter_val is not None:
        where_clause = f" WHERE {_quote_ident(filter_col)} = {_quote_literal(filter_val)}"

    is_count = any(k in q_fold for k in ("count", "how many", "多少", "几条", "几行", "总数", "数量"))
    is_sum = any(k in q_fold for k in ("sum", "total", "合计", "总和", "求和"))
    is_avg = any(k in q_fold for k in ("avg", "average", "均值", "平均"))
    is_min = any(k in q_fold for k in (" min", "minimum", "最小"))
    is_max = any(k in q_fold for k in (" max", "maximum", "最大"))

    agg_kind: str | None = None
    agg_expr = ""
    agg_alias = ""
    if is_count:
        agg_kind = "count"
        agg_expr = "COUNT(*)"
        agg_alias = "count"
    elif is_sum and selected_col:
        agg_kind = "sum"
        agg_expr = f"SUM({selected_col_q})"
        agg_alias = "total"
    elif is_avg and selected_col:
        agg_kind = "avg"
        agg_expr = f"AVG({selected_col_q})"
        agg_alias = "avg"
    elif is_min and selected_col:
        agg_kind = "min"
        agg_expr = f"MIN({selected_col_q})"
        agg_alias = "min_value"
    elif is_max and selected_col:
        agg_kind = "max"
        agg_expr = f"MAX({selected_col_q})"
        agg_alias = "max_value"

    order_col, order_dir = _infer_order_hint(question=q, default_column=agg_alias if agg_alias else selected_col)
    order_clause = ""
    order_diag: dict[str, Any] | None = None
    if order_col and order_dir:
        if agg_alias and _norm_key(order_col) == _norm_key(agg_alias):
            order_clause = f" ORDER BY {agg_alias} {order_dir.upper()}"
            order_diag = {"column": agg_alias, "direction": order_dir}
        else:
            order_clause = f" ORDER BY {_quote_ident(order_col)} {order_dir.upper()}"
            order_diag = {"column": order_col, "direction": order_dir}

    reason = "projection"
    if agg_kind and group_col_q:
        if not order_clause:
            order_clause = f" ORDER BY {agg_alias} DESC"
            order_diag = {"column": agg_alias, "direction": "desc"}
        sql = (
            f"SELECT {group_col_q}, {agg_expr} AS {agg_alias} "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            f"FROM {table_q}{where_clause} GROUP BY {group_col_q}{order_clause} LIMIT {int(limit)}"
        )
        reason = "aggregation_group"
    elif agg_kind:
        sql = f"SELECT {agg_expr} AS {agg_alias} FROM {table_q}{where_clause} LIMIT 1"  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
        reason = "aggregation"
    elif group_col_q:
        if not order_clause:
            order_clause = " ORDER BY count DESC"
            order_diag = {"column": "count", "direction": "desc"}
        sql = (
            f"SELECT {group_col_q}, COUNT(*) AS count "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            f"FROM {table_q}{where_clause} GROUP BY {group_col_q}{order_clause} LIMIT {int(limit)}"
        )
        reason = "group_count"
    else:
        sql = f"SELECT {selected_col_q} FROM {table_q}{where_clause}{order_clause} LIMIT {int(limit)}"  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
        if where_clause:
            reason = "filter_projection"
        elif order_clause:
            reason = "ordered_projection"

    planner: dict[str, Any] = {
        "strategy": "deterministic_heuristic",
        "reason": reason,
        "aggregation": agg_kind,
        "aggregation_column": selected_col if agg_kind in {"sum", "avg", "min", "max"} else None,
        "filter": (
            {"column": filter_col, "operator": "=", "value": filter_val, "source": filter_source}
            if filter_col and filter_val is not None
            else None
        ),
        "group_by": group_col,
        "order_by": order_diag,
        "limit": int(limit),
        "selected_column": selected_col,
    }
    return sql, planner


def _generate_deterministic_sql(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    max_rows: int,
    sample_rows: list[dict[str, Any]] | None = None,
) -> str:
    sql, _planner = _generate_deterministic_sql_with_diagnostics(
        question=question,
        sql_table=sql_table,
        columns=columns,
        max_rows=max_rows,
        sample_rows=sample_rows,
    )
    return sql


def _generate_sql_with_llm(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    max_rows: int,
) -> str:
    """
    Generate a SELECT-only SQL query for a single SQLite table name.
    """
    q = " ".join((question or "").strip().split())
    if not q:
        raise ValueError(_QUESTION_REQUIRED)

    max_rows_i = max(1, int(max_rows or 0))
    cols_str = "\n".join(
        [f"- {str(c.get('name') or '').strip()} ({str(c.get('dtype') or '').strip()})" for c in (columns or []) if isinstance(c, dict)]
    )
    cols_str = cols_str[:8000]

    system = SystemMessage(
        content=(
            "You are a meticulous data analyst. Your job is to translate a natural language question into a single "
            "SQLite SELECT query.\n\n"
            "Hard constraints:\n"
            f"- ONLY output SQL (no markdown, no explanations).\n"
            f"- The query MUST be SELECT-only (or WITH ... SELECT).\n"
            f"- The query MUST reference ONLY this table: \"{sql_table}\".\n"
            f"- You MUST include a LIMIT <= {max_rows_i}.\n"
            "- Never use PRAGMA/ATTACH/DETACH/CREATE/INSERT/UPDATE/DELETE/DROP.\n"
        )
    )
    user = HumanMessage(
        content=(
            f"Table name: \"{sql_table}\"\n"
            "Columns:\n"
            f"{cols_str if cols_str else '(unknown)'}\n\n"
            f"Question: {q}\n"
        )
    )

    llm = _build_llm(temperature=0.0)
    resp = llm.invoke([system, user])
    sql = extract_sql(str(getattr(resp, "content", "") or ""))
    return sql


def generate_sql_for_table_with_mode(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    max_rows: int,
) -> tuple[str, str]:
    """
    Generate SQL with explicit mode metadata: ("llm" | "deterministic").
    """
    sql, mode, _metadata = generate_sql_for_table_with_metadata(
        question=question,
        sql_table=sql_table,
        columns=columns,
        max_rows=max_rows,
    )
    return sql, mode


def generate_sql_for_table_with_metadata(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    max_rows: int,
    sample_rows: list[dict[str, Any]] | None = None,
    table_aliases: list[str] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """
    Generate SQL + mode + diagnostics metadata.

    Backward compatibility: callers that only need `(sql, mode)` should keep using
    `generate_sql_for_table_with_mode`.
    """
    deterministic_only = bool(getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", False))
    deterministic_fallback = bool(getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True))
    llm_key = str(getattr(settings, "LLM_API_KEY", "") or "").strip()

    schema_link = score_schema_link_diagnostics(
        question=question,
        sql_table=sql_table,
        columns=columns,
        sample_rows=sample_rows,
        table_aliases=table_aliases,
    )

    if deterministic_only:
        sql, planner = _generate_deterministic_sql_with_diagnostics(
            question=question,
            sql_table=sql_table,
            columns=columns,
            max_rows=max_rows,
            sample_rows=sample_rows,
        )
        planner = dict(planner)
        planner["sql_fingerprint"] = fingerprint_sql(sql, length=16)
        return sql, "deterministic", {
            "schema_link": schema_link,
            "planner": planner,
            "sql_fingerprint": planner.get("sql_fingerprint"),
            "schema_link_score": schema_link.get("score"),
            "schema_link_strategy": schema_link.get("strategy"),
        }

    if llm_key:
        try:
            sql = _generate_sql_with_llm(
                question=question,
                sql_table=sql_table,
                columns=columns,
                max_rows=max_rows,
            )
            planner = {
                "strategy": "llm",
                "reason": "llm_generation",
                "aggregation": None,
                "filter": None,
                "group_by": None,
                "order_by": None,
                "limit": int(max(1, int(max_rows or 1))),
                "sql_fingerprint": fingerprint_sql(sql, length=16),
            }
            return sql, "llm", {
                "schema_link": schema_link,
                "planner": planner,
                "sql_fingerprint": planner.get("sql_fingerprint"),
                "schema_link_score": schema_link.get("score"),
                "schema_link_strategy": schema_link.get("strategy"),
            }
        except Exception as exc:
            if not deterministic_fallback:
                raise
            sql, planner = _generate_deterministic_sql_with_diagnostics(
                question=question,
                sql_table=sql_table,
                columns=columns,
                max_rows=max_rows,
                sample_rows=sample_rows,
            )
            planner = dict(planner)
            planner["reason"] = f"llm_failed_fallback:{exc.__class__.__name__}"
            planner["sql_fingerprint"] = fingerprint_sql(sql, length=16)
            return sql, "deterministic", {
                "schema_link": schema_link,
                "planner": planner,
                "sql_fingerprint": planner.get("sql_fingerprint"),
                "schema_link_score": schema_link.get("score"),
                "schema_link_strategy": schema_link.get("strategy"),
            }

    if deterministic_fallback:
        sql, planner = _generate_deterministic_sql_with_diagnostics(
            question=question,
            sql_table=sql_table,
            columns=columns,
            max_rows=max_rows,
            sample_rows=sample_rows,
        )
        planner = dict(planner)
        planner["reason"] = "no_llm_key_fallback"
        planner["sql_fingerprint"] = fingerprint_sql(sql, length=16)
        return sql, "deterministic", {
            "schema_link": schema_link,
            "planner": planner,
            "sql_fingerprint": planner.get("sql_fingerprint"),
            "schema_link_score": schema_link.get("score"),
            "schema_link_strategy": schema_link.get("strategy"),
        }

    raise RuntimeError("LLM_API_KEY is not configured and deterministic fallback is disabled")


def generate_sql_for_table(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    max_rows: int,
) -> str:
    """
    Backward-compatible wrapper that returns only SQL.
    """
    sql, _mode = generate_sql_for_table_with_mode(
        question=question,
        sql_table=sql_table,
        columns=columns,
        max_rows=max_rows,
    )
    return sql


def generate_answer_from_result(
    *,
    question: str,
    sql: str,
    result: dict[str, Any],
) -> str:
    """
    Draft a user-facing answer grounded in the executed SQL result.
    """
    if not bool(getattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", False)):
        raise RuntimeError("TABLE_LLM_ALLOW_RESULT_EGRESS=false")

    q = " ".join((question or "").strip().split())
    if not q:
        raise ValueError(_QUESTION_REQUIRED)

    cols = result.get("columns") if isinstance(result, dict) else None
    rows = result.get("rows") if isinstance(result, dict) else None
    truncated = bool(result.get("truncated")) if isinstance(result, dict) else False

    # Keep payload bounded; SQL executor already caps, but double-guard here.
    preview = {
        "sql": str(sql or "")[:20_000],
        "columns": cols if isinstance(cols, list) else [],
        "rows": rows if isinstance(rows, list) else [],
        "truncated": truncated,
    }
    preview_text = str(preview)
    if len(preview_text) > 12_000:
        preview_text = preview_text[:12_000] + "..."

    system = SystemMessage(
        content=(
            "You are a careful assistant. Answer the user's question using ONLY the SQL result provided. "
            "If the result is empty, say so. Do not guess missing values.\n"
            "Keep the answer concise and include key numbers.\n"
        )
    )
    user = HumanMessage(
        content=(
            f"Question: {q}\n\n"
            f"SQL: {str(sql or '').strip()}\n\n"
            f"Result: {preview_text}\n"
        )
    )
    llm = _build_llm(temperature=0.0)
    resp = llm.invoke([system, user])
    return str(getattr(resp, "content", "") or "").strip()


def tag_enabled() -> bool:
    return bool(getattr(settings, "TABLE_NL2SQL_ENABLED", False))
