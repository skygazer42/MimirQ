from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.tenant import Tenant, TenantMember
from scripts.seed_ci_kg_search_regression import ensure_fixture_tenant_owner


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Tenant.__table__, TenantMember.__table__])
    return engine, sessionmaker(bind=engine)


def test_seed_creates_explicit_idempotent_tenant_owner_membership() -> None:
    engine, session_factory = _session_factory()
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


def test_seed_upgrades_existing_membership_to_active_owner() -> None:
    engine, session_factory = _session_factory()
    tenant_id = uuid4()

    try:
        with session_factory() as db:
            db.add(Tenant(id=tenant_id, name="tenant-under-test", status="inactive", plan="enterprise"))
            db.add(
                TenantMember(
                    tenant_id=tenant_id,
                    user_id="ci-bot",
                    role="viewer",
                    is_active=False,
                    is_current=False,
                )
            )
            db.commit()

            ensure_fixture_tenant_owner(db, tenant_id=tenant_id, account_id="ci-bot")
            db.commit()

            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).one()
            member = (
                db.query(TenantMember)
                .filter(TenantMember.tenant_id == tenant_id, TenantMember.user_id == "ci-bot")
                .one()
            )
            assert tenant.status == "inactive"
            assert tenant.plan == "enterprise"
            assert member.role == "owner"
            assert member.is_active is True
            assert member.is_current is True
    finally:
        engine.dispose()
