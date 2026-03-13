from __future__ import annotations


def test_infer_schema_relationships_detects_fk_id_pair() -> None:
    from app.services.table_tag_service import infer_schema_relationships_for_tables

    rels = infer_schema_relationships_for_tables(
        tables=[
            {
                "table_name": "sheet_0",
                "table_aliases": ["orders"],
                "columns": [{"name": "order_id", "dtype": "int"}, {"name": "user_id", "dtype": "int"}],
            },
            {
                "table_name": "sheet_1",
                "table_aliases": ["users"],
                "columns": [{"name": "id", "dtype": "int"}, {"name": "region", "dtype": "text"}],
            },
        ]
    )

    assert len(rels) == 1
    r0 = rels[0]
    assert str(r0.get("left_table") or "") == "sheet_0"
    assert str(r0.get("left_column") or "") == "user_id"
    assert str(r0.get("right_table") or "") == "sheet_1"
    assert str(r0.get("right_column") or "") == "id"
    assert float(r0.get("confidence") or 0.0) > 0.0
    assert str(r0.get("reason") or "")


def test_infer_schema_relationships_ignores_non_key_overlap() -> None:
    from app.services.table_tag_service import infer_schema_relationships_for_tables

    rels = infer_schema_relationships_for_tables(
        tables=[
            {
                "table_name": "sheet_0",
                "table_aliases": ["orders"],
                "columns": [{"name": "amount", "dtype": "float"}, {"name": "status", "dtype": "text"}],
            },
            {
                "table_name": "sheet_1",
                "table_aliases": ["events"],
                "columns": [{"name": "event_time", "dtype": "text"}, {"name": "status", "dtype": "text"}],
            },
        ]
    )

    assert rels == []
