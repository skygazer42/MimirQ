from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_makefile_separates_core_and_full_backend_suites() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "CORE_TESTS :=" in makefile
    assert "test-full:" in makefile
    assert "$(PY) -m pytest -q $(CORE_TESTS) $(PYTEST_ARGS)" in makefile
    assert "$(PY) -m pytest -q $(PYTEST_ARGS)" in makefile

    required_core_tests = (
        "tests/test_worker_startup_logs.py",
        "tests/test_parsing_extract_service.py",
        "tests/test_retrieval_fusion_budgeted_rrf.py",
        "tests/test_rag_trace_schema.py",
        "tests/test_dify_external_knowledge_adapter.py",
        "tests/test_reports_endpoints.py",
        "tests/test_no_future_annotations_imports.py",
        "tests/test_no_module_level_import_fallbacks.py",
        "tests/test_no_import_error_fallbacks.py",
        "tests/test_source_guard_contracts.py",
        "tests/test_test_inventory_contract.py",
        "tests/test_core_test_suite_contract.py",
    )
    for test_path in required_core_tests:
        assert test_path in makefile


def test_makefile_exposes_full_frontend_suite_separately() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "CORE_WEB_TESTS :=" in makefile
    assert "test-web-full:" in makefile
    assert "pnpm exec vitest run $(CORE_WEB_TESTS) $(VITEST_ARGS)" in makefile
    assert "pnpm exec vitest run $(VITEST_ARGS)" in makefile
