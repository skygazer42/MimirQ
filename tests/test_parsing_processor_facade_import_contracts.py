from importlib import import_module

import pytest

from app.parsing.processors import processor

FACADE_EXPORT_SOURCES = (
    ("POSITION_TAG_RE", "app.parsing.artifact_stats", "POSITION_TAG_RE"),
    ("compute_parsing_artifact_stats", "app.parsing.artifact_stats", "compute_parsing_artifact_stats"),
    ("add_chart_data_blocks", "app.parsing.enrich.chart_to_data", "add_chart_data_blocks"),
    ("add_formula_latex_blocks", "app.parsing.enrich.formula_ocr", "add_formula_latex_blocks"),
    ("add_image_captions", "app.parsing.enrich.image_caption", "add_image_captions"),
    ("add_image_code_blocks", "app.parsing.enrich.image_code", "add_image_code_blocks"),
    ("add_vlm_image_captions", "app.parsing.enrich.vlm_image_caption", "add_vlm_image_captions"),
    ("ParsingError", "app.parsing.errors", "ParsingError"),
    ("_apply_inline_asset_audit_patch", "app.parsing.processors.support.assets", "_apply_inline_asset_audit_patch"),
    ("_asset_metadata", "app.parsing.processors.support.assets", "_asset_metadata"),
    ("_chunk_has_asset", "app.parsing.processors.support.assets", "_chunk_has_asset"),
    (
        "_collect_artifact_dir_from_meta",
        "app.parsing.processors.support.assets",
        "_collect_artifact_dir_from_meta",
    ),
    ("_collect_image_ids_from_meta", "app.parsing.processors.support.assets", "_collect_image_ids_from_meta"),
    ("_collect_item_asset_refs", "app.parsing.processors.support.assets", "_collect_item_asset_refs"),
    ("_collect_parser_asset_refs", "app.parsing.processors.support.assets", "_collect_parser_asset_refs"),
    ("_inline_asset_audit_needed", "app.parsing.processors.support.assets", "_inline_asset_audit_needed"),
    (
        "_MERGED_CHUNK_STALE_CONTENT_METADATA_KEYS",
        "app.parsing.processors.support.chunk_postprocess",
        "_MERGED_CHUNK_STALE_CONTENT_METADATA_KEYS",
    ),
    ("_append_unmergeable_chunk", "app.parsing.processors.support.chunk_postprocess", "_append_unmergeable_chunk"),
    ("_build_page_start_offsets", "app.parsing.processors.support.chunk_postprocess", "_build_page_start_offsets"),
    ("_build_page_text_lookup", "app.parsing.processors.support.chunk_postprocess", "_build_page_text_lookup"),
    ("_chunk_asset_indices", "app.parsing.processors.support.chunk_postprocess", "_chunk_asset_indices"),
    ("_chunk_has_record_identity", "app.parsing.processors.support.chunk_postprocess", "_chunk_has_record_identity"),
    ("_chunk_mergeable", "app.parsing.processors.support.chunk_postprocess", "_chunk_mergeable"),
    ("_chunk_page_index", "app.parsing.processors.support.chunk_postprocess", "_chunk_page_index"),
    (
        "_chunk_record_identity_key",
        "app.parsing.processors.support.chunk_postprocess",
        "_chunk_record_identity_key",
    ),
    (
        "_chunks_share_record_identity_boundary",
        "app.parsing.processors.support.chunk_postprocess",
        "_chunks_share_record_identity_boundary",
    ),
    ("_document_page_index", "app.parsing.processors.support.chunk_postprocess", "_document_page_index"),
    ("_ensure_ingest_page_indices", "app.parsing.processors.support.chunk_postprocess", "_ensure_ingest_page_indices"),
    ("_fill_uniform_sample", "app.parsing.processors.support.chunk_postprocess", "_fill_uniform_sample"),
    (
        "_flush_pending_on_page_change",
        "app.parsing.processors.support.chunk_postprocess",
        "_flush_pending_on_page_change",
    ),
    ("_initial_uniform_sample", "app.parsing.processors.support.chunk_postprocess", "_initial_uniform_sample"),
    (
        "_joined_text_total_characters",
        "app.parsing.processors.support.chunk_postprocess",
        "_joined_text_total_characters",
    ),
    ("_local_chunk_range", "app.parsing.processors.support.chunk_postprocess", "_local_chunk_range"),
    (
        "_merge_small_chunks_by_min_chars",
        "app.parsing.processors.support.chunk_postprocess",
        "_merge_small_chunks_by_min_chars",
    ),
    ("_merge_two_small_chunks", "app.parsing.processors.support.chunk_postprocess", "_merge_two_small_chunks"),
    (
        "_merge_with_pending_small_chunk",
        "app.parsing.processors.support.chunk_postprocess",
        "_merge_with_pending_small_chunk",
    ),
    (
        "_rebase_chunk_offsets_by_page_index",
        "app.parsing.processors.support.chunk_postprocess",
        "_rebase_chunk_offsets_by_page_index",
    ),
    (
        "_rebase_single_chunk_offsets",
        "app.parsing.processors.support.chunk_postprocess",
        "_rebase_single_chunk_offsets",
    ),
    (
        "_refresh_merged_chunk_content_metadata",
        "app.parsing.processors.support.chunk_postprocess",
        "_refresh_merged_chunk_content_metadata",
    ),
    ("_retrieval_text_for_merge", "app.parsing.processors.support.chunk_postprocess", "_retrieval_text_for_merge"),
    (
        "_should_skip_near_dedup_for_chunk",
        "app.parsing.processors.support.chunk_postprocess",
        "_should_skip_near_dedup_for_chunk",
    ),
    (
        "_truncate_asset_uniform_chunks",
        "app.parsing.processors.support.chunk_postprocess",
        "_truncate_asset_uniform_chunks",
    ),
    ("_truncate_chunks_for_limit", "app.parsing.processors.support.chunk_postprocess", "_truncate_chunks_for_limit"),
    ("_truncate_head_chunks", "app.parsing.processors.support.chunk_postprocess", "_truncate_head_chunks"),
    (
        "_try_merge_with_previous_chunk",
        "app.parsing.processors.support.chunk_postprocess",
        "_try_merge_with_previous_chunk",
    ),
    ("_uniform_sample_indices", "app.parsing.processors.support.chunk_postprocess", "_uniform_sample_indices"),
    ("REDACTED_MASK", "app.parsing.processors.support.common", "REDACTED_MASK"),
    ("SECRET_MASK", "app.parsing.processors.support.common", "SECRET_MASK"),
    (
        "_attach_logical_source_metadata",
        "app.parsing.processors.support.parse_io",
        "_attach_logical_source_metadata",
    ),
    (
        "_deserialize_documents_from_parse_cache",
        "app.parsing.processors.support.parse_io",
        "_deserialize_documents_from_parse_cache",
    ),
    ("_get_position_tagged_markdown", "app.parsing.processors.support.parse_io", "_get_position_tagged_markdown"),
    ("_join_document_page_content", "app.parsing.processors.support.parse_io", "_join_document_page_content"),
    (
        "_join_original_markdown_for_persistence",
        "app.parsing.processors.support.parse_io",
        "_join_original_markdown_for_persistence",
    ),
    ("_logical_source_from_db_document", "app.parsing.processors.support.parse_io", "_logical_source_from_db_document"),
    (
        "_serialize_documents_for_parse_cache",
        "app.parsing.processors.support.parse_io",
        "_serialize_documents_for_parse_cache",
    ),
    (
        "_append_ocr_quality_candidate",
        "app.parsing.processors.support.quality",
        "_append_ocr_quality_candidate",
    ),
    ("_build_ocr_quality_summary", "app.parsing.processors.support.quality", "_build_ocr_quality_summary"),
    ("_build_seal_summary", "app.parsing.processors.support.quality", "_build_seal_summary"),
    ("_coerce_float", "app.parsing.processors.support.quality", "_coerce_float"),
    ("_coerce_int", "app.parsing.processors.support.quality", "_coerce_int"),
    (
        "_compute_governance_quality_metrics",
        "app.parsing.processors.support.quality",
        "_compute_governance_quality_metrics",
    ),
    ("_format_seal_summary", "app.parsing.processors.support.quality", "_format_seal_summary"),
    (
        "_governance_quality_from_metadata",
        "app.parsing.processors.support.quality",
        "_governance_quality_from_metadata",
    ),
    ("_is_seal_segment_metadata", "app.parsing.processors.support.quality", "_is_seal_segment_metadata"),
    ("_iter_ocr_quality_candidates", "app.parsing.processors.support.quality", "_iter_ocr_quality_candidates"),
    ("_low_confidence_span", "app.parsing.processors.support.quality", "_low_confidence_span"),
    ("_ocr_confidence_from_metadata", "app.parsing.processors.support.quality", "_ocr_confidence_from_metadata"),
    ("_safe_governance_int", "app.parsing.processors.support.quality", "_safe_governance_int"),
    ("_seal_candidate_from_document", "app.parsing.processors.support.quality", "_seal_candidate_from_document"),
    ("_seal_primary_metadata", "app.parsing.processors.support.quality", "_seal_primary_metadata"),
    (
        "_seal_segment_candidate_count",
        "app.parsing.processors.support.quality",
        "_seal_segment_candidate_count",
    ),
    ("_seal_segment_page", "app.parsing.processors.support.quality", "_seal_segment_page"),
    (
        "_seal_summary_to_specialty_signals",
        "app.parsing.processors.support.quality",
        "_seal_summary_to_specialty_signals",
    ),
    ("ChunkAssetOptions", "app.parsing.processors.support.results", "ChunkAssetOptions"),
    ("ChunkAssetResult", "app.parsing.processors.support.results", "ChunkAssetResult"),
    ("ChunkDedupResult", "app.parsing.processors.support.results", "ChunkDedupResult"),
    ("ChunkingResult", "app.parsing.processors.support.results", "ChunkingResult"),
    ("GovernanceResult", "app.parsing.processors.support.results", "GovernanceResult"),
    ("InlineAssetResult", "app.parsing.processors.support.results", "InlineAssetResult"),
    ("ParseResult", "app.parsing.processors.support.results", "ParseResult"),
    ("route_pdf_backend", "app.parsing.routing", "route_pdf_backend"),
    ("should_attempt_pdf_fallback", "app.parsing.routing", "should_attempt_pdf_fallback"),
    ("SubprocessCancelled", "app.parsing.subprocess_runner", "SubprocessCancelled"),
    ("run_parser_subprocess", "app.parsing.subprocess_runner", "run_parser_subprocess"),
    ("classify_chunk_semantic_role", "app.rag.chunking.roles", "classify_chunk_semantic_role"),
    ("classify_chunk_type", "app.rag.chunking.roles", "classify_chunk_type"),
    ("SeparatorChunker", "app.rag.chunking.strategies", "SeparatorChunker"),
    (
        "apply_sequence_hierarchy_metadata",
        "app.rag.chunking.utils.hierarchical",
        "apply_sequence_hierarchy_metadata",
    ),
    (
        "ensure_hierarchy_overlay_metadata",
        "app.rag.core.metadata",
        "ensure_hierarchy_overlay_metadata",
    ),
    ("infer_chunk_structure", "app.rag.core.metadata", "infer_chunk_structure"),
    ("normalize_image_metadata", "app.rag.core.metadata", "normalize_image_metadata"),
    ("normalize_section_metadata", "app.rag.core.metadata", "normalize_section_metadata"),
    ("apply_chunk_python_plugin", "app.rag.pipeline_plugins.runtime", "apply_chunk_python_plugin"),
    ("apply_governance_python_plugin", "app.rag.pipeline_plugins.runtime", "apply_governance_python_plugin"),
    ("canonicalize_markdown", "app.rag.preprocessing.markdown_canonical", "canonicalize_markdown"),
    ("governance_processor", "app.rag.preprocessing.processor", "governance_processor"),
    ("RemoteParseCacheEntry", "app.services.parse_cache", "ParseCacheEntry"),
    ("build_remote_parse_cache_key", "app.services.parse_cache", "build_parse_cache_key"),
    ("parse_cache_service", "app.services.parse_cache", "parse_cache_service"),
    ("compute_document_analytics", "app.types.document_analytics", "compute_document_analytics"),
)

