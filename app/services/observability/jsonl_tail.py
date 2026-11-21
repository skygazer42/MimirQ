import json
import logging
from pathlib import Path
from typing import Any

_logger = logging.getLogger("app.services.jsonl_tail")


def _read_tail_bytes(path: Path, *, max_bytes: int) -> tuple[bytes | None, bool]:
    limit = max(1, max_bytes)
    try:
        size = path.stat().st_size
    except (OSError, ValueError):
        return None, False
    start = max(0, size - limit)
    partial_first_line = False
    try:
        with path.open("rb") as file_handle:
            if start:
                file_handle.seek(start - 1)
                partial_first_line = file_handle.read(1) != b"\n"
            raw = file_handle.read(limit)
    except (OSError, ValueError):
        return None, start > 0
    if partial_first_line:
        newline = raw.find(b"\n")
        raw = raw[newline + 1 :] if newline >= 0 else b""
    return raw, start > 0


def _decode_records(raw: bytes, *, logger: logging.Logger, log_message: str) -> list[dict[str, Any]]:
    text = raw.decode("utf-8", errors="replace")
    records: list[dict[str, Any]] = []
    for line in text.split("\n"):
        item = line.strip()
        if not item:
            continue
        try:
            value = json.loads(item)
        except (ValueError, RecursionError):
            logger.debug(log_message, exc_info=True)
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def read_jsonl_tail(
    path: str | Path,
    *,
    max_bytes: int,
    logger: logging.Logger = _logger,
    log_message: str = "Skipping item after non-critical exception",
) -> tuple[list[dict[str, Any]], bool]:
    """Read bounded JSONL object records and indicate whether the file exceeded the limit."""
    raw, truncated = _read_tail_bytes(Path(path), max_bytes=max_bytes)
    if raw is None:
        return [], truncated
    return _decode_records(raw, logger=logger, log_message=log_message), truncated


__all__ = ["read_jsonl_tail"]
