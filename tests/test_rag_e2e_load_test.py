import asyncio
import json

import httpx

from scripts.rag_e2e_load_test import E2ELoadTestConfig, evaluate_concurrency_gate, run_e2e_load_test


def _load_report(*, concurrency: int, retrieve_rps: float, chat_rps: float, overlap: bool) -> dict:
    return {
        "ingest": {"requested": 0, "completed": 0, "errors": 0},
        "retrieve": {
            "requested": 6,
            "ok": 6,
            "errors": 0,
            "concurrency": concurrency,
            "client_overlap_observed": overlap,
            "throughput_rps": retrieve_rps,
            "latency_ms": {"p95_ms": 1000},
        },
        "chat": {
            "requested": 3,
            "ok": 3,
            "errors": 0,
            "concurrency": concurrency,
            "client_overlap_observed": overlap,
            "throughput_rps": chat_rps,
            "latency_ms": {"p95_ms": 2000},
        },
    }


def test_concurrency_gate_requires_real_throughput_gain() -> None:
    gate = evaluate_concurrency_gate(
        _load_report(concurrency=1, retrieve_rps=0.5, chat_rps=0.25, overlap=False),
        _load_report(concurrency=3, retrieve_rps=0.8, chat_rps=0.4, overlap=True),
        min_retrieve_throughput_ratio=1.1,
        min_chat_throughput_ratio=1.1,
    )

    assert gate["passed"] is True
    assert gate["observed"]["retrieve"]["throughput_ratio"] == 1.6
    assert gate["observed"]["chat"]["throughput_ratio"] == 1.6


def test_concurrency_gate_rejects_client_only_concurrency() -> None:
    gate = evaluate_concurrency_gate(
        _load_report(concurrency=1, retrieve_rps=0.5, chat_rps=0.25, overlap=False),
        _load_report(concurrency=3, retrieve_rps=0.4, chat_rps=0.2, overlap=False),
    )

    assert gate["passed"] is False
    assert "retrieve candidate did not overlap requests" in gate["failures"]
    assert "retrieve throughput_ratio 0.8 < min 1.0" in gate["failures"]
    assert "chat throughput_ratio 0.8 < min 1.0" in gate["failures"]


def test_load_test_exercises_reranker_and_records_concurrency() -> None:
    payloads: dict[str, dict] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        payloads[request.url.path] = json.loads(request.content)
        return httpx.Response(200, json={})

    async def run() -> dict:
        config = E2ELoadTestConfig(
            base_url="http://mimirq.test/api/v1",
            tenant_id="tenant",
            user_id="user",
            bearer="",
            file_bytes=b"",
            filename="test.txt",
            dataset_id="dataset",
            ingest_count=0,
            retrieve_requests=1,
            retrieve_concurrency=2,
            retrieval_mode="keyword",
            chat_requests=1,
            chat_concurrency=3,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_e2e_load_test(config, client=client)

    result = asyncio.run(run())

    assert payloads["/api/v1/rag/retrieve-preview"]["rag_config"]["enable_reranker"] is True
    assert payloads["/api/v1/rag/retrieve-preview"]["rag_config"]["retrieval_mode"] == "keyword"
    assert payloads["/api/v1/chat"]["rag_config"]["enable_reranker"] is True
    assert result["retrieve"]["concurrency"] == 2
    assert result["chat"]["concurrency"] == 3


def test_load_test_varies_requests_and_observes_in_flight_peak() -> None:
    prompts: dict[str, list[str]] = {"retrieve": [], "chat": []}
    request_ids: dict[str, list[str]] = {"retrieve": [], "chat": []}
    active = {"retrieve": 0, "chat": 0}
    peaks = {"retrieve": 0, "chat": 0}
    releases: dict[str, asyncio.Event] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        phase = "retrieve" if request.url.path.endswith("/rag/retrieve-preview") else "chat"
        payload = json.loads(request.content)
        prompts[phase].append(payload["query" if phase == "retrieve" else "message"])
        request_ids[phase].append(request.headers.get("X-Request-ID", ""))
        active[phase] += 1
        peaks[phase] = max(peaks[phase], active[phase])
        if peaks[phase] == 3:
            releases[phase].set()
        try:
            await asyncio.wait_for(releases[phase].wait(), timeout=1)
            return httpx.Response(200, json={})
        finally:
            active[phase] -= 1

    async def run() -> dict:
        releases.update(retrieve=asyncio.Event(), chat=asyncio.Event())
        config = E2ELoadTestConfig(
            base_url="http://mimirq.test/api/v1",
            tenant_id="tenant",
            user_id="user",
            bearer="",
            file_bytes=b"",
            filename="test.txt",
            dataset_id="dataset",
            ingest_count=0,
            retrieve_requests=4,
            retrieve_concurrency=3,
            query="find policy",
            chat_requests=4,
            chat_concurrency=3,
            message="summarize policy",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_e2e_load_test(config, client=client)

    result = asyncio.run(run())

    assert all(prompt.startswith("find policy") for prompt in prompts["retrieve"])
    assert all(prompt.startswith("summarize policy") for prompt in prompts["chat"])
    assert len(set(prompts["retrieve"])) == 4
    assert len(set(prompts["chat"])) == 4
    assert all(len(prompt) <= len("find policy") + 24 for prompt in prompts["retrieve"])
    assert all(len(prompt) <= len("summarize policy") + 24 for prompt in prompts["chat"])
    assert len(set(request_ids["retrieve"])) == 4
    assert len(set(request_ids["chat"])) == 4
    assert all(request_ids["retrieve"])
    assert all(request_ids["chat"])
    assert peaks == {"retrieve": 3, "chat": 3}
    assert result["retrieve"]["client_peak_in_flight"] == 3
    assert result["retrieve"]["client_overlap_observed"] is True
    assert result["chat"]["client_peak_in_flight"] == 3
    assert result["chat"]["client_overlap_observed"] is True


def test_load_test_round_robins_request_base_urls() -> None:
    hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(200, json={})

    async def run() -> dict:
        config = E2ELoadTestConfig(
            base_url="http://primary.test/api/v1",
            request_base_urls=("http://primary.test/api/v1", "http://secondary.test/api/v1"),
            tenant_id="tenant",
            user_id="user",
            bearer="",
            file_bytes=b"",
            filename="test.txt",
            dataset_id="dataset",
            ingest_count=0,
            retrieve_requests=4,
            retrieve_concurrency=2,
            chat_requests=2,
            chat_concurrency=1,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_e2e_load_test(config, client=client)

    result = asyncio.run(run())

    assert result["retrieve"]["ok"] == 4
    assert result["chat"]["ok"] == 2
    assert hosts == [
        "primary.test",
        "secondary.test",
        "primary.test",
        "secondary.test",
        "primary.test",
        "secondary.test",
    ]
