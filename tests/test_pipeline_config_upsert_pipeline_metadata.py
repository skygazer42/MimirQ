from app.services.pipeline_config import upsert_pipeline_metadata
from app.types.pipeline import PipelineOptions


def test_upsert_pipeline_metadata_sets_and_clears():
    meta: dict = {}

    changed = upsert_pipeline_metadata(meta, options=PipelineOptions(governance_enabled=True))
    assert changed is True
    assert isinstance(meta.get("pipeline"), dict)

    changed2 = upsert_pipeline_metadata(meta, options=PipelineOptions())
    assert changed2 is True
    assert "pipeline" not in meta


def test_upsert_pipeline_metadata_noop_when_options_none():
    meta: dict = {"pipeline": {"governance_enabled": True}}
    changed = upsert_pipeline_metadata(meta, options=None)
    assert changed is False
    assert meta["pipeline"]["governance_enabled"] is True

