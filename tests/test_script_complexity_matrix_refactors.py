import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY
from uuid import UUID

import pytest

import scripts.dr_verify_restore as dr_mod
import scripts.learn_fusion_weights_offline as fusion_mod
import scripts.remote_kb_boundary_matrix as kb_mod
import scripts.run_sample_retrieval_benchmark as sample_mod
import scripts.seed_ci_kg_search_regression as seed_mod


def _fixture_file(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "fixtures" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name, encoding="utf-8")
    return path


def _remote_fixture_map(tmp_path: Path, *, alpha_name: str, beta_name: str) -> dict[str, Path]:
    return {
        "alpha-handbook.md": _fixture_file(tmp_path, alpha_name),
        "beta-runbook.md": _fixture_file(tmp_path, beta_name),
    }


def _remote_success_dataset_key(payload: dict[str, object] | None) -> str:
    dataset_name = str((payload or {}).get("name") or "")
    return "alpha" if "Alpha" in dataset_name else "beta"


def _remote_success_export_body(
    path: str,
    *,
    dataset_ids: dict[str, str],
    document_ids: dict[str, str],
) -> dict[str, object]:
    key = "alpha" if dataset_ids["alpha"] in path else "beta"
    return {"documents": [{"document_id": document_ids[key]}]}


def _remote_success_retrieve_body(
    payload: dict[str, object] | None,
    *,
    dataset_ids: dict[str, str],
    document_ids: dict[str, str],
) -> dict[str, object]:
    if payload and payload.get("document_ids"):
        return {"citations": [{"document_id": document_ids["beta"], "chunk_content": "BETA-QUARTZ"}]}
    if payload and payload.get("dataset_id") == dataset_ids["beta"]:
        return {"citations": [{"document_id": document_ids["beta"], "chunk_content": "BETA-QUARTZ"}]}
    return {"citations": [{"document_id": document_ids["alpha"], "chunk_content": "ALOE-COMET"}]}


def _remote_success_chat_body(
    payload: dict[str, object] | None,
    *,
    document_ids: dict[str, str],
) -> dict[str, object]:
    if payload and payload.get("document_ids"):
        return {"citations": [{"document_id": document_ids["beta"]}], "response": "BETA-QUARTZ"}
    return {"citations": [{"document_id": document_ids["alpha"]}], "response": "ALOE-COMET"}


def _remote_success_json_response(
    path: str,
    payload: dict[str, object] | None,
    *,
    dataset_ids: dict[str, str],
    document_ids: dict[str, str],
) -> kb_mod.ApiResponse:
    if path == "/api/v1/health":
        return kb_mod.ApiResponse(200, {}, 0.01)
    if path == "/api/v1/datasets/":
        return kb_mod.ApiResponse(
            200,
            {"id": dataset_ids[_remote_success_dataset_key(payload)]},
            0.01,
        )
    if path.endswith("/chunks?limit=200"):
        return kb_mod.ApiResponse(200, {"items": [{"id": "chunk-1"}]}, 0.01)
    if path.endswith("/parsed-content?max_chars=8000"):
        return kb_mod.ApiResponse(200, {"content": "parsed text"}, 0.01)
    if "/documents/export" in path:
        return kb_mod.ApiResponse(
            200,
            _remote_success_export_body(path, dataset_ids=dataset_ids, document_ids=document_ids),
            0.01,
        )
    if path == "/api/v1/rag/retrieve-preview":
        return kb_mod.ApiResponse(
            200,
            _remote_success_retrieve_body(payload, dataset_ids=dataset_ids, document_ids=document_ids),
            0.01,
        )
    if path == "/api/v1/chat":
        return kb_mod.ApiResponse(200, _remote_success_chat_body(payload, document_ids=document_ids), 0.01)
    raise AssertionError(path)


