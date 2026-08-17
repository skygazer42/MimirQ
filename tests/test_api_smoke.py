from collections import deque
from dataclasses import dataclass, field
from typing import Any

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


@dataclass
class _ResponseSpec:
    status: int = 200
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class _CallRecord:
    method: str
    path_template: str
    path: str
    expected: list[int]
    kwargs: dict[str, Any]


class _SmokeHarness:
    def __init__(
        self,
        *,
        responses: dict[tuple[str, str], _ResponseSpec | list[_ResponseSpec]] | None = None,
        openapi_paths: set[tuple[str, str]] | None = None,
        disable_probe_sweep: bool = False,
        stream_ok: bool = True,
    ) -> None:
        self.calls: list[_CallRecord] = []
        self.probe_calls: list[_CallRecord] = []
        self.stream_calls: list[_CallRecord] = []
        self.openapi_paths = openapi_paths or set()
        self.disable_probe_sweep = disable_probe_sweep
        self.stream_ok = stream_ok
        self._responses: dict[tuple[str, str], deque[_ResponseSpec]] = {}

        for key, value in (responses or {}).items():
            specs = value if isinstance(value, list) else [value]
            self._responses[(key[0].upper(), key[1])] = deque(specs)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(api_smoke, "load_openapi_paths", lambda *_args, **_kwargs: set(self.openapi_paths))
        monkeypatch.setattr(api_smoke.httpx, "Client", _ClientStub)
        monkeypatch.setattr(api_smoke, "parse_json", self.parse_json)
        monkeypatch.setattr(
            api_smoke.SmokeRunner,
            "call",
            lambda runner, method, path_template, path, expected, **kwargs: self.call(
                runner, method, path_template, path, expected, **kwargs
            ),
        )
        monkeypatch.setattr(
            api_smoke.SmokeRunner,
            "probe",
            lambda runner, method, path_template, path, expected, **kwargs: self.probe(
                runner, method, path_template, path, expected, **kwargs
            ),
        )
        monkeypatch.setattr(
            api_smoke.SmokeRunner,
            "stream",
            lambda runner, method, path_template, path, expected, **kwargs: self.stream(
                runner, method, path_template, path, expected, **kwargs
            ),
        )
        if self.disable_probe_sweep:
            monkeypatch.setattr(api_smoke, "probe_uncovered_openapi_endpoints", lambda *_args, **_kwargs: None)

    def parse_json(self, response: Any) -> dict[str, Any]:
        if isinstance(response, _ResponseSpec):
            return response.payload
        if isinstance(response, dict):
            return response
        return {}

    def _next_spec(self, method: str, path_template: str) -> _ResponseSpec:
        key = (method.upper(), path_template)
        specs = self._responses.get(key)
        if not specs:
            return _ResponseSpec(status=-1)
        if len(specs) == 1:
            return specs[0]
        return specs.popleft()

    def _record(
        self,
        bucket: list[_CallRecord],
        *,
        method: str,
        path_template: str,
        path: str,
        expected,
        kwargs: dict[str, Any],
    ) -> None:
        bucket.append(
            _CallRecord(
                method=method.upper(),
                path_template=path_template,
                path=path,
                expected=list(expected),
                kwargs=dict(kwargs),
            )
        )

    def call(self, runner, method: str, path_template: str, path: str, expected, **kwargs):
        runner.mark(method, path_template)
        self._record(
            self.calls,
            method=method,
            path_template=path_template,
            path=path,
            expected=expected,
            kwargs=kwargs,
        )
        spec = self._next_spec(method, path_template)
        status = list(expected)[0] if spec.status < 0 else spec.status
        ok = status in set(expected)
        note = "" if ok else f"unexpected status {status}: {spec.payload!r}"
        runner.results.append(api_smoke.CallResult(method.upper(), path_template, status, ok, note))
        return spec

    def probe(self, runner, method: str, path_template: str, path: str, expected, **kwargs) -> bool:
        runner.mark(method, path_template)
        self._record(
            self.probe_calls,
            method=method,
            path_template=path_template,
            path=path,
            expected=expected,
            kwargs=kwargs,
        )
        runner.results.append(api_smoke.CallResult(method.upper(), path_template, list(expected)[0], True, ""))
        return True

    def stream(self, runner, method: str, path_template: str, path: str, expected, **kwargs) -> tuple[bool, str]:
        runner.mark(method, path_template)
        self._record(
            self.stream_calls,
            method=method,
            path_template=path_template,
            path=path,
            expected=expected,
            kwargs=kwargs,
        )
        status = list(expected)[0]
        note = "" if self.stream_ok else "stream failed"
        runner.results.append(api_smoke.CallResult(method.upper(), path_template, status, self.stream_ok, note))
        return self.stream_ok, note


