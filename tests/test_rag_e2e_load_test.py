from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import httpx
import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "rag_e2e_load_test.py"


def _load_module():
    path = _script_path()
    if not path.exists():
        pytest.skip("load test script not implemented yet")
    spec = importlib.util.spec_from_file_location("rag_e2e_load_test", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # dataclasses + PEP563-style annotations need module globals resolvable via sys.modules.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_load_test_script_exists() -> None:
    assert _script_path().exists(), "expected scripts/rag_e2e_load_test.py to exist"


def test_percentile_ms_nearest_rank() -> None:
    mod = _load_module()
    values = [300, 100, 200]
    assert mod.percentile_ms(values, 0) == 100
    assert mod.percentile_ms(values, 50) == 200
    assert mod.percentile_ms(values, 95) == 300
    assert mod.percentile_ms(values, 100) == 300


def test_summarize_latencies_ms() -> None:
    mod = _load_module()
    summary = mod.summarize_latencies_ms([100, 200, 300])
    assert summary["count"] == 3
    assert summary["min_ms"] == 100
    assert summary["max_ms"] == 300
    assert math.isclose(float(summary["mean_ms"]), 200.0, rel_tol=0.0, abs_tol=1e-9)
    assert summary["p50_ms"] == 200
    assert summary["p95_ms"] == 300
    assert summary["p99_ms"] == 300


def test_throughput_per_sec() -> None:
    mod = _load_module()
    assert math.isclose(mod.throughput_per_sec(count=100, elapsed_ms=10_000), 10.0, rel_tol=0.0, abs_tol=1e-9)
    assert mod.throughput_per_sec(count=100, elapsed_ms=0) == pytest.approx(0.0)


def test_evaluate_load_gate_fails_on_errors_and_thresholds() -> None:
    mod = _load_module()
    report = {
        "ingest": {"requested": 2, "completed": 1, "errors": 1, "e2e_latency_ms": {"p95_ms": 9000}},
        "retrieve": {"requested": 3, "ok": 2, "errors": 1, "latency_ms": {"p95_ms": 1200}},
        "chat": {"requested": 1, "ok": 1, "errors": 0, "latency_ms": {"p95_ms": 5000}},
    }

    gate = mod.evaluate_load_gate(
        report,
        max_ingest_p95_ms=8000,
        max_retrieve_p95_ms=1000,
        max_chat_p95_ms=4000,
    )

    assert gate["passed"] is False
    assert "ingest_errors 1 > 0" in gate["failures"]
    assert "retrieve_ok 2 < requested 3" in gate["failures"]
    assert "chat_p95_ms 5000 > max 4000" in gate["failures"]


def test_evaluate_load_gate_passes_when_counts_match() -> None:
    mod = _load_module()
    report = {
        "ingest": {"requested": 1, "completed": 1, "errors": 0, "e2e_latency_ms": {"p95_ms": 100}},
        "retrieve": {"requested": 1, "ok": 1, "errors": 0, "latency_ms": {"p95_ms": 80}},
        "chat": {"requested": 1, "ok": 1, "errors": 0, "latency_ms": {"p95_ms": 300}},
    }

    gate = mod.evaluate_load_gate(report, max_ingest_p95_ms=1000, max_retrieve_p95_ms=1000, max_chat_p95_ms=1000)

    assert gate["passed"] is True
    assert gate["failures"] == []


def test_main_dry_run(tmp_path: Path) -> None:
    mod = _load_module()
    assert hasattr(mod, "main")

    p = tmp_path / "doc.txt"
    p.write_text("hello", encoding="utf-8")

    rc = mod.main(
        [
            "--dry-run",
            "--base-url",
            "http://test/api/v1",
            "--tenant-id",
            "t1",
            "--user-id",
            "u1",
            "--file",
            str(p),
        ]
    )
    assert rc == 0


@pytest.mark.asyncio
async def test_run_e2e_load_test_smoke_mock_transport() -> None:
    mod = _load_module()
    assert hasattr(mod, "E2ELoadTestConfig")
    assert hasattr(mod, "run_e2e_load_test")

    doc_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-Tenant-ID") == "t1"
        assert request.headers.get("X-User-ID") == "u1"

        if request.method == "POST" and request.url.path.endswith("/datasets/"):
            return httpx.Response(201, json={"id": "ds1"})
        if request.method == "POST" and request.url.path.endswith("/documents/upload"):
            doc_id = f"doc{len(doc_ids) + 1}"
            doc_ids.append(doc_id)
            return httpx.Response(201, json={"id": doc_id})
        if request.method == "GET" and "/documents/" in request.url.path and request.url.path.endswith("/status"):
            return httpx.Response(
                200,
                json={"status": "completed", "processing_progress": 1.0, "current_stage": "completed"},
            )
        if request.method == "POST" and request.url.path.endswith("/rag/retrieve-preview"):
            return httpx.Response(200, json={"query_for_retrieval": "q", "citations": [], "metrics": {}})
        if request.method == "POST" and request.url.path.endswith("/chat"):
            return httpx.Response(200, json={"answer": "ok"})

        return httpx.Response(404, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5.0)) as client:
        cfg = mod.E2ELoadTestConfig(
            base_url="http://test/api/v1",
            tenant_id="t1",
            user_id="u1",
            bearer="",
            file_bytes=b"hello",
            filename="hello.txt",
            ingest_count=2,
            ingest_concurrency=2,
            poll_interval_sec=0.0,
            ingest_timeout_sec=2.0,
            retrieve_requests=3,
            retrieve_concurrency=3,
            query="hello",
            chat_requests=4,
            chat_concurrency=4,
            message="hello",
            doc_sample_size=2,
        )
        out = await mod.run_e2e_load_test(cfg, client=client)

    assert out["dataset_id"] == "ds1"
    assert out["ingest"]["completed"] == 2
    assert out["retrieve"]["ok"] == 3
    assert out["chat"]["ok"] == 4