class _RemoteSuccessApi:
    def __init__(
        self,
        requests: list[tuple[str, str, dict[str, object] | None]],
        dataset_ids: dict[str, str],
        document_ids: dict[str, str],
    ) -> None:
        self.requests = requests
        self.dataset_ids = dataset_ids
        self.document_ids = document_ids

    def json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        timeout: int | None = None,
    ) -> kb_mod.ApiResponse:
        del timeout
        self.requests.append((method, path, payload))
        return _remote_success_json_response(
            path,
            payload,
            dataset_ids=self.dataset_ids,
            document_ids=self.document_ids,
        )

    def multipart(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str],
        file_path: Path,
        timeout: int | None = None,
    ) -> kb_mod.ApiResponse:
        del timeout
        self.requests.append((method, path, fields))
        key = "alpha" if "alpha" in file_path.name else "beta"
        return kb_mod.ApiResponse(200, {"id": self.document_ids[key]}, 0.01)


def _build_remote_failure_api() -> type[object]:
    class _Api:
        def __init__(self, *_args: object) -> None:
            pass

        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            timeout: int | None = None,
        ) -> kb_mod.ApiResponse:
            del method, payload, timeout
            if path == "/api/v1/health":
                return kb_mod.ApiResponse(200, {}, 0.01)
            if path == "/api/v1/datasets/":
                return kb_mod.ApiResponse(200, {"id": "ds-1"}, 0.01)
            if path.endswith("/chunks?limit=200"):
                return kb_mod.ApiResponse(200, {"items": [{"id": "chunk-1"}]}, 0.01)
            if path.endswith("/parsed-content?max_chars=8000"):
                return kb_mod.ApiResponse(200, {"content": "parsed"}, 0.01)
            if "/documents/export" in path:
                return kb_mod.ApiResponse(200, {"documents": [{"document_id": "doc-1"}]}, 0.01)
            if path in {"/api/v1/rag/retrieve-preview", "/api/v1/chat"}:
                return kb_mod.ApiResponse(
                    200,
                    {"citations": [{"document_id": "doc-1"}], "response": "alpha"},
                    0.01,
                )
            raise AssertionError(path)

        def multipart(
            self,
            method: str,
            path: str,
            *,
            fields: dict[str, str],
            file_path: Path,
            timeout: int | None = None,
        ) -> kb_mod.ApiResponse:
            del method, path, fields, file_path, timeout
            return kb_mod.ApiResponse(200, {"id": "doc-1"}, 0.01)

    return _Api


def _configure_remote_main(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
    run_id: str,
    fixture_map: dict[str, Path],
    api_cls: type[object],
) -> None:
    monkeypatch.setattr(
        kb_mod,
        "time",
        SimpleNamespace(strftime=lambda _fmt: run_id, sleep=lambda _s: None),
    )
    monkeypatch.setattr(kb_mod, "make_fixture_files", lambda _dir: fixture_map)
    monkeypatch.setattr(kb_mod, "LiveApi", api_cls)
    monkeypatch.setattr(kb_mod, "wait_for_document_completed", lambda *_args, **_kwargs: {"status": "completed"})
    monkeypatch.setattr(sys, "argv", ["remote_kb_boundary_matrix.py", "--artifact-dir", str(tmp_path / "artifacts")])


class _Field:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> tuple[str, str, object]:
        return ("eq", self.name, other)


class _TestDatasetPermissionEnum:
    ALL_TEAM_MEMBERS = "ALL_TEAM_MEMBERS"


class _TestDataset:
    id = _Field("id")
    tenant_id = _Field("tenant_id")

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class _TestDocument:
    id = _Field("id")
    tenant_id = _Field("tenant_id")

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)
        self.error_message = kwargs.get("error_message")


class _TestDocumentChunk:
    tenant_id = _Field("tenant_id")
    document_id = _Field("document_id")

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class _TestMetadata:
    def __init__(self) -> None:
        self.create_all_calls: list[object] = []

    def create_all(self, *, bind: object) -> None:
        self.create_all_calls.append(bind)


