import json
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

import scripts.production_readiness_chain as prc


def make_args(tmp_path: Path, **overrides: object) -> Namespace:
    values: dict[str, object] = {
        "base_url": "http://127.0.0.1:8000/",
        "tenant_id": prc.TENANT_ID,
        "user_id": prc.USER_ID,
        "timeout": 12.5,
        "processing_timeout": 34.5,
        "per_upload_timeout": None,
        "llm_probe_timeout": 7.5,
        "corpus_dir": str(tmp_path / "corpus"),
        "output_dir": str(tmp_path / "output"),
    }
    values.update(overrides)
    return Namespace(**values)


def test_parse_args_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["production_readiness_chain.py"],
    )

    args = prc.parse_args()

    assert args.base_url == "http://127.0.0.1:8000"
    assert args.tenant_id == prc.TENANT_ID
    assert args.user_id == prc.USER_ID
    assert args.timeout == 180.0
    assert args.processing_timeout == 1800.0
    assert args.per_upload_timeout is None
    assert args.llm_probe_timeout == 15.0
    assert args.corpus_dir == ""
    assert args.output_dir == ""


def test_parse_args_explicit_values(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "production_readiness_chain.py",
            "--base-url",
            "http://example.test/",
            "--tenant-id",
            "tenant-x",
            "--user-id",
            "user-y",
            "--timeout",
            "1.5",
            "--processing-timeout",
            "2.5",
            "--per-upload-timeout",
            "0",
            "--llm-probe-timeout",
            "3.5",
            "--corpus-dir",
            "corpus-path",
            "--output-dir",
            "output-path",
        ],
    )

    args = prc.parse_args()

    assert args.base_url == "http://example.test/"
    assert args.tenant_id == "tenant-x"
    assert args.user_id == "user-y"
    assert args.timeout == 1.5
    assert args.processing_timeout == 2.5
    assert args.per_upload_timeout == 0.0
    assert args.llm_probe_timeout == 3.5
    assert args.corpus_dir == "corpus-path"
    assert args.output_dir == "output-path"


def test_evidence_check_aggregates_failure_reasons() -> None:
    evidence = prc.Evidence(
        started_at="2026-08-16T00:00:00+00:00",
        base_url="http://example.test",
        tenant_id="tenant",
        user_id="user",
        corpus_dir="/tmp/corpus",
        output_dir="/tmp/output",
    )

    evidence.check("ok_check", True, count=1)
    evidence.check("bad_with_reason", False, reason="broken")
    evidence.check("bad_without_reason", False)

    assert evidence.checks == [
        {"name": "ok_check", "ok": True, "count": 1},
        {"name": "bad_with_reason", "ok": False, "reason": "broken"},
        {"name": "bad_without_reason", "ok": False},
    ]
    assert evidence.failures == [
        "bad_with_reason: broken",
        "bad_without_reason",
    ]


