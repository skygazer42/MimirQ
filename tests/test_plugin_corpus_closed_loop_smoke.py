from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "plugin_corpus_closed_loop_smoke.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("plugin_corpus_closed_loop_smoke", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_script_stays_python_310_compatible() -> None:
    text = _script_path().read_text(encoding="utf-8")

    assert "from datetime import UTC" not in text
    assert "timezone.utc" in text


def test_corpus_smoke_requires_explicit_plugin_ref_without_business_default(tmp_path: Path) -> None:
    mod = _load_module()
    parser = mod.build_arg_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--source-dir", str(tmp_path)])


def test_corpus_smoke_script_has_no_business_plugin_default() -> None:
    text = _script_path().read_text(encoding="utf-8")

    assert "changzhou-gov-service-knowledge" not in text
    assert "20260522政务服务智能客服知识" not in text
    assert "max_record_chars" not in text


def test_discovers_supported_corpus_files_and_reports_empty_skips(tmp_path: Path) -> None:
    mod = _load_module()
    (tmp_path / "01").mkdir()
    txt = tmp_path / "01" / "record.txt"
    docx = tmp_path / "guide.docx"
    empty = tmp_path / "空.txt"
    ignored = tmp_path / "image.png"
    txt.write_text("record content", encoding="utf-8")
    docx.write_bytes(b"docx")
    empty.write_bytes(b"")
    ignored.write_bytes(b"png")

    files, skipped = mod.discover_corpus_files(tmp_path, extensions={".txt", ".docx"}, skip_empty=True)

    assert [item.rel_path for item in files] == ["01/record.txt", "guide.docx"]
    assert skipped == [{"path": "空.txt", "reason": "empty_file", "size": 0}]


def test_discovery_skips_hidden_paths_by_default(tmp_path: Path) -> None:
    mod = _load_module()
    visible = tmp_path / "record.txt"
    hidden_dir_file = tmp_path / ".pandoc" / "converted.docx"
    hidden_file = tmp_path / ".scratch.txt"
    hidden_dir_file.parent.mkdir()
    visible.write_text("record content", encoding="utf-8")
    hidden_dir_file.write_bytes(b"docx")
    hidden_file.write_text("scratch", encoding="utf-8")

    files, skipped = mod.discover_corpus_files(tmp_path, extensions={".txt", ".docx"}, skip_empty=True)

    assert skipped == []
    assert [item.rel_path for item in files] == ["record.txt"]


def test_discovery_can_include_hidden_paths_when_explicit(tmp_path: Path) -> None:
    mod = _load_module()
    visible = tmp_path / "record.txt"
    hidden_dir_file = tmp_path / ".pandoc" / "converted.docx"
    hidden_file = tmp_path / ".scratch.txt"
    hidden_dir_file.parent.mkdir()
    visible.write_text("record content", encoding="utf-8")
    hidden_dir_file.write_bytes(b"docx")
    hidden_file.write_text("scratch", encoding="utf-8")

    files, skipped = mod.discover_corpus_files(
        tmp_path,
        extensions={".txt", ".docx"},
        skip_empty=True,
        include_hidden=True,
    )

    assert skipped == []
    assert [item.rel_path for item in files] == [".pandoc/converted.docx", ".scratch.txt", "record.txt"]


def test_discovery_does_not_treat_numbered_roots_as_special_by_default(tmp_path: Path) -> None:
    mod = _load_module()
    root = tmp_path / "04topic-faq"
    root.mkdir()
    file = root / "admissions.txt"
    file.write_text("Question: How to apply?\nAnswer: Follow the notice.", encoding="utf-8")

    files, skipped = mod.discover_corpus_files(root, extensions={".txt"}, skip_empty=True)

    assert skipped == []
    assert [item.rel_path for item in files] == ["admissions.txt"]


def test_discovery_can_include_source_root_name_when_explicit(tmp_path: Path) -> None:
    mod = _load_module()
    root = tmp_path / "04topic-faq"
    root.mkdir()
    file = root / "admissions.txt"
    file.write_text("Question: How to apply?\nAnswer: Follow the notice.", encoding="utf-8")

    files, skipped = mod.discover_corpus_files(
        root,
        extensions={".txt"},
        skip_empty=True,
        include_root_name=True,
    )

    assert skipped == []
    assert [item.rel_path for item in files] == ["04topic-faq/admissions.txt"]