class _TestBase:
    metadata = _TestMetadata()


class _TestQuery:
    def __init__(self, model: type[object], db: "_TestDb") -> None:
        self.model = model
        self.db = db
        self.filters: list[object] = []

    def filter(self, *conditions: object) -> "_TestQuery":
        self.filters.extend(conditions)
        return self

    def first(self) -> object | None:
        return self.db.first_results.get(self.model)

    def delete(self, *, synchronize_session: bool) -> None:
        self.db.deletes.append((self.model.__name__, list(self.filters), synchronize_session))


class _TestDb:
    def __init__(self) -> None:
        self.first_results: dict[type[object], object | None] = {_TestDataset: None, _TestDocument: None}
        self.added: list[object] = []
        self.deletes: list[tuple[str, list[object], bool]] = []
        self.commits = 0
        self.closed = False

    def query(self, model: type[object]) -> _TestQuery:
        return _TestQuery(model, self)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def _seed_fixture_payload() -> dict[str, object]:
    return {
        "tenant_id": "4ccb6554-4856-4916-b6ea-4430f8fa1bbd",
        "account_id": "ci-bot",
        "dataset": {
            "id": "bcfec05a-b631-40c1-9460-9c399f435bbf",
            "name": "Fixture",
            "description": "desc",
        },
        "documents": [
            {
                "id": "1aa35639-f176-44c8-8fc3-914bc39bed77",
                "filename": "alpha.md",
                "file_type": "md",
                "doc_metadata": {"active_pipeline_hash": "pipe-1"},
                "chunks": [
                    {
                        "id": "58a1551c-3f5f-46c7-bf73-a7426d7b7fad",
                        "chunk_index": 0,
                        "content": "hello",
                        "page_number": "7",
                    },
                    {
                        "id": "3fcc4c34-f12f-4f1e-9aca-dd9c8ca94c0d",
                        "chunk_index": 1,
                        "content": "world",
                    },
                ],
            }
        ],
    }


