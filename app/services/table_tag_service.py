"""
TAG (Table Augmented Generation) helpers: NL->SQL + answer drafting.

This is intentionally conservative:
- The SQL produced must be SELECT-only and is validated again by the SQL executor.
- Result size is strictly bounded (rows/cols/bytes) before being passed back to the model.
"""

from __future__ import annotations

from typing import Any
import re

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.core.config import settings


_FENCE_RE = re.compile(r"```(?:sql)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def _build_llm(*, temperature: float = 0.0) -> ChatOpenAI:
    model_name = (getattr(settings, "LLM_MODEL_FAST", None) or getattr(settings, "LLM_MODEL", None) or "").strip()
    if not model_name:
        model_name = "gpt-4o-mini"
    return ChatOpenAI(
        model=model_name,
        api_key=getattr(settings, "LLM_API_KEY", None),
        base_url=getattr(settings, "LLM_API_BASE", None),
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


def generate_sql_for_table(
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
