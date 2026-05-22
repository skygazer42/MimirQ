from __future__ import annotations


def test_api_retries_backend_rate_limit(monkeypatch) -> None:  # noqa: ANN001
    import json
    import time

    import requests

    from scripts.production_readiness_chain import Api

    calls: list[str] = []
    sleeps: list[float] = []

    def _response(status_code: int, payload: dict) -> requests.Response:
        resp = requests.Response()
        resp.status_code = status_code
        resp._content = json.dumps(payload).encode("utf-8")  # noqa: SLF001
        resp.headers["Content-Type"] = "application/json"
        return resp

    def _fake_request(self, method, url, **kwargs):  # noqa: ANN001, ANN202, ARG001
        calls.append(url)
        if len(calls) == 1:
            return _response(
                429,
                {
                    "error": "RATE_LIMIT_EXCEEDED",
                    "detail": {"retry_after_sec": 0.1},
                },
            )
        return _response(200, {"ok": True})

    monkeypatch.setattr(requests.Session, "request", _fake_request, raising=True)
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(float(seconds)), raising=True)

    data, _elapsed = Api("http://localhost:8000", "tenant", "user", 5.0).json("GET", "/probe")

    assert data == {"ok": True}
    assert len(calls) == 2
    assert sleeps == [0.1]


def test_default_chat_gate_accepts_live_llm_answers_with_citations() -> None:
    from scripts.production_readiness_chain import Evidence, run_default_chat_degradation

    class _FakeApi:
        def json(self, method, path, json):  # noqa: ANN001, ANN202
            assert method == "POST"
            assert path == "/api/v1/chat"
            assert json["rag_config"]["enable_query_decomposition"] is False
            return (
                {
                    "content": "这是一个真实 LLM 生成且带引用的回答。",
                    "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1"}],
                    "metrics": {
                        "generation_fallback_used": False,
                        "retrieval_elapsed_sec": 0.42,
                        "generation_elapsed_sec": 5.0,
                    },
                },
                5420.0,
            )

    evidence = Evidence(
        started_at="2026-01-01T00:00:00Z",
        base_url="http://localhost:8000",
        tenant_id="tenant",
        user_id="user",
        corpus_dir="/tmp/corpus",
        output_dir="/tmp/out",
    )
    evidence.provider_health = {"success": True}

    run_default_chat_degradation(_FakeApi(), "dataset-1", evidence)  # type: ignore[arg-type]

    assert "default_chat_answers_or_degrades_with_citations" not in evidence.failures
    assert "default_chat_degrades_with_citations" not in evidence.failures


def test_llm_probe_timeout_is_configurable(monkeypatch) -> None:  # noqa: ANN001
    from scripts import production_readiness_chain as mod
    from scripts.production_readiness_chain import Evidence

    class _Response:
        status_code = 200
        text = '{"success": true}'

        def json(self):  # noqa: ANN202
            return {"success": True, "message": "ok"}

    class _FakeApi:
        captured: dict | None = None

        def json(self, method, path):  # noqa: ANN001, ANN202
            assert method == "GET"
            assert path == "/api/v1/settings"
            return ({"llm": {"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen"}}, 1.0)

        def request(self, method, path, json):  # noqa: ANN001, ANN202
            assert method == "POST"
            assert path == "/api/v1/settings/llm/test"
            self.captured = json
            return _Response(), 12.0

    monkeypatch.setattr(mod, "load_llm_probe_api_key", lambda _api_base: ("sk-test", "test"), raising=True)
    evidence = Evidence(
        started_at="2026-01-01T00:00:00Z",
        base_url="http://localhost:8000",
        tenant_id="tenant",
        user_id="user",
        corpus_dir="/tmp/corpus",
        output_dir="/tmp/out",
    )
    api = _FakeApi()

    mod.probe_llm_provider(api, evidence, timeout_sec=22.0)  # type: ignore[arg-type]

    assert api.captured is not None
    assert api.captured["timeout"] == 22.0
    assert evidence.provider_health["success"] is True


