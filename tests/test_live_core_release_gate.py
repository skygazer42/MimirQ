import httpx

from scripts import live_core_release_gate as gate


def _config() -> gate.LiveCoreReleaseGateConfig:
    return gate.LiveCoreReleaseGateConfig(
        api_base="http://mimirq.test/api/v1",
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
    upload_counts = {"tenant-a": 0, "tenant-b": 0}

    def _fake_load_pair(**_kwargs) -> tuple[dict, dict]:
        return (
            _load_report(concurrency=1, throughput_rps=1.0, overlap=False),
            _load_report(concurrency=3, throughput_rps=1.8, overlap=True),
        )

    monkeypatch.setattr(gate, "_run_retrieve_only_load_pair", _fake_load_pair, raising=True)

    def handler(request: httpx.Request) -> httpx.Response:
        tenant = request.headers.get("X-Tenant-ID", "")
        if request.url.path == "/api/v1/health/ready":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/v1/datasets/" and request.method == "POST":
            return httpx.Response(201, json={"id": f"dataset-{tenant}"})
        if request.url.path == "/api/v1/documents/upload" and request.method == "POST":
            upload_counts[tenant] += 1
            if tenant == "tenant-a":
                return httpx.Response(201, json={"id": "doc-a"})
            return httpx.Response(201, json={"id": "doc-b"})
        if request.url.path in {"/api/v1/documents/doc-a/status", "/api/v1/documents/doc-b/status"}:
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
    assert report["tenant_isolation"]["passed"] is True
    assert upload_counts == {"tenant-a": 2, "tenant-b": 1}


def test_live_core_release_gate_fails_when_duplicate_upload_changes_document_id(monkeypatch) -> None:
    upload_count = 0

    def _fake_load_pair(**_kwargs) -> tuple[dict, dict]:
        return (
            _load_report(concurrency=1, throughput_rps=1.0, overlap=False),
            _load_report(concurrency=3, throughput_rps=1.8, overlap=True),
        )

    monkeypatch.setattr(gate, "_run_retrieve_only_load_pair", _fake_load_pair, raising=True)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal upload_count
        if request.url.path == "/api/v1/health/ready":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/v1/datasets/" and request.method == "POST":
            tenant = request.headers.get("X-Tenant-ID", "")
            return httpx.Response(201, json={"id": f"dataset-{tenant}"})
        if request.url.path == "/api/v1/documents/upload" and request.method == "POST":
            tenant = request.headers.get("X-Tenant-ID", "")
            if tenant == "tenant-a":
                upload_count += 1
                return httpx.Response(201, json={"id": "doc-a" if upload_count == 1 else "doc-a-retry"})
            return httpx.Response(201, json={"id": "doc-b"})
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
    assert any("duplicate upload returned a different document id" in failure for failure in report["failures"])


def test_is_expected_tenant_denial_accepts_acl_responses() -> None:
    assert gate._is_expected_tenant_denial_status(403) is True
    assert gate._is_expected_tenant_denial_status(404) is True
    assert gate._is_expected_tenant_denial_status(409) is False
