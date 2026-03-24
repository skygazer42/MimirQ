from pathlib import Path


def _read(relative_path: str) -> str:
    return Path(relative_path).read_text(encoding='utf-8')


def test_indexer_uses_shared_shadow_vector_event_constant() -> None:
    src = _read('app/services/indexer.py')
    assert 'SHADOW_VECTOR_WRITE_EVENT' in src
    assert src.count('ingest.shadow_vector_write') == 1


def test_perf_suite_diff_nan_check_uses_direct_inequality() -> None:
    src = _read('app/services/perf_suite_diff_service.py')
    assert 'if v != v:' in src
    assert 'if not (v == v):' not in src


def test_kg_completeness_union_find_initializes_sizes_with_fromkeys() -> None:
    src = _read('app/rag/kg/quality/kg_completeness_scorer.py')
    assert 'dict.fromkeys(nodes, 1)' in src
    assert 'size = {n: 1 for n in nodes}' not in src
