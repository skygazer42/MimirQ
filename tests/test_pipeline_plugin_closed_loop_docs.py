from __future__ import annotations

from pathlib import Path


def test_pipeline_plugin_guide_documents_live_golden_closed_loop_smoke() -> None:
    text = Path("docs/guides/pipeline_plugins.md").read_text(encoding="utf-8")

    assert "# Pipeline Plugins" in text
    assert "registered plugin packages" in text
    assert "# Pipeline Business Plugins" not in text
    assert "scripts/plugin_golden_closed_loop_smoke.py" in text
    assert "scripts/plugin_corpus_closed_loop_smoke.py" in text
    assert "--source-dir" in text
    assert "scripts/regression_gate.py" in text
    assert "--plugin-golden-ref" in text
    assert "`--plugin-golden-ref` must be a registered `plugin:<id>@<version>:chunk` ref" in text
    assert "Golden import does not accept governance/KG refs or ad-hoc Python import paths" in text
    assert "--dataset-id" in text
    assert "POST /api/v1/pipeline/plugins/golden-draft/import" in text
    assert "POST /api/v1/evaluations/ragas/regression/runs" in text
    assert "expected_metadata_hit_rate" in text
    assert "expected_metadata_recall" in text
    assert "run_id" in text
    assert "case_source" in text
    assert "thresholds case_source" in text
    assert "PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS" in text
    assert "only chunks produced by the selected plugin" in text
    assert "plugin_package_hash" in text
    assert "plugin package hash" in text
    assert "plugin_source" in text
    assert "/evaluations?tab=regression" in text
    assert "If the selected plugin manifest exposes `refs.kg`" in text
    assert "passes `kg_python_plugin` and enables KG/event/entity indexing" in text
    assert "activation refs still come from plugin `refs`" in text
    assert "append `--stage kg`" in text


def test_generic_plugin_closed_loop_docs_do_not_embed_business_plugin_defaults() -> None:
    texts = [
        Path("docs/guides/pipeline_plugins.md").read_text(encoding="utf-8"),
        Path("docs/guides/manual_kg_import.md").read_text(encoding="utf-8"),
        Path("scripts/README.md").read_text(encoding="utf-8"),
    ]

    for text in texts:
        assert "changzhou-gov-service-knowledge" not in text
        assert "20260522政务服务智能客服知识" not in text
        assert "gov-service-items" not in text
        assert "常州政务事项图谱" not in text
        assert "district:cz" not in text
        assert "business-knowledge-demo" not in text
        assert "/path/to/business-corpus" not in text


def test_plugin_guide_does_not_document_implicit_golden_business_field_defaults() -> None:
    text = Path("docs/guides/pipeline_plugins.md").read_text(encoding="utf-8")

    assert "MimirQ only uses generic defaults" not in text
    assert "dataset_type` for template selection" not in text
    assert "for tags); business-specific fields belong" not in text
    assert "`expected_metadata`, `template_selector_fields`, and `tag_fields` must be arrays" in text
    assert "`expected_metadata` is required for executable Golden plugins" in text
    assert "must declare\nat least one field" in text
    assert "`expected_metadata`, `template_selector_fields`, and `tag_fields` entries must be JSON strings" in text
    assert "Fields listed in `expected_metadata` must also set `evaluable: true`" in text
    assert "Golden draft generation and regression scoring read plugin-owned expectations" in text
    assert "from `_evaluable_metadata` instead of guessing raw business metadata fields" in text
    assert "`query_templates` must be an object" in text
    assert "`query_templates.<bucket>` must be an array of JSON strings" in text


def test_plugin_guide_documents_suggested_patch_as_validated_pipeline_options() -> None:
    text = Path("docs/guides/pipeline_plugins.md").read_text(encoding="utf-8")

    assert "suggested_pipeline_patch" in text
    assert "DocumentPipelineOptions" in text
    assert "unknown top-level keys are rejected" in text
    assert "exported through the narrower `PipelinePluginSuggestedPatch` API schema" in text
    assert "`governance_enabled`, `persist_parsed_content`, `governance_python_params`, `chunk_python_params`, and `kg_python_params`" in text
    assert "must not set `governance_python_plugin`, `chunk_python_plugin`, or `kg_python_plugin`" in text
    assert "activation refs come only from plugin manifest `refs`" in text
    assert "activation refs are injected or derived from the selected plugin" not in text
    assert "does not derive governance refs from chunk refs" in text
    assert "`--pipeline-patch-json` cannot carry activation refs either" in text
    assert "must not set platform strategy fields" in text
    assert "`chunk_size`, `chunk_overlap`, `chunk_merge_small_min_chars`, or `chunk_strategy_params`" in text
    assert "built-in `governance_*` knobs" in text
    assert "`governance_python_params`, `chunk_python_params`, or `kg_python_params` so the platform stores" in text
    assert "governance_python_params" in text
    assert "chunk_python_params" in text
    assert "may be\nsuggested only when the plugin manifest declares the matching `governance`" in text
    assert "`chunk`, or `kg` entry stage" in text
    assert "`governance_python_params`, `chunk_python_params`, and `kg_python_params` may be suggested only for small primitive plugin knobs" in text
    assert "All three python params objects are limited to small JSON primitive values" in text
    assert "`kg_python_plugin` registered refs must target the `kg` stage" in text
    assert "registered plugin refs must target the same stage as the API field" in text
    assert "Legacy Python import refs are disabled by default" in text
    assert "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES" in text
    assert "`governance_python_plugin` uses" in text
    assert "`chunk_python_plugin` uses" in text