def test_discovery_can_sample_each_corpus_group_with_source_root_prefix(tmp_path: Path) -> None:
    mod = _load_module()
    root = tmp_path / "domain-corpus"
    for section in ("01", "02", "06"):
        section_dir = root / section
        section_dir.mkdir(parents=True)
        for index in range(3):
            (section_dir / f"record-{index}.txt").write_text(f"{section} record {index}", encoding="utf-8")

    files, skipped = mod.discover_corpus_files(
        root,
        extensions={".txt"},
        skip_empty=True,
        include_root_name=True,
        max_files_per_group=1,
    )

    assert [item.rel_path for item in files] == [
        "domain-corpus/01/record-0.txt",
        "domain-corpus/02/record-0.txt",
        "domain-corpus/06/record-0.txt",
    ]
    assert {item["reason"] for item in skipped} == {"group_sample_limit"}


def test_discovery_can_sample_nested_corpus_groups(tmp_path: Path) -> None:
    mod = _load_module()
    root = tmp_path / "domain-corpus"
    for group in ("05/real-estate", "05/fund", "06/district"):
        group_dir = root / group
        group_dir.mkdir(parents=True)
        for index in range(2):
            (group_dir / f"record-{index}.txt").write_text(f"{group} record {index}", encoding="utf-8")

    files, skipped = mod.discover_corpus_files(
        root,
        extensions={".txt"},
        skip_empty=True,
        max_files_per_group=1,
        sample_group_depth=2,
    )

    assert [item.rel_path for item in files] == [
        "05/fund/record-0.txt",
        "05/real-estate/record-0.txt",
        "06/district/record-0.txt",
    ]
    assert {item["group"] for item in skipped} == {"05/fund", "05/real-estate", "06/district"}


def test_upload_form_carries_registered_plugin_pipeline(tmp_path: Path) -> None:
    mod = _load_module()
    src = tmp_path / "01" / "record.txt"
    src.parent.mkdir()
    src.write_text("record content", encoding="utf-8")
    item = mod.CorpusFile(path=src, rel_path="01/record.txt", size=src.stat().st_size)

    form = mod.build_upload_form(
        item,
        dataset_id="00000000-0000-0000-0000-000000000001",
        chunk_plugin_ref="plugin:demo-runtime-plugin@1.0.0:chunk",
        governance_plugin_ref="plugin:demo-runtime-plugin@1.0.0:governance",
        kg_plugin_ref="plugin:demo-runtime-plugin@1.0.0:kg",
        pipeline_patch={"chunk_python_params": {"demo_param": 1600}, "chunk_size": 1600},
    )

    pipeline = json.loads(form["pipeline"])
    metadata = json.loads(form["user_metadata"])
    assert pipeline["governance_python_plugin"] == "plugin:demo-runtime-plugin@1.0.0:governance"
    assert pipeline["chunk_python_plugin"] == "plugin:demo-runtime-plugin@1.0.0:chunk"
    assert pipeline["kg_python_plugin"] == "plugin:demo-runtime-plugin@1.0.0:kg"
    assert pipeline["chunk_python_params"] == {"demo_param": 1600}
    assert pipeline["chunk_size"] == 1600
    assert pipeline["chunk_vector_enabled"] is True
    assert pipeline["bm25_index_enabled"] is True
    assert pipeline["kg_enabled"] is True
    assert pipeline["event_vector_enabled"] is True
    assert pipeline["entity_vector_enabled"] is True
    assert metadata["source_rel_path"] == "01/record.txt"
    assert metadata["plugin_ref"] == "plugin:demo-runtime-plugin@1.0.0:chunk"


