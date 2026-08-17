import json
import sys
from pathlib import Path
from unittest.mock import ANY

import pytest

import scripts.remote_prompt_matrix as mod


@pytest.fixture
def fixed_run_id(monkeypatch: pytest.MonkeyPatch) -> str:
    run_id = "20260816-010203"
    monkeypatch.setattr(mod.time, "strftime", lambda _fmt: run_id)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    return run_id


def test_main_success_preserves_request_order_helper_seams_and_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    constructor_calls: list[dict[str, object]] = []
    requests: list[dict[str, object]] = []
    helper_calls: list[tuple[str, object]] = []
    upload_ids = iter(["doc-1", "doc-2"])

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
            responses: dict[tuple[str, str], tuple[int, object]] = {
                ("POST", "/api/v1/prompt-templates/builtins/sync"): (200, {"synced": True}),
                ("POST", "/api/v1/datasets/"): (200, {"id": "ds-1"}),
                (
                    "POST",
                    "/api/v1/rag/prompt-preview",
                ): (
                    200,
                    {
                        "prompt_template_key": mod.PROMPT_KEYS["answer"],
                        "prompt_text": "<context>Alpha rollout uses the blue flag</context>",
                        "citations": [{"id": "cite-1"}],
                    },
                ),
                ("POST", "/api/v1/chat"): (
                    200,
                    {
                        "metrics": {"prompt_template_key": mod.PROMPT_KEYS["answer"]},
                        "citations": [{"id": "cite-1"}],
                        "content": "Alpha rollout uses the blue flag.",
                    },
                ),
                (
                    "POST",
                    "/api/v1/kg/documents/doc-1/extract"
                    "?replace_existing=true&extract_relations=false&extract_skills=false"
                    f"&extraction_backend=llm&prompt_template_key={mod.PROMPT_KEYS['kg']}",
                ): (200, {"started": True}),
                (
                    "GET",
                    "/api/v1/kg/graph?document_ids=doc-1&pipeline_hash=pipe-1&max_events=10&max_entities=20&max_links=20",
                ): (200, {"nodes": [{"id": "event:event-1", "meta": {"kind": "event"}}]}),
                (
                    "GET",
                    "/api/v1/kg/events/event-1?document_ids=doc-1&pipeline_hash=pipe-1",
                ): (
                    200,
                    {"event": {"extra_data": {"kg_prompt_template_key": mod.PROMPT_KEYS["kg"]}}},
                ),
                (
                    "POST",
                    "/api/v1/evaluations/ragas/test-gen/from-documents",
                ): (
                    200,
                    {
                        "generated_questions": [{"metadata": {"prompt_template_key": mod.PROMPT_KEYS["testgen"]}}],
                        "saved_case_ids": ["case-1", "case-2"],
                    },
                ),
                ("POST", "/api/v1/evaluations/ragas/regression/runs"): (200, {"id": "run-1"}),
            }
            return (*responses[(method, path)], 0.25)

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
            assert (method, path) == ("POST", "/api/v1/documents/upload")
            return 200, {"id": next(upload_ids)}, 0.5

    def fake_poll_document_until_completed(
        api: object,
        *,
        document_id: str,
        steps: list[dict[str, object]],
        timeout: int,
    ) -> dict[str, object]:
        helper_calls.append(("poll_document_until_completed", (api, document_id, timeout)))
        mod.record_step(steps, "poll_document", 200, {"status": "completed"}, 0.125, doc_status="completed")
        return {"metadata": {"active_pipeline_hash": {"doc-1": "pipe-1", "doc-2": "pipe-2"}[document_id]}}

    def fake_poll_regression_run(
        api: object,
        *,
        run_id: str,
        steps: list[dict[str, object]],
        timeout: int,
    ) -> dict[str, object]:
        helper_calls.append(("poll_regression_run", (api, run_id, timeout)))
        mod.record_step(
            steps,
            "poll_regression_run",
            200,
            {"run": {"status": "completed"}},
            0.125,
            run_status="completed",
        )
        return {
            "run": {
                "status": "completed",
                "summary": {
                    "llm_judge_items": 2,
                    "llm_judge_prompt_template_key": mod.PROMPT_KEYS["judge"],
                },
            },
            "items": [{"meta": {"llm_judge": {"generation": {"prompt_template_key": mod.PROMPT_KEYS["judge"]}}}}],
        }

    def fake_delete_regression_cases(
        api: object,
        *,
        case_ids: list[str],
        steps: list[dict[str, object]],
        timeout: int,
    ) -> dict[str, object]:
        helper_calls.append(("delete_regression_cases", (api, list(case_ids), timeout)))
        return {"deleted_regression_cases": len(case_ids)}

    def fake_perform_cleanup(**kwargs: object) -> dict[str, object]:
        helper_calls.append(
            (
                "perform_cleanup",
                (
                    kwargs["api"],
                    kwargs["dataset_id"],
                    kwargs["document_id"],
                    kwargs["cleanup_mode"],
                    kwargs["delete_dataset_after"],
                    kwargs["timeout"],
                ),
            )
        )
        return {
            "mode": str(kwargs["cleanup_mode"]),
            "purge_status": 200,
            "post_cleanup_document_count": 0,
            "post_cleanup_kg_stats": {"events": 0, "entities": 0, "links": 0},
            "delete_dataset_status": 204,
        }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "LiveApi", FakeLiveApi)
    monkeypatch.setattr(mod, "poll_document_until_completed", fake_poll_document_until_completed)
    monkeypatch.setattr(mod, "poll_regression_run", fake_poll_regression_run)
    monkeypatch.setattr(mod, "delete_regression_cases", fake_delete_regression_cases)
    monkeypatch.setattr(mod, "perform_cleanup", fake_perform_cleanup)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "remote_prompt_matrix.py",
            "--base-url",
            "https://mimirq.test",
            "--tenant-id",
            "tenant-1",
            "--account-id",
            "acct-1",
            "--user-id",
            "user-1",
            "--timeout",
            "41",
            "--poll-timeout",
            "91",
            "--delete-dataset-after",
        ],
    )

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "prompt-matrix" / fixed_run_id).resolve()
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    output = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert constructor_calls == [
        {
            "base_url": "https://mimirq.test",
            "tenant_id": "tenant-1",
            "account_id": "acct-1",
            "user_id": "user-1",
            "timeout": 41,
        }
    ]
    assert [(call["kind"], call["method"], call["path"]) for call in requests] == [
        ("json", "POST", "/api/v1/prompt-templates/builtins/sync"),
        ("json", "POST", "/api/v1/datasets/"),
        ("multipart", "POST", "/api/v1/documents/upload"),
        ("multipart", "POST", "/api/v1/documents/upload"),
        ("json", "POST", "/api/v1/rag/prompt-preview"),
        ("json", "POST", "/api/v1/chat"),
        (
            "json",
            "POST",
            "/api/v1/kg/documents/doc-1/extract"
            "?replace_existing=true&extract_relations=false&extract_skills=false"
            f"&extraction_backend=llm&prompt_template_key={mod.PROMPT_KEYS['kg']}",
        ),
        (
            "json",
            "GET",
            "/api/v1/kg/graph?document_ids=doc-1&pipeline_hash=pipe-1&max_events=10&max_entities=20&max_links=20",
        ),
        (
            "json",
            "GET",
            "/api/v1/kg/events/event-1?document_ids=doc-1&pipeline_hash=pipe-1",
        ),
        ("json", "POST", "/api/v1/evaluations/ragas/test-gen/from-documents"),
        ("json", "POST", "/api/v1/evaluations/ragas/regression/runs"),
    ]
    assert requests[1]["payload"] == {
        "name": f"Prompt Matrix {fixed_run_id}",
        "description": "Remote prompt workflow verification dataset",
        "default_parser_backend": "basic",
        "default_chunk_strategy": "langchain_recursive",
    }
    assert [request["fields"]["dataset_id"] for request in requests[2:4]] == ["ds-1", "ds-1"]
    assert [request["file_path"].name for request in requests[2:4]] == [
        "alpha-rollout.md",
        "beta-rollout.md",
    ]
    assert helper_calls == [
        ("poll_document_until_completed", (ANY, "doc-1", 91)),
        ("poll_document_until_completed", (ANY, "doc-2", 91)),
        ("poll_regression_run", (ANY, "run-1", 91)),
        ("delete_regression_cases", (ANY, ["case-1", "case-2"], 41)),
        ("perform_cleanup", (ANY, "ds-1", "doc-1", "purge_dataset", True, 41)),
    ]
    assert report["ok"] is True
    assert report["artifact_dir"] == str(artifact_dir)
    assert report["base_url"] == "https://mimirq.test"
    assert report["dataset_id"] == "ds-1"
    assert report["documents"] == [
        {
            "document_id": "doc-1",
            "filename": "alpha-rollout.md",
            "pipeline_hash": "pipe-1",
        },
        {
            "document_id": "doc-2",
            "filename": "beta-rollout.md",
            "pipeline_hash": "pipe-2",
        },
    ]
    assert report["prompt_preview"] == {
        "prompt_template_key": mod.PROMPT_KEYS["answer"],
        "citation_count": 1,
        "prompt_chars": len("<context>Alpha rollout uses the blue flag</context>"),
    }
    assert report["chat"] == {
        "prompt_template_key": mod.PROMPT_KEYS["answer"],
        "citation_count": 1,
        "content_preview": "Alpha rollout uses the blue flag.",
    }
    assert report["kg_extract"] == {
        "event_id": "event-1",
        "kg_prompt_template_key": mod.PROMPT_KEYS["kg"],
    }
    assert report["testgen"] == {
        "generated_questions": 1,
        "saved_case_ids": ["case-1", "case-2"],
        "prompt_template_key": mod.PROMPT_KEYS["testgen"],
    }
    assert report["regression_run"] == {
        "run_id": "run-1",
        "status": "completed",
        "llm_judge_items": 2,
        "llm_judge_prompt_template_key": mod.PROMPT_KEYS["judge"],
        "item_generation_prompt_template_key": mod.PROMPT_KEYS["judge"],
    }
    assert report["cleanup"] == {
        "deleted_regression_cases": 2,
        "mode": "purge_dataset",
        "purge_status": 200,
        "post_cleanup_document_count": 0,
        "post_cleanup_kg_stats": {"events": 0, "entities": 0, "links": 0},
        "delete_dataset_status": 204,
    }
    assert [step["name"] for step in report["steps"]] == [
        "sync_builtin_prompt_templates",
        "create_dataset",
        "upload_document",
        "poll_document",
        "upload_document",
        "poll_document",
        "prompt_preview",
        "chat_answer_prompt",
        "kg_extract_prompt",
        "kg_graph",
        "kg_event_detail",
        "testgen_from_documents",
        "create_regression_run",
        "poll_regression_run",
    ]
    assert output == {
        "ok": True,
        "artifact_dir": str(artifact_dir),
        "dataset_id": "ds-1",
        "error": None,
    }


