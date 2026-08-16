from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.tenant import Tenant, TenantMember
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
