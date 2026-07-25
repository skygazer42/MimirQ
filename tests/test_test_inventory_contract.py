import json
from pathlib import Path

from scripts.generate_test_coverage_matrix import build_matrix

ROOT = Path(__file__).resolve().parents[1]


def test_critical_regression_files_remain_present() -> None:
    required = (
        "tests/test_auth_dependency_sets_request_state.py",
        "tests/test_parsing_extract_service.py",
        "tests/test_retrieval_fusion_budgeted_rrf.py",
        "tests/test_dify_external_knowledge_adapter.py",
        "tests/test_source_guard_contracts.py",
        "web/app/history/page.source.test.ts",
        "web/app/knowledge/knowledge-page.entry.test.ts",
        "web/app/evaluations/page.query.source.test.ts",
        "web/lib/api-runtime-contracts.test.ts",
    )

    for relative_path in required:
        assert (ROOT / relative_path).is_file(), relative_path


def test_test_matrix_reads_openapi_and_collects_nested_tests(tmp_path: Path) -> None:
    openapi_path = tmp_path / "web/openapi.json"
    openapi_path.parent.mkdir(parents=True)
    openapi_path.write_text(
        json.dumps(
            {
                "paths": {
                    "/api/v1/items/{item_id}": {
                        "get": {"operationId": "get_item"},
                        "parameters": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    nested_test = tmp_path / "tests/nested/test_example.py"
    nested_test.parent.mkdir(parents=True)
    nested_test.write_text("def test_example(): pass\n", encoding="utf-8")

    behavior_test = tmp_path / "web/lib/client.test.ts"
    behavior_test.parent.mkdir(parents=True)
    behavior_test.write_text("test('client', () => {})\n", encoding="utf-8")
    source_test = tmp_path / "web/lib/client.source.test.ts"
    source_test.write_text("test('source contract', () => {})\n", encoding="utf-8")
    entry_test = tmp_path / "web/app/example/page.entry.test.tsx"
    entry_test.parent.mkdir(parents=True)
    entry_test.write_text("test('entry contract', () => {})\n", encoding="utf-8")

    matrix = build_matrix(tmp_path)

    assert matrix["backend_routes"] == [
        {
            "operation_id": "get_item",
            "method": "GET",
            "path": "/api/v1/items/{item_id}",
        }
    ]
    assert matrix["backend_tests"] == [{"file": "tests/nested/test_example.py"}]
    assert matrix["frontend_tests"] == [{"file": "web/lib/client.test.ts"}]
    assert matrix["frontend_source_contract_tests"] == [
        {"file": "web/app/example/page.entry.test.tsx"},
        {"file": "web/lib/client.source.test.ts"},
    ]
    assert matrix["summary"]["frontend_tests"] == 1
    assert matrix["summary"]["frontend_source_contract_tests"] == 2