def test_main_failure_runs_finally_cleanup_with_saved_cases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    helper_calls: list[tuple[str, object]] = []
    upload_ids = iter(["doc-1", "doc-2"])

    class FakeLiveApi:
        def __init__(
            self,
            _base_url: str,
            _tenant_id: str,
            _account_id: str,
            _user_id: str,
            _timeout: int,
        ) -> None:
            pass

        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del payload, timeout
            responses: dict[tuple[str, str], tuple[int, object]] = {
                ("POST", "/api/v1/prompt-templates/builtins/sync"): (200, {"synced": True}),
                ("POST", "/api/v1/datasets/"): (200, {"id": "ds-1"}),
                (
                    "POST",
                    "/api/v1/rag/prompt-preview",
                ): (
                    200,
                    {
                        "prompt_template_key": mod.PROMPT_KEYS["answer"],
                        "prompt_text": "<context>Alpha rollout uses the blue flag</context>",
                        "citations": [{"id": "cite-1"}],
                    },
                ),
                ("POST", "/api/v1/chat"): (
                    200,
                    {
                        "metrics": {"prompt_template_key": mod.PROMPT_KEYS["answer"]},
                        "citations": [{"id": "cite-1"}],
                        "content": "Alpha rollout uses the blue flag.",
                    },
                ),
                (
                    "POST",
                    "/api/v1/kg/documents/doc-1/extract"
                    "?replace_existing=true&extract_relations=false&extract_skills=false"
                    f"&extraction_backend=llm&prompt_template_key={mod.PROMPT_KEYS['kg']}",
                ): (200, {"started": True}),
                (
                    "GET",
                    "/api/v1/kg/graph?document_ids=doc-1&pipeline_hash=pipe-1&max_events=10&max_entities=20&max_links=20",
                ): (200, {"nodes": [{"id": "event:event-1", "meta": {"kind": "event"}}]}),
                (
                    "GET",
                    "/api/v1/kg/events/event-1?document_ids=doc-1&pipeline_hash=pipe-1",
                ): (
                    200,
                    {"event": {"extra_data": {"kg_prompt_template_key": mod.PROMPT_KEYS["kg"]}}},
                ),
                (
                    "POST",
                    "/api/v1/evaluations/ragas/test-gen/from-documents",
                ): (
                    200,
                    {
                        "generated_questions": [{"metadata": {"prompt_template_key": mod.PROMPT_KEYS["testgen"]}}],
                        "saved_case_ids": ["case-1", "case-2"],
                    },
                ),
                ("POST", "/api/v1/evaluations/ragas/regression/runs"): (500, {"detail": "run create failed"}),
            }
            return (*responses[(method, path)], 0.25)

        def multipart(
            self,
            method: str,
            path: str,
            *,
            fields: dict[str, str],
            file_path: Path,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del fields, file_path, timeout
            assert (method, path) == ("POST", "/api/v1/documents/upload")
            return 200, {"id": next(upload_ids)}, 0.5

    def fake_poll_document_until_completed(
        _api: object,
        *,
        document_id: str,
        steps: list[dict[str, object]],
        timeout: int,
    ) -> dict[str, object]:
        helper_calls.append(("poll_document_until_completed", (document_id, timeout)))
        mod.record_step(steps, "poll_document", 200, {"status": "completed"}, 0.125, doc_status="completed")
        return {"metadata": {"active_pipeline_hash": {"doc-1": "pipe-1", "doc-2": "pipe-2"}[document_id]}}

    def fake_delete_regression_cases(
        _api: object,
        *,
        case_ids: list[str],
        steps: list[dict[str, object]],
        timeout: int,
    ) -> dict[str, object]:
        del steps
        helper_calls.append(("delete_regression_cases", (list(case_ids), timeout)))
        return {"deleted_regression_cases": len(case_ids)}

    def fake_perform_cleanup(**kwargs: object) -> dict[str, object]:
        helper_calls.append(
            (
                "perform_cleanup",
                (
                    kwargs["dataset_id"],
                    kwargs["document_id"],
                    kwargs["cleanup_mode"],
                    kwargs["delete_dataset_after"],
                    kwargs["timeout"],
                ),
            )
        )
        return {"mode": "purge_dataset", "purge_status": 200}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "LiveApi", FakeLiveApi)
    monkeypatch.setattr(mod, "poll_document_until_completed", fake_poll_document_until_completed)
    monkeypatch.setattr(mod, "delete_regression_cases", fake_delete_regression_cases)
    monkeypatch.setattr(mod, "perform_cleanup", fake_perform_cleanup)
    monkeypatch.setattr(sys, "argv", ["remote_prompt_matrix.py"])

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "prompt-matrix" / fixed_run_id).resolve()
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    output = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert helper_calls == [
        ("poll_document_until_completed", ("doc-1", 1800)),
        ("poll_document_until_completed", ("doc-2", 1800)),
        ("delete_regression_cases", (["case-1", "case-2"], 1200)),
        ("perform_cleanup", ("ds-1", "doc-1", "purge_dataset", False, 1200)),
    ]
    assert report["ok"] is False
    assert report["error"] == 'create regression run failed: {"detail": "run create failed"}'
    assert report["cleanup"] == {
        "deleted_regression_cases": 2,
        "mode": "purge_dataset",
        "purge_status": 200,
    }
    assert output == {
        "ok": False,
        "artifact_dir": str(artifact_dir),
        "dataset_id": "ds-1",
        "error": 'create regression run failed: {"detail": "run create failed"}',
    }