def test_plugin_guide_documents_supported_contract_stage_names() -> None:
    text = Path("docs/guides/pipeline_plugins.md").read_text(encoding="utf-8")

    assert "Contract stage names are `governance`, `chunk`, and `kg`" in text
    assert "KG event contract fields should use `metadata.*`, `references.*`, or `extra_data.*` paths" in text
    assert "KG metadata fields must start with `metadata.`, `references.`, or `extra_data.`" in text
    assert "KG event `metadata` must not contain reserved platform metadata view keys" in text
    assert "`_retrieval_text`, or `_retrieval_display_content`" in text
    assert "KG event metadata containing reserved platform view keys is rejected" in text
    assert "`retrieval_text_schema.stages` only supports `governance` and `chunk`" in text
    assert "`metadata_schema.fields[]` entries must be objects" in text
    assert "`metadata_schema.fields[]` entries are closed contracts" in text
    assert "`metadata_schema.fields[].name` must be a JSON string" in text
    assert "`metadata_schema.fields[].name` must not start with `_`" in text
    assert "KG metadata subpaths such as `metadata._record_identity` are also rejected" in text
    assert "`source`, `document_id`, `chunk_id`, `dataset_id`, `parser_backend`, and `resolved_chunk_strategy`" in text
    assert "platform-owned metadata field names" in text
    assert "`metadata_schema.fields[].stages`" in text
    assert "`retrieval_text_schema.stages`" in text
    assert "`retrieval_text_schema.stages.<stage>` must be an object" in text
    assert "`retrieval_text_schema.stages.<stage>` entries are closed contracts" in text
    assert "`retrieval_text_schema.stages.<stage>.fields[]` entries must be objects" in text
    assert "`retrieval_text_schema.stages.<stage>.fields[]` entries are closed contracts" in text
    assert "`retrieval_text_schema.stages.<stage>.fields[]` entries must set `metadata` or `content: true`" in text
    assert "`retrieval_text_schema.stages.<stage>.fields[].metadata` must be a JSON string" in text
    assert "`retrieval_text_schema.stages.<stage>.fields[].content` must be a JSON boolean" in text
    assert "`record_identity` must be an array" in text
    assert "`record_identity` entries must be JSON strings" in text
    assert "`required`, `filterable`, `display`, and `evaluable` must be JSON booleans" in text
    assert "`max_length` must be a JSON integer" in text
    assert "`enum` must be an array" in text


def test_plugin_guide_documents_entries_are_plugin_local() -> None:
    text = Path("docs/guides/pipeline_plugins.md").read_text(encoding="utf-8")

    assert "Entry modules must resolve inside the plugin directory" in text
    assert "Entry targets must be strings" in text
    assert "Entry callable names must be single Python identifiers" in text
    assert "Entry stages are limited to `governance`, `chunk`, and `kg`" in text
    assert "Do not point entries at `app.*` platform modules" in text
    assert "Do not use platform top-level names such as `app/`, `scripts/`, or `tests/`" in text
    assert "Plugin Python source files must not import MimirQ platform modules such as `app.*`" in text
    assert "Use plugin-local helpers or stable third-party dependencies instead" in text


def test_plugin_guide_documents_manifest_top_level_field_boundary() -> None:
    text = Path("docs/guides/pipeline_plugins.md").read_text(encoding="utf-8")

    assert "Manifest top-level fields are a closed platform contract" in text
    assert "Do not add business-specific top-level fields" in text
    assert "Contract file fields must be non-empty relative paths" in text
    assert "Contract file fields must be strings" in text
    assert "Contract JSON top-level fields are closed platform contracts" in text
    assert "Do not add business-specific top-level fields to `metadata_schema.json`, `retrieval_text_schema.json`, `golden_rules.json`, or `processing_templates.json`" in text
    assert "`processing_templates.json` is a plugin-owned template provenance contract" in text
    assert "`processing_templates.templates[].key` is plugin-local" in text
    assert "must not collide with platform built-in processing script keys" in text
    assert "`processing_templates.templates[].implemented_by` must be a plugin-local symbol ref" in text
    assert "`processing_templates.templates[].related_implementations[]` must also be plugin-local" in text
    assert "The referenced symbol must exist in that plugin file" in text
    assert "does not copy those" in text


def test_plugin_guide_uses_neutral_example_metadata_field_names() -> None:
    text = Path("docs/guides/pipeline_plugins.md").read_text(encoding="utf-8")

    assert "source_record_id" not in text
    assert "chunk_kind" not in text
    assert "knowledge_type" not in text


def test_scripts_readme_indexes_plugin_golden_closed_loop_smoke() -> None:
    text = Path("scripts/README.md").read_text(encoding="utf-8")

    assert "plugin_golden_closed_loop_smoke.py" in text
    assert "Golden import + retrieval-only regression" in text
    assert "plugin_corpus_closed_loop_smoke.py" in text
    assert "plugin-backed corpus ingest + Golden regression" in text
    assert "regression_gate.py" in text
    assert "--plugin-golden-ref" in text
