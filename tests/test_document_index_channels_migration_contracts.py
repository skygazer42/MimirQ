from contextlib import nullcontext
from importlib import util
from pathlib import Path


def _load_migration():
    migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "0027_add_document_index_channels.py"
    spec = util.spec_from_file_location("mimirq_document_index_channels_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_document_index_channels_migration_applies_table_and_indexes(monkeypatch) -> None:
    migration = _load_migration()
    operations: list[tuple[str, str, list]] = []

    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: type("Binding", (), {"dialect": type("Dialect", (), {"name": "postgresql"})})(),
        raising=False,
    )
    monkeypatch.setattr(
        migration.op,
        "get_context",
        lambda: type("Context", (), {"autocommit_block": lambda: nullcontext()})(),
        raising=False,
    )
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda name, *cols, **kwargs: operations.append(("create_table", name, [c for c in cols])),
        raising=False,
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, table, columns, **kwargs: operations.append(("create_index", name, [table, list(columns)])),
        raising=False,
    )
    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, **kwargs: operations.append(("drop_index", name, [])),
        raising=False,
    )
    monkeypatch.setattr(migration.op, "drop_table", lambda name: operations.append(("drop_table", name, [])), raising=False)

    migration.upgrade()
    migration.downgrade()

    create_ops = [op for op in operations if op[0] == "create_table"]
    assert len(create_ops) == 1
    assert create_ops[0][1] == "document_index_channels"

    create_index_ops = [op[1] for op in operations if op[0] == "create_index"]
    assert create_index_ops == [
        "ix_document_index_channels_tenant_id",
        "ix_document_index_channels_dataset_id",
        "ix_document_index_channels_document_id",
        "ix_document_index_channels_status",
        "ix_document_index_channels_tenant_document",
        "ix_document_index_channels_tenant_dataset",
        "ix_document_index_channels_tenant_status",
    ]

    drop_ops = [op for op in operations if op[0] == "drop_index"]
    assert {op[1] for op in drop_ops} == set(create_index_ops)
    assert ("drop_table", "document_index_channels", []) in operations


def test_document_index_channels_revision_chain_contiguous() -> None:
    migration = _load_migration()
    assert migration.down_revision == "0026_add_index_drift_items"
