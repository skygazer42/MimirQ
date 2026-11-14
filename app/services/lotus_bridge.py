"""
LOTUS-like semantic operators (integrated, dependency-light).

Background
----------
The upstream LOTUS project provides DataFrame semantic operators (sem_filter/sem_join/...)
but pulls in a dependency set (e.g. litellm, pydantic constraints) that may not match
this project's runtime. Ragvia only needs a small subset for TAG UX:

- semantic filtering of rows based on a natural-language instruction

We therefore implement a minimal, safe version here:
- Uses the project's existing LLM config (OpenAI-compatible) via LangChain ChatOpenAI.
- Sends bounded, compact row payloads (limits rows/cols/cell sizes).
- Requires explicit feature flags; no implicit network calls.

Note: This is *not* a drop-in replacement for full LOTUS. It is intentionally scoped.
"""

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd  # type: ignore
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.rag.core.code_fence import extract_first_code_fence
from app.services.table_tag_service import create_table_chat_model


@dataclass(frozen=True)
class LotusAvailability:
    ok: bool
    reason: str | None = None


def get_lotus_availability() -> LotusAvailability:
    """Return semantic-operation configuration eligibility and its reason without a provider probe."""
    if not settings.TABLE_LOTUS_ENABLED:
        return LotusAvailability(ok=False, reason="TABLE_LOTUS_ENABLED=false")
    if not settings.LLM_API_KEY.strip():
        return LotusAvailability(ok=False, reason="LLM_API_KEY is not configured")
    if not settings.TABLE_LLM_ALLOW_ROW_EGRESS:
        return LotusAvailability(ok=False, reason="TABLE_LLM_ALLOW_ROW_EGRESS=false")
    return LotusAvailability(ok=True)


def _extract_json_array(text: str) -> list[Any] | None:
    raw = text.strip()
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
    if max_chars > 0 and len(s) > max_chars:
        return s[:max_chars] + "..."
    return s


def _build_row_payload(
    df: "pd.DataFrame",
    *,
    max_rows: int,
    max_cols: int,
    max_cell_chars: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    cols = [str(c) for c in df.columns]
    if max_cols > 0 and len(cols) > max_cols:
        cols = cols[:max_cols]
    df2 = df.loc[:, cols] if cols else df

    rows: list[dict[str, Any]] = []
    for i, row in enumerate(df2.itertuples(index=False, name=None)):  # type: ignore[attr-defined]
        if max_rows > 0 and i >= max_rows:
            break
        rec: dict[str, Any] = {}
        for k, v in zip(cols, row, strict=False):
            rec[k] = _jsonify_value(v, max_chars=max_cell_chars)
        rows.append(rec)
    return cols, rows


def _normalized_sem_filter_instruction(user_instruction: str) -> str:
    return " ".join(user_instruction.strip().split())


def _sem_filter_limits() -> tuple[int, int, int, int]:
    max_in_rows = settings.TABLE_SEM_FILTER_MAX_IN_ROWS
    max_cols = settings.TABLE_SEM_FILTER_MAX_COLS
    max_cell_chars = settings.TABLE_SEM_FILTER_MAX_CELL_CHARS or 200
    batch_size = settings.TABLE_SEM_FILTER_BATCH_SIZE or 25
    return max_in_rows, max_cols, max_cell_chars, batch_size


def _coerce_bool_list(obj: list[Any], *, expected: int) -> list[bool]:
    out: list[bool] = []
    for x in obj:
        if isinstance(x, bool):
            out.append(x)
        elif isinstance(x, (int, float)) and x in (0, 1):
            out.append(bool(x))
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

    while len(out) < expected:
        out.append(False)
    return out[:expected]


def _sem_filter_batch_prompt(
    *,
    instr: str,
    cols: list[str],
    chunk: list[dict[str, Any]],
) -> HumanMessage:
    payload = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
    if len(payload) > 80_000:
        chunk = chunk[: max(1, len(chunk) // 2)]
        payload = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
    return HumanMessage(
        content=(
            f"Instruction: {instr}\n"
            f"Columns: {', '.join(cols) if cols else '(unknown)'}\n"
            f"Rows(JSON): {payload}\n"
            "Return JSON array:"
        )
    )


def _invoke_sem_filter_batch(
    *,
    llm: ChatOpenAI,
    system: SystemMessage,
    instr: str,
    cols: list[str],
    chunk: list[dict[str, Any]],
) -> list[bool]:
    user = _sem_filter_batch_prompt(instr=instr, cols=cols, chunk=chunk)
    resp = llm.invoke([system, user])
    raw = resp.text.strip()
    arr = _extract_json_array(raw)
    if arr is None:
        return [False] * len(chunk)
    return _coerce_bool_list(arr, expected=len(chunk))


def sem_filter(
    df: "pd.DataFrame",
    *,
    user_instruction: str,
) -> "pd.DataFrame":
    """
    Semantic filter over a DataFrame (row-wise).

    Returns a filtered DataFrame containing only rows that satisfy `user_instruction`.

    Notes:
    - This is an LLM-backed operator; keep it behind feature flags and row caps.
    """
    instr = _normalized_sem_filter_instruction(user_instruction)
    if not instr:
        raise ValueError("user_instruction is required")
    if not settings.TABLE_LLM_ALLOW_ROW_EGRESS:
        raise RuntimeError("TABLE_LLM_ALLOW_ROW_EGRESS=false")

    max_in_rows, max_cols, max_cell_chars, batch_size = _sem_filter_limits()
    if max_in_rows > 0 and len(df) > max_in_rows:
        df = df.head(max_in_rows)

    cols, rows = _build_row_payload(df, max_rows=max_in_rows, max_cols=max_cols, max_cell_chars=max_cell_chars)
    if not rows:
        return df.head(0)

    llm = create_table_chat_model(temperature=0.0)

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
    step = max(1, batch_size)
    for i in range(0, len(rows), step):
        chunk = rows[i : i + step]
        flags.extend(
            _invoke_sem_filter_batch(
                llm=llm,
                system=system,
                instr=instr,
                cols=cols,
                chunk=chunk,
            )
        )

    return df[pd.Series(flags, index=df.index)]


__all__ = ["LotusAvailability", "get_lotus_availability", "sem_filter"]