class _PreviewRunner:
    def __init__(self, responses: list[_ResponseSpec]) -> None:
        self.responses = deque(responses)
        self.results: list[api_smoke.CallResult] = []

    def call(self, method: str, path_template: str, path: str, expected, **kwargs):
        response = self.responses.popleft()
        self.results.append(api_smoke.CallResult(method.upper(), path_template, response.status, True, ""))
        return response


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


def test_build_headers_prefers_bearer_token_over_user_header() -> None:
    assert api_smoke.build_headers("tenant-1", "user-1", "token-1") == {
        "X-Tenant-ID": "tenant-1",
        "Authorization": "Bearer token-1",
    }


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
    calls: list[tuple[str, str, list[int], dict[str, Any]]] = []

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
    monkeypatch.setattr(api_smoke, "parse_json", lambda response: response if isinstance(response, dict) else {})
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


def test_main_cleans_up_created_resources_and_sorted_batch_uploads(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _SmokeHarness(
        responses={
            ("POST", api_smoke.API_DATASETS): _ResponseSpec(status=201, payload={"id": "dataset-1"}),
            ("POST", "/api/v1/documents/upload"): _ResponseSpec(status=201, payload={"id": "doc-1"}),
            (
                "POST",
                "/api/v1/documents/upload-batch",
            ): _ResponseSpec(
                status=201,
                payload={
                    "successful": [
                        {"document_id": "batch-z"},
                        {"document_id": "doc-1"},
                        {"document_id": "manual-1"},
                        {"document_id": "batch-a"},
                    ]
                },
            ),
            ("GET", "/api/v1/documents/{document_id}/status"): [
                _ResponseSpec(status=200, payload={}),
                _ResponseSpec(status=200, payload={"status": "completed"}),
            ],
            ("POST", api_smoke.API_DOCUMENTS_MANUAL): _ResponseSpec(status=201, payload={"id": "manual-1"}),
            ("GET", "/api/v1/documents/{document_id}/chunks"): _ResponseSpec(
                status=200,
                payload={"items": [{"id": "chunk-1"}]},
            ),
            ("POST", api_smoke.API_CHAT_CONVERSATIONS): _ResponseSpec(
                status=201,
                payload={"id": "conversation-1"},
            ),
            ("POST", api_smoke.API_PROMPT_TEMPLATES): _ResponseSpec(status=201, payload={"id": "template-1"}),
        }
    )
    harness.install(monkeypatch)

    exit_code = api_smoke.main(
        [
            "--base-url",
            "http://mimirq.test",
            "--tenant-id",
            "tenant-1",
            "--auth-mode",
            "header",
            "--skip-llm-test",
            "--skip-mineru",
        ]
    )

    assert exit_code == 0

    upload = next(record for record in harness.calls if record.path_template == "/api/v1/documents/upload")
    batch_upload = next(record for record in harness.calls if record.path_template == "/api/v1/documents/upload-batch")
    assert upload.kwargs["data"] == {"chunk_vector_enabled": "false", "dataset_id": "dataset-1"}
    assert batch_upload.kwargs["data"] == {"chunk_vector_enabled": "false", "dataset_id": "dataset-1"}

    assert [(record.method, record.path_template, record.path) for record in harness.calls[-7:]] == [
        ("DELETE", "/api/v1/chat/conversations/{conversation_id}", "/api/v1/chat/conversations/conversation-1"),
        ("DELETE", api_smoke.API_PROMPT_TEMPLATE_BY_ID, "/api/v1/prompt-templates/template-1"),
        ("DELETE", api_smoke.API_DOCUMENT_BY_ID, "/api/v1/documents/doc-1"),
        ("DELETE", api_smoke.API_DOCUMENT_BY_ID, "/api/v1/documents/manual-1"),
        ("DELETE", api_smoke.API_DOCUMENT_BY_ID, "/api/v1/documents/batch-a"),
        ("DELETE", api_smoke.API_DOCUMENT_BY_ID, "/api/v1/documents/batch-z"),
        ("DELETE", api_smoke.API_DATASET_BY_ID, "/api/v1/datasets/dataset-1"),
    ]


def test_main_skips_id_dependent_dataset_and_document_branches_when_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _SmokeHarness()
    harness.install(monkeypatch)

    exit_code = api_smoke.main(
        [
            "--base-url",
            "http://mimirq.test",
            "--tenant-id",
            "tenant-1",
            "--auth-mode",
            "header",
            "--skip-llm-test",
            "--skip-mineru",
        ]
    )

    assert exit_code == 0

    call_templates = {(record.method, record.path_template) for record in harness.calls}
    assert ("GET", api_smoke.API_DATASET_BY_ID) not in call_templates
    assert ("PUT", api_smoke.API_DATASET_INGESTION_POLICY) not in call_templates
    assert ("POST", api_smoke.API_DOCUMENTS_MANUAL) not in call_templates
    assert ("GET", "/api/v1/documents/{document_id}/chunks") not in call_templates
    assert ("DELETE", api_smoke.API_DOCUMENT_BY_ID) not in call_templates
    assert ("DELETE", api_smoke.API_DATASET_BY_ID) not in call_templates


def test_main_requires_live_parser_fixture_when_backends_are_requested(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        api_smoke.main(
            [
                "--base-url",
                "http://mimirq.test",
                "--tenant-id",
                "tenant-1",
                "--auth-mode",
                "header",
                "--live-parser-backends",
                "mineru",
            ]
        )

    assert exc_info.value.code == 2
    assert "--live-parser-fixture is required when --live-parser-backends is set" in capsys.readouterr().err


def test_run_live_parser_preview_smokes_validates_backend_echo_and_non_empty_segments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    fixture = tmp_path / "fixture.pdf"
    fixture.write_bytes(b"%PDF-1.4 smoke fixture")
    runner = _PreviewRunner(
        [
            _ResponseSpec(status=200, payload={"parser_backend": "other", "segments": ["ok"]}),
            _ResponseSpec(status=200, payload={"parser_backend": "deepseek_ocr", "segments": []}),
        ]
    )
    monkeypatch.setattr(
        api_smoke,
        "parse_json",
        lambda response: response.payload if isinstance(response, _ResponseSpec) else {},
    )

    api_smoke.run_live_parser_preview_smokes(
        runner=runner,
        fixture_path=fixture,
        parser_backends=["mineru", "deepseek_ocr"],
        timeout=15.0,
    )

    assert [result.ok for result in runner.results] == [False, False]
    assert "requested parser_backend=mineru" in runner.results[0].note
    assert "empty segments for parser_backend=deepseek_ocr" in runner.results[1].note


def test_main_reports_failures_and_missing_endpoints(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    harness = _SmokeHarness(
        responses={
            ("GET", "/health"): _ResponseSpec(status=500, payload={"detail": "boom"}),
        },
        openapi_paths={("GET", "/uncovered")},
        disable_probe_sweep=True,
    )
    harness.install(monkeypatch)

    exit_code = api_smoke.main(
        [
            "--base-url",
            "http://mimirq.test",
            "--tenant-id",
            "tenant-1",
            "--auth-mode",
            "header",
            "--skip-llm-test",
            "--skip-mineru",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Calls:" in output
    assert "Failures: 1" in output
    assert "Missing: 1" in output
    assert "- GET /health: unexpected status 500" in output
    assert "- GET /uncovered" in output
