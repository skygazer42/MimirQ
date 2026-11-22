from argparse import Namespace
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import Uuid, create_engine, literal, select

from app.api.v1.documents import routes as documents
from app.api.v1.documents import versions as document_versions
from app.infrastructure import config
from app.infrastructure.database import migrations
from app.services.dify.common import _citation_dataset_id
from scripts import run_db_maintenance_jobs, run_retention_jobs

document_chunk_preview = documents.document_chunk_preview
document_preview = documents.document_preview


def test_runtime_migration_default_tenant_must_not_fabricate_zero_identity(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr(config.settings, "DEFAULT_TENANT_ID", "invalid-configured-tenant")
    with pytest.raises(ValueError):
        migrations._default_tenant_uuid()


def test_maintenance_tenant_projection_accepts_real_sqlalchemy_rows(monkeypatch):  # noqa: ANN001
    value = uuid4()
    with create_engine("sqlite://").connect() as connection:
        rows = connection.execute(select(literal(value, type_=Uuid()).label("id"))).all()

    class Session:
        closed = False

        def query(self, _field):
            return SimpleNamespace(all=lambda: rows)

        def close(self):
            self.closed = True

    session = Session()
    monkeypatch.setattr(run_db_maintenance_jobs, "SessionLocal", lambda: session)
    monkeypatch.setattr(run_db_maintenance_jobs, "Tenant", SimpleNamespace(id=object()))
    assert run_db_maintenance_jobs._tenant_ids(Namespace(all_tenants=True, tenant_id=None), []) == ([value], True)
    assert session.closed
    session.closed = False
    deps = SimpleNamespace(SessionLocal=lambda: session, Tenant=SimpleNamespace(id=object()))
    assert run_retention_jobs._tenant_ids(Namespace(all_tenants=True, tenant_id=None), deps) == [value]
    assert session.closed


@pytest.mark.parametrize(
    "load", [document_versions._load_version_signatures, document_versions._load_version_chunk_ids]
)
def test_version_lookup_does_not_retry_failed_authoritative_query_as_an_unfiltered_scan(load):  # noqa: ANN001
    class Query:
        def __init__(self, fail):
            self.fail = fail

        def filter(self, *_conditions):
            return self

        def execution_options(self, **_options):
            return self

        def enable_eagerloads(self, _enabled):
            return self

        def all(self):
            if self.fail:
                raise RuntimeError("version query failed")
            return []

    class Session:
        calls = 0

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def query(self, *_columns):
            self.calls += 1
            return Query(self.calls == 1)

    session = Session()
    with pytest.raises(RuntimeError, match="version query failed"):
        load(db=session, tenant_id=uuid4(), document_id=uuid4(), target_key="selected-pipeline")
    assert session.calls == 1


@pytest.mark.parametrize(
    "module, helper",
    [
        (document_preview, document_preview._load_preview_metadata),
        (document_chunk_preview, document_chunk_preview._load_preview_dataset_meta),
    ],
)
def test_selected_dataset_preview_does_not_drop_policy_when_database_lookup_fails(monkeypatch, module, helper):  # noqa: ANN001
    def fail(*_args):
        raise RuntimeError("dataset database unavailable")

    monkeypatch.setattr(module, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(module.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(module.dataset_service, "get_dataset", fail)
    with pytest.raises(RuntimeError, match="dataset database unavailable"):
        helper(tenant_id=uuid4(), account_id="member", dataset_id=str(uuid4()))
    assert helper(tenant_id=uuid4(), account_id="member", dataset_id=None) == {}


def test_citation_parses_only_raw_ids_and_passes_through_the_native_scope_fallback():
    fallback = uuid4()
    assert _citation_dataset_id({}, fallback_dataset_id=fallback) is fallback
    assert _citation_dataset_id({"dataset_id": "invalid"}, fallback_dataset_id=fallback) is fallback
    explicit = uuid4()
    assert _citation_dataset_id({"metadata": {"dataset_id": str(explicit)}}, fallback_dataset_id=fallback) == explicit
