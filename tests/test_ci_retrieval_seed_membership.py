from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.tenant import Tenant, TenantMember
from scripts import seed_ci_retrieval_regression
from scripts.seed_ci_retrieval_regression import ensure_fixture_tenant_owner


def test_seed_creates_explicit_idempotent_tenant_owner_membership() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Tenant.__table__, TenantMember.__table__])
    session_factory = sessionmaker(bind=engine)
    tenant_id = uuid4()

    try:
        with session_factory() as db:
            ensure_fixture_tenant_owner(db, tenant_id=tenant_id, account_id="ci-bot")
            db.commit()
            ensure_fixture_tenant_owner(db, tenant_id=tenant_id, account_id="ci-bot")
            db.commit()

            assert db.query(Tenant).filter(Tenant.id == tenant_id).count() == 1
            members = db.query(TenantMember).filter(TenantMember.tenant_id == tenant_id).all()
            assert len(members) == 1
            assert members[0].user_id == "ci-bot"
            assert members[0].role == "owner"
            assert members[0].is_active is True
            assert members[0].is_current is True
    finally:
        engine.dispose()


def test_membership_only_cli_routes_all_tenants_to_explicit_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_seed(*, tenant_ids: list[UUID], account_id: str) -> None:
        captured["tenant_ids"] = tenant_ids
        captured["account_id"] = account_id

    monkeypatch.setattr(seed_ci_retrieval_regression, "seed_tenant_memberships", fake_seed)

    result = seed_ci_retrieval_regression.main(
        [
            "--membership-only",
            "--tenant-id",
            "11111111-1111-1111-1111-111111111111",
            "--tenant-id",
            "22222222-2222-2222-2222-222222222222",
            "--account-id",
            "ci-live-gate",
        ]
    )

    assert result == 0
    assert captured == {
        "tenant_ids": [
            UUID("11111111-1111-1111-1111-111111111111"),
            UUID("22222222-2222-2222-2222-222222222222"),
        ],
        "account_id": "ci-live-gate",
    }
