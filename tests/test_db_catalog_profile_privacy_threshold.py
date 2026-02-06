from __future__ import annotations

import uuid


def test_sanitize_db_profile_snapshot_small_table_drops_sensitive_fields():
    from app.connectors.db.profile_privacy import sanitize_db_profile_snapshot  # noqa: WPS433

    raw = {
        "row_count_estimate": 10,
        "sample_values": ["a", "b"],
        "top_values": [{"value": "x", "count": 5}],
        "min": "secret-min",
        "max": "secret-max",
        "distinct_count_estimate": 2,
    }
    assert sanitize_db_profile_snapshot(raw, min_rows=50) == {"row_count_estimate": 10}


def test_catalog_store_insert_profile_snapshot_applies_privacy_sanitization():
    from app.connectors.db.catalog_store_sqlalchemy import SqlAlchemyCatalogStore  # noqa: WPS433

    class DummySnapshot:
        def __init__(self, **kwargs):  # noqa: ANN001
            self.kwargs = kwargs
            self.id = uuid.uuid4()

    class DummyDB:
        def __init__(self):
            self.added = []

        def add(self, obj):  # noqa: ANN001
            self.added.append(obj)

        def flush(self) -> None:
            return None

    import app.connectors.db.catalog_store_sqlalchemy as store_module

    db = DummyDB()
    store = SqlAlchemyCatalogStore(db=db)  # type: ignore[arg-type]

    store_module.DbProfileSnapshot = DummySnapshot  # type: ignore[assignment]

    store.insert_profile_snapshot(
        table_id=uuid.uuid4(),
        entitlement_hash="ent",
        profile={"row_count_estimate": 10, "sample_values": ["x"]},
        sample_meta={"strategy": "x"},
    )

    assert db.added
    snap = db.added[0]
    assert snap.kwargs["profile"] == {"row_count_estimate": 10}

