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


def _generate_deterministic_sql(
    *,
    question: str,
    sql_table: str,
    columns: list[dict[str, Any]],
    max_rows: int,
) -> str:
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

    is_count = any(k in q_fold for k in ("count", "how many", "多少", "几条", "几行", "总数", "数量"))
    is_sum = any(k in q_fold for k in ("sum", "total", "合计", "总和", "求和"))
    is_avg = any(k in q_fold for k in ("avg", "average", "均值", "平均"))
    is_min = any(k in q_fold for k in (" min", "minimum", "最小"))
    is_max = any(k in q_fold for k in (" max", "maximum", "最大"))

    if is_count:
        return f"SELECT COUNT(*) AS count FROM {table_q} LIMIT 1"

    if is_sum and selected_col:
        return f"SELECT SUM({selected_col_q}) AS total FROM {table_q} LIMIT 1"

    if is_avg and selected_col:
        return f"SELECT AVG({selected_col_q}) AS avg FROM {table_q} LIMIT 1"

    if is_min and selected_col:
        return f"SELECT MIN({selected_col_q}) AS min_value FROM {table_q} LIMIT 1"

    if is_max and selected_col:
        return f"SELECT MAX({selected_col_q}) AS max_value FROM {table_q} LIMIT 1"

    return f"SELECT {selected_col_q} FROM {table_q} LIMIT {int(limit)}"


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
    deterministic_only = bool(getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", False))
    deterministic_fallback = bool(getattr(settings, "TABLE_NL2SQL_DETERMINISTIC_FALLBACK_ENABLED", True))
    llm_key = str(getattr(settings, "LLM_API_KEY", "") or "").strip()

    if deterministic_only:
        return _generate_deterministic_sql(
            question=question,
            sql_table=sql_table,
            columns=columns,
            max_rows=max_rows,
        ), "deterministic"

    if llm_key:
        try:
            return _generate_sql_with_llm(
                question=question,
                sql_table=sql_table,
                columns=columns,
                max_rows=max_rows,
            ), "llm"
        except Exception:
            if not deterministic_fallback:
                raise

    if deterministic_fallback:
        return _generate_deterministic_sql(
            question=question,
            sql_table=sql_table,
            columns=columns,
            max_rows=max_rows,
        ), "deterministic"

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
