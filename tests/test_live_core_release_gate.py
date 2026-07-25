import asyncio

import httpx
import pytest

from scripts import live_core_release_gate as gate


def _config() -> gate.LiveCoreReleaseGateConfig:
    return gate.LiveCoreReleaseGateConfig(
        api_base="http://mimirq.test/api/v1",
        secondary_api_base=None,
        primary_tenant_id="tenant-a",
        secondary_tenant_id="tenant-b",
        user_id="ci-user",
        parser_backend="auto",
        retrieve_requests=6,
        candidate_concurrency=3,
        min_retrieve_throughput_ratio=1.0,
        ready_timeout_sec=1.0,
        ingest_timeout_sec=1.0,
        poll_interval_sec=0.0,
        timeout_sec=1.0,
        cleanup_on_success=False,
    )


def _load_report(*, concurrency: int, throughput_rps: float, overlap: bool) -> dict:
    return {
        "ingest": {"requested": 0, "completed": 0, "errors": 0},
        "retrieve": {
            "requested": 6,
            "ok": 6,
            "errors": 0,
            "concurrency": concurrency,
            "client_overlap_observed": overlap,
            "throughput_rps": throughput_rps,
            "latency_ms": {"p95_ms": 50},
        },
        "chat": {
            "requested": 0,
            "ok": 0,
            "errors": 0,
            "concurrency": 0,
            "client_overlap_observed": False,
            "throughput_rps": 0.0,
            "latency_ms": {"p95_ms": 0},
        },
    }


