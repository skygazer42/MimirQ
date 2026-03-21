from __future__ import annotations

from app.services.pipeline_config import build_pipeline_metadata, parse_pipeline_from_metadata, resolve_pipeline_options
from app.types.pipeline import PipelineOptions


def test_pipeline_metadata_roundtrip_parsing_optimization_fields() -> None:
    opts = PipelineOptions(
        cross_page_merge_enabled=True,
        cross_page_merge_max_page_gap=2,
        reading_order_enabled=True,
        parse_cache_enabled=True,
        parse_cache_ttl_sec=1800,
        vlm_correction_enabled=True,
        vlm_correction_min_table_score=0.55,
        vlm_correction_max_pages=3,
    )

    meta = build_pipeline_metadata(opts)
    parsed = parse_pipeline_from_metadata({"pipeline": meta})

    assert parsed.cross_page_merge_enabled is True
    assert parsed.cross_page_merge_max_page_gap == 2
    assert parsed.reading_order_enabled is True
    assert parsed.parse_cache_enabled is True
    assert parsed.parse_cache_ttl_sec == 1800
    assert parsed.vlm_correction_enabled is True
    assert parsed.vlm_correction_min_table_score == 0.55
    assert parsed.vlm_correction_max_pages == 3


def test_resolve_pipeline_options_uses_parsing_optimization_overrides() -> None:
    eff = resolve_pipeline_options(
        PipelineOptions(
            cross_page_merge_enabled=True,
            cross_page_merge_max_page_gap=2,
            reading_order_enabled=True,
            parse_cache_enabled=True,
            parse_cache_ttl_sec=120,
            vlm_correction_enabled=True,
            vlm_correction_min_table_score=0.45,
            vlm_correction_max_pages=4,
        )
    )

    assert eff.cross_page_merge_enabled is True
    assert eff.cross_page_merge_max_page_gap == 2
    assert eff.reading_order_enabled is True
    assert eff.parse_cache_enabled is True
    assert eff.parse_cache_ttl_sec == 120
    assert eff.vlm_correction_enabled is True
    assert eff.vlm_correction_min_table_score == 0.45
    assert eff.vlm_correction_max_pages == 4
