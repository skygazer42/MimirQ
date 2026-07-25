
import argparse
import json
import os
from pathlib import Path
from typing import Iterable

FRONTEND_TEST_GLOBS = ('*.test.ts', '*.test.tsx', '*.spec.ts', '*.spec.tsx')
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
SOURCE_CONTRACT_TEST_MARKERS = (".source.test.", ".entry.test.")


def _normalize_frontend_route(app_root: Path, page_path: Path) -> str:
    rel_dir = page_path.relative_to(app_root).parent
    parts: list[str] = []
    for segment in rel_dir.parts:
        if not segment:
            continue
        if segment.startswith("(") and segment.endswith(")"):
            continue
        if segment.startswith("@"):
            continue
        if segment.startswith("[") and segment.endswith("]"):
            parts.append("[]")
            continue
        parts.append(segment)
    route = "/" + "/".join(parts)
    return route.rstrip("/") or "/"


def _iter_files(root: Path, patterns: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    skip_dirs = {"node_modules", ".git", ".next", "dist", "build"}
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in skip_dirs]
        current_path = Path(current_root)
        for filename in filenames:
            for pattern in patterns:
                if Path(filename).match(pattern):
                    files.append(current_path / filename)
                    break
    return sorted(files)


def _parse_backend_routes(repo_root: Path) -> list[dict[str, str]]:
    openapi_path = repo_root / "web" / "openapi.json"
    if not openapi_path.exists():
        return []
    spec = json.loads(openapi_path.read_text(encoding="utf-8"))
    routes: list[dict[str, str]] = []
    for route_path, operations in (spec.get("paths") or {}).items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if method.lower() not in HTTP_METHODS:
                continue
            operation = operation if isinstance(operation, dict) else {}
            routes.append(
                {
                    "operation_id": str(operation.get("operationId") or ""),
                    "method": method.upper(),
                    "path": str(route_path),
                }
            )
    return sorted(routes, key=lambda entry: (entry["path"], entry["method"], entry["operation_id"]))


def _parse_frontend_pages(repo_root: Path) -> list[dict[str, str]]:
    app_root = repo_root / "web" / "app"
    if not app_root.exists():
        return []

    pages: list[dict[str, str]] = []
    skip_dirs = {"node_modules", ".git", ".next", "dist", "build"}
    for current_root, dirnames, filenames in os.walk(app_root):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in skip_dirs]
        if "page.tsx" not in filenames:
            continue
        page = Path(current_root) / "page.tsx"
        if "api" in page.parts:
            continue
        pages.append(
            {
                "file": str(page.relative_to(repo_root)),
                "route": _normalize_frontend_route(app_root, page),
            }
        )
    return sorted(pages, key=lambda entry: entry["route"])


def _collect_tests(
    repo_root: Path,
) -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    backend_tests = [
        {"file": str(path.relative_to(repo_root))}
        for path in sorted((repo_root / "tests").rglob("test_*.py"))
        if path.is_file()
    ]

    frontend_root = repo_root / "web"
    frontend_test_paths = [
        path
        for path in _iter_files(frontend_root, FRONTEND_TEST_GLOBS)
        if "e2e" not in path.parts
    ]
    frontend_tests = [
        {"file": str(path.relative_to(repo_root))}
        for path in frontend_test_paths
        if not any(marker in path.name for marker in SOURCE_CONTRACT_TEST_MARKERS)
    ]
    frontend_source_contract_tests = [
        {"file": str(path.relative_to(repo_root))}
        for path in frontend_test_paths
        if any(marker in path.name for marker in SOURCE_CONTRACT_TEST_MARKERS)
    ]
    playwright_specs = [
        {"file": str(path.relative_to(repo_root))}
        for path in _iter_files(frontend_root / "e2e", ("*.spec.ts", "*.spec.tsx"))
    ]
    return backend_tests, frontend_tests, frontend_source_contract_tests, playwright_specs


def build_matrix(repo_root: Path) -> dict:
    backend_routes = _parse_backend_routes(repo_root)
    frontend_pages = _parse_frontend_pages(repo_root)
    backend_tests, frontend_tests, frontend_source_contract_tests, playwright_specs = _collect_tests(repo_root)

    return {
        "repo_root": str(repo_root),
        "summary": {
            "backend_routes": len(backend_routes),
            "frontend_pages": len(frontend_pages),
            "backend_tests": len(backend_tests),
            "frontend_tests": len(frontend_tests),
            "frontend_source_contract_tests": len(frontend_source_contract_tests),
            "playwright_specs": len(playwright_specs),
        },
        "backend_routes": backend_routes,
        "frontend_pages": frontend_pages,
        "backend_tests": backend_tests,
        "frontend_tests": frontend_tests,
        "frontend_source_contract_tests": frontend_source_contract_tests,
        "playwright_specs": playwright_specs,
    }


def render_markdown(matrix: dict) -> str:
    summary = matrix["summary"]
    lines = [
        "# Full-Stack Test Inventory",
        "",
        "## Summary",
        "",
        "| Surface | Count |",
        "| --- | ---: |",
        f"| Backend routes | {summary['backend_routes']} |",
        f"| Frontend pages | {summary['frontend_pages']} |",
        f"| Backend tests | {summary['backend_tests']} |",
        f"| Frontend behavior tests | {summary['frontend_tests']} |",
        f"| Frontend source-contract tests | {summary['frontend_source_contract_tests']} |",
        f"| Playwright specs | {summary['playwright_specs']} |",
        "",
        "## Backend Routes",
        "",
    ]

    for route in matrix["backend_routes"]:
        lines.append(f"- `{route['method']} {route['path']}` ({route['operation_id']})")

    lines.extend(["", "## Frontend Pages", ""])
    for page in matrix["frontend_pages"]:
        lines.append(f"- `{page['route']}` ({page['file']})")

    lines.extend(["", "## Backend Tests", ""])
    for test in matrix["backend_tests"]:
        lines.append(f"- {test['file']}")

    lines.extend(["", "## Frontend Tests", ""])
    for test in matrix["frontend_tests"]:
        lines.append(f"- {test['file']}")

    lines.extend(["", "## Frontend Source-Contract Tests", ""])
    for test in matrix["frontend_source_contract_tests"]:
        lines.append(f"- {test['file']}")

    lines.extend(["", "## Playwright Specs", ""])
    for spec in matrix["playwright_specs"]:
        lines.append(f"- {spec['file']}")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a full-stack test inventory.")
    parser.add_argument("--repo-root", default=".", help="Repository root to scan.")
    parser.add_argument("--json-out", help="Optional JSON output path.")
    parser.add_argument("--markdown-out", help="Optional Markdown output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    matrix = build_matrix(repo_root)

    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    markdown = render_markdown(matrix)
    if args.markdown_out:
        markdown_path = Path(args.markdown_out)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown + "\n", encoding="utf-8")
    else:
        print(markdown)


if __name__ == "__main__":
    main()