def test_upload_form_does_not_derive_governance_ref_from_chunk_ref(tmp_path: Path) -> None:
    mod = _load_module()
    src = tmp_path / "record.txt"
    src.write_text("record content", encoding="utf-8")
    item = mod.CorpusFile(path=src, rel_path="record.txt", size=src.stat().st_size)

    form = mod.build_upload_form(
        item,
        dataset_id="00000000-0000-0000-0000-000000000001",
        chunk_plugin_ref="plugin:chunk-only-plugin@1.0.0:chunk",
        pipeline_patch={"chunk_python_params": {"demo_param": 1600}},
    )

    pipeline = json.loads(form["pipeline"])
    assert pipeline["chunk_python_plugin"] == "plugin:chunk-only-plugin@1.0.0:chunk"
    assert "governance_python_plugin" not in pipeline


def test_upload_form_rejects_pipeline_patch_activation_refs(tmp_path: Path) -> None:
    mod = _load_module()
    src = tmp_path / "record.txt"
    src.write_text("record content", encoding="utf-8")
    item = mod.CorpusFile(path=src, rel_path="record.txt", size=src.stat().st_size)

    with pytest.raises(RuntimeError, match="pipeline patch must not set plugin activation refs"):
        mod.build_upload_form(
            item,
            dataset_id="00000000-0000-0000-0000-000000000001",
            chunk_plugin_ref="plugin:demo-runtime-plugin@1.0.0:chunk",
            governance_plugin_ref="plugin:demo-runtime-plugin@1.0.0:governance",
            pipeline_patch={
                "governance_python_plugin": "plugin:other-plugin@1.0.0:governance",
                "chunk_python_params": {"demo_param": 1600},
            },
        )


def test_corpus_smoke_rejects_non_chunk_plugin_ref() -> None:
    mod = _load_module()

    with pytest.raises(RuntimeError, match="chunk plugin ref must target the chunk stage"):
        mod.build_plugin_pipeline(chunk_plugin_ref="plugin:demo-runtime-plugin@1.0.0:governance")

    with pytest.raises(RuntimeError, match="registered chunk plugin ref is required"):
        mod.build_plugin_pipeline(chunk_plugin_ref="plugin:chunk")


def test_corpus_smoke_rejects_cross_stage_manifest_refs() -> None:
    mod = _load_module()

    with pytest.raises(RuntimeError, match="governance plugin ref must target the governance stage"):
        mod.build_plugin_pipeline(
            chunk_plugin_ref="plugin:demo-runtime-plugin@1.0.0:chunk",
            governance_plugin_ref="plugin:demo-runtime-plugin@1.0.0:kg",
        )

    with pytest.raises(RuntimeError, match="kg plugin ref must target the kg stage"):
        mod.build_plugin_pipeline(
            chunk_plugin_ref="plugin:demo-runtime-plugin@1.0.0:chunk",
            kg_plugin_ref="plugin:demo-runtime-plugin@1.0.0:governance",
        )


def test_resolves_pipeline_patch_from_plugin_manifest_when_json_is_omitted() -> None:
    mod = _load_module()

    class PluginClient:
        calls: list[tuple[str, str]] = []

        def json(self, method: str, path: str, *, payload=None, query=None):  # noqa: ANN001
            self.calls.append((method, path))
            assert payload is None
            assert query is None
            return {
                "items": [
                    {
                        "refs": {
                            "governance": "plugin:demo-runtime-plugin@1.0.0:governance",
                            "chunk": "plugin:demo-runtime-plugin@1.0.0:chunk",
                        },
                        "suggested_pipeline_patch": {
                            "chunk_python_params": {"demo_param": 1600},
                        },
                    }
                ]
            }

    client = PluginClient()

    patch = mod.resolve_pipeline_patch_for_run(
        client,
        chunk_plugin_ref="plugin:demo-runtime-plugin@1.0.0:chunk",
        pipeline_patch_json="",
    )

    assert patch == {"chunk_python_params": {"demo_param": 1600}}
    assert client.calls == [("GET", "/api/v1/pipeline/plugins")]


