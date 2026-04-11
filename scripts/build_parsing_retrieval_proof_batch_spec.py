from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_SCHEMA = "mimirq.parsing_retrieval_proof_batch.v1"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_batch_spec(
    *,
    manifest_path: Path,
    case_queries: dict[str, dict[str, Any]],
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_obj = _read_json(Path(manifest_path).resolve())
    rows = manifest_obj.get("cases") if isinstance(manifest_obj, dict) else None
    if not isinstance(rows, list):
        raise ValueError("manifest_invalid")

    manifest_dir = Path(manifest_path).resolve().parent
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
        cases.append(
            {
                "id": case_id,
                "input_file": str((manifest_dir / rel_path).resolve()),
                "queries_json": str(Path(queries_json).resolve()),
                "parser_backend": str(query_cfg.get("parser_backend") or defaults.get("parser_backend") or "basic"),
                "top_k": int(query_cfg.get("top_k") or defaults.get("top_k") or 1),
                "retrieval_mode": str(query_cfg.get("retrieval_mode") or defaults.get("retrieval_mode") or "keyword"),
            }
        )

    return {
        "schema": _SCHEMA,
        "defaults": {
            "parser_backend": str((defaults or {}).get("parser_backend") or "basic"),
            "top_k": int((defaults or {}).get("top_k") or 1),
            "retrieval_mode": str((defaults or {}).get("retrieval_mode") or "keyword"),
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
    )
    out_path = Path(str(args.out)).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
