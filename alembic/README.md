# Alembic Migrations

This repository uses **Alembic** to manage database schema migrations.

Quick commands:

```bash
make db-upgrade               # apply migrations to the latest revision
make db-revision m="message"  # generate a new revision (autogenerate)
```

Notes:
- `alembic/env.py` loads the DB URL from `app.core.config.settings.DATABASE_URL` by
  default (or `DATABASE_URL` env var as fallback).
- For existing deployments created before Alembic was wired, you may need to
  `alembic stamp head` after verifying your schema matches the current code.

