import sys

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


def test_main_dry_run_warns_and_lists_only_first_ten_candidates(monkeypatch, capsys) -> None:
    document_ids = [f"doc-{index}" for index in range(12)]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backfill_minio_images.py",
            "--dataset-id",
            "dataset",
            "--tenant-id",
            "tenant",
            "--user-id",
            "user",
            "--dry-run",
        ],
    )
    monkeypatch.setattr(
        backfill_minio_images,
        "_read_storage_readiness",
        lambda **_kwargs: {"minio": {"enabled": False, "status": "disabled"}},
    )
    monkeypatch.setattr(
        backfill_minio_images,
        "_iter_dataset_document_ids",
        lambda **_kwargs: document_ids,
    )
    monkeypatch.setattr(
        backfill_minio_images,
        "_request_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dry run must not retry")),
    )

    assert backfill_minio_images.main() == 0

    output = capsys.readouterr().out
    assert "object storage is disabled" in output
    assert "Candidate documents: 12" in output
    assert "  - doc-0" in output
    assert "  - doc-9" in output
    assert "doc-10" not in output
    assert "  ... (+2 more)" in output


def test_main_ignores_ambient_jwt_auth_mode_for_header_flow(monkeypatch, capsys) -> None:
    headers_seen: list[dict[str, str]] = []

    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backfill_minio_images.py",
            "--dataset-id",
            "dataset",
            "--tenant-id",
            "tenant",
            "--user-id",
            "user",
            "--dry-run",
        ],
    )

    def readiness(**kwargs: object) -> dict[str, dict[str, object]]:
        headers = kwargs.get("headers")
        assert isinstance(headers, dict)
        headers_seen.append({str(key): str(value) for key, value in headers.items()})
        return {"minio": {"enabled": False, "status": "disabled"}}

    def list_ids(**kwargs: object) -> list[str]:
        headers = kwargs.get("headers")
        assert isinstance(headers, dict)
        headers_seen.append({str(key): str(value) for key, value in headers.items()})
        return []

    monkeypatch.setattr(backfill_minio_images, "_read_storage_readiness", readiness)
    monkeypatch.setattr(backfill_minio_images, "_iter_dataset_document_ids", list_ids)

    assert backfill_minio_images.main() == 0

    expected_headers = {
        "Accept": "application/json",
        "X-Tenant-ID": "tenant",
        "X-User-ID": "user",
    }
    assert headers_seen == [expected_headers, expected_headers]
    assert "Candidate documents: 0" in capsys.readouterr().out


def test_main_batches_retry_payloads_and_totals(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backfill_minio_images.py",
            "--dataset-id",
            "dataset",
            "--tenant-id",
            "tenant",
            "--user-id",
            "user",
            "--batch-size",
            "2",
            "--force",
            "--skip-if-unchanged",
        ],
    )
    monkeypatch.setattr(
        backfill_minio_images,
        "_read_storage_readiness",
        lambda **_kwargs: {"minio": {"enabled": True, "status": "connected"}},
    )
    monkeypatch.setattr(
        backfill_minio_images,
        "_iter_dataset_document_ids",
        lambda **_kwargs: ["doc-1", "doc-2", "doc-3"],
    )
    payloads: list[dict] = []

    def retry(_url, *, method, headers, payload, timeout_sec):
        payloads.append(payload)
        return backfill_minio_images.HttpResult(
            status_code=200,
            elapsed_ms=1,
            data={"queued": len(payload["document_ids"]), "skipped": 1, "conflicts": []},
            error=None,
        )

    monkeypatch.setattr(backfill_minio_images, "_request_json", retry)

    assert backfill_minio_images.main() == 0

    assert payloads == [
        {
            "force": True,
            "skip_if_unchanged": True,
            "document_ids": ["doc-1", "doc-2"],
        },
        {
            "force": True,
            "skip_if_unchanged": True,
            "document_ids": ["doc-3"],
        },
    ]
    assert "Done: queued=3 skipped=2" in capsys.readouterr().out
