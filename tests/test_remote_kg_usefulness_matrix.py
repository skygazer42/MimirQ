import json
import sys
from pathlib import Path
from unittest.mock import ANY

import pytest

import scripts.remote_kg_usefulness_matrix as mod


@pytest.fixture
def fixed_run_id(monkeypatch: pytest.MonkeyPatch) -> str:
    run_id = "20260816-010203"
    monkeypatch.setattr(mod.time, "strftime", lambda _fmt: run_id)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    return run_id


def _answer_for_question(question: str) -> str:
    for item in [*mod.QUESTIONS, *mod.SUMMARY_QUESTIONS]:
        if item["question"] == question:
            return str(item["expected_answer"])
    raise AssertionError(f"unexpected question: {question}")


_DOCUMENT_DETAIL_PATHS = {
    "/api/v1/documents/doc-1",
    "/api/v1/documents/doc-2",
    "/api/v1/documents/doc-3",
}
_SUMMARY_QUESTION_SET = {item["question"] for item in mod.SUMMARY_QUESTIONS}


def _maybe_document_detail_response(
    method: str,
    path: str,
) -> tuple[int, object, float] | None:
    if method == "GET" and path in _DOCUMENT_DETAIL_PATHS:
        return 200, {"status": "completed"}, 0.25
    return None


def _maybe_chunk_list_response(
    method: str,
    path: str,
) -> tuple[int, object, float] | None:
    if method != "GET" or not path.endswith("/chunks?limit=2000"):
        return None
    document_id = path.split("/")[4]
    return 200, {"items": [{"id": document_id.replace("doc", "chunk")}]}, 0.25


def _chat_response(
    state: dict[str, object],
    payload: dict[str, object] | None,
) -> tuple[int, object, float]:
    question = str((payload or {}).get("message") or "")
    citations = [{}, {}]
    if question in _SUMMARY_QUESTION_SET:
        citations.append({})

    rag_config = ((payload or {}).get("rag_config") or {}) if payload else {}
    should_fail = bool(state["fail_chat"]) and not bool(state["chat_failed"]) and not bool(rag_config.get("use_graph"))
    if should_fail:
        state["chat_failed"] = True
        return 500, {"detail": "chat failed"}, 0.25

    return 200, {"content": _answer_for_question(question), "citations": citations}, 0.25


def _diagnostics_response() -> tuple[int, object, float]:
    return (
        200,
        {
            "summary": {
                "baseline_hit_rate": 1.0,
                "baseline_recall": 1.0,
                "failure_breakdown": {},
            },
            "items": [
                {
                    "question": item["question"],
                    "baseline": {"metrics": {"hit_at_k": True}, "clues": [{"id": "clue-1"}]},
                }
                for item in mod.QUESTIONS
            ],
            "run_id": "run-1",
        },
        0.25,
    )


