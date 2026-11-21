from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from starlette.requests import Request

from app.api import dependencies as auth
from app.api.v1.evaluation import routes as evaluations
from app.api.v1.pipelines import routes as pipeline
from app.infrastructure.security.jwt_verify import _validate_response_url_chain
from app.models.evaluation.results import RagasRegressionCase


@pytest.mark.asyncio
async def test_account_resolution_preserves_genuinely_absent_tenant_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def decode(token):
        captured["token"] = token
        return {"sub": "reader"}

    monkeypatch.setattr(auth.settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(auth, "decode_access_token", decode)
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer verified-token")]})
    assert await auth.get_current_account_id(request) == "reader"
    assert captured == {"token": "verified-token"}
    assert request.headers.get("X-Tenant-ID") is None
    assert "tenant_id" not in request.state.jwt_payload
    assert not hasattr(request.state, "tenant_id")


def test_synthetic_case_projects_the_actual_generated_kind() -> None:
    case = RagasRegressionCase(id=uuid4(), extra={})
    result = evaluations._build_synthetic_regression_case(
        base_case=case,
        hardcase=SimpleNamespace(kind=False, rationale=None),
        reference_sources=[],
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        account_id="reader",
        question="Generated question",
        tag="generated",
    )
    assert result.extra["hardcase_kind"] is False


def test_missing_required_generated_question_is_not_a_successful_empty_batch() -> None:
    with pytest.raises(AttributeError):
        evaluations._persist_generated_hardcases(
            db=object(),
            hardcases=[SimpleNamespace()],
            base_case=RagasRegressionCase(id=uuid4()),
            reference_sources=[],
            tenant_id=uuid4(),
            dataset_id=uuid4(),
            account_id="reader",
            max_created=1,
            tag="generated",
            dry_run=True,
            existing_keys=set(),
            created_ids=[],
        )


def test_plugin_response_requires_the_descriptor_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "build_golden_draft_bundle_from_chunks", lambda **_kwargs: {"items": []})
    descriptor = SimpleNamespace(version="1", package_hash="hash", golden_rules={})
    with pytest.raises(AttributeError):
        pipeline._build_plugin_golden_draft_response(
            dataset_id=uuid4(), plugin_ref="plugin:example@1", descriptor=descriptor, chunks=[], max_items=1
        )


def test_remote_jwt_response_requires_its_url_attribute() -> None:
    with pytest.raises(AttributeError):
        _validate_response_url_chain(
            requested_url="https://issuer.invalid/jwks",
            response=SimpleNamespace(history=[]),
            error_name="invalid chain",
        )


def test_remote_jwt_response_keeps_the_real_validated_url_chain() -> None:
    response = httpx.Response(200, request=httpx.Request("GET", "https://issuer.example.com/jwks"))
    _validate_response_url_chain(
        requested_url="https://issuer.example.com/jwks", response=response, error_name="invalid chain"
    )
