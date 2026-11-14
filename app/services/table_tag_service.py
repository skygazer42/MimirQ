"""
TAG (Table Augmented Generation) helpers: NL->SQL + answer drafting.

This is intentionally conservative:
- The SQL produced must be SELECT-only and is validated again by the SQL executor.
- Result size is strictly bounded (rows/cols/bytes) before being passed back to the model.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.rag.core.code_fence import extract_first_code_fence
from app.services.table_join_stats import build_join_statistics_snapshot
from app.services.table_schema_graph import (
    score_join_plan_candidates,
    score_multi_join_plan_candidates,
)
from app.services.table_sql_fingerprint import fingerprint_sql

_SCHEMA_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?")
_QUOTED_LITERAL_RE = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{1,80})[\"“”'‘’]")
_NUMERIC_LITERAL_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_NUMERIC_DTYPE_HINTS = ("int", "float", "double", "decimal", "number", "numeric", "real")
_TABLE_PICK_SUM_INTENT_RE = re.compile(r"(?i)\b(sum|total|amount|gmv|revenue)\b|合计|总和|求和|金额|销售额")
_TABLE_PICK_COUNT_INTENT_RE = re.compile(r"(?i)\b(count|how many)\b|多少|几条|几行|总数|数量")
_QUESTION_REQUIRED = "question is required"


class _SchemaLinkDiagnostics(TypedDict):
    matched_columns: list[str]
    matched_values: list[str]
    matched_tables: list[str]
    score: float
    raw_score: int
    strategy: str
    reason: str


def _table_column_names(columns: list[dict[str, Any]]) -> list[str]:
    return [column["name"].strip() for column in columns if isinstance(column, dict) and column["name"].strip()]


def _column_is_numeric(column: dict[str, Any]) -> bool:
    dtype = column.get("dtype")
    if dtype is None:
        return False
    dtype = dtype.lower()
    return any(hint in dtype for hint in _NUMERIC_DTYPE_HINTS)


def _iter_named_columns(columns: list[dict[str, Any]]) -> Iterator[tuple[dict[str, Any], str]]:
    for column in columns:
        if not isinstance(column, dict):
            continue
        name = column["name"].strip()
        if name:
            yield column, name


def create_table_chat_model(*, temperature: float = 0.0) -> ChatOpenAI:
    model_name = (settings.LLM_MODEL_FAST or settings.LLM_MODEL).strip()
    if not model_name:
        model_name = "gpt-5.4-mini"
    return ChatOpenAI(
        model=model_name,
        api_key=settings.LLM_API_KEY,
        base_url=normalize_openai_compatible_base_url(settings.LLM_API_BASE),
        temperature=float(temperature),
        timeout=float(settings.LLM_TIMEOUT),
        max_retries=settings.LLM_MAX_RETRIES,
        streaming=False,
    )


def extract_sql(text: str) -> str:
    """
    Extract best-effort SQL from LLM output (handles fenced code blocks).
    """
    raw = text.strip()
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
    s = name.strip()
    if not s:
        return '"_"'
    return f'"{s.replace(chr(34), chr(34) * 2)}"'


def _quote_literal(value: str) -> str:
    s = value.strip()
    if _NUMERIC_LITERAL_RE.match(s):
        return s
    return "'" + s.replace("'", "''") + "'"


def _norm_key(value: str) -> str:
    s = value.strip()
    return s.casefold() if s.isascii() else s


def _iter_filtered_named_columns(
    columns: list[dict[str, Any]], *, exclude: str | None = None
) -> Iterator[tuple[dict[str, Any], str]]:
    excluded_key = _norm_key(exclude) if exclude else None
    for column, name in _iter_named_columns(columns):
        if excluded_key and _norm_key(name) == excluded_key:
            continue
        yield column, name


def _iter_table_named_columns(
    tables: list[dict[str, Any]], *, numeric: bool | None = None
) -> Iterator[tuple[str, dict[str, Any], str]]:
    for table in tables:
        if not isinstance(table, dict):
            continue
        table_name = table["table_name"].strip()
        for column, name in _iter_named_columns(table.get("columns") or []):
            is_numeric = _column_is_numeric(column)
            if numeric is True and not is_numeric:
                continue
            if numeric is False and is_numeric:
                continue
            yield table_name, column, name


def _match_text(hay: str, needle: str) -> bool:
    hs = hay.strip()
    nd = needle.strip()
    if not hs or not nd:
        return False
    if nd.isascii():
        return nd.casefold() in hs.casefold()
    return nd in hs


def _unique_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        s = raw.strip()
        if not s:
            continue
        key = _norm_key(s)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _extract_schema_terms(question: str, *, max_terms: int = 18) -> list[str]:
    q = question.strip()
    if not q:
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for m in _SCHEMA_TERM_RE.finditer(q):
        t = m.group(0).strip()
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
    q = question
    if not q:
        return []
    out: list[str] = []
    for m in _QUOTED_LITERAL_RE.finditer(q):
        s = m.group(1).strip()
        if s:
            out.append(s)
        if len(out) >= max(1, int(max_values or 0)):
            break
    return _unique_keep_order(out)


def _schema_link_matches(
    terms: list[str], *, col_names: list[str], table_names: list[str]
) -> tuple[list[str], list[str]]:
    matched_columns: list[str] = []
    matched_tables: list[str] = []
    for term in terms:
        matched_columns.extend(column for column in col_names if _match_text(column, term))
        matched_tables.extend(table for table in table_names if _match_text(table, term))
    return _unique_keep_order(matched_columns), _unique_keep_order(matched_tables)


def _schema_sample_values(sample_rows: list[dict[str, Any]] | None) -> list[str]:
    sample_values: list[str] = []
    for row in (sample_rows or [])[:12]:
        if not isinstance(row, dict):
            continue
        for value in list(row.values())[:40]:
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            sample_values.append(text)
            if len(sample_values) >= 400:
                break
        if len(sample_values) >= 400:
            break
    return _unique_keep_order(sample_values)


def _schema_value_candidates(question: str, terms: list[str]) -> list[str]:
    value_candidates = _extract_quoted_literals(question, max_values=8)
    skip_terms = {"count", "sum", "avg", "group", "order", "where", "limit"}
    for term in terms:
        if term.isascii() and len(term) < 3 and not term.isupper():
            continue
        if term not in value_candidates and term not in skip_terms:
            value_candidates.append(term)
    return _unique_keep_order(value_candidates)[:12]


def _schema_matched_values(question: str, *, sample_values: list[str], terms: list[str]) -> list[str]:
    quoted = _extract_quoted_literals(question, max_values=8)
    matched_values: list[str] = []
    for candidate in _schema_value_candidates(question, terms):
        if sample_values and any(_match_text(value, candidate) for value in sample_values):
            matched_values.append(candidate)
            continue
        if candidate in quoted:
            matched_values.append(candidate)
    return _unique_keep_order(matched_values)


def _schema_link_strategy(
    *,
    matched_columns: list[str],
    matched_tables: list[str],
    matched_values: list[str],
) -> tuple[str, str]:
    if matched_columns and matched_values:
        return "column_value_overlap", "matched_columns_and_values"
    if matched_columns:
        return "column_overlap", "matched_columns"
    if matched_tables and matched_values:
        return "table_value_overlap", "matched_tables_and_values"
    if matched_tables:
        return "table_overlap", "matched_tables"
    if matched_values:
        return "value_overlap", "matched_values"
    return "none", "no_schema_overlap"


def _has_table_intent(question: str) -> bool:
    q_fold = question.casefold()
    ascii_intents = (
        "select",
        "where",
        "group by",
        "order by",
        "limit",
        "sum",
        "avg",
        "count",
        "min",
        "max",
        "top",
        "前",
    )
    zh_intents = ("统计", "汇总", "求和", "平均", "最大", "最小", "筛选", "过滤", "分组", "多少", "几条")
    return any(key in q_fold for key in ascii_intents) or any(key in question for key in zh_intents)


def score_schema_link_diagnostics(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]] | None = None,
    table_aliases: list[str] | None = None,
) -> _SchemaLinkDiagnostics:
    """
    Heuristic schema-link scorer for TAG requests.

    Diagnostics are intentionally compact and PII-safe: only matched schema/value signals,
    score, strategy, and reason.
    """
    q = " ".join(question.strip().split())
    col_names = _table_column_names(columns)
    table_names = _unique_keep_order([sql_table.strip(), *list(table_aliases or [])])
    terms = _extract_schema_terms(q, max_terms=20)

    matched_columns, matched_tables = _schema_link_matches(terms, col_names=col_names, table_names=table_names)
    matched_values = _schema_matched_values(q, sample_values=_schema_sample_values(sample_rows), terms=terms)

    raw_score = len(matched_columns) * 3 + len(matched_tables) * 2 + len(matched_values)
    score = round(min(float(raw_score) / 10.0, 1.0), 3)

    strategy, reason = _schema_link_strategy(
        matched_columns=matched_columns,
        matched_tables=matched_tables,
        matched_values=matched_values,
    )

    if strategy == "none":
        if _has_table_intent(q) and (col_names or table_names):
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


def _pick_join_group_column(question: str, tables: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    q = question
    if not q:
        return None, None
    for table_name, _column, column_name in _iter_table_named_columns(tables, numeric=False):
        if _match_text(q, column_name):
            return table_name, column_name
    return None, None


def _pick_join_metric_column(question: str, tables: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    q = question
    # Prefer explicitly mentioned numeric columns first.
    for table_name, _column, column_name in _iter_table_named_columns(tables, numeric=True):
        if _match_text(q, column_name):
            return table_name, column_name
    # Fallback: first numeric column.
    for table_name, _column, column_name in _iter_table_named_columns(tables, numeric=True):
        return table_name, column_name
    return None, None


def _build_join_plan_risk_contract(
    *,
    selected_candidate: dict[str, Any],
    dry_run_cardinality: dict[str, Any],
) -> dict[str, Any]:
    cost_signals = selected_candidate.get("cost_signals", {})
    fanout_ratio = cost_signals.get("fanout_ratio", 0.0)
    left_sel = cost_signals.get("left_selectivity")
    right_sel = cost_signals.get("right_selectivity")
    selectivity_unknown = left_sel is None or right_sel is None
    fanout_explosive = fanout_ratio >= 20.0 or dry_run_cardinality["explosive"]

    reason_codes: list[str] = []
    if fanout_explosive:
        reason_codes.append("fanout_explosive")
    if selectivity_unknown:
        reason_codes.append("selectivity_unknown")

    return {
        "schema": "mimirq.tag_join_plan_risk.v1",
        "fanout_explosive": fanout_explosive,
        "selectivity_unknown": selectivity_unknown,
        "reason_codes": reason_codes,
    }


def _dry_run_join_cardinality(
    *,
    selected_candidate: dict[str, Any],
    max_rows: int,
) -> dict[str, Any]:
    join = selected_candidate.get("join", {})
    left_rows = max(0, join.get("left_row_count") or 0)
    right_rows = max(0, join.get("right_row_count") or 0)
    cost_signals = selected_candidate.get("cost_signals", {})
    fanout_ratio = cost_signals.get("fanout_ratio", 1.0)
    left_sel = cost_signals.get("left_selectivity")
    right_sel = cost_signals.get("right_selectivity")
    left_sel_v = -1.0 if left_sel is None else left_sel
    right_sel_v = -1.0 if right_sel is None else right_sel
    selectivity_known = left_sel_v >= 0.0 and right_sel_v >= 0.0
    min_sel = min(left_sel_v, right_sel_v) if selectivity_known else 0.1
    min_sel = min(1.0, max(0.001, min_sel))

    base_rows = max(left_rows, right_rows, max_rows or 1)
    estimated_upper_rows = int(max(1.0, float(base_rows) * max(1.0, fanout_ratio) / min_sel))
    explosive = estimated_upper_rows > max(1, max_rows) * 10

    return {
        "schema": "mimirq.tag_join_cardinality_dryrun.v1",
        "left_row_count": left_rows,
        "right_row_count": right_rows,
        "fanout_ratio": round(fanout_ratio, 6),
        "left_selectivity": (round(left_sel_v, 6) if left_sel_v >= 0.0 else None),
        "right_selectivity": (round(right_sel_v, 6) if right_sel_v >= 0.0 else None),
        "estimated_upper_rows": estimated_upper_rows,
        "max_rows_budget": max(1, max_rows),
        "explosive": explosive,
    }


@dataclass(frozen=True)
class _JoinPlanningState:
    top_n: int
    ambiguity_gap: float
    strict_ambiguity: bool
    max_join_tables: int
    plan_candidates: dict[str, Any]
    multi_plan_candidates: dict[str, Any]
    candidate_rows: list[dict[str, Any]]
    multi_candidate_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class _JoinCandidateSelection:
    candidate: dict[str, Any]
    selected_from_multi: bool


def _normalize_join_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid_tables: list[dict[str, Any]] = []
    for raw in tables:
        if not isinstance(raw, dict):
            continue
        table_name = raw["table_name"].strip()
        columns = raw.get("columns")
        if not table_name or not isinstance(columns, list):
            continue
        try:
            row_count = int(raw.get("row_count") or 0)
        except (OverflowError, TypeError, ValueError):
            row_count = 0
        sample_rows_raw = raw.get("sample_rows")
        sample_rows = (
            [row for row in sample_rows_raw if isinstance(row, dict)] if isinstance(sample_rows_raw, list) else []
        )
        valid_tables.append(
            {
                "table_name": table_name,
                "table_aliases": [str(v) for v in (raw.get("table_aliases") or []) if str(v).strip()],
                "columns": [column for column in columns if isinstance(column, dict)],
                "row_count": max(0, row_count),
                "sample_rows": sample_rows[:50],
            }
        )
    return valid_tables


def _build_join_planning_state(valid_tables: list[dict[str, Any]]) -> _JoinPlanningState:
    top_n = max(1, settings.TABLE_TAG_PLAN_CANDIDATES_TOP_N or 3)
    ambiguity_gap = settings.TABLE_TAG_AMBIGUITY_SCORE_GAP or 0.03
    strict_ambiguity = settings.TABLE_TAG_AMBIGUITY_STRICT_ENABLED
    max_join_tables = max(2, settings.TABLE_QUERY_MAX_JOIN_TABLES or 4)
    plan_candidates = score_join_plan_candidates(
        tables=valid_tables,
        top_n=top_n,
        ambiguity_score_gap=ambiguity_gap,
    )
    multi_plan_candidates = score_multi_join_plan_candidates(
        tables=valid_tables,
        top_n=top_n,
        ambiguity_score_gap=ambiguity_gap,
        max_states=max(8, max_join_tables * 8),
    )
    candidate_rows = list(plan_candidates["candidates"])
    multi_candidate_rows = list(multi_plan_candidates["candidates"])
    return _JoinPlanningState(
        top_n=top_n,
        ambiguity_gap=ambiguity_gap,
        strict_ambiguity=strict_ambiguity,
        max_join_tables=max_join_tables,
        plan_candidates=plan_candidates,
        multi_plan_candidates=multi_plan_candidates,
        candidate_rows=candidate_rows,
        multi_candidate_rows=multi_candidate_rows,
    )


def _select_join_candidate(
    valid_tables: list[dict[str, Any]],
    state: _JoinPlanningState,
) -> _JoinCandidateSelection:
    if not state.candidate_rows:
        raise ValueError("no_join_relationship_found")

    selected_candidate = state.candidate_rows[0]
    if len(valid_tables) <= 2 or not state.multi_candidate_rows:
        return _JoinCandidateSelection(candidate=selected_candidate, selected_from_multi=False)

    multi_selected = state.multi_candidate_rows[0]
    multi_tables = multi_selected["selected_tables"]
    pair_score = selected_candidate["score"]
    multi_score = multi_selected["score"]
    if len(multi_tables) >= 3 and multi_score >= (pair_score * 0.9):
        return _JoinCandidateSelection(candidate=multi_selected, selected_from_multi=True)
    return _JoinCandidateSelection(candidate=selected_candidate, selected_from_multi=False)


def _selected_plan_candidates(
    state: _JoinPlanningState,
    selection: _JoinCandidateSelection,
) -> dict[str, Any]:
    return state.multi_plan_candidates if selection.selected_from_multi else state.plan_candidates


def _join_confidence_state(selected_candidate: dict[str, Any]) -> tuple[float, float, bool, bool]:
    selected_score = selected_candidate["score"]
    low_confidence_threshold = settings.TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD or 0.55
    low_confidence_threshold = min(1.0, max(0.0, low_confidence_threshold))
    low_confidence = selected_score < low_confidence_threshold
    low_confidence_strict = settings.TABLE_TAG_PLAN_LOW_CONFIDENCE_STRICT_ENABLED
    return selected_score, low_confidence_threshold, low_confidence, low_confidence_strict


def _selected_join_payload(selected_candidate: dict[str, Any]) -> dict[str, Any]:
    if "join" in selected_candidate:
        return selected_candidate["join"]
    return selected_candidate["joins"][0]


def _dedupe_join_relationships(
    selected_candidate: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    relationships = [*selected_candidate.get("joins", []), *(candidate["join"] for candidate in candidate_rows)]

    dedupe_keys: set[str] = set()
    unique_relationships: list[dict[str, Any]] = []
    for rel in relationships:
        key = (
            f"{rel['left_table'].strip()}."
            f"{rel['left_column'].strip()}->"
            f"{rel['right_table'].strip()}."
            f"{rel['right_column'].strip()}"
        )
        if key in dedupe_keys:
            continue
        dedupe_keys.add(key)
        unique_relationships.append(rel)
    return unique_relationships


def _join_group_expr(
    *,
    alias_map: dict[str, str],
    group_table: str,
    group_col: str,
) -> str:
    return f"{alias_map[group_table]}.{_quote_ident(group_col)}"


def _join_metric_expr(
    *,
    alias_map: dict[str, str],
    metric_table: str,
    metric_col: str,
) -> str:
    return f"{alias_map[metric_table]}.{_quote_ident(metric_col)}"


def _join_metric_aggregation(question: str, *, question_fold: str, group_col: str | None) -> str | None:
    if bool(_TABLE_PICK_SUM_INTENT_RE.search(question)) or (group_col is not None and "金额" in question):
        return "sum"
    if any(k in question_fold for k in ("avg", "average", "均值", "平均")):
        return "avg"
    if any(k in question_fold for k in (" min", "minimum", "最小")):
        return "min"
    if any(k in question_fold for k in (" max", "maximum", "最大")):
        return "max"
    return None


def _build_join_query_sql(
    *,
    question: str,
    limit: int,
    left_table: str,
    right_table: str,
    left_column: str,
    right_column: str,
    alias_map: dict[str, str],
    left_alias: str,
    right_alias: str,
    group_table: str | None,
    group_col: str | None,
    metric_table: str | None,
    metric_col: str | None,
) -> tuple[str, str, str | None, str | None, dict[str, Any] | None]:
    sql = (
        f"SELECT {right_alias}.{_quote_ident(group_col or right_column)} AS {_quote_ident(group_col or right_column)} "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
        f"FROM {_quote_ident(left_table)} AS {left_alias} "
        f"JOIN {_quote_ident(right_table)} AS {right_alias} "
        f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
        f"LIMIT {int(limit)}"
    )
    reason = "join_projection"
    aggregation_column = metric_col if metric_table and metric_col else None
    if bool(_TABLE_PICK_COUNT_INTENT_RE.search(question)):
        if group_table and group_col:
            group_expr = _join_group_expr(alias_map=alias_map, group_table=group_table, group_col=group_col)
            sql = (
                f"SELECT {group_expr} AS {_quote_ident(group_col)}, COUNT(*) AS count "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                f"FROM {_quote_ident(left_table)} AS {left_alias} "
                f"JOIN {_quote_ident(right_table)} AS {right_alias} "
                f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
                f"GROUP BY {group_expr} ORDER BY count DESC LIMIT {int(limit)}"
            )
            return sql, "join_count_group", "count", None, {"column": "count", "direction": "desc"}
        sql = (
            f"SELECT COUNT(*) AS count "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            f"FROM {_quote_ident(left_table)} AS {left_alias} "
            f"JOIN {_quote_ident(right_table)} AS {right_alias} "
            f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
            "LIMIT 1"
        )
        return sql, "join_count", "count", None, None

    if not metric_table or not metric_col:
        return sql, reason, None, aggregation_column, None

    aggregation = _join_metric_aggregation(
        question,
        question_fold=question.casefold(),
        group_col=group_col,
    )
    if aggregation == "sum":
        metric_expr = _join_metric_expr(alias_map=alias_map, metric_table=metric_table, metric_col=metric_col)
        if group_table and group_col:
            group_expr = _join_group_expr(alias_map=alias_map, group_table=group_table, group_col=group_col)
            sql = (
                f"SELECT {group_expr} AS {_quote_ident(group_col)}, SUM({metric_expr}) AS total "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                f"FROM {_quote_ident(left_table)} AS {left_alias} "
                f"JOIN {_quote_ident(right_table)} AS {right_alias} "
                f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
                f"GROUP BY {group_expr} ORDER BY total DESC LIMIT {int(limit)}"
            )
            return sql, "join_aggregation_group", "sum", aggregation_column, {"column": "total", "direction": "desc"}
        sql = (
            f"SELECT SUM({metric_expr}) AS total "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            f"FROM {_quote_ident(left_table)} AS {left_alias} "
            f"JOIN {_quote_ident(right_table)} AS {right_alias} "
            f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
            "LIMIT 1"
        )
        return sql, "join_aggregation", "sum", aggregation_column, None

    if aggregation in {"avg", "min", "max"}:
        metric_expr = _join_metric_expr(alias_map=alias_map, metric_table=metric_table, metric_col=metric_col)
        agg_sql = aggregation.upper()
        if group_table and group_col:
            group_expr = _join_group_expr(alias_map=alias_map, group_table=group_table, group_col=group_col)
            sql = (
                f"SELECT {group_expr} AS {_quote_ident(group_col)}, {agg_sql}({metric_expr}) AS value "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                f"FROM {_quote_ident(left_table)} AS {left_alias} "
                f"JOIN {_quote_ident(right_table)} AS {right_alias} "
                f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
                f"GROUP BY {group_expr} ORDER BY value DESC LIMIT {int(limit)}"
            )
            return (
                sql,
                "join_aggregation_group",
                aggregation,
                aggregation_column,
                {"column": "value", "direction": "desc"},
            )
        sql = (
            f"SELECT {agg_sql}({metric_expr}) AS value "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            f"FROM {_quote_ident(left_table)} AS {left_alias} "
            f"JOIN {_quote_ident(right_table)} AS {right_alias} "
            f"ON {left_alias}.{_quote_ident(left_column)} = {right_alias}.{_quote_ident(right_column)} "
            "LIMIT 1"
        )
        return sql, "join_aggregation", aggregation, aggregation_column, None

    return sql, reason, None, aggregation_column, None


def _build_join_planner(
    *,
    reason: str,
    state: _JoinPlanningState,
    selection: _JoinCandidateSelection,
    selected_score: float,
    low_confidence_threshold: float,
    low_confidence: bool,
    low_confidence_strict: bool,
    relationships: list[dict[str, Any]],
    selected_tables: list[str],
    join_plan_risk: dict[str, Any],
    dry_run_cardinality: dict[str, Any],
    join_statistics_snapshot: dict[str, Any],
    aggregation: str | None,
    aggregation_column: str | None,
    group_table: str | None,
    group_col: str | None,
    order_by: dict[str, Any] | None,
    limit: int,
    sql_fingerprint: str,
) -> dict[str, Any]:
    selected_plan = _selected_plan_candidates(state, selection)
    candidate_id = selection.candidate["candidate_id"]
    return {
        # Keep strategy stable for downstream compatibility; expose beam usage via mode.
        "strategy": "deterministic_join",
        "planner_mode": ("beam" if selection.selected_from_multi else "pairwise"),
        "reason": reason,
        "joins": relationships[: max(1, state.max_join_tables - 1)],
        "selected_tables": selected_tables,
        "candidates": state.candidate_rows[: state.top_n],
        "multi_candidates": state.multi_candidate_rows[: state.top_n],
        "selected_candidate_id": candidate_id,
        "selected_score": round(selected_score, 6),
        "ambiguous": selected_plan["ambiguous"],
        "ambiguity_gap": selected_plan["ambiguity_gap"],
        "strict_ambiguity": state.strict_ambiguity,
        "low_confidence": low_confidence,
        "low_confidence_threshold": round(low_confidence_threshold, 6),
        "strict_low_confidence": low_confidence_strict,
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
        "limit": limit,
        "sql_fingerprint": sql_fingerprint,
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
    max_rows_i = max(1, max_rows)
    limit = min(max_rows_i, _extract_question_limit(question, default_limit=min(max_rows_i, 20)))
    valid_tables = _normalize_join_tables(tables)
    if len(valid_tables) < 2:
        raise ValueError("at least two tables are required for join planning")

    state = _build_join_planning_state(valid_tables)
    selection = _select_join_candidate(valid_tables, state)
    selected_plan = _selected_plan_candidates(state, selection)
    if state.strict_ambiguity and selected_plan["ambiguous"]:
        raise ValueError("ambiguous_join_plan")

    selected_score, low_confidence_threshold, low_confidence, low_confidence_strict = _join_confidence_state(
        selection.candidate
    )
    if low_confidence and low_confidence_strict:
        raise ValueError("low_confidence_join_plan")

    rel = _selected_join_payload(selection.candidate)
    left_table = rel["left_table"].strip()
    right_table = rel["right_table"].strip()
    left_column = rel["left_column"].strip()
    right_column = rel["right_column"].strip()
    if not left_table or not right_table or not left_column or not right_column:
        raise ValueError("invalid_join_relationship")

    relationships = _dedupe_join_relationships(selection.candidate, state.candidate_rows)
    table_map = {t["table_name"]: t for t in valid_tables}
    selected_tables = list(selection.candidate["selected_tables"])

    alias_map = {left_table: "t0", right_table: "t1"}
    left_alias = alias_map[left_table]
    right_alias = alias_map[right_table]

    group_table, group_col = _pick_join_group_column(question, [table_map[left_table], table_map[right_table]])
    metric_table, metric_col = _pick_join_metric_column(question, [table_map[left_table], table_map[right_table]])
    sql, reason, aggregation, aggregation_column, order_by = _build_join_query_sql(
        question=question,
        limit=limit,
        left_table=left_table,
        right_table=right_table,
        left_column=left_column,
        right_column=right_column,
        alias_map=alias_map,
        left_alias=left_alias,
        right_alias=right_alias,
        group_table=group_table,
        group_col=group_col,
        metric_table=metric_table,
        metric_col=metric_col,
    )

    sql_fingerprint = fingerprint_sql(sql, length=16)
    dry_run_cardinality = _dry_run_join_cardinality(
        selected_candidate=selection.candidate,
        max_rows=max_rows_i,
    )
    join_plan_risk = _build_join_plan_risk_contract(
        selected_candidate=selection.candidate,
        dry_run_cardinality=dry_run_cardinality,
    )
    join_statistics_snapshot = build_join_statistics_snapshot(
        tables=valid_tables,
        top_n=state.top_n,
        ambiguity_score_gap=state.ambiguity_gap,
        max_states=max(8, state.max_join_tables * 8),
    )
    planner = _build_join_planner(
        reason=reason,
        state=state,
        selection=selection,
        selected_score=selected_score,
        low_confidence_threshold=low_confidence_threshold,
        low_confidence=low_confidence,
        low_confidence_strict=low_confidence_strict,
        relationships=relationships,
        selected_tables=selected_tables,
        join_plan_risk=join_plan_risk,
        dry_run_cardinality=dry_run_cardinality,
        join_statistics_snapshot=join_statistics_snapshot,
        aggregation=aggregation,
        aggregation_column=aggregation_column,
        group_table=group_table,
        group_col=group_col,
        order_by=order_by,
        limit=limit,
        sql_fingerprint=sql_fingerprint,
    )
    return {"sql": sql, "planner": planner}


def _extract_question_limit(question: str, *, default_limit: int) -> int:
    q = question.strip()
    if not q:
        return max(1, default_limit)

    patterns = [
        re.compile(r"(?i)\btop\s*(\d{1,4})\b"),
        re.compile(r"前\s*(\d{1,4})\s*[条行个]?"),
        re.compile(r"(?i)\blimit\s*(\d{1,4})\b"),
    ]
    for p in patterns:
        m = p.search(q)
        if not m:
            continue
        n = int(m.group(1))
        if n > 0:
            return max(1, n)
    return max(1, default_limit)


def _pick_numeric_column(columns: list[dict[str, Any]]) -> str | None:
    for c in columns:
        if not isinstance(c, dict):
            continue
        name = c["name"].strip()
        if not name:
            continue
        if _column_is_numeric(c):
            return name
    return None


def _pick_mentioned_column(question: str, columns: list[dict[str, Any]]) -> str | None:
    q = question
    q_fold = q.casefold()
    for _column, name in _iter_named_columns(columns):
        key = name.casefold() if name.isascii() else name
        if key and key in q_fold:
            return name
    return None


def _extract_group_terms(question: str) -> list[str]:
    terms: list[str] = []
    for pattern in (r"(?i)\bgroup\s+by\s+(\w+)", r"按\s*([A-Za-z0-9_\u4e00-\u9fff]+)\s*分组"):
        match = re.search(pattern, question)
        if match:
            terms.append(match.group(1).strip())
    return terms


def _find_group_term_match(
    question_terms: list[str], columns: list[dict[str, Any]], *, exclude: str | None = None
) -> str | None:
    for term in question_terms:
        if not term:
            continue
        for _column, name in _iter_filtered_named_columns(columns, exclude=exclude):
            if _match_text(name, term) or _match_text(term, name):
                return name
    return None


def _match_group_requested_column(
    question: str, question_fold: str, columns: list[dict[str, Any]], *, exclude: str | None = None
) -> str | None:
    for _column, name in _iter_filtered_named_columns(columns, exclude=exclude):
        key = name.casefold() if name.isascii() else name
        if key and key in (question_fold if name.isascii() else question):
            return name
    return None


def _pick_group_column(question: str, columns: list[dict[str, Any]], *, exclude: str | None = None) -> str | None:
    q = question
    if not q:
        return None
    q_fold = q.casefold()
    group_match = _find_group_term_match(_extract_group_terms(q), columns, exclude=exclude)
    if group_match:
        return group_match

    group_requested = any(k in q_fold for k in ("group by", "分组", "每个", "各"))
    if not group_requested:
        return None
    return _match_group_requested_column(q, q_fold, columns, exclude=exclude)


def _column_names(columns: list[dict[str, Any]]) -> list[str]:
    return [name for _column, name in _iter_named_columns(columns)]


def _match_explicit_filter_predicate(question: str, col_names: list[str]) -> tuple[str | None, str | None]:
    for col in col_names:
        pat = re.compile(
            rf"{re.escape(col)}\s*(?:=|==|is|equals?|eq|为|是|等于)\s*['\"“”]?([A-Za-z0-9_./:\-]+|[\u4e00-\u9fff]{{1,40}})",
            re.IGNORECASE,
        )
        match = pat.search(question)
        if not match:
            continue
        value = match.group(1).strip().strip(".,，。;；")
        if value:
            return col, value
    return None, None


def _sample_value_matches_preferred_column(col: str, col_names: list[str], preferred_column: str | None) -> bool:
    if not preferred_column:
        return True
    if _norm_key(preferred_column) == _norm_key(col):
        return True
    return preferred_column not in col_names


def _match_sample_value_filter(
    question: str,
    *,
    col_names: list[str],
    sample_rows: list[dict[str, Any]] | None,
    preferred_column: str | None,
) -> tuple[str | None, str | None]:
    for row in (sample_rows or [])[:12]:
        if not isinstance(row, dict):
            continue
        for key, value in list(row.items())[:40]:
            col = key.strip()
            if not col or (col_names and col not in col_names):
                continue
            if not _sample_value_matches_preferred_column(col, col_names, preferred_column):
                continue
            if value is None:
                continue
            sval = str(value).strip()
            if sval and _match_text(question, sval):
                return col, sval
    return None, None


def _infer_filter_predicate(
    *,
    question: str,
    columns: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]] | None = None,
    preferred_column: str | None = None,
) -> tuple[str | None, str | None, str]:
    q = question.strip()
    if not q:
        return None, None, "none"

    col_names = _column_names(columns)

    # Explicit predicate: `region = US` / `region 为 US` / `region is US`.
    explicit_col, explicit_val = _match_explicit_filter_predicate(q, col_names)
    if explicit_col and explicit_val is not None:
        return explicit_col, explicit_val, "explicit_predicate"

    # Quoted literals can be used when a target column is already mentioned.
    quoted_vals = _extract_quoted_literals(q, max_values=6)
    if quoted_vals and preferred_column:
        return preferred_column, quoted_vals[0], "quoted_literal"

    # Sample-value match fallback for unquoted values.
    sample_col, sample_val = _match_sample_value_filter(
        q,
        col_names=col_names,
        sample_rows=sample_rows,
        preferred_column=preferred_column,
    )
    if sample_col and sample_val is not None:
        return sample_col, sample_val, "sample_value_match"

    return None, None, "none"


def _infer_order_hint(
    *,
    question: str,
    default_column: str | None,
) -> tuple[str | None, str | None]:
    q_fold = question.casefold()
    has_order = any(k in q_fold for k in ("order by", "排序", "排名", "top", "前"))
    if not has_order:
        return None, None

    is_asc = any(k in q_fold for k in (" asc", "ascending", "升序", "最低", "最小", "least"))
    is_desc = any(k in q_fold for k in (" desc", "descending", "降序", "最高", "最大", "最多", "top", "前"))
    direction = "asc" if is_asc and not is_desc else "desc"
    return default_column, direction


def _infer_aggregation_plan(
    *,
    question_fold: str,
    selected_col: str | None,
    selected_col_q: str,
) -> tuple[str | None, str, str]:
    if any(k in question_fold for k in ("count", "how many", "多少", "几条", "几行", "总数", "数量")):
        return "count", "COUNT(*)", "count"
    if any(k in question_fold for k in ("sum", "total", "合计", "总和", "求和")) and selected_col:
        return "sum", f"SUM({selected_col_q})", "total"
    if any(k in question_fold for k in ("avg", "average", "均值", "平均")) and selected_col:
        return "avg", f"AVG({selected_col_q})", "avg"
    if any(k in question_fold for k in (" min", "minimum", "最小")) and selected_col:
        return "min", f"MIN({selected_col_q})", "min_value"
    if any(k in question_fold for k in (" max", "maximum", "最大")) and selected_col:
        return "max", f"MAX({selected_col_q})", "max_value"
    return None, "", ""


def _resolve_order_clause(
    *,
    order_col: str | None,
    order_dir: str | None,
    agg_alias: str,
) -> tuple[str, dict[str, Any] | None]:
    if not order_col or not order_dir:
        return "", None
    if agg_alias and _norm_key(order_col) == _norm_key(agg_alias):
        return f" ORDER BY {agg_alias} {order_dir.upper()}", {"column": agg_alias, "direction": order_dir}
    return f" ORDER BY {_quote_ident(order_col)} {order_dir.upper()}", {"column": order_col, "direction": order_dir}


def _render_single_table_sql(
    *,
    table_q: str,
    selected_col_q: str,
    where_clause: str,
    group_col_q: str | None,
    agg_kind: str | None,
    agg_expr: str,
    agg_alias: str,
    order_clause: str,
    order_diag: dict[str, Any] | None,
    limit: int,
) -> tuple[str, str, dict[str, Any] | None]:
    reason = "projection"
    if agg_kind and group_col_q:
        resolved_order_clause = order_clause or f" ORDER BY {agg_alias} DESC"
        resolved_order_diag = order_diag or {"column": agg_alias, "direction": "desc"}
        sql = (
            f"SELECT {group_col_q}, {agg_expr} AS {agg_alias} "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            f"FROM {table_q}{where_clause} GROUP BY {group_col_q}{resolved_order_clause} LIMIT {int(limit)}"
        )
        return sql, "aggregation_group", resolved_order_diag
    if agg_kind:
        sql = f"SELECT {agg_expr} AS {agg_alias} FROM {table_q}{where_clause} LIMIT 1"  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
        return sql, "aggregation", order_diag
    if group_col_q:
        resolved_order_clause = order_clause or " ORDER BY count DESC"
        resolved_order_diag = order_diag or {"column": "count", "direction": "desc"}
        sql = (
            f"SELECT {group_col_q}, COUNT(*) AS count "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
            f"FROM {table_q}{where_clause} GROUP BY {group_col_q}{resolved_order_clause} LIMIT {int(limit)}"
        )
        return sql, "group_count", resolved_order_diag

    sql = f"SELECT {selected_col_q} FROM {table_q}{where_clause}{order_clause} LIMIT {int(limit)}"  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
    if where_clause:
        reason = "filter_projection"
    elif order_clause:
        reason = "ordered_projection"
    return sql, reason, order_diag


def _generate_deterministic_sql_with_diagnostics(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    max_rows: int,
    sample_rows: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    q = " ".join(question.strip().split())
    if not q:
        raise ValueError(_QUESTION_REQUIRED)

    q_fold = q.casefold()
    max_rows_i = max(1, max_rows)
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

    agg_kind, agg_expr, agg_alias = _infer_aggregation_plan(
        question_fold=q_fold,
        selected_col=selected_col,
        selected_col_q=selected_col_q,
    )

    order_col, order_dir = _infer_order_hint(question=q, default_column=agg_alias if agg_alias else selected_col)
    order_clause, order_diag = _resolve_order_clause(order_col=order_col, order_dir=order_dir, agg_alias=agg_alias)
    sql, reason, order_diag = _render_single_table_sql(
        table_q=table_q,
        selected_col_q=selected_col_q,
        where_clause=where_clause,
        group_col_q=group_col_q,
        agg_kind=agg_kind,
        agg_expr=agg_expr,
        agg_alias=agg_alias,
        order_clause=order_clause,
        order_diag=order_diag,
        limit=limit,
    )

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
        "limit": limit,
        "selected_column": selected_col,
    }
    return sql, planner


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
    q = " ".join(question.strip().split())
    if not q:
        raise ValueError(_QUESTION_REQUIRED)

    max_rows_i = max(1, max_rows)
    schema_lines: list[str] = []
    for column in columns:
        if not isinstance(column, dict):
            continue
        name = column["name"].strip()
        dtype = column.get("dtype")
        if dtype is None:
            schema_lines.append(f"- {name} ()")
        else:
            schema_lines.append(f"- {name} ({dtype.strip()})")
    cols_str = "\n".join(schema_lines)
    cols_str = cols_str[:8000]

    system = SystemMessage(
        content=(
            "You are a meticulous data analyst. Your job is to translate a natural language question into a single "
            "SQLite SELECT query.\n\n"
            "Hard constraints:\n"
            f"- ONLY output SQL (no markdown, no explanations).\n"
            f"- The query MUST be SELECT-only (or WITH ... SELECT).\n"
            f'- The query MUST reference ONLY this table: "{sql_table}".\n'
            f"- You MUST include a LIMIT <= {max_rows_i}.\n"
            "- Never use PRAGMA/ATTACH/DETACH/CREATE/INSERT/UPDATE/DELETE/DROP.\n"
        )
    )
    user = HumanMessage(
        content=(f'Table name: "{sql_table}"\nColumns:\n{cols_str if cols_str else "(unknown)"}\n\nQuestion: {q}\n')
    )

    llm = create_table_chat_model(temperature=0.0)
    resp = llm.invoke([system, user])
    sql = extract_sql(resp.text)
    return sql


def _sql_generation_result(
    sql: str,
    mode: str,
    planner: dict[str, Any],
    schema_link: _SchemaLinkDiagnostics,
) -> tuple[str, str, dict[str, Any]]:
    return (
        sql,
        mode,
        {
            "schema_link": schema_link,
            "planner": planner,
            "sql_fingerprint": planner["sql_fingerprint"],
            "schema_link_score": schema_link["score"],
            "schema_link_strategy": schema_link["strategy"],
        },
    )


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

    """
    deterministic_only = settings.TABLE_NL2SQL_DETERMINISTIC_ONLY
    deterministic_fallback = settings.TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED
    llm_key = settings.LLM_API_KEY.strip()

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
        return _sql_generation_result(sql, "deterministic", planner, schema_link)

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
                "limit": max(1, max_rows),
                "sql_fingerprint": fingerprint_sql(sql, length=16),
            }
            return _sql_generation_result(sql, "llm", planner, schema_link)
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
            return _sql_generation_result(sql, "deterministic", planner, schema_link)

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
        return _sql_generation_result(sql, "deterministic", planner, schema_link)

    raise RuntimeError("LLM_API_KEY is not configured and deterministic fallback is disabled")


def generate_sql_for_table(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    max_rows: int,
) -> str:
    """
    Generate SQL for callers that do not consume planning diagnostics.
    """
    sql, _mode, _metadata = generate_sql_for_table_with_metadata(
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
    if not settings.TABLE_LLM_ALLOW_RESULT_EGRESS:
        raise RuntimeError("TABLE_LLM_ALLOW_RESULT_EGRESS=false")

    q = " ".join(question.strip().split())
    if not q:
        raise ValueError(_QUESTION_REQUIRED)

    # Keep payload bounded; SQL executor already caps, but double-guard here.
    preview = {
        "sql": sql[:20_000],
        "columns": result["columns"],
        "rows": result["rows"],
        "truncated": result["truncated"],
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
    user = HumanMessage(content=(f"Question: {q}\n\nSQL: {sql.strip()}\n\nResult: {preview_text}\n"))
    llm = create_table_chat_model(temperature=0.0)
    resp = llm.invoke([system, user])
    return resp.text.strip()
