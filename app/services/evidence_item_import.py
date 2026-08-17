
import csv
import io
import json
import os
import re
from collections.abc import Iterable, Sequence
from typing import Any

_QUERY_KEYS = ("query", "question", "q")
_EXPECTED_ANSWER_KEYS = ("expected_answer", "expected", "answer", "expectedAnswer", "expected_answer_text")
_TAGS_KEYS = ("tags", "tag")
_QUERY_REQUIRED_ERROR = "query is required"


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _normalize_query(query: str) -> str:
    # Keep it deterministic and user-visible. Collapse whitespace to reduce accidental dupes.
    return " ".join(str(query or "").strip().split())


def _parse_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = [str(x or "").strip() for x in value]
    else:
        s = str(value or "").strip()
        if not s:
            return []
        # If it's JSON, prefer that.
        if s.startswith("[") and s.endswith("]"):
            try:
                obj = json.loads(s)
                if isinstance(obj, list):
                    raw = [str(x or "").strip() for x in obj]
                else:
                    raw = [s]
            except Exception:
                raw = re.split(r"[,;|]\s*", s)
        else:
            raw = re.split(r"[,;|]\s*", s)

    out: list[str] = []
    seen: set[str] = set()
    for t in raw:
        tag = str(t or "").strip()
        if not tag:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _parse_source_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    s = str(value or "").strip()
    if not s:
        return {}
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return dict(obj)
        except Exception:
            return {"source": s}
    return {"source": s}


def _pick_first(mapping: dict[str, Any], keys: Sequence[str]) -> Any:
    for k in keys:
        if k in mapping:
            return mapping.get(k)
        # Common CSV variants.
        lk = k.lower()
        for mk in mapping.keys():
            if str(mk or "").strip().lower() == lk:
                return mapping.get(mk)
    return None


def _coerce_record(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if hasattr(raw, "model_dump"):
        return raw.model_dump(mode="json")
    if isinstance(raw, dict):
        return dict(raw)
    return {"query": getattr(raw, "query", None), "expected_answer": getattr(raw, "expected_answer", None)}


def _build_item(payload: dict[str, Any]) -> dict[str, Any]:
    query_raw = _pick_first(payload, _QUERY_KEYS)
    expected_raw = _pick_first(payload, _EXPECTED_ANSWER_KEYS)
    tags_raw = _pick_first(payload, _TAGS_KEYS)

    query = _normalize_query(_coerce_str(query_raw))
    expected_answer = _coerce_str(expected_raw).strip() if expected_raw is not None else None
    if expected_answer == "":
        expected_answer = None

    tags = _parse_tags(tags_raw)

    # "source metadata" is a catch-all. We treat an explicit `source_metadata`/`metadata`/`source` key specially,
    # and otherwise carry through unknown columns/keys.
    source_meta = {}
    for key in ("source_metadata", "source_meta", "metadata", "source"):
        if key in payload and payload.get(key) is not None:
            source_meta.update(_parse_source_metadata(payload.get(key)))
            break

    reserved = {k.lower() for k in (*_QUERY_KEYS, *_EXPECTED_ANSWER_KEYS, *_TAGS_KEYS, "source_metadata", "source_meta", "metadata", "source")}
    for k, v in (payload or {}).items():
        kk = str(k or "").strip()
        if not kk:
            continue
        if kk.lower() in reserved:
            continue
        if v is None:
            continue
        # Keep simple JSON-friendly primitives.
        source_meta.setdefault(kk, v)

    return {
        "query": query,
        "expected_answer": expected_answer,
        "tags": tags,
        "source_metadata": source_meta,
    }


def _append_import_item(
    *,
    items: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    payload: dict[str, Any],
    error_key: str,
    error_value: int,
) -> None:
    item = _build_item(payload)
    if item.get("query"):
        items.append(item)
        return
    errors.append({error_key: error_value, "error": _QUERY_REQUIRED_ERROR})


def _parse_csv_import_text(*, text: str, cap: int, items: list[dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    reader = csv.DictReader(io.StringIO(text))
    for idx, row in enumerate(reader):
        if row is None:
            continue
        _append_import_item(items=items, errors=errors, payload=_coerce_record(row), error_key="index", error_value=idx)
        if len(items) >= cap:
            break


def _parse_jsonl_import_text(*, text: str, cap: int, items: list[dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    for idx, line in enumerate(text.splitlines(), start=1):
        ln = line.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            errors.append({"line": idx, "error": "invalid JSON"})
            continue
        _append_import_item(items=items, errors=errors, payload=_coerce_record(obj), error_key="line", error_value=idx)
        if len(items) >= cap:
            break


def parse_qa_faq_import_bytes(
    *,
    raw: bytes,
    filename: str | None,
    max_items: int = 2000,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Parse a QA/FAQ import file into normalized EvidenceItem-like payloads.

    Supported formats:
    - CSV: requires a header row
    - JSONL: one JSON object per line
    """
    cap = max(1, min(10_000, int(max_items or 0))) if max_items else 2000
    name = str(filename or "").strip()
    ext = os.path.splitext(name.lower())[1]

    errors: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []

    # Decode as UTF-8 (with optional BOM). CSV/JSONL are expected to be UTF-8.
    try:
        text = raw.decode("utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid encoding (expect UTF-8)") from exc

    if ext == ".csv":
        _parse_csv_import_text(text=text, cap=cap, items=items, errors=errors)
    elif ext == ".jsonl":
        _parse_jsonl_import_text(text=text, cap=cap, items=items, errors=errors)
    else:
        raise ValueError("unsupported file type (expect .csv or .jsonl)")

    return items, errors


def plan_evidence_item_import(
    *,
    existing_queries: set[str],
    items: Iterable[dict[str, Any]],
    max_items: int = 2000,
) -> dict[str, Any]:
    """
    Plan draft EvidenceItem inserts using query.strip() as a stable key.

    Returns counts plus `create_items` for the API layer.
    """
    cap = max(1, min(10_000, int(max_items or 0))) if max_items else 2000

    created = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    create_items: list[dict[str, Any]] = []
    seen: set[str] = set()

    items_list = list(items or [])

    for idx, raw in enumerate(items_list[:cap]):
        payload = _coerce_record(raw) if not isinstance(raw, dict) else dict(raw)
        query = _normalize_query(_coerce_str(payload.get("query")))
        if not query:
            skipped += 1
            errors.append({"index": idx, "error": _QUERY_REQUIRED_ERROR})
            continue

        if query in seen:
            skipped += 1
            errors.append({"index": idx, "query": query, "error": "duplicate query in import batch"})
            continue
        seen.add(query)

        if query in existing_queries:
            skipped += 1
            continue

        # Ensure normalized fields are present and JSON-friendly.
        payload["query"] = query
        if "expected_answer" not in payload:
            payload["expected_answer"] = None
        payload["tags"] = list(payload.get("tags") or [])
        src = payload.get("source_metadata")
        payload["source_metadata"] = dict(src) if isinstance(src, dict) else {}

        created += 1
        create_items.append(payload)

    # If input is larger than cap, treat remaining items as skipped.
    if items_list and len(items_list) > cap:
        skipped += len(items_list) - cap
        errors.append({"error": "max_items exceeded", "max_items": cap, "ignored": len(items_list) - cap})

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "create_items": create_items,
    }