def _install_seed_mocks(monkeypatch: pytest.MonkeyPatch, db: _TestDb) -> tuple[list[object], list[dict[str, object]]]:
    migration_calls: list[object] = []
    kg_calls: list[dict[str, object]] = []
    monkeypatch.setattr(seed_mod, "Dataset", _TestDataset)
    monkeypatch.setattr(seed_mod, "DatasetPermissionEnum", _TestDatasetPermissionEnum)
    monkeypatch.setattr(seed_mod, "DBDocument", _TestDocument)
    monkeypatch.setattr(seed_mod, "DocumentChunk", _TestDocumentChunk)
    monkeypatch.setattr(seed_mod, "Base", _TestBase)
    monkeypatch.setattr(seed_mod, "engine", "engine-sentinel")
    monkeypatch.setattr(seed_mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(seed_mod, "apply_runtime_migrations", lambda engine: migration_calls.append(engine))
    monkeypatch.setattr(seed_mod, "_seed_kg_rows", lambda **kwargs: kg_calls.append(kwargs))
    return migration_calls, kg_calls


def _block_seed_db_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unexpected_side_effect() -> None:
        raise AssertionError("fixture validation must precede DB side effects")

    monkeypatch.setattr(seed_mod, "_ensure_schema_ready", _unexpected_side_effect)
    monkeypatch.setattr(seed_mod, "SessionLocal", _unexpected_side_effect)


def test_dr_run_smoke_test_redacts_secrets_and_loads_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _run(cmd: list[str], **kwargs: object) -> SimpleNamespace:
        out_path = Path(cmd[cmd.index("--out") + 1])
        out_path.write_text(json.dumps({"dataset_id": "ds-smoke"}), encoding="utf-8")
        assert kwargs["cwd"] == str(tmp_path)
        return SimpleNamespace(returncode=3, stdout="x" * 2105, stderr="y" * 2105)

    monkeypatch.setattr(dr_mod.subprocess, "run", _run)

    exit_code, report = dr_mod._run_smoke_test(
        repo_root=tmp_path,
        base_url="http://example.test",
        tenant_id="tenant-1",
        auth_mode="jwt",
        user_id="user-1",
        token="secret-token",
        allow_unstructured=True,
        verbose=True,
    )

    assert exit_code == 3
    assert report["command"] == [
        dr_mod.sys.executable,
        "scripts/smoke_test.py",
        "--base-url",
        "http://example.test",
        "--tenant-id",
        "tenant-1",
        "--out",
        ANY,
        "--auth-mode",
        "jwt",
        "--token",
        "***",
        "--user-id",
        "user-1",
        "--allow-unstructured",
        "--verbose",
    ]
    assert report["stdout_tail"] == "x" * 2000
    assert report["stderr_tail"] == "y" * 2000
    assert report["report"] == {"dataset_id": "ds-smoke"}


def test_dr_main_readiness_failure_preserves_exit_and_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Client:
        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None) -> dr_mod.httpx.Response:
            assert headers is None
            request = dr_mod.httpx.Request("GET", url)
            return dr_mod.httpx.Response(503, json={"ok": False}, request=request)

    monkeypatch.setattr(dr_mod.httpx, "Client", lambda **_kwargs: _Client())
    out_path = tmp_path / "dr-report.json"

    exit_code = dr_mod.main(["--base-url", "http://api.test", "--out", str(out_path)])
    printed = json.loads(capsys.readouterr().out)
    report = json.loads(out_path.read_text(encoding="utf-8"))

    assert exit_code == 2
    assert printed["error"] == "readiness_failed"
    assert report["schema"] == "mimirq.dr_verify_restore.v1"
    assert report["api_base"] == "http://api.test/api/v1"
    assert report["steps"]["ready"]["status_code"] == 503


def test_dr_main_uses_smoke_dataset_for_index_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Client:
        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None) -> dr_mod.httpx.Response:
            assert url.endswith("/health/ready")
            assert headers is None
            request = dr_mod.httpx.Request("GET", url)
            return dr_mod.httpx.Response(200, json={"ok": True}, request=request)

    audit_calls: list[dict[str, object]] = []

    def _audit(
        _client: object,
        *,
        api_base: str,
        headers: dict[str, str],
        dataset_id: str,
        max_check_ids: int,
        milvus_list_limit: int,
        sample_limit: int,
    ) -> tuple[bool, dict[str, object]]:
        audit_calls.append(
            {
                "api_base": api_base,
                "headers": headers,
                "dataset_id": dataset_id,
                "max_check_ids": max_check_ids,
                "milvus_list_limit": milvus_list_limit,
                "sample_limit": sample_limit,
            }
        )
        return True, {
            "url": "http://example.test/api/v1/observability/index-audit?dataset_id=ds-smoke",
            "status_code": 200,
            "body": {
                "vector_id_missing": 0,
                "vector_ids_missing_in_backend": 0,
                "milvus_orphan_ids_sample": [],
            },
        }

    monkeypatch.setattr(dr_mod.httpx, "Client", lambda **_kwargs: _Client())
    monkeypatch.setattr(
        dr_mod,
        "_run_smoke_test",
        lambda **_kwargs: (0, {"report": {"dataset_id": "ds-smoke"}, "exit_code": 0}),
    )
    monkeypatch.setattr(dr_mod, "_get_index_audit", _audit)

    exit_code = dr_mod.main(
        [
            "--base-url",
            "http://example.test/api/v1",
            "--tenant-id",
            "tenant-1",
            "--user-id",
            "user-1",
            "--out",
            str(tmp_path / "report.json"),
        ]
    )
    printed = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert printed["ok"] is True
    assert printed["steps"]["index_audit_check"] == {
        "vector_id_missing": 0,
        "vector_ids_missing_in_backend": 0,
        "milvus_orphan_ids_sample_count": 0,
    }
    assert audit_calls == [
        {
            "api_base": "http://example.test/api/v1",
            "headers": {"X-Tenant-ID": "tenant-1", "X-User-ID": "user-1"},
            "dataset_id": "ds-smoke",
            "max_check_ids": 2000,
            "milvus_list_limit": 500,
            "sample_limit": 20,
        }
    ]


