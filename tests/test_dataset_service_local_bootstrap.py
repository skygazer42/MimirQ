from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.core.request_state import bind_request_state, reset_request_state
from app.models.tenant import Tenant, TenantMember
from app.services.dataset_service import DatasetService


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Tenant.__table__, TenantMember.__table__])
    return engine, sessionmaker(bind=engine)


def test_default_tenant_bootstrap_requires_implicit_default_tenant_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, test_session = _session_factory()
    tenant_id = uuid4()
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr("app.services.dataset_service.settings.AUTH_MODE", "header", raising=False)
    monkeypatch.setattr(
        "app.services.dataset_service.settings.LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED", True, raising=False
    )
    monkeypatch.setattr("app.services.dataset_service.settings.DEFAULT_TENANT_ID", str(tenant_id), raising=False)

    token = bind_request_state(SimpleNamespace(tenant_id_source="header", client_host="127.0.0.1"))
    try:
        with test_session() as db:
            with pytest.raises(HTTPException) as excinfo:
                DatasetService.ensure_member(db, tenant_id, "acct-1")
        assert excinfo.value.status_code == 403
    finally:
        reset_request_state(token)
        engine.dispose()


def test_default_tenant_bootstrap_requires_loopback_header_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, test_session = _session_factory()
    tenant_id = uuid4()
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr("app.services.dataset_service.settings.AUTH_MODE", "header", raising=False)
    monkeypatch.setattr(
        "app.services.dataset_service.settings.LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED", True, raising=False
    )
    monkeypatch.setattr("app.services.dataset_service.settings.DEFAULT_TENANT_ID", str(tenant_id), raising=False)

    token = bind_request_state(SimpleNamespace(tenant_id_source="default", client_host="198.51.100.8"))
    try:
        with test_session() as db:
            with pytest.raises(HTTPException) as excinfo:
                DatasetService.ensure_member(db, tenant_id, "acct-1")
        assert excinfo.value.status_code == 403
    finally:
        reset_request_state(token)
        engine.dispose()


def test_default_tenant_bootstrap_allows_loopback_header_auth_without_client_tenant_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, test_session = _session_factory()
    tenant_id = uuid4()
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr("app.services.dataset_service.settings.AUTH_MODE", "header", raising=False)
    monkeypatch.setattr(
        "app.services.dataset_service.settings.LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED", True, raising=False
    )
    monkeypatch.setattr("app.services.dataset_service.settings.DEFAULT_TENANT_ID", str(tenant_id), raising=False)

    token = bind_request_state(SimpleNamespace(tenant_id_source="default", client_host="127.0.0.1"))
    try:
        with test_session() as db:
            member = DatasetService.ensure_member(db, tenant_id, "acct-1")

            assert member.role == "owner"
            assert db.query(TenantMember).count() == 1
            assert db.query(Tenant).count() == 1
    finally:
        reset_request_state(token)
        engine.dispose()


def test_default_tenant_bootstrap_is_disabled_without_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, test_session = _session_factory()
    tenant_id = uuid4()
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr("app.services.dataset_service.settings.AUTH_MODE", "header", raising=False)
    monkeypatch.setattr(
        "app.services.dataset_service.settings.LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED", False, raising=False
    )
    monkeypatch.setattr("app.services.dataset_service.settings.DEFAULT_TENANT_ID", str(tenant_id), raising=False)

    token = bind_request_state(SimpleNamespace(tenant_id_source="default", client_host="127.0.0.1"))
    try:
        with test_session() as db:
            with pytest.raises(HTTPException) as excinfo:
                DatasetService.ensure_member(db, tenant_id, "acct-1")
        assert excinfo.value.status_code == 403
        with test_session() as db:
            assert db.query(TenantMember).count() == 0
            assert db.query(Tenant).count() == 0
    finally:
        reset_request_state(token)
        engine.dispose()


def test_local_bootstrap_setting_requires_header_auth() -> None:
    with pytest.raises(ValueError, match="LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED requires AUTH_MODE=header"):
        Settings(
            SECRET_KEY="x" * 32,
            AUTH_MODE="jwt",
            LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED=True,
        )
