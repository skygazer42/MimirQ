"""Alembic environment configuration.

This file is intentionally kept lightweight:
- Adds repo root to sys.path so `app.*` imports work when running Alembic from the
  repository root.
- Loads DB URL from `app.core.config.settings.DATABASE_URL` (fallback: `DATABASE_URL` env var).
- Imports all model modules so `Base.metadata` is complete for autogeneration.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import MetaData, engine_from_config, pool

from alembic import context

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

config = context.config

# Configure Python logging using the config file.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _get_database_url() -> str:
    # Prefer app settings (supports .env). Fall back to DATABASE_URL when
    # app imports are unavailable (e.g. minimal tooling environments).
    try:
        from app.core.config import settings

        url = settings.DATABASE_URL.strip()
        if url:
            return url
    except Exception:  # noqa: BLE001
        pass

    env_url = os.getenv("DATABASE_URL", "").strip()
    if env_url:
        return env_url

    # Last resort: alembic.ini value.
    return (config.get_main_option("sqlalchemy.url") or "").strip()


def _load_target_metadata() -> MetaData:
    # Ensure all model modules are imported so Base.metadata includes every table.
    # This is required for correct autogenerate output.
    import app.models._all as model_registry
    from app.core.database import Base

    _ = model_registry.REGISTERED_MODEL_MODULES
    return Base.metadata


target_metadata = _load_target_metadata()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    url = _get_database_url()

    # This call produces a SQLAlchemy Engine.
    connectable = engine_from_config(
        configuration=config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=url,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