def test_fusion_weight_variants_are_deterministic_and_normalized() -> None:
    assert fusion_mod._weight_variants(channels=[" vector ", "bm25"], step=0.5) == [
        {"bm25": 1.0},
        {"bm25": 0.5, "vector": 0.5},
        {"vector": 1.0},
    ]


def test_fusion_main_preserves_request_sequence_and_report_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.regression_cases.v1",
                "dataset_id": "ds-1",
                "items": [{"question": "What happened?", "reference_sources": ["doc-1"]}],
            }
        ),
        encoding="utf-8",
    )
    out_json = tmp_path / "search.json"
    out_weights = tmp_path / "weights.json"
    post_calls: list[dict[str, object]] = []

    class _Response:
        def __init__(self, weight_score: float) -> None:
            self._weight_score = weight_score

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"citations": [{"score": self._weight_score}]}

    class _Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> _Response:
            weights = dict(json["rag_config"]["fusion_weights"])
            post_calls.append({"url": url, "headers": headers, "body": json, "weights": weights})
            return _Response(weights.get("vector", 0.0))

    monkeypatch.setattr(fusion_mod.httpx, "Client", _Client)
    monkeypatch.setattr(
        fusion_mod,
        "compute_retrieval_item_meta",
        lambda *, case, citations: {
            "question": case["question"],
            "score": float((citations or [{}])[0].get("score") or 0.0),
        },
    )
    monkeypatch.setattr(
        fusion_mod,
        "build_retrieval_gate_summary",
        lambda items_meta: {
            "retrieval_mrr": round(sum(float(row["score"]) for row in items_meta) / len(items_meta), 6)
            if items_meta
            else 0.0,
            "retrieval_recall": round(sum(float(row["score"]) for row in items_meta) / len(items_meta), 6)
            if items_meta
            else 0.0,
            "retrieval_ndcg_at_10": 0.25,
            "retrieval_hit_at_10": 0.5,
        },
    )
    monkeypatch.setattr(fusion_mod, "stable_hash", lambda text, length=16: text[:length])

    exit_code = fusion_mod.main(
        [
            "--cases",
            str(cases_path),
            "--channels",
            "vector,bm25",
            "--step",
            "0.5",
            "--tenant-id",
            "tenant-1",
            "--user-id",
            "user-1",
            "--out-json",
            str(out_json),
            "--out-weights",
            str(out_weights),
            "--top-n",
            "2",
        ]
    )
    stdout = capsys.readouterr().out
    report = json.loads(out_json.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert [call["weights"] for call in post_calls] == [
        {"bm25": 1.0},
        {"bm25": 0.5, "vector": 0.5},
        {"vector": 1.0},
    ]
    assert all(call["url"] == "http://localhost:8000/api/v1/rag/retrieve" for call in post_calls)
    assert report["schema"] == "mimirq.fusion_weights_search.v1"
    assert report["best"]["weights"] == {"vector": 1.0}
    assert json.loads(out_weights.read_text(encoding="utf-8")) == {"vector": 1.0}
    assert "| rank | objective | recall | ndcg@10 | hit@10 | weights |" in stdout
    assert "Best weights:" in stdout


def test_remote_boundary_case_reports_failures_in_stable_order() -> None:
    failures = kb_mod.evaluate_boundary_case(
        {
            "name": "alpha",
            "allowed_document_ids": ["doc-1"],
            "expected_document_ids": ["doc-1"],
            "required_document_ids": ["doc-2"],
            "expected_terms": ["ALOE"],
            "forbidden_terms": ["QUARTZ"],
            "min_citations": 2,
            "max_citations": 1,
        },
        citation_doc_ids=["doc-3"],
        citation_count=3,
        response_text="Missing the expected token but includes quartz.",
    )

    assert failures == [
        "alpha: unexpected document_ids=['doc-3']",
        "alpha: expected_document_ids=['doc-1'] actual=['doc-3']",
        "alpha: required_document_ids missing=['doc-2'] actual=['doc-3']",
        "alpha: max_citations=1 actual=3",
        "alpha: missing expected_terms=['ALOE']",
        "alpha: forbidden_terms=['QUARTZ']",
    ]


def test_remote_main_success_writes_summary_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture_map = _remote_fixture_map(tmp_path, alpha_name="alpha-handbook.md", beta_name="beta-runbook.md")
    cleanup_calls: list[str] = []
    requests: list[tuple[str, str, dict[str, object] | None]] = []
    document_ids = {"alpha": "doc-alpha", "beta": "doc-beta"}
    dataset_ids = {"alpha": "ds-alpha", "beta": "ds-beta"}
    _configure_remote_main(
        monkeypatch,
        tmp_path=tmp_path,
        run_id="20260816-010203",
        fixture_map=fixture_map,
        api_cls=lambda *_args: _RemoteSuccessApi(
            requests=requests,
            dataset_ids=dataset_ids,
            document_ids=document_ids,
        ),
    )
    monkeypatch.setattr(
        kb_mod,
        "perform_cleanup",
        lambda _api, *, steps, dataset_id: cleanup_calls.append(dataset_id) or {"dataset_id": dataset_id, "ok": True},
    )
    monkeypatch.setattr(sys, "argv", ["remote_kb_boundary_matrix.py", "--artifact-dir", str(tmp_path / "artifacts")])

    exit_code = kb_mod.main()
    stdout = capsys.readouterr().out
    report_path = tmp_path / "artifacts" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert cleanup_calls == ["ds-alpha", "ds-beta"]
    assert [req[:2] for req in requests[:6]] == [
        ("GET", "/api/v1/health"),
        ("POST", "/api/v1/datasets/"),
        ("POST", "/api/v1/documents/upload"),
        ("GET", "/api/v1/documents/doc-alpha/chunks?limit=200"),
        ("GET", "/api/v1/documents/doc-alpha/parsed-content?max_chars=8000"),
        ("POST", "/api/v1/datasets/"),
    ]
    assert report["summary"]["ok"] is True
    assert report["summary"]["retrieve_checks"][0]["name"] == "dataset_alpha_positive"
    assert report["summary"]["chat_checks"][1]["name"] == "cross_dataset_beta_chat_positive"
    assert '"ok": true' in stdout


def test_remote_main_failure_writes_report_and_skips_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_remote_main(
        monkeypatch,
        tmp_path=tmp_path,
        run_id="20260816-030405",
        fixture_map=_remote_fixture_map(tmp_path, alpha_name="alpha.md", beta_name="beta.md"),
        api_cls=_build_remote_failure_api(),
    )
    monkeypatch.setattr(kb_mod, "perform_cleanup", lambda *_args, **_kwargs: pytest.fail("cleanup should not run"))
    monkeypatch.setattr(
        kb_mod,
        "evaluate_boundary_case",
        lambda case, **_kwargs: ["boom"] if case["name"] == "dataset_alpha_positive" else [],
    )

    exit_code = kb_mod.main()
    printed = json.loads(capsys.readouterr().out)
    report_path = tmp_path / "artifacts" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert printed["ok"] is False
    assert "retrieve case failed dataset_alpha_positive" in printed["error"]
    assert report["summary"]["ok"] is False
    assert "cleanup" not in report["summary"]


def test_sample_validate_fixture_rejects_unknown_chunk_ids() -> None:
    with pytest.raises(ValueError, match=r"queries\[0\] references unknown chunk_id\(s\): \['chunk-2'\]"):
        sample_mod._validate_fixture(
            {
                "schema": "mimirq.sample_retrieval_fixture.v1",
                "documents": [{"chunk_id": "chunk-1", "text": "sample"}],
                "queries": [{"question": "sample?", "expected_chunk_ids": ["chunk-2"]}],
            }
        )


def test_sample_evaluate_query_preserves_family_metrics() -> None:
    class _Retriever:
        def _hybrid_search(self, **_kwargs: object) -> list[dict[str, object]]:
            return [{"chunk_id": "chunk-1"}, {"chunk_id": "chunk-2"}, {"chunk_id": "chunk-3"}]

    result = sample_mod._evaluate_query(
        retriever=_Retriever(),
        tenant_id=sample_mod._uuid_from_seed("tenant"),
        question="sample?",
        expected_chunk_ids=["chunk-2"],
        expected_family_keys=["family-b"],
        top_k=3,
        retrieval_mode="keyword",
        chunk_doc_ids={"chunk-1": "doc-a", "chunk-2": "doc-a", "chunk-3": "doc-b"},
        chunk_family_keys={"chunk-1": "family-a", "chunk-2": "family-a", "chunk-3": "family-b"},
    )

    assert result["ranked_chunk_ids"] == ["chunk-1", "chunk-2", "chunk-3"]
    assert result["ranked_family_keys"] == ["family-a", "family-b"]
    assert result["hit_at_k"] == 1.0
    assert result["reciprocal_rank"] == 0.5
    assert result["family_reciprocal_rank"] == 0.5
    assert result["distinct_documents"] == 2
    assert result["distinct_families"] == 2
    assert result["top_doc_share"] == pytest.approx(2 / 3, abs=1e-6)
    assert result["top_family_share"] == pytest.approx(2 / 3, abs=1e-6)


def test_sample_main_uses_cli_defaults_and_preserves_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []

    def _run_benchmark(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "summary": {
                "cases_total": 2,
                "hit_at_k": 1.0,
                "mrr": 0.75,
                "ndcg_at_k": 0.82,
            }
        }

    monkeypatch.setattr(sample_mod, "run_benchmark", _run_benchmark)

    exit_code = sample_mod.main([])
    stdout = capsys.readouterr().out.strip()

    assert exit_code == 0
    assert calls == [
        {
            "fixture_path": (sample_mod._repo_root() / "data" / "sample" / "retrieval_fixture_v1.json").resolve(),
            "output_path": (sample_mod._repo_root() / "runs" / "sample_bench.json").resolve(),
            "top_k": None,
            "retrieval_mode": None,
            "sparse_retrieval_enabled": False,
            "sparse_retrieval_provider": "deterministic",
            "colbert_retrieval_enabled": None,
            "colbert_retrieval_provider": None,
        }
    ]
    assert stdout == (
        "[sample-bench] cases=2 hit@k=1.0 mrr=0.75 ndcg@k=0.82 "
        f"out={(sample_mod._repo_root() / 'runs' / 'sample_bench.json').resolve()}"
    )


def test_seed_build_cases_bundle_requires_reference_sources() -> None:
    with pytest.raises(ValueError, match="each case must include reference_sources\\[\\]"):
        seed_mod.build_cases_bundle(
            {
                "dataset": {"id": "f65ba34b-e284-40fb-9ce8-35eca0a8e4cd"},
                "cases": [{"question": "What happened?"}],
            }
        )


def test_seed_fixture_rejects_empty_documents_before_db_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _seed_fixture_payload()
    fixture["documents"] = []
    _block_seed_db_side_effects(monkeypatch)

    with pytest.raises(ValueError, match="fixture.documents must be a non-empty list"):
        seed_mod.seed_fixture(fixture=fixture)


def test_seed_fixture_rejects_bad_tenant_uuid_before_db_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _seed_fixture_payload()
    fixture["tenant_id"] = "not-a-uuid"
    _block_seed_db_side_effects(monkeypatch)

    with pytest.raises(ValueError):
        seed_mod.seed_fixture(fixture=fixture)


def test_seed_fixture_uses_db_mocks_and_preserves_chunk_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _TestDb()
    migration_calls, kg_calls = _install_seed_mocks(monkeypatch, db)
    membership_calls: list[dict[str, object]] = []

    def _record_membership(db_arg: object, **kwargs: object) -> None:
        membership_calls.append({"db": db_arg, **kwargs})

    monkeypatch.setattr(seed_mod, "ensure_fixture_tenant_owner", _record_membership)
    fixture = _seed_fixture_payload()

    seed_mod.seed_fixture(fixture=fixture)

    assert migration_calls == ["engine-sentinel", "engine-sentinel"]
    assert _TestBase.metadata.create_all_calls == ["engine-sentinel"]
    assert membership_calls == [
        {
            "db": db,
            "tenant_id": UUID("4ccb6554-4856-4916-b6ea-4430f8fa1bbd"),
            "account_id": "ci-bot",
        }
    ]
    assert db.commits == 2
    assert db.closed is True
    assert [type(obj).__name__ for obj in db.added] == [
        "_TestDataset",
        "_TestDocument",
        "_TestDocumentChunk",
        "_TestDocumentChunk",
    ]
    document = db.added[1]
    chunk = db.added[2]
    assert document.file_path == "ci://alpha.md"
    assert document.chunk_count == 2
    assert chunk.page_number == 7
    assert chunk.doc_metadata["doc_pipeline_key"] == f"{document.id}:pipe-1"
    assert db.deletes == [
        (
            "_TestDocumentChunk",
            [
                ("eq", "tenant_id", UUID("4ccb6554-4856-4916-b6ea-4430f8fa1bbd")),
                ("eq", "document_id", UUID("1aa35639-f176-44c8-8fc3-914bc39bed77")),
            ],
            False,
        )
    ]
    assert kg_calls == [
        {
            "db": db,
            "tenant_id": UUID("4ccb6554-4856-4916-b6ea-4430f8fa1bbd"),
            "account_id": "ci-bot",
            "fixture": fixture,
        }
    ]


def test_seed_main_writes_cases_bundle_and_ok_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = {"dataset": {"id": "ds-1"}, "cases": [{"question": "Q", "reference_sources": ["doc-1"]}]}
    written: list[tuple[Path, dict[str, object]]] = []
    seeded: list[dict[str, object]] = []

    monkeypatch.setattr(seed_mod, "_load_json", lambda _path: fixture)
    monkeypatch.setattr(seed_mod, "seed_fixture", lambda *, fixture: seeded.append(fixture))
    monkeypatch.setattr(
        seed_mod,
        "build_cases_bundle",
        lambda payload: {"schema": "mimirq.regression_cases.v1", **payload},
    )
    monkeypatch.setattr(seed_mod, "write_json_file", lambda path, obj: written.append((path, obj)))
    monkeypatch.setattr(sys, "argv", ["seed_ci_kg_search_regression.py"])

    exit_code = seed_mod.main()
    stdout = capsys.readouterr().out.strip()

    assert exit_code == 0
    assert stdout == "[seed_ci_kg_search_regression] OK"
    assert seeded == [fixture]
    assert written == []

    out_path = tmp_path / "cases.json"
    monkeypatch.setattr(sys, "argv", ["seed_ci_kg_search_regression.py", "--out-cases", str(out_path)])
    exit_code = seed_mod.main()

    assert exit_code == 0
    assert written == [(out_path, {"schema": "mimirq.regression_cases.v1", **fixture})]