def test_main_first_document_poll_failure_preserves_id_for_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fixed_run_id: str,
) -> None:
    helper_calls: list[tuple[str, object]] = []
    finalize_document_ids: list[list[str]] = []

    class FakeLiveApi:
        def __init__(self, *_args: object) -> None:
            pass

        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del payload, timeout
            responses: dict[tuple[str, str], tuple[int, object]] = {
                ("POST", "/api/v1/prompt-templates/builtins/sync"): (200, {"synced": True}),
                ("POST", "/api/v1/datasets/"): (200, {"id": "ds-1"}),
            }
            return (*responses[(method, path)], 0.25)

        def multipart(
            self,
            method: str,
            path: str,
            *,
            fields: dict[str, str],
            file_path: Path,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del fields, file_path, timeout
            assert (method, path) == ("POST", "/api/v1/documents/upload")
            return 200, {"id": "doc-1"}, 0.5

    def fake_poll_document_until_completed(
        _api: object,
        *,
        document_id: str,
        steps: list[dict[str, object]],
        timeout: int,
    ) -> dict[str, object]:
        helper_calls.append(("poll_document_until_completed", (document_id, timeout)))
        del steps
        raise RuntimeError("first document poll failed")

    def fake_perform_cleanup(**kwargs: object) -> dict[str, object]:
        helper_calls.append(
            (
                "perform_cleanup",
                (
                    kwargs["dataset_id"],
                    kwargs["document_id"],
                    kwargs["cleanup_mode"],
                    kwargs["delete_dataset_after"],
                    kwargs["timeout"],
                ),
            )
        )
        return {"mode": "purge_dataset", "purge_status": 200}

    original_finalize_cleanup = mod.finalize_cleanup

    def capture_finalize_cleanup(*args: object, **kwargs: object) -> None:
        finalize_document_ids.append(list(kwargs["document_ids"]))
        original_finalize_cleanup(*args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "LiveApi", FakeLiveApi)
    monkeypatch.setattr(mod, "poll_document_until_completed", fake_poll_document_until_completed)
    monkeypatch.setattr(mod, "perform_cleanup", fake_perform_cleanup)
    monkeypatch.setattr(mod, "finalize_cleanup", capture_finalize_cleanup)
    monkeypatch.setattr(sys, "argv", ["remote_prompt_matrix.py"])

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "prompt-matrix" / fixed_run_id).resolve()
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))

    assert rc == 1
    assert finalize_document_ids == [["doc-1"]]
    assert helper_calls == [
        ("poll_document_until_completed", ("doc-1", 1800)),
        ("perform_cleanup", ("ds-1", "doc-1", "purge_dataset", False, 1200)),
    ]
    assert report["error"] == "first document poll failed"
    assert report["cleanup"] == {"mode": "purge_dataset", "purge_status": 200}