def test_ensure_kg_preserves_extract_search_and_retry_order(monkeypatch) -> None:
    calls: list[tuple[str, str, object]] = []
    sleeps: list[float] = []
    stats_responses = iter(
        [
            ({"events": 0, "entities": 0}, 5.0),
            ({"events": 2, "entities": 3}, 6.0),
        ]
    )
    search_responses = iter(
        [
            ({"events": [], "entities": []}, 3501.0),
            ({"events": ["warm"], "entities": []}, 100.0),
            ({"events": ["quic"], "entities": []}, 200.0),
            ({"events": [], "entities": []}, 4000.0),
            ({"events": [], "entities": ["fastapi"]}, 250.0),
            ({"events": ["a11y"], "entities": ["wcag"]}, 300.0),
        ]
    )

    class FakeApi:
        def json(self, method: str, path: str, expected=None, **kwargs):
            calls.append((method, path, expected))
            if method == "GET":
                return next(stats_responses)
            if "/documents/doc-1/extract?" in path:
                return {"events_created": 1}, 12.34
            if "/documents/doc-2/extract?" in path:
                raise RuntimeError("extract failed")
            raw, elapsed_ms = next(search_responses)
            return {"result": {**raw, "stats": {"source": "stub"}}}, elapsed_ms

    evidence = prc.Evidence(
        started_at="2026-08-16T00:00:00+00:00",
        base_url="http://example.test",
        tenant_id="tenant",
        user_id="user",
        corpus_dir="/tmp/corpus",
        output_dir="/tmp/output",
    )
    monkeypatch.setattr(prc.time, "sleep", sleeps.append)

    prc.ensure_kg(FakeApi(), "dataset-1", ["doc-1", "doc-2"], evidence)

    extract_query = "replace_existing=true&extract_relations=false&extract_skills=false&extraction_backend=heuristic"
    assert calls == [
        ("GET", "/api/v1/kg/stats?dataset_id=dataset-1", None),
        ("POST", f"/api/v1/kg/documents/doc-1/extract?{extract_query}", {200}),
        ("POST", f"/api/v1/kg/documents/doc-2/extract?{extract_query}", {200}),
        ("GET", "/api/v1/kg/stats?dataset_id=dataset-1", None),
        ("POST", "/api/v1/kg/search", None),
        ("POST", "/api/v1/kg/search", None),
        ("POST", "/api/v1/kg/search", None),
        ("POST", "/api/v1/kg/search", None),
        ("POST", "/api/v1/kg/search", None),
        ("POST", "/api/v1/kg/search", None),
    ]
    assert sleeps == [0.25]
    assert evidence.kg["stats"] == {"events": 2, "entities": 3}
    assert evidence.kg["manual_extracts"] == [
        {"document_id": "doc-1", "elapsed_ms": 12.34, "events_created": 1},
        {"document_id": "doc-2", "error": "extract failed"},
    ]
    assert [len(row["attempts"]) for row in evidence.kg["search"]] == [1, 2, 1]
    assert [row["query"] for row in evidence.kg["search"]] == [
        "QUIC transport handshake",
        "FastAPI HTTP client",
        "accessibility conformance",
    ]
    assert [check["name"] for check in evidence.checks] == [
        "kg_has_entities_and_events",
        "kg_search_warmup_completed",
        "kg_search_under_3s",
        "kg_search_returns_results",
    ]
    assert all(check["ok"] for check in evidence.checks)


def test_write_report_writes_expected_schema(tmp_path: Path) -> None:
    output_dir = tmp_path / "evidence"
    evidence = prc.Evidence(
        started_at="2026-08-16T00:00:00+00:00",
        base_url="http://example.test",
        tenant_id="tenant",
        user_id="user",
        corpus_dir="/tmp/corpus",
        output_dir=str(output_dir),
    )
    evidence.dataset = {"id": "dataset-1", "name": "Dataset"}
    evidence.documents = [
        {
            "filename": "alpha.txt",
            "file_type": "txt",
            "status": "completed",
            "chunk_total": 2,
            "parsed_markdown_chars": 40,
        }
    ]
    evidence.retrieval = [{"query": "q1", "elapsed_ms": 12.3, "citation_count": 2}]
    evidence.retrieval_warmups = [{"attempt": 1, "elapsed_ms": 11.1, "citation_count": 1}]
    evidence.kg = {
        "warmup": [{"attempt": 1, "elapsed_ms": 10.0, "events": 1, "entities": 2}],
        "search": [{"query": "kg", "elapsed_ms": 9.0, "events": 3, "entities": 4}],
    }
    evidence.provider_health = {
        "checked": True,
        "success": False,
        "model": "gpt-test",
        "elapsed_ms": 8.0,
        "reason": "missing_key",
    }
    evidence.chat = [
        {
            "question": "chat-q",
            "elapsed_ms": 7.0,
            "content_chars": 120,
            "citation_count": 3,
        }
    ]
    evidence.default_chat = [
        {
            "question": "default-q",
            "elapsed_ms": 6.0,
            "content_chars": 140,
            "citation_count": 4,
            "fallback_reason": "provider_unavailable",
        }
    ]
    evidence.check("report_ok", True, detail="kept")
    evidence.failures.append("manual failure")

    prc.write_report(evidence)

    report_json = output_dir / "report.json"
    report_md = output_dir / "report.md"
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    markdown = report_md.read_text(encoding="utf-8")

    assert set(payload) == set(evidence.__dict__)
    assert payload["checks"] == [{"name": "report_ok", "ok": True, "detail": "kept"}]
    assert payload["failures"] == ["manual failure"]
    assert "## Gate Summary" in markdown
    assert "## Documents" in markdown
    assert "## Retrieval Warmup" in markdown
    assert "## KG Search Latency" in markdown
    assert "## Default Chat" in markdown
    assert "## Failures" in markdown


