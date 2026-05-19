import ast
from pathlib import Path


def _read(relative_path: str) -> str:
    return Path(relative_path).read_text(encoding='utf-8')


def _exception_handler_logs_fallback(handler: ast.ExceptHandler) -> bool:
    for stmt in handler.body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id.startswith('_log_'):
                return True
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == 'logger':
                return True
    return False


def test_critical_rag_broad_exception_handlers_are_observable() -> None:
    paths = [
        Path('app/rag/retriever.py'),
        Path('app/rag/retrieval/orchestrator.py'),
        Path('app/parsing/processors/processor.py'),
    ]

    unlogged: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            if ast.unparse(node.type) != 'Exception':
                continue
            if not _exception_handler_logs_fallback(node):
                unlogged.append(f'{path}:{node.lineno}')

    assert unlogged == []


def test_indexer_uses_shared_shadow_vector_event_constant() -> None:
    src = _read('app/services/indexer.py')
    assert 'SHADOW_VECTOR_WRITE_EVENT' in src
    assert src.count('ingest.shadow_vector_write') == 1


def test_perf_suite_diff_nan_check_uses_math_isnan() -> None:
    src = _read('app/services/perf_suite_diff_service.py')
    assert 'if math.isnan(v):' in src
    assert 'if v != v:' not in src
    assert 'if not (v == v):' not in src


def test_kg_completeness_union_find_initializes_sizes_with_fromkeys() -> None:
    src = _read('app/rag/kg/quality/kg_completeness_scorer.py')
    assert 'dict.fromkeys(nodes, 1)' in src
    assert 'size = {n: 1 for n in nodes}' not in src
