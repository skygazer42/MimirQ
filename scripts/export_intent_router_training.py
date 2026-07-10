#!/usr/bin/env python3
"""
Export intent-router training rows from retrieval traces / metrics payloads.
"""


import argparse
import json
from pathlib import Path
from typing import Any


def _resolve_path_under_cwd(raw_path: str, *, must_exist: bool) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise SystemExit("path_required")

    base = Path.cwd().resolve(strict=False)
    candidate = Path(raw).expanduser()
    resolved = candidate.resolve(strict=False) if candidate.is_absolute() else (base / candidate).resolve(strict=False)
    try:
        resolved.relative_to(base)
    except Exception as exc:
        raise SystemExit(f"path_outside_cwd_not_allowed: {raw}") from exc

    if must_exist and not resolved.exists():
        raise SystemExit(f"path_not_found: {resolved}")
    return resolved


def _load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    stripped = text.strip()
    if not stripped:
        return []

    # JSONL
    if "\n" in stripped and stripped[0] != "[":
        out: list[dict[str, Any]] = []
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
        return out

    # JSON object / array
    obj = json.loads(stripped)
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        if isinstance(obj.get("items"), list):
            return [x for x in obj.get("items") if isinstance(x, dict)]
        return [obj]
    return []


def _extract_query(record: dict[str, Any]) -> str:
    for key in ("question", "query", "query_for_retrieval"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.strip().split())

    qd = record.get("query_debug")
    if isinstance(qd, dict):
        for key in ("query_for_retrieval", "normalized", "original"):
            value = qd.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.strip().split())
    return ""


def _extract_label_overrides(record: dict[str, Any]) -> dict[str, Any]:
    metrics = record.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    out: dict[str, Any] = {}

    mode = metrics.get("retrieval_mode") if metrics.get("retrieval_mode") is not None else record.get("retrieval_mode")
    if isinstance(mode, str) and mode.strip():
        out["retrieval_mode"] = mode.strip().lower()

    profile = (
        metrics.get("retrieval_profile")
        if metrics.get("retrieval_profile") is not None
        else record.get("retrieval_profile")
    )
    if isinstance(profile, str) and profile.strip():
        out["retrieval_profile"] = profile.strip().lower()

    if metrics.get("intent_router_used") is not None:
        out["intent_router_used"] = bool(metrics.get("intent_router_used"))

    if metrics.get("must_recall_enabled") is not None:
        out["must_recall_enabled"] = bool(metrics.get("must_recall_enabled"))

    return out


def export_training_rows(
    *,
    records: list[dict[str, Any]],
    max_items: int = 20_000,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        query = _extract_query(record)
        if len(query) < 2:
            continue
        label_overrides = _extract_label_overrides(record)
        if not label_overrides:
            continue

        dedupe_key = json.dumps(
            {
                "q": query.casefold(),
                "o": label_overrides,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        rows.append(
            {
                "query": query,
                "label_overrides": label_overrides,
            }
        )
        if len(rows) >= max(1, int(max_items or 1)):
            break

    return {
        "schema": "mimirq.intent_router_training.v1",
        "items_total": int(len(rows)),
        "items": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export intent-router training rows")
    parser.add_argument("--input", required=True, help="Input JSON/JSONL path")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--max-items", type=int, default=20000)
    args = parser.parse_args(argv)

    in_path = _resolve_path_under_cwd(str(args.input), must_exist=True)
    out_path = _resolve_path_under_cwd(str(args.out), must_exist=False)
    records = _load_records(in_path)
    payload = export_training_rows(records=records, max_items=max(1, int(args.max_items or 1)))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"items_total": payload.get("items_total", 0)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