def test_kg_search_gate_warms_before_measuring_slo() -> None:
    from scripts.production_readiness_chain import Evidence, ensure_kg

    class _FakeApi:
        def __init__(self) -> None:
            self.search_calls = 0
            self.calls_by_query: dict[str, int] = {}

        def json(self, method, path, **kwargs):  # noqa: ANN001, ANN202
            if method == "GET" and path.startswith("/api/v1/kg/stats?"):
                return ({"events": 3, "entities": 5}, 4.0)
            assert method == "POST"
            assert path == "/api/v1/kg/search"
            payload = kwargs.get("json", {})
            assert payload.get("dataset_id") == "dataset-1"
            query = str(payload.get("query") or "")
            self.search_calls += 1
            self.calls_by_query[query] = self.calls_by_query.get(query, 0) + 1
            if query.startswith("Warm up"):
                elapsed = 6500.0 if self.calls_by_query[query] == 1 else 420.0
            elif query == "accessibility conformance":
                elapsed = 5200.0 if self.calls_by_query[query] == 1 else 380.0
            else:
                elapsed = 420.0
            return (
                {
                    "result": {
                        "events": [{"id": "event-1"}],
                        "entities": [{"id": "entity-1"}],
                        "stats": {"timing_sec": {"total": elapsed / 1000.0}},
                    }
                },
                elapsed,
            )

    evidence = Evidence(
        started_at="2026-01-01T00:00:00Z",
        base_url="http://localhost:8000",
        tenant_id="tenant",
        user_id="user",
        corpus_dir="/tmp/corpus",
        output_dir="/tmp/out",
    )

    ensure_kg(_FakeApi(), "dataset-1", [], evidence)  # type: ignore[arg-type]

    assert evidence.kg["warmup"][0]["elapsed_ms"] == 6500.0
    assert evidence.kg["warmup"][-1]["elapsed_ms"] == 420.0
    retry_row = next(row for row in evidence.kg["search"] if row["query"] == "accessibility conformance")
    assert retry_row["elapsed_ms"] == 380.0
    assert [attempt["elapsed_ms"] for attempt in retry_row["attempts"]] == [5200.0, 380.0]
    assert {row["name"]: row["ok"] for row in evidence.checks}["kg_search_warmup_completed"] is True
    assert {row["name"]: row["ok"] for row in evidence.checks}["kg_search_under_3s"] is True
    assert "kg_search_under_3s" not in evidence.failures


def test_chunk_preview_retries_empty_transient_response(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    import time

    from scripts.production_readiness_chain import Evidence, run_chunk_previews

    files = [
        tmp_path / "a.txt",
        tmp_path / "b.txt",
        tmp_path / "c.md",
        tmp_path / "d.csv",
    ]
    for path in files:
        path.write_text("hello world", encoding="utf-8")

    sleeps: list[float] = []

    class _Response:
        status_code = 200
        text = "{}"

        def __init__(self, chunks: list[dict]) -> None:
            self._chunks = chunks

        def json(self):  # noqa: ANN202
            return {"chunks": self._chunks, "metrics": {"count": len(self._chunks)}}

    class _FakeApi:
        def __init__(self) -> None:
            self.calls_by_strategy: dict[str, int] = {}

        def request(self, method, path, **kwargs):  # noqa: ANN001, ANN202
            assert method == "POST"
            assert path == "/api/v1/documents/chunk-preview"
            strategy = kwargs["data"]["chunk_strategy"]
            self.calls_by_strategy[strategy] = self.calls_by_strategy.get(strategy, 0) + 1
            if strategy == "langchain_recursive" and self.calls_by_strategy[strategy] == 1:
                return (_Response([]), 100.0)
            return (_Response([{"text": "chunk"}]), 120.0)

    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(float(seconds)), raising=True)
    evidence = Evidence(
        started_at="2026-01-01T00:00:00Z",
        base_url="http://localhost:8000",
        tenant_id="tenant",
        user_id="user",
        corpus_dir="/tmp/corpus",
        output_dir="/tmp/out",
    )

    api = _FakeApi()
    run_chunk_previews(api, "dataset-1", files, evidence)  # type: ignore[arg-type]

    first = evidence.chunk_previews[0]
    assert first["strategy"] == "langchain_recursive"
    assert first["ok"] is True
    assert first["chunk_count"] == 1
    assert len(first["attempts"]) == 2
    assert sleeps == [0.5]
    assert {row["name"]: row["ok"] for row in evidence.checks}["chunk_preview_strategies_work"] is True


