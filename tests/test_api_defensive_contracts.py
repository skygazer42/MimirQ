import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import dependencies as auth
from app.api.v1.conversations import feedback
from app.rag.ingestion.parsing.utils import scalars
from app.services.documents.processing import _retry_chunk_exists


class BrokenString:
    def __str__(self):
        raise RuntimeError("unexpected string implementation failure")


class BrokenNumber:
    def __int__(self):
        raise RuntimeError("unexpected numeric implementation failure")

    def __float__(self):
        raise RuntimeError("unexpected numeric implementation failure")


@pytest.mark.parametrize("helper", [feedback._coerce_int, scalars.coerce_int, scalars.coerce_float])
def test_api_numeric_boundaries_do_not_hide_unexpected_implementation_failures(helper):  # noqa: ANN001
    with pytest.raises(RuntimeError, match="unexpected numeric implementation"):
        helper(BrokenNumber())


def test_feedback_uuid_boundary_does_not_hide_unexpected_string_failure():
    with pytest.raises(RuntimeError, match="unexpected string implementation"):
        feedback._coerce_uuid(BrokenString())


@pytest.mark.parametrize("raw", ["", "not-a-uuid", 0, False, [], {}])
def test_jwt_tenant_claim_rejects_invalid_boundary_values(monkeypatch, raw):  # noqa: ANN001
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(auth.settings, "JWT_TENANT_CLAIM", "tenant_id")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(auth.get_tenant_id(_verified_request(raw)))
    assert caught.value.status_code == 401


def _verified_request(tenant_claim, tenant_header=None):
    headers = [] if tenant_header is None else [(b"x-tenant-id", tenant_header.encode())]
    request = Request({"type": "http", "headers": headers})
    request.state.authenticated_account_id = "reader"
    request.state.jwt_payload = {"tenant_id": tenant_claim}
    return request


@pytest.mark.parametrize("raw", [None, ""])
def test_tenant_header_validation_remains_an_explicit_bad_request(monkeypatch, raw):  # noqa: ANN001
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(auth.settings, "JWT_TENANT_CLAIM", "tenant_id")
    monkeypatch.setattr(auth.settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", True)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(auth.get_tenant_id(_verified_request("123e4567-e89b-42d3-a456-426614174000", raw)))
    assert caught.value.status_code == 400


@pytest.mark.parametrize("raw", [" ", "invalid-uuid"])
def test_malformed_tenant_header_is_an_explicit_bad_request(monkeypatch, raw):  # noqa: ANN001
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(auth.settings, "JWT_TENANT_CLAIM", "tenant_id")
    monkeypatch.setattr(auth.settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", True)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(auth.get_tenant_id(_verified_request("123e4567-e89b-42d3-a456-426614174000", raw)))
    assert caught.value.status_code == 400


def test_valid_tenant_claim_is_canonicalized_once_at_the_jwt_boundary(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(auth.settings, "JWT_TENANT_CLAIM", "tenant_id")
    monkeypatch.setattr(auth.settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False)
    assert asyncio.run(auth.get_tenant_id(_verified_request("{123e4567-e89b-42d3-a456-426614174000}"))) == UUID(
        "123e4567-e89b-42d3-a456-426614174000"
    )


@pytest.mark.parametrize("helper", [feedback._coerce_int, scalars.coerce_float])
def test_real_malformed_numeric_input_still_returns_the_documented_absence(helper):  # noqa: ANN001
    assert helper("not-a-number") is None


def test_retry_chunk_lookup_does_not_replace_query_failure_with_a_bounded_fallback_scan():
    from uuid import uuid4

    class Query:
        def filter(self, *_args):
            return self

        def limit(self, _limit):
            return self

        def first(self):
            raise RuntimeError("primary lookup failed")

        def all(self):
            return []

    class Database:
        def query(self, _model):
            return Query()

    with pytest.raises(RuntimeError, match="primary lookup failed"):
        _retry_chunk_exists(db=Database(), tenant_id=uuid4(), document_id=uuid4(), target_key="pipeline")
