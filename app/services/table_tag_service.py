"""
TAG (Table Augmented Generation) helpers: NL->SQL + answer drafting.

This is intentionally conservative:
- The SQL produced must be SELECT-only and is validated again by the SQL executor.
- Result size is strictly bounded (rows/cols/bytes) before being passed back to the model.
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url

_FENCE_RE = re.compile(r"```(?:sql)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
_SCHEMA_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?")
_QUOTED_LITERAL_RE = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{1,80})[\"“”'‘’]")
_NUMERIC_LITERAL_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _build_llm(*, temperature: float = 0.0) -> ChatOpenAI:
    model_name = (getattr(settings, "LLM_MODEL_FAST", None) or getattr(settings, "LLM_MODEL", None) or "").strip()
    if not model_name:
        model_name = "gpt-4o-mini"
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
    m = _FENCE_RE.search(raw)
    if m:
        raw = (m.group(1) or "").strip()
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


def _extract_question_limit(question: str, *, default_limit: int) -> int:
    q = str(question or "").strip()
    if not q:
        return max(1, int(default_limit or 1))

    patterns = [
        re.compile(r"(?i)\btop\s*(\d{1,4})\b"),
        re.compile(r"前\s*(\d{1,4})\s*(条|行|个)?"),
        re.compile(r"(?i)\blimit\s*(\d{1,4})\b"),
    ]
    for p in patterns:
        m = p.search(q)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except Exception:
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
    m_en = re.search(r"(?i)\bgroup\s+by\s+([A-Za-z0-9_]+)", q)
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
        raise ValueError("question is required")

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
    sql = f"SELECT {selected_col_q} FROM {table_q}{where_clause} LIMIT {int(limit)}"
    if agg_kind and group_col_q:
        if not order_clause:
            order_clause = f" ORDER BY {agg_alias} DESC"
            order_diag = {"column": agg_alias, "direction": "desc"}
        sql = (
            f"SELECT {group_col_q}, {agg_expr} AS {agg_alias} "
            f"FROM {table_q}{where_clause} GROUP BY {group_col_q}{order_clause} LIMIT {int(limit)}"
        )
        reason = "aggregation_group"
    elif agg_kind:
        sql = f"SELECT {agg_expr} AS {agg_alias} FROM {table_q}{where_clause} LIMIT 1"
        reason = "aggregation"
    elif group_col_q:
        if not order_clause:
            order_clause = " ORDER BY count DESC"
            order_diag = {"column": "count", "direction": "desc"}
        sql = (
            f"SELECT {group_col_q}, COUNT(*) AS count "
            f"FROM {table_q}{where_clause} GROUP BY {group_col_q}{order_clause} LIMIT {int(limit)}"
        )
        reason = "group_count"
    else:
        sql = f"SELECT {selected_col_q} FROM {table_q}{where_clause}{order_clause} LIMIT {int(limit)}"
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
        raise ValueError("question is required")

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
        return sql, "deterministic", {
            "schema_link": schema_link,
            "planner": planner,
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
            }
            return sql, "llm", {
                "schema_link": schema_link,
                "planner": planner,
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
            return sql, "deterministic", {
                "schema_link": schema_link,
                "planner": planner,
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
        return sql, "deterministic", {
            "schema_link": schema_link,
            "planner": planner,
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
        raise ValueError("question is required")

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