def test_retrieval_retries_slow_provider_jitter(monkeypatch) -> None:  # noqa: ANN001
    import time

    from scripts.production_readiness_chain import Evidence, run_retrieval

    sleeps: list[float] = []

    class _FakeApi:
        def __init__(self) -> None:
            self.calls_by_query: dict[str, int] = {}

        def json(self, method, path, json):  # noqa: ANN001, ANN202
            assert method == "POST"
            assert path == "/api/v1/rag/retrieve-preview"
            query = json["query"]
            self.calls_by_query[query] = self.calls_by_query.get(query, 0) + 1
            if query.startswith("What does RFC 9000") and self.calls_by_query[query] == 1:
                elapsed = 4200.0
            else:
                elapsed = 280.0
            return (
                {
                    "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1"}],
                    "metrics": {"retrieval_elapsed_sec": elapsed / 1000.0},
                },
                elapsed,
            )

    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(float(seconds)), raising=True)
    evidence = Evidence(
        started_at="2026-01-01T00:00:00Z",
        base_url="http://localhost:8000",
        tenant_id="tenant",
        user_id="user",
        corpus_dir="/tmp/corpus",
        output_dir="/tmp/out",
    )

    run_retrieval(_FakeApi(), "dataset-1", evidence)  # type: ignore[arg-type]

    first = evidence.retrieval[0]
    assert first["elapsed_ms"] == 280.0
    assert first["citation_count"] == 1
    assert len(first["attempts"]) == 2
    assert sleeps == [0.25]
    assert {row["name"]: row["ok"] for row in evidence.checks}["rag_retrieval_under_3s"] is True


def test_upload_documents_waits_for_each_document_when_throttled(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    import time

    from scripts.production_readiness_chain import Evidence, upload_documents

    first = tmp_path / "a.md"
    second = tmp_path / "b.md"
    first.write_text("# A", encoding="utf-8")
    second.write_text("# B", encoding="utf-8")
    sleeps: list[float] = []

    class _Response:
        status_code = 201

        def __init__(self, doc_id: str) -> None:
            self._doc_id = doc_id
            self.text = "{}"

        def json(self):  # noqa: ANN202
            return {
                "id": self._doc_id,
                "status": "pending",
                "file_type": "md",
                "file_size": 3,
                "metadata": {},
            }

    class _FakeApi:
        def __init__(self) -> None:
            self.uploaded: list[str] = []
            self.detail_calls: dict[str, int] = {}
            self.forms: list[dict[str, str]] = []

        def request(self, method, path, **kwargs):  # noqa: ANN001, ANN202
            assert method == "POST"
            assert path == "/api/v1/documents/upload"
            filename = kwargs["files"]["file"][0]
            self.uploaded.append(filename)
            self.forms.append(dict(kwargs["data"]))
            doc_id = f"doc-{len(self.uploaded)}"
            return (_Response(doc_id), 10.0)

        def json(self, method, path):  # noqa: ANN001, ANN202
            assert method == "GET"
            doc_id = path.rsplit("/", 1)[-1]
            self.detail_calls[doc_id] = self.detail_calls.get(doc_id, 0) + 1
            if doc_id == "doc-1":
                assert self.uploaded == ["a.md"]
            return ({"id": doc_id, "status": "completed"}, 5.0)

    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(float(seconds)), raising=True)
    evidence = Evidence(
        started_at="2026-01-01T00:00:00Z",
        base_url="http://localhost:8000",
        tenant_id="tenant",
        user_id="user",
        corpus_dir="/tmp/corpus",
        output_dir="/tmp/out",
    )

    api = _FakeApi()
    doc_ids = upload_documents(api, "dataset-1", [first, second], evidence, per_upload_timeout_sec=30.0)  # type: ignore[arg-type]

    assert doc_ids == ["doc-1", "doc-2"]
    assert api.uploaded == ["a.md", "b.md"]
    assert {form["kg_enabled"] for form in api.forms} == {"false"}
    assert {form["event_vector_enabled"] for form in api.forms} == {"false"}
    assert {form["entity_vector_enabled"] for form in api.forms} == {"false"}
    assert api.detail_calls == {"doc-1": 1, "doc-2": 1}
    assert [row["terminal_status"] for row in evidence.uploads] == ["completed", "completed"]
    assert sleeps == []


def test_create_dataset_disables_background_kg_until_explicit_heuristic_extract() -> None:
    from scripts.production_readiness_chain import Evidence, create_dataset

    class _FakeApi:
        payload: dict | None = None

        def json(self, method, path, **kwargs):  # noqa: ANN001, ANN202
            assert method == "POST"
            assert path == "/api/v1/datasets/"
            self.payload = kwargs["json"]
            return ({"id": "dataset-1", "name": self.payload["name"]}, 8.0)

    evidence = Evidence(
        started_at="2026-01-01T00:00:00Z",
        base_url="http://localhost:8000",
        tenant_id="tenant",
        user_id="user",
        corpus_dir="/tmp/corpus",
        output_dir="/tmp/out",
    )

    api = _FakeApi()
    dataset_id = create_dataset(api, evidence)  # type: ignore[arg-type]

    assert dataset_id == "dataset-1"
    assert api.payload is not None
    pipeline = api.payload["pipeline"]
    assert pipeline["kg_enabled"] is False
    assert pipeline["event_vector_enabled"] is False
    assert pipeline["entity_vector_enabled"] is False
