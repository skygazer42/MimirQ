from __future__ import annotations

import ast
from pathlib import Path

DOCSTRING_GUARDED_API_MODULES = [
    Path("app/api/v1/auth.py"),
    Path("app/api/v1/dataset_analysis.py"),
    Path("app/api/v1/dataset_categories.py"),
]


def _is_endpoint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    methods = {"delete", "get", "patch", "post", "put"}
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in methods:
            return True
    return False


def test_guarded_api_endpoints_have_docstrings() -> None:
    offenders: list[str] = []

    for path in DOCSTRING_GUARDED_API_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _is_endpoint(node):
                if ast.get_docstring(node) is None:
                    offenders.append(f"{path}:{node.lineno}:{node.name}")

    assert offenders == []