def test_resolves_pipeline_config_from_plugin_manifest_including_stage_refs_when_json_is_omitted() -> None:
    mod = _load_module()

    class PluginClient:
        calls: list[tuple[str, str]] = []

        def json(self, method: str, path: str, *, payload=None, query=None):  # noqa: ANN001
            self.calls.append((method, path))
            assert payload is None
            assert query is None
            return {
                "items": [
                    {
                        "refs": {
                            "governance": "plugin:demo-runtime-plugin@1.0.0:governance",
                            "chunk": "plugin:demo-runtime-plugin@1.0.0:chunk",
                            "kg": "plugin:demo-runtime-plugin@1.0.0:kg",
                        },
                        "suggested_pipeline_patch": {
                            "chunk_python_params": {"demo_param": 1600},
                        },
                    }
                ]
            }

    client = PluginClient()

    config = mod.resolve_plugin_pipeline_for_run(
        client,
        chunk_plugin_ref="plugin:demo-runtime-plugin@1.0.0:chunk",
        pipeline_patch_json="",
    )

    assert config == {
        "pipeline_patch": {"chunk_python_params": {"demo_param": 1600}},
        "governance_plugin_ref": "plugin:demo-runtime-plugin@1.0.0:governance",
        "kg_plugin_ref": "plugin:demo-runtime-plugin@1.0.0:kg",
    }
    assert client.calls == [("GET", "/api/v1/pipeline/plugins")]


def test_explicit_pipeline_patch_json_still_uses_manifest_stage_refs() -> None:
    mod = _load_module()

    class PluginClient:
        calls: list[tuple[str, str]] = []

        def json(self, method: str, path: str, *, payload=None, query=None):  # noqa: ANN001
            self.calls.append((method, path))
            assert payload is None
            assert query is None
            return {
                "items": [
                    {
                        "refs": {
                            "governance": "plugin:demo-runtime-plugin@1.0.0:governance",
                            "chunk": "plugin:demo-runtime-plugin@1.0.0:chunk",
                        },
                        "suggested_pipeline_patch": {
                            "chunk_python_params": {"ignored": 1},
                        },
                    }
                ]
            }

    client = PluginClient()

    config = mod.resolve_plugin_pipeline_for_run(
        client,
        chunk_plugin_ref="plugin:demo-runtime-plugin@1.0.0:chunk",
        pipeline_patch_json='{"chunk_python_params":{"demo_param":2400}}',
    )

    assert config == {
        "pipeline_patch": {"chunk_python_params": {"demo_param": 2400}},
        "governance_plugin_ref": "plugin:demo-runtime-plugin@1.0.0:governance",
        "kg_plugin_ref": "",
    }
    assert client.calls == [("GET", "/api/v1/pipeline/plugins")]


def test_explicit_pipeline_patch_json_rejects_activation_refs() -> None:
    mod = _load_module()

    with pytest.raises(RuntimeError, match="--pipeline-patch-json must not set plugin activation refs"):
        mod.parse_pipeline_patch_json(
            '{"governance_python_plugin":"plugin:other-plugin@1.0.0:governance","chunk_python_params":{"demo_param":2400}}'
        )


def test_corpus_smoke_uploads_and_waits_in_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(mod, "create_dataset", lambda *_args, **_kwargs: "dataset-1", raising=True)

    def fake_upload(_client, files, **_kwargs):  # noqa: ANN001, ANN003
        rel_paths = [item.rel_path for item in files]
        calls.append(("upload", rel_paths))
        return [
            mod.UploadedDocument(
                document_id=f"doc-{item.rel_path}",
                file=item,
                upload_status="pending",
            )
            for item in files
        ]

    def fake_wait(_client, uploaded, **_kwargs):  # noqa: ANN001, ANN003
        rel_paths = [item.file.rel_path for item in uploaded]
        calls.append(("wait", rel_paths))
        return [{"document_id": item.document_id, "source_rel_path": item.file.rel_path} for item in uploaded]

    def fake_closed_loop(**kwargs):  # noqa: ANN003
        assert kwargs["regression_top_k"] == 5
        return mod.ClosedLoopResult(
            dataset_id="dataset-1",
            plugin_ref="plugin:demo-runtime-plugin@1.0.0:chunk",
            run_id="run-1",
            case_ids=[],
            summary={},
            import_result={},
            plugin_source={},
        )

    monkeypatch.setattr(mod, "upload_corpus_files", fake_upload, raising=True)
    monkeypatch.setattr(mod, "wait_for_uploaded_documents", fake_wait, raising=True)
    monkeypatch.setattr(mod, "run_closed_loop_smoke", fake_closed_loop, raising=True)

    result = mod.run_corpus_closed_loop_smoke(
        client=object(),
        source_dir=tmp_path,
        dataset_id="",
        dataset_name="Dataset",
        chunk_plugin_ref="plugin:demo-runtime-plugin@1.0.0:chunk",
        pipeline_patch={},
        governance_plugin_ref="",
        kg_plugin_ref="",
        extensions=".txt",
        skip_empty=True,
        max_files=0,
        max_files_per_group=0,
        sample_group_depth=1,
        include_root_name=False,
        include_hidden=False,
        upload_batch_size=2,
        processing_timeout_sec=1,
        poll_interval_sec=0,
        golden_max_items=1,
        golden_max_chunks=10,
        regression_top_k=5,
        overwrite_goldens=False,
    )

    assert calls == [
        ("upload", ["a.txt", "b.txt"]),
        ("wait", ["a.txt", "b.txt"]),
        ("upload", ["c.txt"]),
        ("wait", ["c.txt"]),
    ]
    assert result.uploaded_count == 3
    assert [item["source_rel_path"] for item in result.documents] == ["a.txt", "b.txt", "c.txt"]


