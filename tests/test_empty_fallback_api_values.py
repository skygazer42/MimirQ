from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from starlette.requests import Request

from app.api.dependencies import auth
from app.api.schemas.auth import AuthHeaders
from app.api.v1 import evaluations, pipeline
from app.core.jwt_verify import _validate_response_url_chain
from app.models.evaluation import RagasRegressionCase


@pytest.mark.asyncio
async def test_account_resolution_preserves_genuinely_absent_tenant_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def resolve(**kwargs):
        captured.update(kwargs)
        return "reader"

    monkeypatch.setattr(auth, "get_current_account_id_from_headers", resolve)
    request = Request({"type": "http", "headers": []})
    assert await auth.get_current_account_id(request, AuthHeaders()) == "reader"
    assert captured["x_tenant_id"] is None


def test_synthetic_case_projects_the_actual_generated_kind() -> None:
    case = RagasRegressionCase(id=uuid4(), extra={})
    result = evaluations._synthetic_case_extra(case, SimpleNamespace(kind=False, rationale=None))
    assert result["hardcase_kind"] is False


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