def test_main_test_generation_validation_failure_deletes_saved_cases_first(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fixed_run_id: str,
) -> None:
    helper_calls: list[tuple[str, object]] = []
    upload_ids = iter(["doc-1", "doc-2"])

    class FakeLiveApi:
        def __init__(self, *_args: object) -> None:
            pass

        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del payload, timeout
            responses: dict[tuple[str, str], tuple[int, object]] = {
                ("POST", "/api/v1/prompt-templates/builtins/sync"): (200, {"synced": True}),
                ("POST", "/api/v1/datasets/"): (200, {"id": "ds-1"}),
                ("POST", "/api/v1/evaluations/ragas/test-gen/from-documents"): (
                    200,
                    {
                        "generated_questions": [{"metadata": {"prompt_template_key": "unexpected-template"}}],
                        "saved_case_ids": ["case-1", "case-2"],
                    },
                ),
            }
            return (*responses[(method, path)], 0.25)

        def multipart(
            self,
            method: str,
            path: str,
            *,
            fields: dict[str, str],
            file_path: Path,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del fields, file_path, timeout
            assert (method, path) == ("POST", "/api/v1/documents/upload")
            return 200, {"id": next(upload_ids)}, 0.5

    def fake_poll_document_until_completed(
        _api: object,
        *,
        document_id: str,
        steps: list[dict[str, object]],
        timeout: int,
    ) -> dict[str, object]:
        helper_calls.append(("poll_document_until_completed", (document_id, timeout)))
        mod.record_step(
            steps,
            "poll_document",
            200,
            {"status": "completed"},
            0.125,
            doc_status="completed",
        )
        return {"metadata": {"active_pipeline_hash": f"pipe-{document_id[-1]}"}}

    def fake_delete_regression_cases(
        _api: object,
        *,
        case_ids: list[str],
        steps: list[dict[str, object]],
        timeout: int,
    ) -> dict[str, object]:
        del steps
        helper_calls.append(("delete_regression_cases", (list(case_ids), timeout)))
        return {"deleted_regression_cases": len(case_ids)}

    def fake_perform_cleanup(**kwargs: object) -> dict[str, object]:
        helper_calls.append(
            (
                "perform_cleanup",
                (
                    kwargs["dataset_id"],
                    kwargs["document_id"],
                    kwargs["cleanup_mode"],
                    kwargs["delete_dataset_after"],
                    kwargs["timeout"],
                ),
            )
        )
        return {"mode": "purge_dataset", "purge_status": 200}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "LiveApi", FakeLiveApi)
    monkeypatch.setattr(mod, "poll_document_until_completed", fake_poll_document_until_completed)
    monkeypatch.setattr(mod, "run_prompt_preview_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "run_chat_answer_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "run_kg_extract_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "delete_regression_cases", fake_delete_regression_cases)
    monkeypatch.setattr(mod, "perform_cleanup", fake_perform_cleanup)
    monkeypatch.setattr(sys, "argv", ["remote_prompt_matrix.py"])

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "prompt-matrix" / fixed_run_id).resolve()
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))

    assert rc == 1
    assert helper_calls == [
        ("poll_document_until_completed", ("doc-1", 1800)),
        ("poll_document_until_completed", ("doc-2", 1800)),
        ("delete_regression_cases", (["case-1", "case-2"], 1200)),
        ("perform_cleanup", ("ds-1", "doc-1", "purge_dataset", False, 1200)),
    ]
    assert "test generation metadata missing prompt_template_key" in report["error"]
    assert report["cleanup"] == {
        "deleted_regression_cases": 2,
        "mode": "purge_dataset",
        "purge_status": 200,
    }


def test_delete_regression_cases_preserves_order_and_accepts_204() -> None:
    calls: list[tuple[str, str, int | None]] = []
    steps: list[dict[str, object]] = []

    class FakeLiveApi:
        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del payload
            calls.append((method, path, timeout))
            responses: dict[str, tuple[int, object]] = {
                "/api/v1/evaluations/ragas/regression/cases/case-1": (204, None),
                "/api/v1/evaluations/ragas/regression/cases/case-2": (200, {"deleted": True}),
            }
            return (*responses[path], 0.02)

    summary = mod.delete_regression_cases(
        FakeLiveApi(),
        case_ids=["case-1", "case-2"],
        steps=steps,
        timeout=77,
    )

    assert summary == {"deleted_regression_cases": 2}
    assert calls == [
        ("DELETE", "/api/v1/evaluations/ragas/regression/cases/case-1", 77),
        ("DELETE", "/api/v1/evaluations/ragas/regression/cases/case-2", 77),
    ]
    assert [step["name"] for step in steps] == [
        "cleanup:delete_regression_case",
        "cleanup:delete_regression_case",
    ]
