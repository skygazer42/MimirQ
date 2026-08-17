import argparse
import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.rag.evaluation.parse_bench import DEFAULT_FIXTURE_DIR, DEFAULT_MANIFEST, build_doc_type_matrix

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_parser_benchmark_module():
    path = REPO_ROOT / "scripts" / "parser_benchmark.py"
    spec = importlib.util.spec_from_file_location("parse_bench_parser_benchmark", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed_to_load_parser_benchmark:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@contextmanager
def _patched_argv(argv: list[str]):
    original = list(sys.argv)
    sys.argv = [original[0], *argv]
    try:
        yield
    finally:
        sys.argv = original


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _filter_manifest_cases(manifest_path: Path, docs_arg: str) -> tuple[Path, Path]:
    payload = _load_json(manifest_path)
    rows = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("manifest_invalid")

    docs_raw = str(docs_arg or "").strip().lower()
    if docs_raw in {"", "all", "*"}:
        return manifest_path.parent, manifest_path

    requested = {item.strip() for item in docs_raw.split(",") if item.strip()}
    filtered = [row for row in rows if isinstance(row, dict) and str(row.get("id") or "").strip().lower() in requested]
    if not filtered:
        raise ValueError("docs_filter_empty")

    out_dir = Path("artifacts/parse_bench")
    out_dir.mkdir(parents=True, exist_ok=True)
    filtered_manifest = out_dir / "manifest.filtered.json"
    filtered_manifest.write_text(json.dumps({"cases": filtered}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path.parent, filtered_manifest


def _augment_report(out_path: Path) -> None:
    report = _load_json(out_path)
    if not isinstance(report, dict):
        return
    report["doc_type_matrix"] = build_doc_type_matrix(report)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse benchmark CLI.")
    parser.add_argument("--parsers", default="auto", help="Comma-separated parser backends.")
    parser.add_argument("--docs", default="all", help="Comma-separated case ids or 'all'.")
    parser.add_argument("--input-dir", default=str(DEFAULT_FIXTURE_DIR), help="Fixture root directory.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Manifest path.")
    parser.add_argument("--out", default="artifacts/parse_bench/report.json", help="Output JSON path.")
    parser.add_argument("--baseline", default="", help="Optional baseline report path.")
    parser.add_argument(
        "--strict-profile", default="ci/parser_strict_profile.v1.json", help="Strict profile JSON path."
    )
    parser.add_argument("--strict", action="store_true", help="Fail on baseline regression.")
    parser.add_argument("--max-files", type=int, default=50, help="Max cases to run.")
    args = parser.parse_args(argv)

    manifest_root, manifest_path = _filter_manifest_cases(Path(args.manifest).resolve(), str(args.docs or "all"))
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bench_argv = [
        "--input-dir",
        str(Path(args.input_dir).resolve() if str(args.input_dir).strip() else manifest_root),
        "--manifest",
        str(manifest_path),
        "--backends",
        str(args.parsers or "auto"),
        "--max-files",
        str(int(args.max_files or 0)),
        "--out",
        str(out_path),
    ]
    if str(args.baseline or "").strip():
        bench_argv.extend(["--baseline", str(Path(args.baseline).resolve())])
    if str(args.strict_profile or "").strip():
        bench_argv.extend(["--strict-profile", str(Path(args.strict_profile).resolve())])
    if bool(args.strict):
        bench_argv.append("--strict")

    parser_benchmark_script = _load_parser_benchmark_module()
    with _patched_argv(bench_argv):
        exit_code = int(parser_benchmark_script.main() or 0)
    if out_path.exists():
        _augment_report(out_path)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    command = argparse.ArgumentParser(description="app.rag.evaluation.parse_bench")
    sub = command.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Run parse benchmark.")
    parsed, remaining = command.parse_known_args(argv)
    if parsed.command == "run":
        return run(remaining)
    raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
