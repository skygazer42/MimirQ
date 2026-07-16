from app.core.config import settings
from app.services.pipeline_config import resolve_pipeline_options
from app.types.pipeline import PipelineOptions


def test_zero_limit_settings_keep_their_documented_sentinel(monkeypatch) -> None:
    fields = (
        "GOVERNANCE_PII_MAX_HITS",
        "GOVERNANCE_SECRETS_MAX_HITS",
        "TABLE_STORE_MAX_ROWS",
        "TABLE_STORE_MAX_COLS",
        "TABLE_STORE_SAMPLE_ROWS",
    )
    for field in fields:
        monkeypatch.setattr(settings, field, 0)

    effective = resolve_pipeline_options(PipelineOptions())

    assert effective.governance_pii_max_hits == 0
    assert effective.governance_secrets_max_hits == 0
    assert effective.table_store_max_rows == 0
    assert effective.table_store_max_cols == 0
    assert effective.table_store_sample_rows == 0
