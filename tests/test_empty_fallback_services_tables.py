from uuid import uuid4

import pytest

from app.services import chat_tag_service, table_store_service, table_tag_service


def candidate(sheet_name=None):
    return chat_tag_service._TableCandidate(
        document_id=uuid4(), dataset_id=uuid4(), filename="table.csv", file_type="csv", source_ext=None,
        table_id="table-id", sheet_index=0, sheet_name=sheet_name, row_count=0, col_count=1,
        columns=[{"name": "amount", "dtype": "int64"}], sample_rows=[], row_source_table=None,
        row_source_sync_token=None, row_source_pk_hash_col=None, score=0,
    )


@pytest.mark.parametrize("column,error", [({}, KeyError), ({"name": 0}, AttributeError), ({"name": None}, AttributeError)])
def test_sql_generation_requires_the_column_names_emitted_by_table_producers(column, error, monkeypatch):
    monkeypatch.setattr(table_tag_service.settings, "TABLE_NL2SQL_DETERMINISTIC_ONLY", True)
    with pytest.raises(error):
        table_tag_service.generate_sql_for_table_with_metadata(
            question="count rows", sql_table="sheet_0", columns=[column], max_rows=10,
        )


def test_numeric_column_classification_keeps_unknown_type_distinct_from_invalid_zero():
    assert table_tag_service._column_is_numeric({"name": "amount", "dtype": None}) is False
    with pytest.raises(AttributeError):
        table_tag_service._column_is_numeric({"name": "amount", "dtype": 0})


def test_missing_sheet_name_does_not_create_an_empty_table_alias():
    inputs, _ = chat_tag_service._join_inputs_for_candidates([candidate()])
    assert inputs[0]["table_aliases"] == ["table-id", "table.csv"]


def test_invalid_supplied_sheet_name_is_not_ignored():
    with pytest.raises(AttributeError):
        chat_tag_service._join_inputs_for_candidates([candidate(0)])


def test_snapshot_column_label_zero_is_not_discarded():
    assert table_store_service._db_snapshot_column_names({"columns": [0]}, max_cols=10) == ["0"]


def test_planner_metadata_does_not_invent_an_empty_fingerprint():
    _, _, fingerprint = chat_tag_service._sql_plan_metadata({}, schema_link_diagnostics={})
    assert fingerprint is None
