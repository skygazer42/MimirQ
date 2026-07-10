"""
DB maintenance helpers (ops automation).

Currently supported:
- Postgres VACUUM / ANALYZE (bounded by optional table allowlist)

Design principles:
- Idempotent: safe to run repeatedly
- Safe-by-default: validate table identifiers when provided
- Script-friendly: return small JSON-safe summaries
"""


import re
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine.url import make_url

from app.core.config import settings
from app.core.database import engine

_TABLE_RE = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)?$")


def build_postgres_maintenance_commands(
    *,
    vacuum: bool,
    analyze: bool,
    verbose: bool,
    tables: list[str] | None,
) -> list[str]:
    """
    Build Postgres maintenance SQL commands.

    Safety:
    - When `tables` is provided, identifiers are validated against a conservative
      regex to prevent SQL injection via ops tooling.
    """
    if not bool(vacuum) and not bool(analyze):
        raise ValueError("No operation selected (vacuum/analyze)")

    table_list = ""
    if tables:
        cleaned: list[str] = []
        for raw in tables:
            name = str(raw or "").strip()
            if not name:
                continue
            if not _TABLE_RE.match(name):
                raise ValueError(f"Invalid table identifier: {name!r}")
            cleaned.append(name)
        if cleaned:
            table_list = " " + ", ".join(cleaned)

    cmds: list[str] = []
    if bool(vacuum):
        opts: list[str] = []
        if bool(analyze):
            opts.append("ANALYZE")
        if bool(verbose):
            opts.append("VERBOSE")
        opt_sql = f" ({', '.join(opts)})" if opts else ""
        cmds.append(f"VACUUM{opt_sql}{table_list};")
        return cmds

    # analyze-only
    verbose_sql = " VERBOSE" if bool(verbose) else ""
    cmds.append(f"ANALYZE{verbose_sql}{table_list};")
    return cmds


def run_postgres_maintenance(
    *,
    vacuum: bool,
    analyze: bool,
    verbose: bool,
    tables: list[str] | None,
    dry_run: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Execute Postgres maintenance commands (VACUUM/ANALYZE) using AUTOCOMMIT.

    Notes:
    - VACUUM cannot run inside a transaction; we use an AUTOCOMMIT connection.
    - When the configured DB isn't Postgres, this is a no-op with `skipped=true`.
    """
    now0 = now or datetime.now(UTC)
    commands = build_postgres_maintenance_commands(vacuum=vacuum, analyze=analyze, verbose=verbose, tables=tables)

    url = make_url(settings.DATABASE_URL)
    driver = str(url.drivername or "").lower()
    if not driver.startswith("postgres"):
        return {
            "ok": True,
            "skipped": True,
            "skip_reason": "not_postgres",
            "driver": driver,
            "ran_at": now0.isoformat(),
            "dry_run": bool(dry_run),
            "commands": list(commands),
        }

    if bool(dry_run):
        return {
            "ok": True,
            "skipped": False,
            "ran_at": now0.isoformat(),
            "dry_run": True,
            "commands": list(commands),
        }

    t0 = time.perf_counter()
    executed: list[str] = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for cmd in commands:
            conn.execute(text(cmd))
            executed.append(cmd)
    elapsed = time.perf_counter() - t0

    return {
        "ok": True,
        "skipped": False,
        "ran_at": now0.isoformat(),
        "dry_run": False,
        "elapsed_sec": round(elapsed, 3),
        "commands": list(commands),
        "executed": list(executed),
    }


__all__ = [
    "build_postgres_maintenance_commands",
    "run_postgres_maintenance",
]

