from __future__ import annotations

import ast
from pathlib import Path

_RUNTIME_BOUNDARY_ROOTS = (
    Path("app/parsing"),
    Path("app/services"),
    Path("app/tasks"),
    Path("scripts"),
)


def _import_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.ImportFrom):
        return node.module
    if isinstance(node, ast.Import):
        return ",".join(alias.name for alias in node.names)
    return None


def test_runtime_modules_do_not_import_api_v1_routers() -> None:
    offenders: list[str] = []
    for root in _RUNTIME_BOUNDARY_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                name = _import_name(node)
                if not name:
                    continue
                if name == "app.api.v1" or name.startswith("app.api.v1."):
                    offenders.append(f"{path}:{getattr(node, 'lineno', 0)} imports {name}")

    assert offenders == []


def test_document_lifecycle_service_keeps_indexer_lazy() -> None:
    path = Path("app/services/document_lifecycle_service.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    offenders: list[str] = []
    for node in tree.body:
        name = _import_name(node)
        if not name:
            continue
        if name == "app.services.indexer" or name.startswith("app.services.indexer."):
            offenders.append(f"{path}:{getattr(node, 'lineno', 0)} imports {name}")

    assert offenders == []