def test_live_core_release_gate_passes_for_header_auth_happy_path(monkeypatch) -> None:
    waited_document_ids: list[str] = []

    def _fake_load_pair(**_kwargs) -> tuple[dict, dict]:
        assert "doc-dup" in waited_document_ids
        return (
            _load_report(concurrency=1, throughput_rps=1.0, overlap=False),
            _load_report(concurrency=3, throughput_rps=1.8, overlap=True),
        )

    monkeypatch.setattr(
        gate,
        "_wait_for_document_completion",
        lambda *_args, document_id, **_kwargs: waited_document_ids.append(document_id),
        raising=True,
    )
    monkeypatch.setattr(gate, "_run_retrieve_only_load_pair", _fake_load_pair, raising=True)
    monkeypatch.setattr(
        gate,
        "_concurrent_duplicate_upload_ids",
        lambda **_kwargs: ["doc-dup", "doc-dup"],
        raising=True,
    )
    monkeypatch.setattr(
        gate,
        "_same_key_dual_instance_probe",
        lambda **_kwargs: {"passed": True, "requests": []},
        raising=True,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        tenant = request.headers.get("X-Tenant-ID", "")
        if request.url.path == "/api/v1/health/ready":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/v1/datasets/" and request.method == "POST":
            return httpx.Response(201, json={"id": f"dataset-{tenant}"})
        if request.url.path == "/api/v1/documents/upload" and request.method == "POST":
            if tenant == "tenant-a":
                return httpx.Response(201, json={"id": "doc-a"})
            return httpx.Response(201, json={"id": "doc-b"})
        if request.url.path in {
            "/api/v1/documents/doc-a/status",
            "/api/v1/documents/doc-b/status",
            "/api/v1/documents/doc-dup/status",
        }:
            return httpx.Response(200, json={"status": "completed"})
        if request.url.path == "/api/v1/rag/retrieve" and request.method == "POST":
            payload = request.read().decode("utf-8")
            data = gate.json.loads(payload)
            dataset_id = str(data.get("dataset_id") or "")
            query = str(data.get("query") or "")
            allowed = {
                ("tenant-a", "dataset-tenant-a"): ("doc-a", query),
                ("tenant-b", "dataset-tenant-b"): ("doc-b", query),
            }
            hit = allowed.get((tenant, dataset_id))
            if hit is None:
                return httpx.Response(404, json={"detail": "Dataset not found"})
            document_id, marker = hit
            return httpx.Response(
                200,
                json={
                    "has_evidence": True,
                    "citations": [{"document_id": document_id, "chunk_content": marker}],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = gate.run_live_core_release_gate(_config(), client=client)

    assert report["passed"] is True
    assert report["duplicate_upload"]["passed"] is True
    assert report["concurrency"]["gate"]["passed"] is True
    assert report["concurrency"]["query"].endswith("varied-throughput")
    assert report["tenant_isolation"]["passed"] is True
    assert report["same_key_dual_instance"]["passed"] is True


def test_live_core_release_gate_uses_secondary_api_for_duplicate_probe(monkeypatch) -> None:
    config = gate.LiveCoreReleaseGateConfig(
        api_base="http://primary.test/api/v1",
        secondary_api_base="http://secondary.test/api/v1",
        primary_tenant_id="tenant-a",
        secondary_tenant_id="tenant-b",
        user_id="ci-user",
        cleanup_on_success=False,
    )
    upload_hosts: list[str] = []

    monkeypatch.setattr(
        gate,
        "_run_retrieve_only_load_pair",
        lambda **_kwargs: (_load_report(concurrency=1, throughput_rps=1.0, overlap=False), _load_report(concurrency=3, throughput_rps=1.8, overlap=True)),
        raising=True,
    )
    monkeypatch.setattr(
        gate,
        "_same_key_dual_instance_probe",
        lambda **_kwargs: {"passed": True, "requests": []},
        raising=True,
    )

    def _fake_duplicate_probe(**_kwargs) -> list[str]:
        upload_hosts.extend(["primary.test", "secondary.test"])
        return ["doc-dup", "doc-dup"]

    monkeypatch.setattr(gate, "_concurrent_duplicate_upload_ids", _fake_duplicate_probe, raising=True)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health/ready":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/v1/datasets/" and request.method == "POST":
            return httpx.Response(201, json={"id": f"dataset-{request.headers.get('X-Tenant-ID', '')}"})
        if request.url.path == "/api/v1/documents/upload" and request.method == "POST":
            tenant = request.headers.get("X-Tenant-ID", "")
            return httpx.Response(201, json={"id": "doc-a" if tenant == "tenant-a" else "doc-b"})
        if request.url.path in {
            "/api/v1/documents/doc-a/status",
            "/api/v1/documents/doc-b/status",
            "/api/v1/documents/doc-dup/status",
        }:
            return httpx.Response(200, json={"status": "completed"})
        if request.url.path == "/api/v1/rag/retrieve" and request.method == "POST":
            payload = gate.json.loads(request.read().decode("utf-8"))
            dataset_id = str(payload.get("dataset_id") or "")
            tenant = request.headers.get("X-Tenant-ID", "")
            if tenant == "tenant-a" and dataset_id == "dataset-tenant-a":
                return httpx.Response(200, json={"has_evidence": True, "citations": [{"document_id": "doc-a", "chunk_content": payload["query"]}]})
            if tenant == "tenant-b" and dataset_id == "dataset-tenant-b":
                return httpx.Response(200, json={"has_evidence": True, "citations": [{"document_id": "doc-b", "chunk_content": payload["query"]}]})
            return httpx.Response(404, json={"detail": "Dataset not found"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = gate.run_live_core_release_gate(config, client=client)

    assert report["passed"] is True
    assert upload_hosts[:2] == ["primary.test", "secondary.test"]


def test_live_core_release_gate_fails_when_duplicate_upload_changes_document_id(monkeypatch) -> None:
    def _fake_load_pair(**_kwargs) -> tuple[dict, dict]:
        return (
            _load_report(concurrency=1, throughput_rps=1.0, overlap=False),
            _load_report(concurrency=3, throughput_rps=1.8, overlap=True),
        )

    monkeypatch.setattr(gate, "_run_retrieve_only_load_pair", _fake_load_pair, raising=True)
    monkeypatch.setattr(
        gate,
        "_concurrent_duplicate_upload_ids",
        lambda **_kwargs: ["doc-a", "doc-a-retry"],
        raising=True,
    )
    monkeypatch.setattr(
        gate,
        "_same_key_dual_instance_probe",
        lambda **_kwargs: {"passed": True, "requests": []},
        raising=True,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health/ready":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/v1/datasets/" and request.method == "POST":
            tenant = request.headers.get("X-Tenant-ID", "")
            return httpx.Response(201, json={"id": f"dataset-{tenant}"})
        if request.url.path == "/api/v1/documents/upload" and request.method == "POST":
            tenant = request.headers.get("X-Tenant-ID", "")
            return httpx.Response(201, json={"id": "doc-a" if tenant == "tenant-a" else "doc-b"})
        if request.url.path in {
            "/api/v1/documents/doc-a/status",
            "/api/v1/documents/doc-a-retry/status",
            "/api/v1/documents/doc-b/status",
        }:
            return httpx.Response(200, json={"status": "completed"})
        if request.url.path == "/api/v1/rag/retrieve" and request.method == "POST":
            payload = gate.json.loads(request.read().decode("utf-8"))
            dataset_id = str(payload.get("dataset_id") or "")
            query = str(payload.get("query") or "")
            tenant = request.headers.get("X-Tenant-ID", "")
            if tenant == "tenant-a" and dataset_id == "dataset-tenant-a":
                return httpx.Response(
                    200,
                    json={
                        "has_evidence": True,
                        "citations": [{"document_id": "doc-a", "chunk_content": query}],
                    },
                )
            if tenant == "tenant-b" and dataset_id == "dataset-tenant-b":
                return httpx.Response(
                    200,
                    json={
                        "has_evidence": True,
                        "citations": [{"document_id": "doc-b", "chunk_content": query}],
                    },
                )
            return httpx.Response(404, json={"detail": "Dataset not found"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = gate.run_live_core_release_gate(_config(), client=client)

    assert report["passed"] is False
    assert report["duplicate_upload"]["passed"] is False
    assert any("concurrent duplicate upload returned different document ids" in failure for failure in report["failures"])


def test_same_key_dual_instance_probe_requires_follower_hit(monkeypatch) -> None:
    config = gate.LiveCoreReleaseGateConfig(
        api_base="http://primary.test/api/v1",
        secondary_api_base="http://secondary.test/api/v1",
        primary_tenant_id="tenant-a",
        secondary_tenant_id="tenant-b",
        user_id="ci-user",
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        cache = {"singleflight_role": "leader"}
        if request.url.host == "secondary.test":
            cache = {"singleflight_role": "follower", "distributed_singleflight_hit": True}
        return httpx.Response(200, json={"query_debug": {"channels": {"cache": cache}}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        probe = gate._same_key_dual_instance_probe(
            config=config,
            headers={"X-Tenant-ID": "tenant-a", "X-User-ID": "ci-user"},
            dataset_id="dataset-a",
            query="same-key-query",
            client=client,
        )

    assert probe["passed"] is True
    assert probe["overlap_observed"] is True
    assert len(probe["requests"]) == 2


def test_retrieve_load_pair_prewarms_every_candidate_instance(monkeypatch) -> None:
    config = gate.LiveCoreReleaseGateConfig(
        api_base="http://primary.test/api/v1",
        secondary_api_base="http://secondary.test/api/v1",
        primary_tenant_id="tenant-a",
        secondary_tenant_id="tenant-b",
        user_id="ci-user",
        retrieve_requests=6,
        candidate_concurrency=3,
    )
    calls: list[tuple[int, int, tuple[str, ...]]] = []

    async def _fake_load_test(cfg, *, client):
        del client
        calls.append((cfg.retrieve_requests, cfg.retrieve_concurrency, cfg.request_base_urls))
        return _load_report(
            concurrency=cfg.retrieve_concurrency,
            throughput_rps=float(cfg.retrieve_concurrency),
            overlap=cfg.retrieve_concurrency > 1,
        )

    monkeypatch.setattr(gate, "run_e2e_load_test", _fake_load_test)

    gate._run_retrieve_only_load_pair(config=config, dataset_id="dataset-a", query="knowledge query")

    assert calls[:2] == [
        (1, 1, ("http://primary.test/api/v1",)),
        (1, 1, ("http://secondary.test/api/v1",)),
    ]
    assert calls[2:] == [
        (6, 1, ("http://primary.test/api/v1",)),
        (6, 3, ("http://primary.test/api/v1", "http://secondary.test/api/v1")),
    ]


def test_live_core_release_gate_cleans_up_created_datasets_after_failure(monkeypatch) -> None:
    def _fake_load_pair(**_kwargs) -> tuple[dict, dict]:
        return (
            _load_report(concurrency=1, throughput_rps=1.0, overlap=False),
            _load_report(concurrency=3, throughput_rps=1.8, overlap=True),
        )

    monkeypatch.setattr(gate, "_run_retrieve_only_load_pair", _fake_load_pair, raising=True)
    monkeypatch.setattr(
        gate,
        "_concurrent_duplicate_upload_ids",
        lambda **_kwargs: ["doc-a", "doc-a-retry"],
        raising=True,
    )
    monkeypatch.setattr(
        gate,
        "_same_key_dual_instance_probe",
        lambda **_kwargs: {"passed": True, "requests": []},
        raising=True,
    )

    purge_calls: list[str] = []
    delete_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health/ready":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/v1/datasets/" and request.method == "POST":
            tenant = request.headers.get("X-Tenant-ID", "")
            return httpx.Response(201, json={"id": f"dataset-{tenant}"})
        if request.url.path == "/api/v1/documents/upload" and request.method == "POST":
            tenant = request.headers.get("X-Tenant-ID", "")
            return httpx.Response(201, json={"id": "doc-a" if tenant == "tenant-a" else "doc-b"})
        if request.url.path in {
            "/api/v1/documents/doc-a/status",
            "/api/v1/documents/doc-a-retry/status",
            "/api/v1/documents/doc-b/status",
        }:
            return httpx.Response(200, json={"status": "completed"})
        if request.url.path.endswith("/purge") and request.method == "POST":
            purge_calls.append(request.url.path)
            return httpx.Response(200, json={"deleted": 1})
        if request.url.path.startswith("/api/v1/datasets/") and request.method == "DELETE":
            delete_calls.append(request.url.path)
            return httpx.Response(204)
        if request.url.path == "/api/v1/rag/retrieve" and request.method == "POST":
            payload = gate.json.loads(request.read().decode("utf-8"))
            dataset_id = str(payload.get("dataset_id") or "")
            query = str(payload.get("query") or "")
            tenant = request.headers.get("X-Tenant-ID", "")
            if tenant == "tenant-a" and dataset_id == "dataset-tenant-a":
                return httpx.Response(
                    200,
                    json={"has_evidence": True, "citations": [{"document_id": "doc-a", "chunk_content": query}]},
                )
            if tenant == "tenant-b" and dataset_id == "dataset-tenant-b":
                return httpx.Response(
                    200,
                    json={"has_evidence": True, "citations": [{"document_id": "doc-b", "chunk_content": query}]},
                )
            return httpx.Response(404, json={"detail": "Dataset not found"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = gate.run_live_core_release_gate(_config(), client=client)

    assert report["passed"] is False
    assert sorted(report["cleanup"]) == ["dataset-tenant-a", "dataset-tenant-b"]
    assert len(purge_calls) == 2
    assert len(delete_calls) == 2


def test_live_core_release_gate_cleans_up_when_duplicate_wait_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        gate,
        "_upload_and_wait_for_evidence",
        lambda *_args, **_kwargs: "doc-a",
        raising=True,
    )
    monkeypatch.setattr(
        gate,
        "_concurrent_duplicate_upload_ids",
        lambda **_kwargs: ["doc-dup", "doc-dup"],
        raising=True,
    )

    def _raise_for_duplicate(*_args, document_id: str, **_kwargs) -> None:
        assert document_id == "doc-dup"
        raise RuntimeError("duplicate ingestion failed")

    monkeypatch.setattr(gate, "_wait_for_document_completion", _raise_for_duplicate, raising=True)

    cleanup_calls: list[str] = []

    def _fake_cleanup(*_args, dataset_id: str, **_kwargs) -> dict:
        cleanup_calls.append(dataset_id)
        return {"dataset_id": dataset_id, "deleted": True}

    monkeypatch.setattr(gate, "_cleanup_created_dataset", _fake_cleanup, raising=True)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health/ready":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/v1/datasets/" and request.method == "POST":
            return httpx.Response(201, json={"id": "dataset-tenant-a"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="duplicate ingestion failed"):
            gate.run_live_core_release_gate(_config(), client=client)

    assert cleanup_calls == ["dataset-tenant-a"]


def test_is_expected_tenant_denial_accepts_acl_responses() -> None:
    assert gate._is_expected_tenant_denial_status(403) is True
    assert gate._is_expected_tenant_denial_status(404) is True
    assert gate._is_expected_tenant_denial_status(409) is False