def test_main_runs_steps_in_order_and_uses_processing_timeout_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    order: list[str] = []
    captured: dict[str, object] = {}
    args = make_args(tmp_path, base_url="http://example.test/")

    class FixedDatetime:
        @staticmethod
        def now(_tz: timezone) -> datetime:
            return datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    class DummyApi:
        def __init__(self, base_url: str, tenant_id: str, user_id: str, timeout: float) -> None:
            order.append("Api")
            captured["api_init"] = (base_url, tenant_id, user_id, timeout)

    def record(name: str):
        def inner(*_args, **_kwargs):
            order.append(name)
            if name == "download_corpus":
                return [tmp_path / "download-1.txt", tmp_path / "download-2.txt"]
            if name == "generate_office_files":
                return [tmp_path / "generated-1.docx"]
            if name == "create_dataset":
                return "dataset-123"
            if name == "upload_documents":
                captured["upload"] = {
                    "dataset_id": _args[1],
                    "files": [str(path) for path in _args[2]],
                    "per_upload_timeout_sec": _kwargs["per_upload_timeout_sec"],
                }
                return ["doc-1", "doc-2"]
            if name == "write_report":
                captured["report_failures"] = list(_args[0].failures)
            return None

        return inner

    monkeypatch.setattr(prc, "parse_args", lambda: args)
    monkeypatch.setattr(prc, "now_id", lambda: "run-001")
    monkeypatch.setattr(prc, "datetime", FixedDatetime)
    monkeypatch.setattr(prc, "Api", DummyApi)
    monkeypatch.setattr(prc, "download_corpus", record("download_corpus"))
    monkeypatch.setattr(prc, "generate_office_files", record("generate_office_files"))
    monkeypatch.setattr(prc, "ensure_runtime_settings", record("ensure_runtime_settings"))
    monkeypatch.setattr(prc, "probe_llm_provider", record("probe_llm_provider"))
    monkeypatch.setattr(prc, "create_dataset", record("create_dataset"))
    monkeypatch.setattr(prc, "upload_documents", record("upload_documents"))
    monkeypatch.setattr(prc, "wait_for_documents", record("wait_for_documents"))
    monkeypatch.setattr(prc, "run_chunk_previews", record("run_chunk_previews"))
    monkeypatch.setattr(prc, "ensure_kg", record("ensure_kg"))
    monkeypatch.setattr(prc, "warm_retrieval_path", record("warm_retrieval_path"))
    monkeypatch.setattr(prc, "run_retrieval", record("run_retrieval"))
    monkeypatch.setattr(prc, "run_chat", record("run_chat"))
    monkeypatch.setattr(prc, "run_default_chat_degradation", record("run_default_chat_degradation"))
    monkeypatch.setattr(prc, "summarize_generation_readiness", record("summarize_generation_readiness"))
    monkeypatch.setattr(prc, "summarize_formats", record("summarize_formats"))
    monkeypatch.setattr(prc, "summarize_runtime_quality", record("summarize_runtime_quality"))
    monkeypatch.setattr(prc, "write_report", record("write_report"))

    exit_code = prc.main()

    assert exit_code == 0
    assert order == [
        "download_corpus",
        "generate_office_files",
        "Api",
        "ensure_runtime_settings",
        "probe_llm_provider",
        "create_dataset",
        "upload_documents",
        "wait_for_documents",
        "run_chunk_previews",
        "ensure_kg",
        "warm_retrieval_path",
        "run_retrieval",
        "run_chat",
        "run_default_chat_degradation",
        "summarize_generation_readiness",
        "summarize_formats",
        "summarize_runtime_quality",
        "write_report",
    ]
    assert captured["api_init"] == (
        "http://example.test/",
        prc.TENANT_ID,
        prc.USER_ID,
        12.5,
    )
    assert captured["upload"] == {
        "dataset_id": "dataset-123",
        "files": [
            str(tmp_path / "download-1.txt"),
            str(tmp_path / "download-2.txt"),
            str(tmp_path / "generated-1.docx"),
        ],
        "per_upload_timeout_sec": 34.5,
    }
    assert captured["report_failures"] == []


def test_main_records_exception_and_returns_nonzero(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    args = make_args(tmp_path)
    captured: dict[str, object] = {}

    class FixedDatetime:
        @staticmethod
        def now(_tz: timezone) -> datetime:
            return datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)

    def write_report(evidence: prc.Evidence) -> None:
        captured["failures"] = list(evidence.failures)

    monkeypatch.setattr(prc, "parse_args", lambda: args)
    monkeypatch.setattr(prc, "now_id", lambda: "run-001")
    monkeypatch.setattr(prc, "datetime", FixedDatetime)
    monkeypatch.setattr(prc, "download_corpus", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(prc, "write_report", write_report)

    exit_code = prc.main()

    stderr = capsys.readouterr().err
    assert exit_code == 1
    assert "ERROR: boom" in stderr
    assert captured["failures"] == ["boom"]
