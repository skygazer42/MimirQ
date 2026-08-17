import asyncio
import json

import httpx

from scripts import rag_e2e_load_test
from scripts.rag_e2e_load_test import (
    E2ELoadTestConfig,
    evaluate_concurrency_gate,
    evaluate_load_gate,
    main,
    run_e2e_load_test,
)


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


def test_evaluate_load_gate_preserves_failure_aggregation_order() -> None:
    gate = evaluate_load_gate(
        {
            "ingest": {
                "requested": 2,
                "completed": 1,
                "errors": 3,
                "e2e_latency_ms": {"p95_ms": 111},
            },
            "retrieve": {
                "requested": 4,
                "ok": 2,
                "errors": 5,
                "latency_ms": {"p95_ms": 222},
            },
            "chat": {
                "requested": 6,
                "ok": 3,
                "errors": 7,
                "latency_ms": {"p95_ms": 333},
            },
        },
        max_ingest_p95_ms=100,
        max_retrieve_p95_ms=200,
        max_chat_p95_ms=300,
    )

    assert gate["passed"] is False
    assert gate["failures"] == [
        "ingest_completed 1 < requested 2",
        "ingest_errors 3 > 0",
        "retrieve_ok 2 < requested 4",
        "retrieve_errors 5 > 0",
        "chat_ok 3 < requested 6",
        "chat_errors 7 > 0",
        "ingest_p95_ms 111 > max 100",
        "retrieve_p95_ms 222 > max 200",
        "chat_p95_ms 333 > max 300",
    ]


def test_main_dry_run_preserves_cli_defaults(tmp_path, monkeypatch, capsys) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello", encoding="utf-8")
    monkeypatch.delenv("NEXT_PUBLIC_API_URL", raising=False)

    exit_code = main(["--dry-run", "--file", str(file_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "[rag-e2e-loadtest] base_url=http://localhost:8000/api/v1" in captured.out
    assert "[rag-e2e-loadtest] ingest_count=1 ingest_concurrency=1" in captured.out
    assert "[rag-e2e-loadtest] retrieve_requests=20 retrieve_concurrency=10" in captured.out
    assert "[rag-e2e-loadtest] chat_requests=10 chat_concurrency=5" in captured.out


def test_main_comparison_mode_writes_schema_and_returns_zero(tmp_path, capsys) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    out_path = tmp_path / "comparison.json"
    baseline.write_text(
        json.dumps(_load_report(concurrency=1, retrieve_rps=0.5, chat_rps=0.25, overlap=False)),
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps(_load_report(concurrency=3, retrieve_rps=0.8, chat_rps=0.4, overlap=True)),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--baseline-report",
            str(baseline),
            "--candidate-report",
            str(candidate),
            "--out",
            str(out_path),
            "--min-retrieve-throughput-ratio",
            "1.1",
            "--min-chat-throughput-ratio",
            "1.1",
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["schema"] == "mimirq.rag_concurrency_gate.v1"
    assert report["baseline_report"] == str(baseline)
    assert report["candidate_report"] == str(candidate)
    assert report["passed"] is True
    assert "[rag-e2e-loadtest] CONCURRENCY PASS" in captured.out


def test_main_reports_gate_failures_and_returns_2(tmp_path, monkeypatch, capsys) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello", encoding="utf-8")

    async def fake_run_e2e_load_test(
        cfg: E2ELoadTestConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> dict:
        del cfg, client
        return {
            "ingest": {
                "requested": 0,
                "completed": 0,
                "errors": 0,
                "throughput_docs_per_sec": 0.0,
                "e2e_latency_ms": {"p95_ms": 0},
            },
            "retrieve": {
                "requested": 1,
                "ok": 0,
                "errors": 1,
                "throughput_rps": 0.0,
                "latency_ms": {"p95_ms": 150},
                "client_peak_in_flight": 1,
            },
            "chat": {
                "requested": 0,
                "ok": 0,
                "errors": 0,
                "throughput_rps": 0.0,
                "latency_ms": {"p95_ms": 0},
                "client_peak_in_flight": 1,
            },
        }

    monkeypatch.setattr(rag_e2e_load_test, "run_e2e_load_test", fake_run_e2e_load_test)

    exit_code = main(
        [
            "--file",
            str(file_path),
            "--max-retrieve-p95-ms",
            "100",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "[rag-e2e-loadtest] FAIL: retrieve_ok 0 < requested 1" in captured.err
    assert "[rag-e2e-loadtest] FAIL: retrieve_errors 1 > 0" in captured.err
    assert "[rag-e2e-loadtest] FAIL: retrieve_p95_ms 150 > max 100" in captured.err
