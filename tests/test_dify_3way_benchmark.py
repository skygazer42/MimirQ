import importlib.util
import json
import sys
import zipfile
from pathlib import Path


def _load_module():
    path = Path("scripts/dify_3way_benchmark.py")
    spec = importlib.util.spec_from_file_location("dify_3way_benchmark", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _case(case_id: str, question: str = "示例卡补办在哪里办？") -> dict:
    return {
        "id": case_id,
        "question": question,
        "query": question,
        "dify_inputs": {"areaName": "A区"},
        "source_record_title": "示例卡补办",
        "dimension_fields": ["办理地点", "咨询方式", "收费情况"],
        "subquestions": [
            {"id": "办理地点", "required_clause_ids": ["location"]},
            {"id": "咨询方式", "required_clause_ids": ["phone"]},
        ],
        "evidence_clauses": [
            {"id": "location", "required_terms": ["A区服务中心"]},
            {"id": "phone", "required_terms": ["0519-88516920"]},
        ],
    }


def test_build_benchmark_cases_expands_native_rubrics_to_target_count() -> None:
    mod = _load_module()

    cases = mod.build_benchmark_cases(mixed_cases=[_case("mixed-1")], golden_cases=[_case("golden-1")], target_count=12, seed=7)

    assert len(cases) == 12
    assert len({item["id"] for item in cases}) == 12
    assert {item["benchmark_generation"] for item in cases} == {"dify_3way_800_v1"}
    assert {item["source_case_id"] for item in cases} == {"mixed-1", "golden-1"}
    assert {item["case_type"] for item in cases} >= {"mixed", "qa", "simulated_user"}
    assert all(item["evidence_clauses"] for item in cases)
    assert all(item["dify_inputs"]["areaName"] == "A区" for item in cases)

    summary = mod.summarize_cases(cases)
    assert summary["cases"] == 12
    assert summary["unique_source_cases"] == 2
    assert summary["by_case_type"]["mixed"] >= 1

    truth = mod.build_truth_manifest(cases[:1])
    assert truth[0]["case_id"] == cases[0]["id"]
    assert truth[0]["source_case_id"] in {"mixed-1", "golden-1"}
    assert truth[0]["evidence_clause_ids"] == ["location", "phone"]
    assert truth[0]["subquestion_ids"] == ["办理地点", "咨询方式"]


def test_select_cases_to_run_can_sample_evenly_by_case_type() -> None:
    mod = _load_module()
    cases = []
    for index, case_type in enumerate(["qa", "qa", "mixed", "mixed", "simulated_user", "simulated_user"], 1):
        case = _case(f"case-{index}")
        case["case_type"] = case_type
        cases.append(case)

    selected = mod.select_cases_to_run(cases, limit=1, sample_per_type=1)

    assert len(selected) == 3
    assert {case["case_type"] for case in selected} == {"mixed", "qa", "simulated_user"}


def test_load_prebuilt_cases_accepts_object_with_cases_array(tmp_path: Path) -> None:
    mod = _load_module()
    path = tmp_path / "prebuilt.json"
    path.write_text(
        json.dumps({"schema": "demo", "cases": [_case("case-1"), _case("case-2")]}, ensure_ascii=False),
        encoding="utf-8",
    )

    cases = mod.load_prebuilt_cases(str(path))

    assert [case["id"] for case in cases] == ["case-1", "case-2"]


def test_resolve_expected_case_count_uses_prebuilt_case_total() -> None:
    mod = _load_module()
    cases = [_case("case-1"), _case("case-2"), _case("case-3")]

    expected = mod.resolve_expected_case_count(
        prebuilt_cases="artifacts/custom_cases.json",
        target_count=800,
        cases=cases,
    )

    assert expected == 3


def test_run_mimirq_direct_retries_timeout_cases(monkeypatch) -> None:
    mod = _load_module()
    attempts = {"case-1": 0}

    def _fake_call_mimirq_case(*, case, base_url, token, timeout, retrieval_overrides=None):
        attempts[case["id"]] += 1
        if attempts[case["id"]] == 1:
            return {
                "id": case["id"],
                "case_id": case["id"],
                "query": case["question"],
                "system": "mimirq_direct",
                "records": [],
                "answer": "",
                "ok": False,
                "error": "timed out",
            }
        return {
            "id": case["id"],
            "case_id": case["id"],
            "query": case["question"],
            "system": "mimirq_direct",
            "records": [{"title": "ok"}],
            "answer": "ok",
            "ok": True,
        }

    monkeypatch.setattr(mod, "_call_mimirq_case", _fake_call_mimirq_case)

    run = mod.run_mimirq_direct(
        cases=[_case("case-1")],
        base_url="http://127.0.0.1:8000",
        token="token",
        timeout=10,
        concurrency=1,
    )

    assert attempts["case-1"] == 2
    assert run["summary"]["succeeded"] == 1
    assert run["summary"]["failed"] == 0


def test_load_app_specs_reads_key_file_without_emitting_secrets(tmp_path: Path) -> None:
    mod = _load_module()
    key_file = tmp_path / "keys.json"
    key_file.write_text(
        json.dumps(
            {
                "dify_native_kb": {"api_key": "native-secret"},
                "00000000-0000-0000-0000-000000000002": {"api_key": "http-secret", "mode": "workflow"},
            }
        ),
        encoding="utf-8",
    )

    specs = mod.load_app_specs([], str(key_file))
    by_label = {item.label: item for item in specs}

    assert by_label["dify_native_kb"].api_key == "native-secret"
    assert by_label["dify_http_mimirq"].api_key == "http-secret"
    assert by_label["dify_http_mimirq"].mode == "workflow"
    assert by_label["dify_native_kb"].app_id == "00000000-0000-0000-0000-000000000001"


def test_key_requirements_describes_missing_dify_app_keys_without_secrets() -> None:
    mod = _load_module()
    apps = mod.load_app_specs([], "")

    requirements = mod.build_key_requirements(apps)

    assert requirements["schema"] == "mimirq.dify_3way_benchmark.key_requirements.v1"
    assert requirements["summary"]["apps"] == 2
    assert requirements["summary"]["missing_api_keys"] == 2
    assert {item["label"] for item in requirements["apps"]} == {
        "dify_http_mimirq",
        "dify_native_kb",
    }
    assert requirements["template"]["dify_http_mimirq"]["api_key"] == "app-xxx"
    assert requirements["template"]["dify_http_mimirq"]["mode"] == "auto"
    assert "00000000-0000-0000-0000-000000000002" in requirements["apps"][0]["accepted_keys"]
    assert "native-secret" not in json.dumps(requirements, ensure_ascii=False)


def test_response_records_are_normalized_from_dify_retriever_resources() -> None:
    mod = _load_module()

    records = mod._extract_records_from_response(
        {
            "metadata": {
                "retriever_resources": [
                    {
                        "document_name": "A区示例清单",
                        "content": "事项名称：示例卡补办 办理地点：A区服务中心",
                        "score": 0.91,
                    }
                ]
            }
        }
    )

    assert records == [
        {
            "title": "A区示例清单",
            "content": "事项名称：示例卡补办 办理地点：A区服务中心",
            "metadata": {},
            "score": 0.91,
        }
    ]


def test_response_records_are_extracted_from_http_workflow_mimirq_outputs() -> None:
    mod = _load_module()

    records = mod._extract_records_from_response(
        {
            "data": {
                "outputs": {
                    "answer": "可在A区服务中心办理。",
                    "mimirq_records": [
                        {
                            "document_name": "A区示例清单.txt",
                            "chunk_content": "事项名称：示例卡补办\n办理地点：A区服务中心",
                            "score": 0.93,
                            "metadata": {"chunk_id": "chunk-1"},
                        }
                    ],
                }
            }
        }
    )

    assert records == [
        {
            "title": "A区示例清单.txt",
            "content": "事项名称：示例卡补办\n办理地点：A区服务中心",
            "metadata": {"chunk_id": "chunk-1"},
            "score": 0.93,
        }
    ]


def test_response_records_are_extracted_from_json_string_http_outputs() -> None:
    mod = _load_module()

    records = mod._extract_records_from_response(
        {
            "data": {
                "outputs": {
                    "mimirq_citations_json": json.dumps(
                        [
                            {
                                "filename": "园区FAQ.txt",
                                "content": "问题：在哪里办理企业社会保险登记？\n答案：园区服务中心。",
                                "metadata": {"source_record_id": "qa-1"},
                            }
                        ],
                        ensure_ascii=False,
                    )
                }
            }
        }
    )

    assert records[0]["title"] == "园区FAQ.txt"
    assert "企业社会保险登记" in records[0]["content"]
    assert records[0]["metadata"]["source_record_id"] == "qa-1"


def test_streaming_sse_payloads_are_folded_into_dify_response() -> None:
    mod = _load_module()

    response = mod._stream_payload_to_response(
        mod._iter_dify_sse_payloads(
            [
                'data: {"event":"message","id":"msg-1","conversation_id":"conv-1","task_id":"task-1","answer":"办理地点："}\n',
                'data: {"event":"message","id":"msg-1","conversation_id":"conv-1","task_id":"task-1","answer":"A区服务中心"}\n',
                (
                    "data: "
                    + json.dumps(
                        {
                            "event": "message_end",
                            "id": "msg-1",
                            "metadata": {
                                "retriever_resources": [
                                    {
                                        "document_name": "A区示例清单",
                                        "content": "办理地点：A区服务中心",
                                    }
                                ]
                            },
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                ),
            ]
        )
    )

    assert response["answer"] == "办理地点：A区服务中心"
    assert response["conversation_id"] == "conv-1"
    assert response["message_id"] == "msg-1"
    assert response["task_id"] == "task-1"
    assert mod._extract_records_from_response(response)[0]["title"] == "A区示例清单"


def test_call_case_can_request_streaming_response_mode() -> None:
    mod = _load_module()
    app = mod.AppSpec(
        label="dify_http_mimirq",
        app_id="00000000-0000-0000-0000-000000000002",
        kind="http_to_mimirq",
        description="HTTP 接入 MimirQ",
        api_key="secret",
        mode="chat",
    )
    seen_payloads = []

    def fake_request_json(**kwargs):
        seen_payloads.append(kwargs["payload"])
        return {"answer": "可在A区服务中心办理。", "message_id": "msg-1"}

    item = mod._call_case(
        app=app,
        case=_case("case-stream"),
        base_url="https://example.test/v1",
        timeout=3,
        workflow_query_key="query",
        user_prefix="test",
        response_mode="streaming",
        request_json_fn=fake_request_json,
    )

    assert item["ok"] is True
    assert seen_payloads[0]["response_mode"] == "streaming"


def test_http_mimirq_call_backfills_records_from_mimirq_history_when_response_has_no_records() -> None:
    mod = _load_module()
    app = mod.AppSpec(
        label="dify_http_mimirq",
        app_id="00000000-0000-0000-0000-000000000002",
        kind="http_to_mimirq",
        description="HTTP 接入 MimirQ",
        api_key="secret",
        mode="chat",
    )

    def fake_request_json(**_kwargs):
        return {
            "answer": "可在A区服务中心办理。",
            "conversation_id": "dify-conversation-1",
            "message_id": "dify-message-1",
            "task_id": "workflow-run-1",
        }

    def fake_history_lookup(*, app, item, **_kwargs):
        assert app.label == "dify_http_mimirq"
        assert item["conversation_id"] == "dify-conversation-1"
        assert item["task_id"] == "workflow-run-1"
        return {
            "records": [
                {
                    "document_name": "A区示例清单",
                    "chunk_content": "事项名称：示例卡补办 办理地点：A区服务中心",
                    "relevance_score": 0.91,
                    "metadata": {"chunk_id": "chunk-1"},
                }
            ],
            "source": "mimirq_history",
        }

    item = mod._call_case(
        app=app,
        case=_case("case-1"),
        base_url="https://example.test/v1",
        timeout=3,
        workflow_query_key="query",
        user_prefix="test",
        request_json_fn=fake_request_json,
        history_records_fn=fake_history_lookup,
    )

    assert item["ok"] is True
    assert item["record_source"] == "mimirq_history"
    assert item["records"][0]["title"] == "A区示例清单"
    assert "A区服务中心" in item["records"][0]["content"]


def test_console_node_executions_extract_merged_mimirq_records() -> None:
    mod = _load_module()

    records = mod.extract_mimirq_records_from_console_node_executions(
        {
            "data": [
                {
                    "node_id": "1745223008372",
                    "title": "合并知识库知识",
                    "node_type": "code",
                    "outputs": {
                        "records_json": json.dumps(
                            [
                                {
                                    "title": "金坛区事项清单",
                                    "content": "办理地点：示例市金园区清风路1号市民中心C座三楼3-E06窗口",
                                    "metadata": {"chunk_id": "chunk-1"},
                                    "score": 0.94,
                                }
                            ],
                            ensure_ascii=False,
                        )
                    },
                }
            ]
        }
    )

    assert records == [
        {
            "title": "金坛区事项清单",
            "content": "办理地点：示例市金园区清风路1号市民中心C座三楼3-E06窗口",
            "metadata": {"chunk_id": "chunk-1"},
            "score": 0.94,
        }
    ]


def test_http_mimirq_call_falls_back_to_console_records_when_history_unavailable() -> None:
    mod = _load_module()
    app = mod.AppSpec(
        label="dify_http_mimirq",
        app_id="00000000-0000-0000-0000-000000000002",
        kind="http_to_mimirq",
        description="HTTP 接入 MimirQ",
        api_key="secret",
        mode="chat",
    )

    def fake_request_json(**_kwargs):
        return {
            "answer": "支持窗口办理、网上办理和快递申请。",
            "conversation_id": "dify-conversation-2",
            "message_id": "dify-message-2",
            "task_id": "task-id-not-workflow-run-id",
        }

    def fake_history_lookup(**_kwargs):
        return {"records": [], "source": "mimirq_history", "status": "error", "error": "db down"}

    def fake_console_lookup(*, item, **_kwargs):
        assert item["message_id"] == "dify-message-2"
        return {
            "records": [
                {
                    "title": "示例市事项清单",
                    "content": "办理形式：窗口办理,网上办理,快递申请",
                    "score": 0.98,
                }
            ],
            "source": "dify_console_node_executions",
            "status": "found",
            "workflow_run_id": "real-workflow-run-id",
        }

    item = mod._call_case(
        app=app,
        case=_case("case-2"),
        base_url="https://example.test/v1",
        timeout=3,
        workflow_query_key="query",
        user_prefix="test",
        request_json_fn=fake_request_json,
        history_records_fn=fake_history_lookup,
        console_records_fn=fake_console_lookup,
    )

    assert item["record_source"] == "dify_console_node_executions"
    assert item["console_record_backfill_status"] == "found"
    assert item["record_backfill_error"] == "db down"
    assert item["workflow_run_id"] == "real-workflow-run-id"
    assert item["records"][0]["content"] == "办理形式：窗口办理,网上办理,快递申请"


def test_resolve_app_modes_selects_workflow_when_chat_probe_fails() -> None:
    mod = _load_module()
    app = mod.AppSpec(
        label="dify_http_mimirq",
        app_id="00000000-0000-0000-0000-000000000002",
        kind="http_to_mimirq",
        description="HTTP 接入 MimirQ",
        api_key="secret",
        mode="auto",
    )
    attempts: list[str] = []

    def fake_probe(*, app, **_kwargs):
        probe_app = app
        attempts.append(probe_app.mode)
        return {"ok": probe_app.mode == "workflow", "error": "" if probe_app.mode == "workflow" else "HTTP 404"}

    resolved, report = mod.resolve_app_modes(
        apps=[app],
        probe_case=_case("case-1"),
        base_url="https://dify.example.com:5001/v1",
        timeout=1,
        workflow_query_key="query",
        user_prefix="test",
        force=False,
        probe_fn=fake_probe,
    )

    assert resolved[0].mode == "workflow"
    assert attempts == ["chat", "workflow"]
    assert report["items"][0]["selected_mode"] == "workflow"
    assert report["items"][0]["selected_endpoint"].endswith("/workflows/run")


def test_mimirq_direct_run_is_skipped_without_token() -> None:
    mod = _load_module()

    run = mod.run_mimirq_direct(cases=[_case("case-1")], base_url="http://127.0.0.1:8000", token="", timeout=1, concurrency=1)

    assert run["system"] == "mimirq_direct"
    assert run["summary"]["cases"] == 1
    assert run["summary"]["succeeded"] == 0
    assert run["summary"]["failed"] == 1
    assert run["summary"]["skipped"] is True
    assert run["summary"]["reason"] == "missing_mimirq_token"
    assert run["summary"]["resumed"] == 0
    assert run["items"] == []


def test_missing_dify_key_reuses_complete_existing_run_items() -> None:
    mod = _load_module()
    cases = [_case("case-a"), _case("case-b")]
    app = mod.AppSpec(
        label="dify_native_kb",
        app_id="00000000-0000-0000-0000-000000000001",
        kind="native_dify_knowledge",
        description="原生 Dify 知识库",
        api_key="",
    )

    run = mod.run_app(
        app=app,
        cases=cases,
        base_url="https://dify.example.com:5001/v1",
        timeout=1,
        concurrency=1,
        workflow_query_key="query",
        user_prefix="test",
        existing_items=[
            {"case_id": "case-a", "ok": True, "answer": "cached answer a"},
            {"case_id": "case-b", "ok": True, "answer": "cached answer b"},
        ],
    )

    assert run["summary"]["reused_without_key"] is True
    assert "skipped" not in run["summary"]
    assert run["summary"]["resumed"] == 2
    assert run["summary"]["executed"] == 0
    assert [item["case_id"] for item in run["items"]] == ["case-a", "case-b"]


def test_pending_cases_reuses_existing_items_and_can_retry_failures() -> None:
    mod = _load_module()
    cases = [_case("case-a"), _case("case-b"), _case("case-c")]
    existing = [
        {"case_id": "case-a", "ok": True, "answer": "cached success"},
        {"case_id": "case-b", "ok": False, "error": "timed out"},
        {"case_id": "outside-case", "ok": True},
    ]

    pending, reusable = mod._pending_cases(cases, existing, retry_failures=False)

    assert [item["id"] for item in pending] == ["case-c"]
    assert [item["case_id"] for item in reusable] == ["case-a", "case-b"]

    pending, reusable = mod._pending_cases(cases, existing, retry_failures=True)

    assert [item["id"] for item in pending] == ["case-b", "case-c"]
    assert [item["case_id"] for item in reusable] == ["case-a"]


def test_call_case_records_structured_dify_timeout_diagnostics(monkeypatch) -> None:
    mod = _load_module()
    app = mod.AppSpec(
        label="dify_http_mimirq",
        app_id="00000000-0000-0000-0000-000000000002",
        kind="http_to_mimirq",
        description="HTTP 接入 MimirQ",
        api_key="secret",
    )

    def fake_request_json(**_kwargs):
        raise RuntimeError('HTTP 400: {"code":"invalid_param","message":"Run failed: timed out","status":400}')

    monkeypatch.setattr(mod, "_request_json", fake_request_json)

    item = mod._call_case(
        app=app,
        case=_case("case-timeout"),
        base_url="https://dify.example.com:5001/v1",
        timeout=1,
        workflow_query_key="query",
        user_prefix="test",
    )

    assert item["ok"] is False
    assert item["dify_error_code"] == "invalid_param"
    assert item["dify_error_message"] == "Run failed: timed out"
    assert item["error_kind"] == "transient_dify_workflow_error"


def test_run_app_can_flush_partial_checkpoint(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    app = mod.AppSpec(
        label="dify_native_kb",
        app_id="00000000-0000-0000-0000-000000000001",
        kind="native_dify_knowledge",
        description="原生 Dify 知识库",
        api_key="secret",
    )
    cases = [_case("case-a"), _case("case-b")]
    run_path = tmp_path / "run_dify_native_kb.json"

    def fake_call_case(*, case, app, **_kwargs):
        return {
            "id": case["id"],
            "case_id": case["id"],
            "system": app.label,
            "app_id": app.app_id,
            "query": case["query"],
            "records": [],
            "answer": f"answer {case['id']}",
            "ok": True,
            "latency_ms": 1.0,
        }

    monkeypatch.setattr(mod, "_call_case", fake_call_case)

    run = mod.run_app(
        app=app,
        cases=cases,
        base_url="https://dify.example.com:5001/v1",
        timeout=1,
        concurrency=1,
        workflow_query_key="query",
        user_prefix="test",
        run_path=run_path,
        flush_every=1,
    )

    flushed = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["summary"]["succeeded"] == 2
    assert flushed["summary"]["cases"] == 2
    assert flushed["summary"]["succeeded"] == 2
    assert flushed["summary"]["partial"] is False
    assert [item["case_id"] for item in flushed["items"]] == ["case-a", "case-b"]


def test_load_existing_run_items_and_sort_key_support_resume_artifacts(tmp_path: Path) -> None:
    mod = _load_module()
    run_path = tmp_path / "run_dify_native_kb.json"
    run_path.write_text(
        json.dumps(
            {
                "items": [
                    {"case_id": "case-b", "ok": True},
                    "invalid",
                    {"id": "case-a", "ok": True},
                ]
            }
        ),
        encoding="utf-8",
    )

    items = mod._load_existing_run_items(run_path)
    items.sort(key=mod._run_item_sort_key)

    assert [item.get("case_id") or item.get("id") for item in items] == ["case-a", "case-b"]


def test_report_only_loads_existing_runs_without_synthesizing_missing_runs(tmp_path: Path) -> None:
    mod = _load_module()
    apps = mod.load_app_specs([], "")
    (tmp_path / "run_dify_native_kb.json").write_text(
        json.dumps({"system": "dify_native_kb", "items": [{"case_id": "case-a", "ok": True}]}),
        encoding="utf-8",
    )

    runs = mod.load_report_only_runs(out_dir=tmp_path, apps=apps, include_mimirq_direct=False)

    assert [run["system"] for run in runs] == ["dify_native_kb"]
    assert runs[0]["items"][0]["case_id"] == "case-a"


def test_artifact_manifest_records_hashes_for_existing_outputs(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "cases_800.json").write_text('{"cases":[]}\n', encoding="utf-8")
    (tmp_path / "comparison_report.json").write_text('{"ok":true}\n', encoding="utf-8")

    manifest = mod.build_artifact_manifest(
        out_dir=tmp_path,
        report={"completion_status": {"complete_3way_800": False}},
        apps=mod.load_app_specs([], ""),
        include_mimirq_direct=False,
    )

    by_name = {Path(item["path"]).name: item for item in manifest["files"]}
    assert manifest["schema"] == "mimirq.dify_3way_benchmark.artifact_manifest.v1"
    assert manifest["complete_3way_800"] is False
    assert by_name["cases_800.json"]["bytes"] > 0
    assert len(by_name["cases_800.json"]["sha256"]) == 64


def test_write_artifact_bundle_packages_manifest_files_without_secrets(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "comparison_report.md").write_text("# report\n", encoding="utf-8")
    (tmp_path / "audit_review.csv").write_text("case_id,system\n", encoding="utf-8")
    (tmp_path / "run_dify_native_kb.json").write_text('{"api_key":"<redacted>","items":[]}\n', encoding="utf-8")
    (tmp_path / "artifact_manifest.json").write_text('{"files":[]}\n', encoding="utf-8")
    manifest = {
        "files": [
            {"path": str(tmp_path / "comparison_report.md")},
            {"path": str(tmp_path / "audit_review.csv")},
            {"path": str(tmp_path / "run_dify_native_kb.json")},
        ]
    }

    bundle = mod.write_artifact_bundle(out_dir=tmp_path, manifest=manifest)

    assert bundle.name == "dify_3way_benchmark_bundle.zip"
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert names == {
            "artifact_manifest.json",
            "comparison_report.md",
            "audit_review.csv",
            "run_dify_native_kb.json",
        }
        assert "native-secret" not in archive.read("run_dify_native_kb.json").decode("utf-8")


def test_write_artifact_bundle_accepts_manifest_paths_relative_to_cwd(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.chdir(tmp_path)
    out_dir = Path("artifacts/dify_3way_benchmark")
    out_dir.mkdir(parents=True)
    (out_dir / "artifact_manifest.json").write_text('{"files":[]}\n', encoding="utf-8")
    (out_dir / "comparison_report.md").write_text("# report\n", encoding="utf-8")
    manifest = {"files": [{"path": "artifacts/dify_3way_benchmark/comparison_report.md"}]}

    bundle = mod.write_artifact_bundle(out_dir=out_dir, manifest=manifest)

    with zipfile.ZipFile(bundle) as archive:
        assert set(archive.namelist()) == {"artifact_manifest.json", "comparison_report.md"}


def test_preflight_reports_missing_keys_without_running_full_benchmark() -> None:
    mod = _load_module()
    apps = mod.load_app_specs([], "")

    report = mod.run_preflight(
        apps=apps,
        cases=[_case("case-1")],
        base_url="https://dify.example.com:5001/v1",
        timeout=1,
        workflow_query_key="query",
        user_prefix="test",
    )

    assert report["schema"] == "mimirq.dify_3way_benchmark.preflight.v1"
    assert report["summary"]["apps"] == 2
    assert report["summary"]["ok"] == 0
    assert report["summary"]["missing_api_key"] == 2
    assert report["summary"]["all_ready"] is False
    assert {item["status"] for item in report["items"]} == {"missing_api_key"}
    assert all(item["key_present"] is False for item in report["items"])


def test_safe_error_redacts_known_secrets() -> None:
    mod = _load_module()

    assert mod._safe_error("failed with app-secret-token", secrets=["app-secret-token"]) == "failed with <redacted>"


def test_case_type_advantage_and_markdown_surface_business_summary() -> None:
    mod = _load_module()
    case_a = _case("case-a")
    case_a["case_type"] = "qa"
    case_b = _case("case-b")
    case_b["case_type"] = "simulated_user"
    report = {
        "generated_at": "2026-07-04T00:00:00Z",
        "summary": {"cases": 2, "skipped_systems": ["dify_native_kb"]},
        "case_type_advantage": [
            {
                "case_type": "qa",
                "system": "dify_http_mimirq",
                "cases": 1,
                "business_score": 1.0,
                "answer_clause_coverage": 1.0,
                "answer_subquestion_coverage": 1.0,
                "wrong_evidence_rate": 0.0,
            },
            {
                "case_type": "simulated_user",
                "system": "dify_http_mimirq",
                "cases": 1,
                "business_score": 0.6,
                "answer_clause_coverage": 0.5,
                "answer_subquestion_coverage": 0.5,
                "wrong_evidence_rate": 0.2,
            },
        ],
        "dimension_advantage": [
            {
                "dimension": "办理地点",
                "system": "dify_http_mimirq",
                "cases": 2,
                "business_score": 0.9,
                "answer_clause_coverage": 1.0,
                "answer_subquestion_coverage": 0.9,
                "wrong_evidence_rate": 0.0,
            }
        ],
        "audit_verdict_summary": [
            {
                "system": "dify_http_mimirq",
                "cases": 2,
                "accurate": 1,
                "partially_accurate": 1,
                "insufficient_evidence": 0,
                "no_answer": 0,
                "accurate_rate": 0.5,
                "usable_rate": 1.0,
            }
        ],
        "top_issue_cases": [
            {
                "system": "dify_http_mimirq",
                "verdict": "部分准确",
                "business_score": 0.42,
                "case_type": "qa",
                "source_record_title": "示例卡补办",
                "query": "社保卡补卡在哪里办？",
                "missing_evidence_clause_ids": ["phone"],
            }
        ],
        "leaderboard": [
            {
                "system": "dify_http_mimirq",
                "cases": 2,
                "retrieval_pass_rate": 1.0,
                "mean_evidence_coverage": 0.9,
                "mean_subquestion_coverage": 0.9,
                "mean_answer_clause_coverage": 0.8,
                "mean_answer_subquestion_coverage": 0.8,
                "mean_answer_supported_clause_rate": 1.0,
                "mean_wrong_evidence_rate": 0.1,
                "unsupported_answered_clause_cases": 0,
                "forbidden_hit_cases": 0,
                "mean_latency_ms": 1200,
            }
        ],
        "items": [
            {
                "system": "dify_http_mimirq",
                "case_id": "case-a",
                "answer_clause_coverage": 1.0,
                "answer_subquestion_coverage": 1.0,
                "evidence_coverage": 1.0,
                "answer_supported_clause_rate": 1.0,
                "wrong_evidence_rate": 0.0,
            },
            {
                "system": "dify_native_kb",
                "case_id": "case-a",
                "answer_clause_coverage": 0.0,
                "answer_subquestion_coverage": 0.0,
                "evidence_coverage": 0.0,
                "answer_supported_clause_rate": 0.0,
                "wrong_evidence_rate": 1.0,
            },
            {
                "system": "dify_http_mimirq",
                "case_id": "case-b",
                "answer_clause_coverage": 0.5,
                "answer_subquestion_coverage": 0.5,
                "evidence_coverage": 0.5,
                "answer_supported_clause_rate": 1.0,
                "wrong_evidence_rate": 0.2,
            },
        ],
        "systems": [],
        "pairwise": [],
    }

    rows = mod.build_case_type_advantage(report, [case_a, case_b])
    qa_rows = [row for row in rows if row["case_type"] == "qa"]

    assert {row["system"] for row in qa_rows} == {"dify_http_mimirq", "dify_native_kb"}
    assert max(qa_rows, key=lambda row: row["business_score"])["system"] == "dify_http_mimirq"

    dimension_rows = mod.build_dimension_advantage(report, [case_a, case_b])
    location_rows = [row for row in dimension_rows if row["dimension"] == "办理地点"]

    assert {row["system"] for row in location_rows} == {"dify_http_mimirq", "dify_native_kb"}
    assert max(location_rows, key=lambda row: row["business_score"])["system"] == "dify_http_mimirq"

    summary = mod.build_advantage_summary(report)

    assert summary["overall_best_system"] == "dify_http_mimirq"
    assert summary["systems"]["dify_http_mimirq"]["case_type_wins"] == 2
    assert summary["systems"]["dify_http_mimirq"]["dimension_wins"] == 1

    markdown = mod.build_comparison_markdown(report, apps=mod.load_app_specs([], ""), cases=[case_a, case_b])

    assert "## 中文结论摘要" in markdown
    assert "## 优势汇总" in markdown
    assert "## 审计判定分布" in markdown
    assert "## 按问题类型看优势" in markdown
    assert "## 按业务维度看优势" in markdown
    assert "## Top 问题样本" in markdown
    assert "dify_native_kb" in markdown
    assert "业务综合分" in markdown

    sharing = mod.build_sharing_markdown(report)

    assert "评测摘要" in sharing
    assert "## 优势汇总" in sharing
    assert "## 准确率结构" in sharing
    assert "## 业务维度优势" in sharing
    assert "## 优先排查样本" in sharing
    assert "comparison_report.json" in sharing


def test_verdict_summary_counts_accuracy_distribution() -> None:
    mod = _load_module()

    summary = mod.build_verdict_summary(
        [
            {"system": "dify_http_mimirq", "verdict": "准确"},
            {"system": "dify_http_mimirq", "verdict": "部分准确"},
            {"system": "dify_http_mimirq", "verdict": "证据不足"},
            {"system": "dify_native_kb", "verdict": "无答案"},
        ]
    )
    by_system = {row["system"]: row for row in summary}

    assert by_system["dify_http_mimirq"]["cases"] == 3
    assert by_system["dify_http_mimirq"]["accurate"] == 1
    assert by_system["dify_http_mimirq"]["partially_accurate"] == 1
    assert by_system["dify_http_mimirq"]["usable_rate"] == 0.666667
    assert by_system["dify_native_kb"]["no_answer"] == 1


def test_top_issue_cases_prioritize_bad_verdicts_and_low_scores() -> None:
    mod = _load_module()

    rows = [
        {
            "system": "dify_http_mimirq",
            "case_id": "case-good",
            "verdict": "准确",
            "business_score": 1.0,
            "wrong_evidence_rate": 0.0,
            "missing_evidence_clause_ids": [],
            "missing_subquestion_ids": [],
            "query": "好样本",
        },
        {
            "system": "dify_http_mimirq",
            "case_id": "case-partial",
            "verdict": "部分准确",
            "business_score": 0.7,
            "wrong_evidence_rate": 0.1,
            "missing_evidence_clause_ids": ["phone"],
            "missing_subquestion_ids": [],
            "query": "部分准确样本",
        },
        {
            "system": "dify_http_mimirq",
            "case_id": "case-empty",
            "verdict": "无答案",
            "business_score": 0.0,
            "wrong_evidence_rate": 1.0,
            "missing_evidence_clause_ids": ["location", "phone"],
            "missing_subquestion_ids": ["办理地点"],
            "query": "无答案样本",
        },
    ]

    issues = mod.build_top_issue_cases(rows, per_system=2)

    assert [item["case_id"] for item in issues] == ["case-empty", "case-partial"]


def test_completion_status_requires_all_configured_apps_and_full_800_cases() -> None:
    mod = _load_module()
    apps = mod.load_app_specs([], "")
    complete_runs = [
        {
            "system": app.label,
            "summary": {"cases": 800, "succeeded": 800, "failed": 0},
            "items": [{"case_id": f"case-{index}"} for index in range(800)],
        }
        for app in apps
    ]

    complete = mod.build_completion_status(
        runs=complete_runs,
        apps=apps,
        requested_cases=800,
        executed_cases=800,
    )

    assert complete["complete_3way_800"] is True
    assert complete["all_systems_executed"] is True
    assert complete["skipped_systems"] == []

    incomplete = mod.build_completion_status(
        runs=complete_runs[:1]
        + [
            {
                "system": apps[1].label,
                "summary": {"cases": 800, "succeeded": 0, "failed": 800, "skipped": True},
                "items": [],
            }
        ],
        apps=apps,
        requested_cases=800,
        executed_cases=800,
    )

    assert incomplete["complete_3way_800"] is False
    assert incomplete["skipped_systems"] == [apps[1].label]
    assert apps[1].label in incomplete["incomplete_systems"]


def test_audit_rows_join_scores_with_source_truth_and_answer_preview() -> None:
    mod = _load_module()
    case = _case("case-1")
    case["case_type"] = "qa"
    case["source_file"] = "01示例服务事项/A区.json"
    case["source_section"] = "01示例服务事项"
    report = {
        "items": [
            {
                "system": "dify_http_mimirq",
                "case_id": "case-1",
                "answer_clause_coverage": 1.0,
                "answer_subquestion_coverage": 1.0,
                "evidence_coverage": 1.0,
                "answer_supported_clause_rate": 1.0,
                "wrong_evidence_rate": 0.0,
                "missing_evidence_clause_ids": [],
                "missing_subquestion_ids": [],
            }
        ]
    }
    runs = [
        {
            "system": "dify_http_mimirq",
            "items": [
                {
                    "case_id": "case-1",
                    "answer": "请到A区服务中心办理，咨询电话 0519-88516920。",
                    "records": [
                        {
                            "title": "示例卡补办",
                            "content": "办理地点：A区服务中心；咨询电话：0519-88516920",
                        }
                    ],
                }
            ],
        }
    ]

    rows = mod.build_audit_rows(report, [case], runs)

    assert len(rows) == 1
    assert rows[0]["verdict"] == "准确"
    assert rows[0]["business_score"] == 1.0
    assert rows[0]["required_evidence_terms"] == [
        {"id": "location", "required_terms": ["A区服务中心"]},
        {"id": "phone", "required_terms": ["0519-88516920"]},
    ]
    assert rows[0]["expected_answer_basis"] == "location：A区服务中心；phone：0519-88516920"
    assert rows[0]["score_reason"] == "准确：回答覆盖全部必答证据，检索证据可支撑答案，未发现明显错证据。"
    assert "示例卡补办" in rows[0]["native_evidence_preview"]
    assert "办理地点：A区服务中心" in rows[0]["native_evidence_preview"]
    assert "A区服务中心" in rows[0]["answer_preview"]
    assert "示例卡补办" in rows[0]["top_record_preview"]
