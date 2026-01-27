from app.services.pipeline_config import build_pipeline_metadata, parse_pipeline_from_metadata, resolve_pipeline_options
from app.types.pipeline import PipelineOptions


def test_pipeline_metadata_roundtrip_table_auto_fields():
    opts = PipelineOptions(
        table_store_enabled=True,
        table_store_max_rows=123,
        table_store_max_cols=45,
        table_store_sample_rows=6,
        table_store_auto_route=True,
        table_store_auto_row_threshold=5001,
        table_store_auto_col_threshold=81,
        table_store_auto_sheet_threshold=7,
        table_store_auto_file_bytes_threshold=9000000,
    )
    meta = build_pipeline_metadata(opts)
    parsed = parse_pipeline_from_metadata({"pipeline": meta})

    assert parsed.table_store_enabled is True
    assert parsed.table_store_max_rows == 123
    assert parsed.table_store_max_cols == 45
    assert parsed.table_store_sample_rows == 6
    assert parsed.table_store_auto_route is True
    assert parsed.table_store_auto_row_threshold == 5001
    assert parsed.table_store_auto_col_threshold == 81
    assert parsed.table_store_auto_sheet_threshold == 7
    assert parsed.table_store_auto_file_bytes_threshold == 9000000


def test_resolve_pipeline_options_uses_overrides_for_table_auto_fields():
    eff = resolve_pipeline_options(
        PipelineOptions(
            table_store_enabled=True,
            table_store_auto_route=True,
            table_store_auto_row_threshold=111,
            table_store_auto_col_threshold=22,
            table_store_auto_sheet_threshold=3,
            table_store_auto_file_bytes_threshold=4444,
        )
    )
    assert eff.table_store_enabled is True
    assert eff.table_store_auto_route is True
    assert eff.table_store_auto_row_threshold == 111
    assert eff.table_store_auto_col_threshold == 22
    assert eff.table_store_auto_sheet_threshold == 3
    assert eff.table_store_auto_file_bytes_threshold == 4444

