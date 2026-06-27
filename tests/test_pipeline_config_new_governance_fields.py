from app.services.pipeline_config import build_pipeline_metadata, parse_pipeline_from_metadata, resolve_pipeline_options
from app.types.pipeline import PipelineOptions


def test_pipeline_metadata_roundtrip_new_governance_fields():
    opts = PipelineOptions(
        governance_extract_frontmatter=True,
        governance_strip_frontmatter=True,
        governance_detect_language=True,
        governance_language_min_chars=50,
        governance_normalize_urls=True,
        governance_normalize_urls_strip_tracking=False,
        governance_drop_duplicate_paragraphs=True,
        governance_drop_duplicate_paragraphs_min_occurrences=4,
        governance_drop_duplicate_paragraphs_min_chars=10,
        governance_drop_duplicate_paragraphs_max_chars=2000,
        governance_trim_references=True,
        governance_extract_keywords=True,
        governance_keywords_provider="simple",
        governance_keywords_top_k=12,
        governance_keywords_max_chars=12345,
        governance_quarantine_on_drop=True,
        governance_llm_auto_tagging_enabled=True,
        governance_llm_auto_tagging_max_chars=4096,
        governance_llm_auto_tagging_max_items=12,
        ingest_pre_poc_scanner_enabled=True,
        ingest_pre_poc_quality_gate_mode="strict",
    )
    meta = build_pipeline_metadata(opts)
    parsed = parse_pipeline_from_metadata({"pipeline": meta})

    assert parsed.governance_extract_frontmatter is True
    assert parsed.governance_strip_frontmatter is True
    assert parsed.governance_detect_language is True
    assert parsed.governance_language_min_chars == 50
    assert parsed.governance_normalize_urls is True
    assert parsed.governance_normalize_urls_strip_tracking is False
    assert parsed.governance_drop_duplicate_paragraphs is True
    assert parsed.governance_drop_duplicate_paragraphs_min_occurrences == 4
    assert parsed.governance_drop_duplicate_paragraphs_min_chars == 10
    assert parsed.governance_drop_duplicate_paragraphs_max_chars == 2000
    assert parsed.governance_trim_references is True
    assert parsed.governance_extract_keywords is True
    assert parsed.governance_keywords_provider == "simple"
    assert parsed.governance_keywords_top_k == 12
    assert parsed.governance_keywords_max_chars == 12345
    assert parsed.governance_quarantine_on_drop is True
    assert parsed.governance_llm_auto_tagging_enabled is True
    assert parsed.governance_llm_auto_tagging_max_chars == 4096
    assert parsed.governance_llm_auto_tagging_max_items == 12
    assert parsed.ingest_pre_poc_scanner_enabled is True
    assert parsed.ingest_pre_poc_quality_gate_mode == "strict"


def test_resolve_pipeline_options_uses_overrides_for_new_fields():
    eff = resolve_pipeline_options(
        PipelineOptions(
            governance_extract_frontmatter=True,
            governance_keywords_provider="simple",
            governance_quarantine_on_drop=True,
            governance_llm_auto_tagging_enabled=True,
            governance_llm_auto_tagging_max_chars=4096,
            governance_llm_auto_tagging_max_items=12,
            ingest_pre_poc_scanner_enabled=True,
            ingest_pre_poc_quality_gate_mode="strict",
        )
    )
    assert eff.governance_extract_frontmatter is True
    assert eff.governance_keywords_provider == "simple"
    assert eff.governance_quarantine_on_drop is True
    assert eff.governance_llm_auto_tagging_enabled is True
    assert eff.governance_llm_auto_tagging_max_chars == 4096
    assert eff.governance_llm_auto_tagging_max_items == 12
    assert eff.ingest_pre_poc_scanner_enabled is True
    assert eff.ingest_pre_poc_quality_gate_mode == "strict"


def test_resolve_pipeline_options_normalizes_invalid_pre_poc_gate_mode():
    eff = resolve_pipeline_options(
        PipelineOptions(
            ingest_pre_poc_scanner_enabled=True,
            ingest_pre_poc_quality_gate_mode="delete-everything",
        )
    )

    assert eff.ingest_pre_poc_scanner_enabled is True
    assert eff.ingest_pre_poc_quality_gate_mode == "warn"
