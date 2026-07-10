
import argparse
import json
import os
import re
from pathlib import Path
from typing import Iterable

INCLUDE_ROUTER_RE = re.compile(
    r"router\.include_router\(\s*(?P<alias>[a-zA-Z_][a-zA-Z0-9_]*)\.router(?:,\s*prefix=(?P<prefix>[^,\n)]+))?",
    re.MULTILINE,
)
IMPORT_MODULE_RE = re.compile(
    r'(?P<alias>[a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*import_module\("(?P<module>[^"]+)"\)',
    re.MULTILINE,
)
CONST_RE = re.compile(r'(?P<name>_[A-Z0-9_]+)\s*=\s*"(?P<value>/[^"]*)"', re.MULTILINE)
ROUTE_DECORATOR_RE = re.compile(
    r"@router\.(?P<method>get|post|put|patch|delete|head|options|api_route)\((?P<body>.*?)\)",
    re.DOTALL,
)
PATH_LITERAL_RE = re.compile(r'["\'](?P<path>/[^"\']*)["\']')
METHODS_RE = re.compile(r"methods\s*=\s*\[(?P<methods>[^\]]+)\]", re.DOTALL)
METHOD_LITERAL_RE = re.compile(r'["\'](?P<method>[A-Za-z]+)["\']')
FRONTEND_TEST_GLOBS = ('*.test.ts', '*.test.tsx', '*.spec.ts', '*.spec.tsx')


def _normalize_backend_path(prefix: str, route_path: str) -> str:
    combined = f"{prefix.rstrip('/')}/{route_path.lstrip('/')}" if prefix else route_path
    combined = "/" + combined.lstrip("/")
    combined = re.sub(r"/{2,}", "/", combined)
    combined = re.sub(r"\{[^}/]+\}", "{}", combined)
    return combined


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


def _resolve_prefix(raw_prefix: str | None, constants: dict[str, str]) -> str:
    if not raw_prefix:
        return ""
    value = raw_prefix.strip()
    if value in constants:
        return constants[value]
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return value[1:-1]
    return value


def _parse_methods(method: str, body: str) -> list[str]:
    if method != "api_route":
        return [method.upper()]
    match = METHODS_RE.search(body)
    if not match:
        return ["ANY"]
    methods = [entry.group("method").upper() for entry in METHOD_LITERAL_RE.finditer(match.group("methods"))]
    return methods or ["ANY"]


def _parse_backend_routes(repo_root: Path) -> list[dict[str, str]]:
    init_path = repo_root / "app" / "api" / "v1" / "__init__.py"
    if not init_path.exists():
        return []

    src = init_path.read_text(encoding="utf-8")
    alias_to_module = {match.group("alias"): match.group("module") for match in IMPORT_MODULE_RE.finditer(src)}
    constants = {match.group("name"): match.group("value") for match in CONST_RE.finditer(src)}
    routes: list[dict[str, str]] = []

    for match in INCLUDE_ROUTER_RE.finditer(src):
        alias = match.group("alias")
        module_name = alias_to_module.get(alias)
        if not module_name:
            fallback_path = repo_root / "app" / "api" / "v1" / f"{alias}.py"
            if fallback_path.exists():
                module_name = f"app.api.v1.{alias}"
            else:
                continue
        if not module_name.startswith("app.api.v1."):
            continue

        module_path = repo_root.joinpath(*module_name.split(".")).with_suffix(".py")
        if not module_path.exists():
            continue

        prefix = _resolve_prefix(match.group("prefix"), constants)
        module_src = module_path.read_text(encoding="utf-8")
        for decorator in ROUTE_DECORATOR_RE.finditer(module_src):
            body = decorator.group("body")
            path_match = PATH_LITERAL_RE.search(body)
            if not path_match:
                continue
            route_path = path_match.group("path")
            for http_method in _parse_methods(decorator.group("method"), body):
                routes.append(
                    {
                        "module": module_name,
                        "method": http_method,
                        "path": _normalize_backend_path(prefix, route_path),
                    }
                )

    return sorted(routes, key=lambda entry: (entry["path"], entry["method"], entry["module"]))


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


def _collect_tests(repo_root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    backend_tests = [
        {"file": str(path.relative_to(repo_root))}
        for path in sorted((repo_root / "tests").glob("test_*.py"))
        if path.is_file()
    ]

    frontend_root = repo_root / "web"
    frontend_tests = [
        {"file": str(path.relative_to(repo_root))}
        for path in _iter_files(frontend_root, FRONTEND_TEST_GLOBS)
        if "e2e" not in path.parts
    ]
    playwright_specs = [
        {"file": str(path.relative_to(repo_root))}
        for path in _iter_files(frontend_root / "e2e", ("*.spec.ts", "*.spec.tsx"))
    ]
    return backend_tests, frontend_tests, playwright_specs


def build_matrix(repo_root: Path) -> dict:
    backend_routes = _parse_backend_routes(repo_root)
    frontend_pages = _parse_frontend_pages(repo_root)
    backend_tests, frontend_tests, playwright_specs = _collect_tests(repo_root)

    return {
        "repo_root": str(repo_root),
        "summary": {
            "backend_routes": len(backend_routes),
            "frontend_pages": len(frontend_pages),
            "backend_tests": len(backend_tests),
            "frontend_tests": len(frontend_tests),
            "playwright_specs": len(playwright_specs),
        },
        "backend_routes": backend_routes,
        "frontend_pages": frontend_pages,
        "backend_tests": backend_tests,
        "frontend_tests": frontend_tests,
        "playwright_specs": playwright_specs,
    }


def render_markdown(matrix: dict) -> str:
    summary = matrix["summary"]
    lines = [
        "# Full-Stack Test Coverage Matrix",
        "",
        "## Summary",
        "",
        "| Surface | Count |",
        "| --- | ---: |",
        f"| Backend routes | {summary['backend_routes']} |",
        f"| Frontend pages | {summary['frontend_pages']} |",
        f"| Backend tests | {summary['backend_tests']} |",
        f"| Frontend tests | {summary['frontend_tests']} |",
        f"| Playwright specs | {summary['playwright_specs']} |",
        "",
        "## Backend Routes",
        "",
    ]

    for route in matrix["backend_routes"]:
        lines.append(f"- `{route['method']} {route['path']}` ({route['module']})")

    lines.extend(["", "## Frontend Pages", ""])
    for page in matrix["frontend_pages"]:
        lines.append(f"- `{page['route']}` ({page['file']})")

    lines.extend(["", "## Backend Tests", ""])
    for test in matrix["backend_tests"]:
        lines.append(f"- {test['file']}")

    lines.extend(["", "## Frontend Tests", ""])
    for test in matrix["frontend_tests"]:
        lines.append(f"- {test['file']}")

    lines.extend(["", "## Playwright Specs", ""])
    for spec in matrix["playwright_specs"]:
        lines.append(f"- {spec['file']}")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a full-stack test coverage matrix.")
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
