import json
from pathlib import Path
from typing import Any

from app.rag.core.logging import get_logger


def _read_tail_bytes(path: Path, *, max_bytes: int) -> tuple[bytes, bool] | None:
    limit = max(1, int(max_bytes or 0))
    try:
        size = int(path.stat().st_size)
    except Exception:
        return None
    start = max(0, size - limit)
    try:
        with path.open("rb") as file_handle:
            if start:
                file_handle.seek(start)
            raw = file_handle.read()
    except Exception:
        return None
    if start:
        newline = raw.find(b"\n")
        if newline >= 0:
            raw = raw[newline + 1 :]
    return raw, start > 0


def _decode_records(raw: bytes, *, log_message: str) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return []
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        item = (line or "").strip()
        if not item:
            continue
        try:
            value = json.loads(item)
        except Exception:
            get_logger(__name__).debug(log_message, exc_info=True)
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def read_jsonl_tail(
    path: Path,
    *,
    max_bytes: int,
    log_message: str = "Skipping item after non-critical exception",
) -> tuple[list[dict[str, Any]], bool]:
    tail = _read_tail_bytes(path, max_bytes=max_bytes)
    if tail is None:
        return [], False
    raw, truncated = tail
    return _decode_records(raw, log_message=log_message), truncated


__all__ = ["read_jsonl_tail"]