def test_corpus_api_client_retries_rate_limited_json(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()
    calls = 0
    sleeps: list[float] = []

    def fake_json(self, method, path, *, payload=None, query=None):  # noqa: ANN001
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError('HTTP 429: {"detail": {"retry_after_sec": 1}}')
        return {"ok": True}

    monkeypatch.setattr(mod.LiveApiClient, "json", fake_json, raising=True)
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: sleeps.append(float(seconds)), raising=True)

    client = mod.CorpusApiClient(base_url="http://127.0.0.1:8000")

    assert client.json("GET", "/api/v1/health") == {"ok": True}
    assert calls == 2
    assert sleeps == [1.0]


def test_corpus_api_client_retries_transient_get_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()
    calls = 0
    sleeps: list[float] = []

    def fake_json(self, method, path, *, payload=None, query=None):  # noqa: ANN001
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("timed out")
        return {"ok": True}

    monkeypatch.setattr(mod.LiveApiClient, "json", fake_json, raising=True)
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: sleeps.append(float(seconds)), raising=True)

    client = mod.CorpusApiClient(base_url="http://127.0.0.1:8000")

    assert client.json("GET", "/api/v1/documents/doc-1") == {"ok": True}
    assert calls == 2
    assert sleeps == [1.0]


def test_upload_file_wraps_request_errors_with_source_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()
    src = tmp_path / "05" / "large.docx"
    src.parent.mkdir()
    src.write_bytes(b"docx")
    item = mod.CorpusFile(path=src, rel_path="05/large.docx", size=src.stat().st_size)

    def fail_post(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise mod.requests.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr(mod.requests, "post", fail_post, raising=True)
    client = mod.CorpusApiClient(base_url="http://127.0.0.1:8000", timeout_sec=1)

    with pytest.raises(RuntimeError, match="05/large\\.docx"):
        client.upload_file("/api/v1/documents/upload", data={"dataset_id": "dataset-1"}, file=item)


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def json(self, method: str, path: str, *, payload: dict | None = None, query: dict | None = None) -> dict:
        self.calls.append((method, path, query or payload))
        if method == "GET" and path == "/api/v1/documents/doc-1":
            return {"id": "doc-1", "status": "completed", "filename": "record.txt"}
        if method == "GET" and path == "/api/v1/documents/doc-1/chunks":
            return {"total": 0, "items": []}
        raise AssertionError(f"unexpected call: {method} {path}")


def test_wait_for_uploaded_documents_rejects_non_empty_completed_docs_without_chunks(tmp_path: Path) -> None:
    mod = _load_module()
    src = tmp_path / "record.txt"
    src.write_text("record content", encoding="utf-8")
    uploaded = mod.UploadedDocument(
        document_id="doc-1",
        file=mod.CorpusFile(path=src, rel_path="record.txt", size=src.stat().st_size),
        upload_status="pending",
    )

    with pytest.raises(RuntimeError, match="completed without chunks"):
        mod.wait_for_uploaded_documents(
            _FakeClient(),
            [uploaded],
            timeout_sec=1,
            poll_interval_sec=0,
        )
