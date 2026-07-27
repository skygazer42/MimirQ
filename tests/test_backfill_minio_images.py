from scripts import backfill_minio_images


def test_storage_readiness_prefers_authenticated_details(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_request(url, *, method, headers, payload=None, timeout_sec=30.0):  # noqa: ANN001, ANN202
        calls.append((url, headers))
        return backfill_minio_images.HttpResult(
            status_code=200,
            elapsed_ms=1,
            data={"ok": True, "minio": {"enabled": True, "status": "connected"}},
            error=None,
        )

    monkeypatch.setattr(backfill_minio_images, "_request_json", fake_request)

    payload = backfill_minio_images._read_storage_readiness(
        base_url="http://localhost:8000",
        headers={"Authorization": "Bearer token", "X-Tenant-ID": "tenant"},
        timeout_sec=2.0,
    )

    assert payload["minio"] == {"enabled": True, "status": "connected"}
    assert calls == [
        (
            "http://localhost:8000/api/v1/health/details",
            {"Authorization": "Bearer token", "X-Tenant-ID": "tenant"},
        )
    ]


def test_storage_readiness_falls_back_to_legacy_ready_shape(monkeypatch) -> None:
    calls: list[str] = []

    def fake_request(url, *, method, headers, payload=None, timeout_sec=30.0):  # noqa: ANN001, ANN202
        calls.append(url)
        if url.endswith("/health/details"):
            return backfill_minio_images.HttpResult(
                status_code=404,
                elapsed_ms=1,
                data={"detail": "Not Found"},
                error="HTTPError: 404",
            )
        return backfill_minio_images.HttpResult(
            status_code=200,
            elapsed_ms=1,
            data={"ok": True, "minio": {"enabled": False, "status": "disabled"}},
            error=None,
        )

    monkeypatch.setattr(backfill_minio_images, "_request_json", fake_request)

    payload = backfill_minio_images._read_storage_readiness(
        base_url="http://localhost:8000",
        headers={"X-User-ID": "admin", "X-Tenant-ID": "tenant"},
        timeout_sec=2.0,
    )

    assert payload["minio"] == {"enabled": False, "status": "disabled"}
    assert calls == [
        "http://localhost:8000/api/v1/health/details",
        "http://localhost:8000/api/v1/health/ready",
    ]
