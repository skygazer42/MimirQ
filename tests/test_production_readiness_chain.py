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
