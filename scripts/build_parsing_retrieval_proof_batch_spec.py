
import argparse
import json
from pathlib import Path
from typing import Any

_SCHEMA = "mimirq.parsing_retrieval_proof_batch.v1"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _derive_case_category(*, case_id: str, rel_path: str) -> str:
    path_parts = [part.strip() for part in Path(rel_path).parts if str(part).strip()]
    raw = path_parts[0] if path_parts else case_id
    slug = str(raw or case_id or "unknown").strip().lower().replace("-", "_")
    if slug.endswith("_case"):
        slug = slug[: -len("_case")]
    if "chart" in slug:
        return "chart"
    if "diagram" in slug:
        return "diagram"
    if slug.startswith("qr") or "_qr" in slug or "qr_" in slug:
        return "qr"
    if "barcode" in slug:
        return "barcode"
    return slug or "unknown"


def _derive_case_family(case_category: str) -> str:
    category = str(case_category or "").strip().lower()
    if category in {"chart", "diagram", "qr", "barcode"}:
        return "specialty"
    if "table" in category:
        return "table"
    if category in {"two_column_pdf", "header_footer_noise_pdf", "mixed_layout_pdf"} or "layout" in category:
        return "layout"
    return "document"


def _count_queries(path: Path) -> int:
    payload = _read_json(Path(path).resolve())
    if isinstance(payload, list):
        return int(len(payload))
    return 0


def build_batch_spec(
    *,
    manifest_path: Path,
    case_queries: dict[str, dict[str, Any]],
    defaults: dict[str, Any] | None = None,
    case_queries_path: Path | None = None,
) -> dict[str, Any]:
    defaults_obj = defaults or {}
    manifest_obj = _read_json(Path(manifest_path).resolve())
    rows = manifest_obj.get("cases") if isinstance(manifest_obj, dict) else None
    if not isinstance(rows, list):
        raise ValueError("manifest_invalid")

    resolved_manifest_path = Path(manifest_path).resolve()
    resolved_case_queries_path = Path(case_queries_path).resolve() if case_queries_path is not None else None
    manifest_dir = resolved_manifest_path.parent
    cases: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        case_id = str(row.get("id") or row.get("case_id") or "").strip()
        rel_path = str(row.get("path") or "").strip()
        query_cfg = case_queries.get(case_id) if isinstance(case_queries, dict) else None
        if not case_id or not rel_path or not isinstance(query_cfg, dict):
            continue
        queries_json = str(query_cfg.get("queries_json") or "").strip()
        if not queries_json:
            continue
        resolved_queries_path = Path(queries_json).resolve()
        case_category = _derive_case_category(case_id=case_id, rel_path=rel_path)
        cases.append(
            {
                "id": case_id,
                "input_file": str((manifest_dir / rel_path).resolve()),
                "queries_json": str(resolved_queries_path),
                "parser_backend": str(query_cfg.get("parser_backend") or defaults_obj.get("parser_backend") or "basic"),
                "top_k": int(query_cfg.get("top_k") or defaults_obj.get("top_k") or 1),
                "retrieval_mode": str(query_cfg.get("retrieval_mode") or defaults_obj.get("retrieval_mode") or "keyword"),
                "governance_rule_packs": [
                    str(item).strip()
                    for item in (query_cfg.get("governance_rule_packs") or [])
                    if str(item).strip()
                ],
                "case_family": _derive_case_family(case_category),
                "case_category": case_category,
                "query_count": _count_queries(resolved_queries_path),
                "manifest_rel_path": rel_path,
            }
        )

    query_count_total = int(sum(int(item.get("query_count") or 0) for item in cases))
    return {
        "schema": _SCHEMA,
        "defaults": {
            "parser_backend": str(defaults_obj.get("parser_backend") or "basic"),
            "top_k": int(defaults_obj.get("top_k") or 1),
            "retrieval_mode": str(defaults_obj.get("retrieval_mode") or "keyword"),
        },
        "cases_total": int(len(cases)),
        "query_count_total": query_count_total,
        "provenance": {
            "manifest_path": str(resolved_manifest_path),
            "case_queries_path": str(resolved_case_queries_path) if resolved_case_queries_path is not None else None,
        },
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a parsing-proof batch spec from a parser manifest plus a case-query mapping JSON.")
    parser.add_argument("--manifest-json", required=True, help="Path to parser manifest JSON.")
    parser.add_argument("--case-queries-json", required=True, help="Path to case-id -> queries-json mapping JSON.")
    parser.add_argument("--out", required=True, help="Output batch spec JSON path.")
    parser.add_argument("--default-parser-backend", default="basic", help="Default parser backend.")
    parser.add_argument("--default-top-k", type=int, default=1, help="Default top_k.")
    parser.add_argument("--default-retrieval-mode", default="keyword", help="Default retrieval mode.")
    args = parser.parse_args(argv)

    case_queries = _read_json(Path(str(args.case_queries_json)).resolve())
    spec = build_batch_spec(
        manifest_path=Path(str(args.manifest_json)),
        case_queries=case_queries if isinstance(case_queries, dict) else {},
        defaults={
            "parser_backend": str(args.default_parser_backend or "basic"),
            "top_k": int(args.default_top_k or 1),
            "retrieval_mode": str(args.default_retrieval_mode or "keyword"),
        },
        case_queries_path=Path(str(args.case_queries_json)),
    )
    out_path = Path(str(args.out)).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
