from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def run_sample_parsing_retrieval_proof(
    *,
    manifest_path: Path,
    case_queries_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    import json

    from scripts.build_parsing_retrieval_proof_batch_spec import build_batch_spec
    from scripts.run_parsing_retrieval_proof_batch import run_batch

    case_queries = json.loads(Path(case_queries_path).resolve().read_text(encoding="utf-8"))
    spec = build_batch_spec(
        manifest_path=Path(manifest_path).resolve(),
        case_queries=case_queries if isinstance(case_queries, dict) else {},
        defaults={"parser_backend": "basic", "top_k": 1, "retrieval_mode": "keyword"},
    )

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / "parsing_proof_batch.spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_batch(spec_path=spec_path, out_dir=out_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the repo sample broader parsing retrieval proof sweep.")
    parser.add_argument(
        "--manifest-json",
        default=str(_REPO_ROOT / "tests" / "fixtures" / "parsing_golden_broader" / "manifest.json"),
        help="Parser manifest JSON (default: tests/fixtures/parsing_golden_broader/manifest.json).",
    )
    parser.add_argument(
        "--case-queries-json",
        default=str(_REPO_ROOT / "tests" / "fixtures" / "parsing_retrieval_proof" / "broader_case_queries.sample.json"),
        help="Case-id to queries mapping JSON.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(_REPO_ROOT / "runs" / "parsing_proof_broader_sample"),
        help="Output directory for generated batch spec and reports.",
    )
    args = parser.parse_args(argv)

    report = run_sample_parsing_retrieval_proof(
        manifest_path=Path(str(args.manifest_json)),
        case_queries_path=Path(str(args.case_queries_json)),
        out_dir=Path(str(args.out_dir)),
    )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    print(
        "[sample-parsing-proof] "
        f"cases={report.get('cases_total', 0)} "
        f"hit@k_mean={summary.get('hit_at_k_mean', 0.0)} "
        f"mrr_mean={summary.get('mrr_mean', 0.0)} "
        f"out={Path(str(args.out_dir)).resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