SEAM_EXPORT_SOURCES = (
    ("CheckpointedRetryRequiredError", "app.parsing.processors.support.recovery", "CheckpointedRetryRequiredError"),
    ("ChunkAssetStage", "app.parsing.processors.support.stages", "ChunkAssetStage"),
    ("ChunkDedupStage", "app.parsing.processors.support.stages", "ChunkDedupStage"),
    ("ChunkingStage", "app.parsing.processors.support.stages", "ChunkingStage"),
    ("DocumentChunk", "app.models.document", "DocumentChunk"),
    ("DocumentParsedContent", "app.models.document", "DocumentParsedContent"),
    ("GovernanceStage", "app.parsing.processors.support.stages", "GovernanceStage"),
    ("Indexer", "app.services.indexer", "Indexer"),
    ("NormalizeStage", "app.parsing.processors.support.stages", "NormalizeStage"),
    ("ParsingStage", "app.parsing.processors.support.stages", "ParsingStage"),
    ("_indexed_checkpoint_is_reusable", "app.parsing.processors.support.recovery", "indexed_checkpoint_is_reusable"),
    ("_parsed_checkpoint_is_reusable", "app.parsing.processors.support.recovery", "parsed_checkpoint_is_reusable"),
    ("build_indexing_options", "app.services.pipeline_config", "build_indexing_options"),
    ("log_metrics", "app.services.metrics_logger", "log_metrics"),
    ("maybe_enrich_document_questions", "app.parsing.processors.support.recovery", "maybe_enrich_document_questions"),
    ("metrics_span", "app.services.metrics_logger", "metrics_span"),
    ("resolve_pipeline_effective", "app.services.pipeline_config", "resolve_pipeline_effective"),
    ("run_post_completion_kg", "app.parsing.processors.support.recovery", "run_post_completion_kg"),
)


@pytest.mark.parametrize(("name", "module_name", "attr_name"), FACADE_EXPORT_SOURCES + SEAM_EXPORT_SOURCES)
def test_processor_facade_reexports_expected_symbols(name: str, module_name: str, attr_name: str) -> None:
    expected = getattr(import_module(module_name), attr_name)
    assert getattr(processor, name) is expected
    assert name in processor.__all__


def test_processor_facade_keeps_public_service_exports_and_import_side_effects() -> None:
    assert isinstance(processor.document_processor, processor.DocumentProcessorService)

    for name in (
        "AUDIT_ACTION_DOCUMENT_QUARANTINE",
        "DocumentProcessorService",
        "IndexStage",
        "LOG_DOC_ID_FMT",
        "RetryCleanupStatus",
        "document_processor",
    ):
        assert name in processor.__all__
        assert hasattr(processor, name)
