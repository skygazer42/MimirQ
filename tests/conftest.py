import os

import pytest
from sqlalchemy import text


def _integration_enabled() -> bool:
    return str(os.getenv("MIMIRQ_INTEGRATION_TESTS", "") or "").strip().lower() in {"1", "true", "yes", "y", "on"}


@pytest.fixture()
def pg_session():
    """
    Postgres-backed DB session for integration tests.

    Disabled by default. Enable with:
      - set MIMIRQ_INTEGRATION_TESTS=1
      - set DATABASE_URL to a dedicated test database
    """
    if not _integration_enabled():
        pytest.skip("Integration tests disabled (set MIMIRQ_INTEGRATION_TESTS=1)")

    # Import models lazily so pure unit tests don't pull DB config eagerly.
    from app.core.database import Base, SessionLocal, engine  # noqa: WPS433

    # Ensure required models are registered for create_all.
    import app.models.dataset  # noqa: F401
    import app.models.document  # noqa: F401
    import app.models.tenant  # noqa: F401
    import app.models.dataset_profile_scan  # noqa: F401

    # Create tables (idempotent).
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

    # Best-effort cleanup for the next test run.
    try:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE dataset_profile_scan_runs RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE document_parsed_contents RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE document_chunks RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE document_permissions RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE documents RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE dataset_permissions RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE datasets RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE tenant_members RESTART IDENTITY CASCADE;"))
            conn.execute(text("TRUNCATE TABLE tenants RESTART IDENTITY CASCADE;"))
    except Exception:
        # Do not fail tests due to cleanup issues.
        pass

