import pytest

from scripts import api_smoke


class _StopSmokeError(Exception):
    pass


class _ClientStub:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


@pytest.mark.parametrize(
    ("tenant_id", "system_tenant_id", "expected"),
    [
        ("tenant-1", "tenant-1", [200]),
        ("tenant-1", "system-tenant", [403]),
    ],
)
def test_settings_write_expectation_tracks_system_tenant(
    tenant_id: str, system_tenant_id: str, expected: list[int]
) -> None:
    assert (
        api_smoke.settings_write_expected_statuses(
            tenant_id=tenant_id,
            system_tenant_id=system_tenant_id,
        )
        == expected
    )


def test_header_auth_bootstraps_dataset_membership_before_settings_put(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_call(self, method: str, path_template: str, path: str, expected, **kwargs):
        calls.append((method.upper(), path_template))
        if method.upper() == "PUT" and path_template == api_smoke.API_SETTINGS:
            raise _StopSmokeError()
        return None

    monkeypatch.setattr(api_smoke, "load_openapi_paths", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(api_smoke.httpx, "Client", _ClientStub)
    monkeypatch.setattr(api_smoke.SmokeRunner, "call", fake_call)

    with pytest.raises(_StopSmokeError):
        api_smoke.main(
            [
                "--base-url",
                "http://mimirq.test",
                "--tenant-id",
                "tenant-1",
                "--auth-mode",
                "header",
                "--skip-llm-test",
            ]
        )

    assert ("GET", api_smoke.API_DATASETS) in calls
    assert calls.index(("GET", api_smoke.API_DATASETS)) < calls.index(("PUT", api_smoke.API_SETTINGS))


def test_jwt_auth_can_reuse_an_existing_smoke_account(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, list[int], dict]] = []

    def fake_call(self, method: str, path_template: str, path: str, expected, **kwargs):
        calls.append((method.upper(), path_template, list(expected), dict(kwargs.get("json") or {})))
        if path_template == "/api/v1/auth/register":
            return {"status": 409}
        if path_template == "/api/v1/auth/login":
            return {"token": {"access_token": "existing-token"}}
        if method.upper() == "GET" and path_template == api_smoke.API_SETTINGS:
            raise _StopSmokeError()
        return {}

    monkeypatch.setattr(api_smoke, "load_openapi_paths", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(api_smoke.httpx, "Client", _ClientStub)
    monkeypatch.setattr(api_smoke, "parse_json", lambda response: response or {})
    monkeypatch.setattr(api_smoke.SmokeRunner, "call", fake_call)

    with pytest.raises(_StopSmokeError):
        api_smoke.main(
            [
                "--base-url",
                "http://mimirq.test",
                "--auth-mode",
                "jwt",
                "--jwt-identifier",
                "existing@example.com",
                "--jwt-password",
                "existing-password",
                "--skip-llm-test",
            ]
        )

    register = next(call for call in calls if call[1] == "/api/v1/auth/register")
    login = next(call for call in calls if call[1] == "/api/v1/auth/login")
    assert register[2] == [201, 400, 409]
    assert login[3] == {"identifier": "existing@example.com", "password": "existing-password"}


def test_upload_forms_disable_chunk_vectors_for_offline_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    upload_data: dict[str, dict[str, str]] = {}

    def fake_parse_json(resp):
        return resp if isinstance(resp, dict) else {}

    def fake_call(self, method: str, path_template: str, path: str, expected, **kwargs):
        if method.upper() == "POST" and path_template == api_smoke.API_DATASETS:
            return {"id": "dataset-1"}
        if method.upper() == "POST" and path_template in {
            "/api/v1/documents/upload",
            "/api/v1/documents/upload-batch",
        }:
            upload_data[path_template] = dict(kwargs.get("data") or {})
        if method.upper() == "GET" and path_template == "/api/v1/documents/stats":
            raise _StopSmokeError()
        return None

    monkeypatch.setattr(api_smoke, "load_openapi_paths", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(api_smoke.httpx, "Client", _ClientStub)
    monkeypatch.setattr(api_smoke, "parse_json", fake_parse_json)
    monkeypatch.setattr(api_smoke.SmokeRunner, "call", fake_call)

    with pytest.raises(_StopSmokeError):
        api_smoke.main(
            [
                "--base-url",
                "http://mimirq.test",
                "--tenant-id",
                "tenant-1",
                "--auth-mode",
                "header",
                "--skip-llm-test",
            ]
        )

    assert upload_data["/api/v1/documents/upload"]["chunk_vector_enabled"] == "false"
    assert upload_data["/api/v1/documents/upload-batch"]["chunk_vector_enabled"] == "false"