def _json_response(
    state: dict[str, object],
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> tuple[int, object, float]:
    key = (method, path)
    exact_responses: dict[tuple[str, str], tuple[int, object, float]] = {
        ("GET", "/api/v1/evaluations/kg/search/diagnostics/runs/run-1"): (
            200,
            {"run": {"status": "completed"}},
            0.25,
        ),
        ("POST", "/api/v1/datasets/"): (
            201,
            {"id": "ds-1", "dataset_id": "ds-shadow"},
            0.25,
        ),
        ("POST", "/api/v1/kg/search"): (
            200,
            {"result": {"clues": [{"id": "clue-1"}], "events": [{"id": "event-1"}]}},
            0.25,
        ),
    }
    if key in exact_responses:
        return exact_responses[key]

    response = _maybe_document_detail_response(method, path)
    if response is not None:
        return response

    response = _maybe_chunk_list_response(method, path)
    if response is not None:
        return response

    if method == "POST" and path.startswith("/api/v1/kg/documents/doc-"):
        return 200, {"started": True}, 0.25
    if key == ("POST", "/api/v1/evaluations/ragas/regression/cases"):
        state["case_count"] = int(state["case_count"]) + 1
        return 201, {"id": f"case-{state['case_count']}"}, 0.25
    if key == ("POST", "/api/v1/chat"):
        return _chat_response(state, payload)
    if key == ("POST", "/api/v1/evaluations/kg/search/diagnostics"):
        return _diagnostics_response()
    if method == "DELETE" and path.startswith("/api/v1/evaluations/ragas/regression/cases/"):
        return 204, None, 0.25
    raise AssertionError(f"unexpected request: {method} {path}")


def _multipart_response(
    state: dict[str, object],
    method: str,
    path: str,
) -> tuple[int, object, float]:
    if (method, path) != ("POST", "/api/v1/documents/upload"):
        raise AssertionError(f"unexpected multipart request: {method} {path}")
    state["upload_count"] = int(state["upload_count"]) + 1
    return 201, {"id": f"doc-{state['upload_count']}"}, 0.25


def _make_fake_live_api(
    constructor_calls: list[dict[str, object]],
    requests: list[dict[str, object]],
    *,
    fail_chat: bool = False,
):
    state: dict[str, object] = {
        "case_count": 0,
        "chat_failed": False,
        "fail_chat": fail_chat,
        "upload_count": 0,
    }

    class FakeLiveApi:
        def __init__(
            self,
            base_url: str,
            tenant_id: str,
            account_id: str,
            user_id: str,
            timeout: int,
        ) -> None:
            constructor_calls.append(
                {
                    "base_url": base_url,
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "user_id": user_id,
                    "timeout": timeout,
                }
            )

        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            requests.append(
                {
                    "kind": "json",
                    "method": method,
                    "path": path,
                    "payload": payload,
                    "timeout": timeout,
                }
            )
            return _json_response(state, method, path, payload)

        def multipart(
            self,
            method: str,
            path: str,
            *,
            fields: dict[str, str],
            file_path: Path,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            requests.append(
                {
                    "kind": "multipart",
                    "method": method,
                    "path": path,
                    "fields": fields,
                    "file_path": file_path,
                    "timeout": timeout,
                }
            )
            return _multipart_response(state, method, path)

    return FakeLiveApi


def test_delete_regression_cases_preserves_request_order_and_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, str, int | None]] = []
    step_names: list[str] = []

    class _Api:
        def json(
            self,
            method: str,
            path: str,
            *,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            requests.append((method, path, timeout))
            return 204, None, 0.25

    monkeypatch.setattr(
        mod,
        "record_step",
        lambda _steps, name, _status, _body, _elapsed, **_extra: step_names.append(name),
    )

    summary = mod.delete_regression_cases(
        _Api(),
        case_ids=["case-2", "case-1"],
        steps=[],
        timeout=77,
    )

    assert summary == {"deleted_regression_cases": 2}
    assert requests == [
        ("DELETE", "/api/v1/evaluations/ragas/regression/cases/case-2", 77),
        ("DELETE", "/api/v1/evaluations/ragas/regression/cases/case-1", 77),
    ]
    assert step_names == [
        "cleanup:delete_regression_case",
        "cleanup:delete_regression_case",
    ]


def test_main_success_preserves_defaults_requests_payloads_and_report_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    constructor_calls: list[dict[str, object]] = []
    requests: list[dict[str, object]] = []
    cleanup_calls: list[dict[str, object]] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "LiveApi", _make_fake_live_api(constructor_calls, requests))
    monkeypatch.setattr(
        mod,
        "perform_cleanup",
        lambda **kwargs: (
            cleanup_calls.append(kwargs)
            or {
                "cleanup_mode": kwargs["cleanup_mode"],
                "document_id": kwargs["document_id"],
                "dataset_id": kwargs["dataset_id"],
                "delete_dataset_after": kwargs["delete_dataset_after"],
            }
        ),
    )
    monkeypatch.setattr(sys, "argv", ["remote_kg_usefulness_matrix.py"])

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "kg-usefulness-matrix" / fixed_run_id).resolve()
    output = json.loads(capsys.readouterr().out)
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))

    assert rc == 0
    assert constructor_calls == [
        {
            "base_url": "http://127.0.0.1:8000",
            "tenant_id": mod.DEFAULT_TENANT_ID,
            "account_id": "demo",
            "user_id": "demo",
            "timeout": 1800,
        }
    ]
    assert [(call["kind"], call["method"], call["path"]) for call in requests] == [
        ("json", "POST", "/api/v1/datasets/"),
        ("multipart", "POST", "/api/v1/documents/upload"),
        ("json", "GET", "/api/v1/documents/doc-1"),
        ("json", "GET", "/api/v1/documents/doc-1/chunks?limit=2000"),
        ("multipart", "POST", "/api/v1/documents/upload"),
        ("json", "GET", "/api/v1/documents/doc-2"),
        ("json", "GET", "/api/v1/documents/doc-2/chunks?limit=2000"),
        ("multipart", "POST", "/api/v1/documents/upload"),
        ("json", "GET", "/api/v1/documents/doc-3"),
        ("json", "GET", "/api/v1/documents/doc-3/chunks?limit=2000"),
        (
            "json",
            "POST",
            "/api/v1/kg/documents/doc-1/extract"
            "?replace_existing=true&extract_relations=false&extract_skills=false&extraction_backend=heuristic",
        ),
        (
            "json",
            "POST",
            "/api/v1/kg/documents/doc-2/extract"
            "?replace_existing=true&extract_relations=false&extract_skills=false&extraction_backend=heuristic",
        ),
        (
            "json",
            "POST",
            "/api/v1/kg/documents/doc-3/extract"
            "?replace_existing=true&extract_relations=false&extract_skills=false&extraction_backend=heuristic",
        ),
        ("json", "POST", "/api/v1/evaluations/ragas/regression/cases"),
        ("json", "POST", "/api/v1/evaluations/ragas/regression/cases"),
        ("json", "POST", "/api/v1/kg/search"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/kg/search"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/kg/search"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/kg/search"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/kg/search"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/evaluations/kg/search/diagnostics"),
        ("json", "GET", "/api/v1/evaluations/kg/search/diagnostics/runs/run-1"),
        ("json", "DELETE", "/api/v1/evaluations/ragas/regression/cases/case-1"),
        ("json", "DELETE", "/api/v1/evaluations/ragas/regression/cases/case-2"),
    ]
    assert requests[0]["payload"] == {
        "name": f"KG Usefulness Matrix {fixed_run_id}",
        "description": "Remote KG usefulness verification dataset",
        "default_parser_backend": "basic",
        "default_chunk_strategy": "langchain_recursive",
    }
    assert requests[1]["fields"] == {
        "dataset_id": "ds-1",
        "parser_backend": "basic",
        "chunk_strategy": "langchain_recursive",
        "governance_enabled": "true",
        "chunk_vector_enabled": "true",
        "bm25_index_enabled": "true",
        "kg_enabled": "false",
        "event_vector_enabled": "false",
        "entity_vector_enabled": "false",
    }
    assert requests[13]["payload"] == {
        "dataset_id": "ds-1",
        "question": mod.QUESTIONS[0]["question"],
        "expected_answer": mod.QUESTIONS[0]["expected_answer"],
        "reference_sources": [
            {"document_id": "doc-1", "chunk_id": "chunk-1"},
            {"document_id": "doc-2", "chunk_id": "chunk-2"},
        ],
        "tags": ["kg_usefulness", "multi_hop"],
        "document_ids": ["doc-1", "doc-2"],
    }
    assert requests[16]["payload"] == {
        "message": mod.QUESTIONS[0]["question"],
        "dataset_id": "ds-1",
        "stream": False,
        "rag_config": {
            "top_k": 4,
            "score_threshold": 0.0,
            "retrieval_mode": "hybrid",
            "enable_reranker": False,
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_query_decomposition": False,
            "use_graph": False,
            "answer_mode": "extractive",
        },
    }
    assert requests[17]["payload"] == {
        **requests[16]["payload"],
        "rag_config": {
            **requests[16]["payload"]["rag_config"],
            "use_graph": True,
        },
    }
    assert requests[30]["payload"] == {
        "dataset_id": "ds-1",
        "case_ids": ["case-1", "case-2"],
        "max_cases": 2,
        "k": 5,
        "auto_extract_kg": False,
        "hardcase_mode": "off",
        "hardcases_per_failed_case": 0,
        "max_failed_cases_for_hardcase": 0,
        "persist_run": True,
    }
    assert cleanup_calls == [
        {
            "api": ANY,
            "steps": ANY,
            "dataset_id": "ds-1",
            "document_id": "doc-1",
            "cleanup_mode": "purge_dataset",
            "delete_dataset_after": False,
            "timeout": 1800,
        }
    ]
    assert output == {
        "ok": True,
        "artifact_dir": str(artifact_dir),
        "dataset_id": "ds-1",
        "error": None,
    }
    assert report["artifact_dir"] == str(artifact_dir)
    assert report["documents"] == [
        {"filename": "atlas-acquisition.md", "document_id": "doc-1", "chunk_id": "chunk-1"},
        {"filename": "integration-lead.md", "document_id": "doc-2", "chunk_id": "chunk-2"},
        {"filename": "orion-migration.md", "document_id": "doc-3", "chunk_id": "chunk-3"},
    ]
    assert report["cases"] == [
        {
            "question": mod.QUESTIONS[0]["question"],
            "expected_answer": mod.QUESTIONS[0]["expected_answer"],
            "case_id": "case-1",
        },
        {
            "question": mod.QUESTIONS[1]["question"],
            "expected_answer": mod.QUESTIONS[1]["expected_answer"],
            "case_id": "case-2",
        },
    ]
    assert report["question_results"][0] == {
        "question": mod.QUESTIONS[0]["question"],
        "expected_answer": mod.QUESTIONS[0]["expected_answer"],
        "expected_terms": [],
        "kg_search_clues": 1,
        "kg_search_events": 1,
        "chat_baseline": {
            "answer_preview": "Mira Chen",
            "citation_count": 2,
            "matches_expected": True,
            "matched_terms": [],
            "matched_term_count": 0,
            "expected_terms": [],
            "min_expected_terms": 0,
            "min_citations": 1,
            "require_expected_match": True,
            "passes_gate": True,
            "elapsed_sec": 0.25,
        },
        "chat_graph": {
            "answer_preview": "Mira Chen",
            "citation_count": 2,
            "matches_expected": True,
            "matched_terms": [],
            "matched_term_count": 0,
            "expected_terms": [],
            "min_expected_terms": 0,
            "min_citations": 1,
            "require_expected_match": True,
            "passes_gate": True,
            "elapsed_sec": 0.25,
        },
    }
    assert report["question_results"][2] == {
        "question": mod.SUMMARY_QUESTIONS[0]["question"],
        "expected_answer": mod.SUMMARY_QUESTIONS[0]["expected_answer"],
        "expected_terms": [
            "Project Atlas",
            "Blue Harbor",
            "Mira Chen",
            "Orion billing service",
        ],
        "kg_search_clues": 1,
        "kg_search_events": 1,
        "chat_baseline": {
            "answer_preview": mod.SUMMARY_QUESTIONS[0]["expected_answer"][:200],
            "citation_count": 3,
            "matches_expected": True,
            "matched_terms": [
                "Project Atlas",
                "Blue Harbor",
                "Mira Chen",
                "Orion billing service",
            ],
            "matched_term_count": 4,
            "expected_terms": [
                "Project Atlas",
                "Blue Harbor",
                "Mira Chen",
                "Orion billing service",
            ],
            "min_expected_terms": 3,
            "min_citations": 3,
            "require_expected_match": False,
            "passes_gate": True,
            "elapsed_sec": 0.25,
        },
        "chat_graph": {
            "answer_preview": mod.SUMMARY_QUESTIONS[0]["expected_answer"][:200],
            "citation_count": 3,
            "matches_expected": True,
            "matched_terms": [
                "Project Atlas",
                "Blue Harbor",
                "Mira Chen",
                "Orion billing service",
            ],
            "matched_term_count": 4,
            "expected_terms": [
                "Project Atlas",
                "Blue Harbor",
                "Mira Chen",
                "Orion billing service",
            ],
            "min_expected_terms": 3,
            "min_citations": 3,
            "require_expected_match": False,
            "passes_gate": True,
            "elapsed_sec": 0.25,
        },
    }
    assert report["kg_diagnostics_run"] == {"run_id": "run-1", "status": "completed"}
    assert report["kg_diagnostics"] == {
        "run_id": "run-1",
        "baseline_hit_rate": 1.0,
        "baseline_recall": 1.0,
        "failure_breakdown": {},
    }
    assert report["cleanup"] == {
        "deleted_regression_cases": 2,
        "cleanup_mode": "purge_dataset",
        "document_id": "doc-1",
        "dataset_id": "ds-1",
        "delete_dataset_after": False,
    }


def test_main_failure_preserves_exit_semantics_and_runs_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    constructor_calls: list[dict[str, object]] = []
    requests: list[dict[str, object]] = []
    cleanup_calls: list[dict[str, object]] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "LiveApi", _make_fake_live_api(constructor_calls, requests, fail_chat=True))
    monkeypatch.setattr(
        mod,
        "perform_cleanup",
        lambda **kwargs: (
            cleanup_calls.append(kwargs)
            or {
                "cleanup_mode": kwargs["cleanup_mode"],
                "document_id": kwargs["document_id"],
                "dataset_id": kwargs["dataset_id"],
                "delete_dataset_after": kwargs["delete_dataset_after"],
            }
        ),
    )
    monkeypatch.setattr(sys, "argv", ["remote_kg_usefulness_matrix.py"])

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "kg-usefulness-matrix" / fixed_run_id).resolve()
    output = json.loads(capsys.readouterr().out)
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))

    assert rc == 1
    assert constructor_calls == [
        {
            "base_url": "http://127.0.0.1:8000",
            "tenant_id": mod.DEFAULT_TENANT_ID,
            "account_id": "demo",
            "user_id": "demo",
            "timeout": 1800,
        }
    ]
    assert output == {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "dataset_id": "ds-1",
        "error": 'chat_baseline failed: {"detail": "chat failed"}',
    }
    assert report["ok"] is False
    assert report["error"] == 'chat_baseline failed: {"detail": "chat failed"}'
    assert report["cleanup"] == {
        "deleted_regression_cases": 2,
        "cleanup_mode": "purge_dataset",
        "document_id": "doc-1",
        "dataset_id": "ds-1",
        "delete_dataset_after": False,
    }
    assert cleanup_calls == [
        {
            "api": ANY,
            "steps": ANY,
            "dataset_id": "ds-1",
            "document_id": "doc-1",
            "cleanup_mode": "purge_dataset",
            "delete_dataset_after": False,
            "timeout": 1800,
        }
    ]
    assert [(call["method"], call["path"]) for call in requests[-3:]] == [
        ("POST", "/api/v1/chat"),
        ("DELETE", "/api/v1/evaluations/ragas/regression/cases/case-1"),
        ("DELETE", "/api/v1/evaluations/ragas/regression/cases/case-2"),
    ]
