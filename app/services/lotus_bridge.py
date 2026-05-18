"""
LOTUS-like semantic operators (integrated, dependency-light).

Background
----------
The upstream LOTUS project provides DataFrame semantic operators (sem_filter/sem_join/...)
but pulls in a dependency set (e.g. litellm, pydantic constraints) that may not match
this project's runtime. For MimirQ we only need a small subset for TAG UX:

- semantic filtering of rows based on a natural-language instruction

We therefore implement a minimal, safe version here:
- Uses the project's existing LLM config (OpenAI-compatible) via LangChain ChatOpenAI.
- Sends bounded, compact row payloads (limits rows/cols/cell sizes).
- Requires explicit feature flags; no implicit network calls.

Note: This is *not* a drop-in replacement for full LOTUS. It is intentionally scoped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd  # type: ignore
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.openai_compat import normalize_openai_compatible_base_url
from app.rag.core.code_fence import extract_first_code_fence


@dataclass(frozen=True)
class LotusAvailability:
    ok: bool
    reason: str | None = None


def lotus_available() -> LotusAvailability:
    """
    Backwards-compatible guard used by the tables API.

    This returns whether semantic ops are *runnable* in the current environment.
    """
    if not bool(getattr(settings, "TABLE_LOTUS_ENABLED", False)):
        return LotusAvailability(ok=False, reason="TABLE_LOTUS_ENABLED=false")
    if not str(getattr(settings, "LLM_API_KEY", "") or "").strip():
        return LotusAvailability(ok=False, reason="LLM_API_KEY is not configured")
    if not bool(getattr(settings, "TABLE_LLM_ALLOW_ROW_EGRESS", False)):
        return LotusAvailability(ok=False, reason="TABLE_LLM_ALLOW_ROW_EGRESS=false")
    return LotusAvailability(ok=True)


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


def _extract_json_array(text: str) -> list[Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    # Direct JSON.
    try:
        obj = json.loads(raw)
    except Exception:
        obj = None
    if isinstance(obj, list):
        return obj

    # Fenced JSON.
    inner = extract_first_code_fence(raw, allowed_info_strings={"", "json"})
    if inner:
        try:
            obj2 = json.loads(inner)
        except Exception:
            obj2 = None
        if isinstance(obj2, list):
            return obj2

    # Heuristic slice from first '[' to last ']'.
    i = raw.find("[")
    j = raw.rfind("]")
    if 0 <= i < j:
        chunk = raw[i : j + 1]
        try:
            obj3 = json.loads(chunk)
        except Exception:
            obj3 = None
        if isinstance(obj3, list):
            return obj3

    return None


def _jsonify_value(v: Any, *, max_chars: int) -> Any:
    if v is None:
        return None
    if isinstance(v, (bool, int, float)):
        return v
    # Keep strings bounded.
    s = str(v)
    if max_chars > 0 and len(s) > int(max_chars):
        return s[: int(max_chars)] + "..."
    return s


def _build_row_payload(
    df: "pd.DataFrame",
    *,
    max_rows: int,
    max_cols: int,
    max_cell_chars: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    cols = [str(c) for c in (getattr(df, "columns", []) or [])]
    if max_cols > 0 and len(cols) > int(max_cols):
        cols = cols[: int(max_cols)]
    df2 = df.loc[:, cols] if cols else df

    rows: list[dict[str, Any]] = []
    for i, row in enumerate(df2.itertuples(index=False, name=None)):  # type: ignore[attr-defined]
        if max_rows > 0 and i >= int(max_rows):
            break
        rec: dict[str, Any] = {}
        for k, v in zip(cols, row, strict=False):
            rec[str(k)] = _jsonify_value(v, max_chars=max_cell_chars)
        rows.append(rec)
    return cols, rows


def sem_filter(
    df: "pd.DataFrame",
    *,
    user_instruction: str,
    strategy: str = "cot",
) -> "pd.DataFrame":
    """
    Semantic filter over a DataFrame (row-wise).

    Returns a filtered DataFrame containing only rows that satisfy `user_instruction`.

    Notes:
    - This is an LLM-backed operator; keep it behind feature flags and row caps.
    - `strategy` is accepted for API compatibility; currently it only toggles prompting style.
    """
    _ = strategy
    instr = " ".join(str(user_instruction or "").strip().split())
    if not instr:
        raise ValueError("user_instruction is required")
    if not bool(getattr(settings, "TABLE_LLM_ALLOW_ROW_EGRESS", False)):
        raise RuntimeError("TABLE_LLM_ALLOW_ROW_EGRESS=false")

    # Apply conservative caps before serializing rows to the LLM.
    max_in_rows = int(getattr(settings, "TABLE_SEM_FILTER_MAX_IN_ROWS", 2000) or 2000)
    max_cols = int(getattr(settings, "TABLE_SEM_FILTER_MAX_COLS", 30) or 30)
    max_cell_chars = int(getattr(settings, "TABLE_SEM_FILTER_MAX_CELL_CHARS", 200) or 200)
    batch_size = int(getattr(settings, "TABLE_SEM_FILTER_BATCH_SIZE", 25) or 25)

    if max_in_rows > 0 and len(df) > max_in_rows:
        df = df.head(max_in_rows)

    cols, rows = _build_row_payload(df, max_rows=max_in_rows, max_cols=max_cols, max_cell_chars=max_cell_chars)
    if not rows:
        return df.head(0)

    llm = _build_llm(temperature=0.0)

    system = SystemMessage(
        content=(
            "You are a meticulous data analyst.\n"
            "For each table row, decide whether it satisfies the user's instruction.\n\n"
            "Hard constraints:\n"
            "- Output ONLY a JSON array of booleans (true/false).\n"
            "- The array length MUST equal the number of input rows.\n"
            "- Do NOT output any explanations or markdown.\n"
        )
    )

    flags: list[bool] = []

    def _coerce_bool_list(obj: list[Any], *, expected: int) -> list[bool]:
        out: list[bool] = []
        for x in obj:
            if isinstance(x, bool):
                out.append(bool(x))
            elif isinstance(x, (int, float)) and x in (0, 1):
                out.append(bool(int(x)))
            elif isinstance(x, str):
                s = x.strip().lower()
                if s in {"true", "t", "yes", "y", "1"}:
                    out.append(True)
                elif s in {"false", "f", "no", "n", "0"}:
                    out.append(False)
                else:
                    out.append(False)
            else:
                out.append(False)
            if len(out) >= expected:
                break
        # Pad to expected with False (fail-closed).
        while len(out) < expected:
            out.append(False)
        return out[:expected]

    for i in range(0, len(rows), max(1, batch_size)):
        chunk = rows[i : i + max(1, batch_size)]
        payload = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        if len(payload) > 80_000:
            # Defensive truncation: if rows are wide even after caps, shrink the batch.
            chunk = chunk[: max(1, len(chunk) // 2)]
            payload = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))

        user = HumanMessage(
            content=(
                f"Instruction: {instr}\n"
                f"Columns: {', '.join(cols) if cols else '(unknown)'}\n"
                f"Rows(JSON): {payload}\n"
                "Return JSON array:"
            )
        )
        resp = llm.invoke([system, user])
        raw = str(getattr(resp, "content", "") or "").strip()
        arr = _extract_json_array(raw)
        if arr is None:
            # Fail closed for the whole batch.
            flags.extend([False] * len(chunk))
            continue
        flags.extend(_coerce_bool_list(arr, expected=len(chunk)))

    if not flags:
        return df.head(0)
    # Align length just in case.
    if len(flags) < len(df):
        flags.extend([False] * (len(df) - len(flags)))
    flags = flags[: len(df)]

    try:
        mask = pd.Series(flags, index=df.index)
        return df[mask]
    except Exception:
        # Best-effort fallback: manual filtering.
        keep_idx = [idx for idx, ok in zip(list(df.index), flags, strict=False) if ok]
        return df.loc[keep_idx]


__all__ = ["LotusAvailability", "lotus_available", "sem_filter"]
