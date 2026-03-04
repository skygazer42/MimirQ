from __future__ import annotations

import pytest


def test_build_postgres_maintenance_commands_vacuum_analyze():
    from app.services.db_maintenance_jobs import build_postgres_maintenance_commands

    cmds = build_postgres_maintenance_commands(vacuum=True, analyze=True, verbose=False, tables=None)
    assert cmds == ["VACUUM (ANALYZE);"]


def test_build_postgres_maintenance_commands_vacuum_only():
    from app.services.db_maintenance_jobs import build_postgres_maintenance_commands

    cmds = build_postgres_maintenance_commands(vacuum=True, analyze=False, verbose=False, tables=None)
    assert cmds == ["VACUUM;"]


def test_build_postgres_maintenance_commands_analyze_only_verbose():
    from app.services.db_maintenance_jobs import build_postgres_maintenance_commands

    cmds = build_postgres_maintenance_commands(vacuum=False, analyze=True, verbose=True, tables=None)
    assert cmds == ["ANALYZE VERBOSE;"]


def test_build_postgres_maintenance_commands_tables_are_validated():
    from app.services.db_maintenance_jobs import build_postgres_maintenance_commands

    with pytest.raises(ValueError):
        build_postgres_maintenance_commands(vacuum=True, analyze=True, verbose=False, tables=["documents; DROP TABLE x;"])

