import ast
import subprocess
import sys
from pathlib import Path

import pytest

KG_HELPERS = {
    "_apply_kg_chunk_boost",
    "_fetch_document_chunks_for_kg_injection",
    "_merge_kg_docs_preserving_main",
    "_resolve_kg_scope",
}


def _runtime_imports(source: str):
    tree = ast.parse(source)
    type_names = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "typing"
        for alias in node.names
        if alias.name == "TYPE_CHECKING"
    }
    typing_modules = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "typing"
    }

    def visit(node):
        if isinstance(node, ast.If):
            guard = node.test
            type_only = isinstance(guard, ast.Name) and guard.id in type_names
            type_only |= (
                isinstance(guard, ast.Attribute)
                and guard.attr == "TYPE_CHECKING"
                and isinstance(guard.value, ast.Name)
                and guard.value.id in typing_modules
            )
            if type_only:
                for child in node.orelse:
                    yield from visit(child)
                return
        if isinstance(node, ast.ImportFrom):
            yield node
        for child in ast.iter_child_nodes(node):
            yield from visit(child)

    return list(visit(tree))


def test_kg_stage_imports_pure_helpers_from_their_implementation_owner() -> None:
    source = Path("app/rag/retrieval/stages/knowledge_graph.py").read_text(encoding="utf-8")
    imports = _runtime_imports(source)
    references = {alias.name: node.module for node in imports for alias in node.names if alias.name in KG_HELPERS}
    assert references == dict.fromkeys(KG_HELPERS, "app.rag.retrieval.ranking.knowledge_graph")


def test_dependency_rule_ignores_type_only_edges_but_keeps_the_runtime_else() -> None:
    imports = _runtime_imports(
        "from typing import TYPE_CHECKING as TC\n"
        "if TC:\n    from app.rag.retrieval.orchestrator import _resolve_kg_scope\n"
        "else:\n    from app.rag.retrieval.ranking.knowledge_graph import _resolve_kg_scope\n"
    )
    assert [node.module for node in imports if any(alias.name == "_resolve_kg_scope" for alias in node.names)] == [
        "app.rag.retrieval.ranking.knowledge_graph"
    ]


@pytest.mark.parametrize(
    "order",
    [("runtime.engine", "retrieval.stages.knowledge_graph"), ("retrieval.stages.knowledge_graph", "runtime.engine")],
)
def test_engine_and_kg_stage_import_in_both_orders_with_the_same_helpers(order) -> None:
    code = f"""
import importlib
for name in {order!r}:
    importlib.import_module('app.rag.' + name)
stage = importlib.import_module('app.rag.retrieval.stages.knowledge_graph')
owner = importlib.import_module('app.rag.retrieval.ranking.knowledge_graph')
for name in {sorted(KG_HELPERS)!r}:
    assert getattr(stage, name) is getattr(owner, name), name
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
