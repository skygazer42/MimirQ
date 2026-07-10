#!/usr/bin/env python3
"""
Convert an Evidence Pack JSON (from Knowledge → Retrieval preview) into a
portable regression case bundle (schema v1).

This is intended as an operator workflow helper:
  Evidence Pack → Regression bundle → API import → Regression gate
"""


import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REGRESSION_CASE_BUNDLE_SCHEMA_V1 = "mimirq.regression_cases.v1"
MAX_QUOTE_CHARS = 2000


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _coerce_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",")]
        raw = [p for p in parts if p]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        s = str(item or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _iter_dicts(raw: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def _coerce_nonneg_int(value: Any) -> int | None:
    try:
        iv = int(value) if value is not None else None
    except Exception:
        return None
    if iv is None or iv < 0:
        return None
    return iv


def _truncate_quote(value: Any) -> str | None:
    s = str(value or "")
    if not s:
        return None
    if len(s) > MAX_QUOTE_CHARS:
        return s[:MAX_QUOTE_CHARS]
    return s


def _normalize_reference_sources(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for src in raw or []:
        if not isinstance(src, dict):
            continue
        doc_id = src.get("document_id")
        chunk_id = src.get("chunk_id")
        if not doc_id or not chunk_id:
            continue
        cid = str(chunk_id).strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(
            {
                "document_id": doc_id,
                "chunk_id": chunk_id,
                "chunk_index": _coerce_nonneg_int(src.get("chunk_index")),
                "page_number": _coerce_nonneg_int(src.get("page_number")),
                "start_char": _coerce_nonneg_int(src.get("start_char")),
                "end_char": _coerce_nonneg_int(src.get("end_char")),
                "doc_pipeline_key": src.get("doc_pipeline_key"),
                "pipeline_hash": src.get("pipeline_hash"),
                "quote": _truncate_quote(src.get("quote")),
                "label": src.get("label"),
            }
        )
    return out


def _build_reference_sources_from_citations(pack: dict[str, Any]) -> list[dict[str, Any]]:
    selected = {str(x).strip() for x in (pack.get("selected_chunk_ids") or []) if str(x).strip()}
    if not selected:
        return []

    citations = list(_iter_dicts(pack.get("citations")))
    refs: list[dict[str, Any]] = []
    for c in citations:
        cid = str(c.get("chunk_id") or "").strip()
        if not cid or cid not in selected:
            continue
        refs.append(
            {
                "document_id": c.get("document_id"),
                "chunk_id": c.get("chunk_id"),
                "chunk_index": _coerce_nonneg_int(c.get("chunk_index")),
                "page_number": c.get("page_number"),
                "start_char": c.get("start_char"),
                "end_char": c.get("end_char"),
                "doc_pipeline_key": c.get("doc_pipeline_key"),
                "pipeline_hash": c.get("pipeline_hash"),
                "quote": _truncate_quote(c.get("chunk_content")),
                "label": "evidence_pack",
            }
        )
    return _normalize_reference_sources(refs)


def convert_evidence_pack_to_regression_bundle(
    pack: Any,
    *,
    dataset_id: str | None = None,
    question: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """
    Convert an Evidence Pack payload into `mimirq.regression_cases.v1`.
    """
    def _convert_one_pack(obj: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        ds = str(dataset_id or obj.get("dataset_id") or "").strip()
        if not ds:
            raise ValueError("dataset_id is required")

        q = str(question or obj.get("query") or "").strip()
        if not q:
            raise ValueError("query is required")

        # Prefer explicit reference_sources exported from the UI; fall back to building them from
        # (selected_chunk_ids + citations).
        refs = _normalize_reference_sources(list(_iter_dicts(obj.get("reference_sources"))))
        if not refs:
            refs = _build_reference_sources_from_citations(obj)

        if not refs:
            raise ValueError("reference_sources is empty (select at least one citation before exporting)")

        bundle_tags = _coerce_tags(tags) if tags is not None else ["evidence_pack"]

        item = {
            "question": q,
            "expected_answer": None,
            "reference_sources": refs,
            "tags": bundle_tags,
        }
        return ds, item

    if isinstance(pack, list):
        if question:
            raise ValueError("question override is not supported for list input")
        packs = [p for p in pack if isinstance(p, dict)]
        if not packs:
            raise ValueError("evidence pack list is empty")

        ds_first, first_item = _convert_one_pack(packs[0])
        ds = ds_first
        items = [first_item]
        for obj in packs[1:]:
            ds_i, item_i = _convert_one_pack(obj)
            if ds_i != ds:
                raise ValueError("mixed dataset_id in evidence pack list (use --dataset-id to override)")
            items.append(item_i)

        return {"schema": REGRESSION_CASE_BUNDLE_SCHEMA_V1, "dataset_id": ds, "items": items}

    if not isinstance(pack, dict):
        raise ValueError("evidence pack must be an object or list of objects")

    ds, item = _convert_one_pack(pack)
    return {"schema": REGRESSION_CASE_BUNDLE_SCHEMA_V1, "dataset_id": ds, "items": [item]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Convert Evidence Pack JSON to regression case bundle v1.")
    p.add_argument("--in", dest="in_path", required=True, help="Path to Evidence Pack JSON")
    p.add_argument("--out", dest="out_path", default="", help="Output path (default: stdout)")
    p.add_argument("--dataset-id", default="", help="Override dataset_id (optional)")
    p.add_argument("--question", default="", help="Override question/query (optional)")
    p.add_argument("--tags", default="", help='Comma-separated tags (default: "evidence_pack")')
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    args = p.parse_args(argv)
    in_path = Path(args.in_path)
    if not in_path.exists():
        print(f"[evidence_pack_to_regression_bundle] ERROR: input file not found: {in_path}", file=sys.stderr)
        return 2

    try:
        pack = _load_json(in_path)
        bundle = convert_evidence_pack_to_regression_bundle(
            pack,
            dataset_id=(str(args.dataset_id).strip() or None),
            question=(str(args.question).strip() or None),
            tags=_coerce_tags(args.tags) if str(args.tags).strip() else None,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[evidence_pack_to_regression_bundle] ERROR: {str(exc)[:200]}", file=sys.stderr)
        return 2

    indent = 2 if bool(args.pretty) else None
    out = json.dumps(bundle, ensure_ascii=False, indent=indent) + "\n"
    if args.out_path:
        Path(args.out_path).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
