from __future__ import annotations

from pathlib import Path


def test_generic_pipeline_plugin_runtime_tests_do_not_embed_business_plugin() -> None:
    text = Path("tests/test_python_pipeline_plugins.py").read_text(encoding="utf-8")

    for forbidden in (
        "changzhou-gov-service-knowledge",
        "20260522政务服务智能客服知识",
        "常州",
        "经开",
        "天宁",
        "新北",
        "经开区",
        "天宁区",
        "新北区",
        "社会保障卡",
        "就业创业证",
        "government_service",
        "苏服办",
        "0519-",
    ):
        assert forbidden not in text


def test_platform_surfaces_do_not_embed_changzhou_plugin_defaults() -> None:
    roots = [Path("app"), Path("scripts"), Path("tests"), Path("web"), Path("docs")]
    allowed_files = {
        Path("tests/test_changzhou_gov_service_knowledge_plugin.py"),
        Path("tests/test_builtin_prompt_library.py"),
        Path("tests/test_dify_external_knowledge_adapter.py"),
        Path("tests/test_external_conversation_ingest.py"),
        Path("tests/test_governance_profile_validation.py"),
        Path("tests/test_lexical_db_primary_keyword_mode.py"),
        Path("tests/test_pipeline_plugin_boundary.py"),
        Path("tests/test_pipeline_plugin_closed_loop_docs.py"),
        Path("tests/test_plugin_corpus_closed_loop_smoke.py"),
        Path("tests/test_plugin_corpus_closed_loop_evidence.py"),
        Path("tests/test_ragas_conversation_deterministic_eval.py"),
        Path("web/components/chunk-preview/components/workbench/sidebar-client.messages.source.test.ts"),
        Path("web/e2e/chunk-preview-plugin-readiness.spec.ts"),
        Path("docs/plans/2026-06-08-rag-retrieval-quality-closed-loop.md"),
        Path("docs/plans/2026-06-09-rag-platform-design-optimization-plan.md"),
    }
    ignored_parts = {
        "__pycache__",
        "deepdoc/resources",
        "web/public",
    }
    checked_suffixes = {".py", ".ts", ".tsx", ".md", ".json", ".yaml", ".yml"}
    forbidden_terms = (
        "changzhou-gov-service-knowledge",
        "20260522政务服务智能客服知识",
        "政务服务事项知识",
        "高效办成一件事",
        "/data/temp50/政务服务",
        "常州政务事项图谱",
        "district:cz",
        "jingkai",
        "xinbei",
        "常州",
        "经开区",
        "天宁区",
        "新北区",
        "苏服办",
        "社会保障卡",
        "就业创业证",
        "事项清单.txt",
        "服务事项内容",
        "government_service",
        "app.rag.pipeline_plugins.gov_service_items",
        "max_record_chars",
        "NUMBERED_SECTION_ROOT_RE",
        "BUSINESS_SECTION_ROOT_RE",
    )

    leaks: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in checked_suffixes:
                continue
            rel = path.relative_to(Path.cwd()) if path.is_absolute() else path
            rel_text = rel.as_posix()
            if rel in allowed_files:
                continue
            if (
                rel_text.startswith("scripts/changzhou_gov_")
                or rel_text.startswith("tests/test_changzhou_gov_")
                or rel_text.startswith("docs/deployment/changzhou_")
            ):
                continue
            if any(part in rel_text for part in ignored_parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for term in forbidden_terms:
                if term in text:
                    leaks.append(f"{rel_text}: {term}")

    assert leaks == []


def test_dify_adapter_reuses_pipeline_contract_metadata_view_keys() -> None:
    text = Path("app/api/v1/integrations_dify.py").read_text(encoding="utf-8")

    assert "from app.rag.pipeline_plugins.contracts import" in text
    assert "INDEXED_METADATA_KEY" in text
    assert "DISPLAY_METADATA_KEY" in text
    assert "EVALUABLE_METADATA_KEY" in text
    assert '_PUBLIC_METADATA_VIEW_KEYS = ("_evaluable_metadata", "_display_metadata")' not in text
    assert '_RETRIEVAL_METADATA_VIEW_KEYS = ("_indexed_metadata", *_PUBLIC_METADATA_VIEW_KEYS)' not in text


def test_core_retrieval_modules_reuse_pipeline_contract_metadata_view_keys() -> None:
    files = [
        Path("app/rag/retriever.py"),
        Path("app/rag/core/filters.py"),
    ]

    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "from app.rag.pipeline_plugins.contracts import" in text
        if path.name == "retriever.py":
            assert "METADATA_SCHEMA_VIEW_KEYS" in text
            assert "_PLATFORM_METADATA_VIEW_KEYS = (" not in text
        assert '_INDEXED_METADATA_KEY = "_indexed_metadata"' not in text
        assert '_DISPLAY_METADATA_KEY = "_display_metadata"' not in text
        assert '_EVALUABLE_METADATA_KEY = "_evaluable_metadata"' not in text


def test_vector_storage_reuses_pipeline_contract_indexed_metadata_key() -> None:
    text = Path("app/storage/vector/milvus.py").read_text(encoding="utf-8")

    assert "from app.rag.pipeline_plugins.contracts import INDEXED_METADATA_KEY" in text
    assert '_INDEXED_METADATA_VIEW_KEY = "_indexed_metadata"' not in text


def test_evaluation_modules_reuse_pipeline_contract_metadata_view_keys() -> None:
    files = [
        Path("app/rag/evaluation/regression_sample_builder.py"),
        Path("app/rag/evaluation/ragas.py"),
    ]

    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "from app.rag.pipeline_plugins.contracts import" in text
        assert '"_evaluable_metadata",' not in text
        assert '"_indexed_metadata",' not in text
        assert '"_display_metadata",' not in text
        assert '"_record_identity",' not in text


def test_golden_draft_builder_uses_declared_plugin_fields_not_business_defaults() -> None:
    text = Path("app/rag/pipeline_plugins/golden_drafts.py").read_text(encoding="utf-8")

    for forbidden in (
        "gov_knowledge_type",
        '"chunk_kind"',
        '"knowledge_type"',
        '"dataset_type"',
        "_DEFAULT_TEMPLATE_SELECTOR_FIELDS",
        "_DEFAULT_TAG_FIELDS",
    ):
        assert forbidden not in text


def test_kg_runtime_does_not_embed_plugin_reference_field_defaults() -> None:
    text = Path("app/rag/pipeline_plugins/runtime.py").read_text(encoding="utf-8")

    for forbidden in (
        '"source_record_id"',
        '"source_record_index"',
        '"chunk_kind"',
    ):
        assert forbidden not in text


def test_platform_filter_helper_uses_schema_declared_metadata_language() -> None:
    text = Path("app/rag/core/filters.py").read_text(encoding="utf-8")

    assert "schema-declared metadata field" in text
    assert "business-field" not in text


def test_dify_adapter_delegates_retrieval_policy_scoring_to_platform_module() -> None:
    text = Path("app/api/v1/integrations_dify.py").read_text(encoding="utf-8")

    assert "from app.rag.retrieval.plugin_policy import" in text
    assert "class _RetrievalPolicySignalScores" not in text
    assert "def _retrieval_policy_signal_scores" not in text
    assert "def _retrieval_policy_query_expansion_bonus" not in text


def test_dify_adapter_does_not_embed_business_intent_alignment_groups() -> None:
    text = Path("app/api/v1/integrations_dify.py").read_text(encoding="utf-8")

    assert "_QUERY_INTENT_ALIGNMENT_GROUPS" not in text
    assert "_filter_records_by_query_intent_alignment" not in text
    for forbidden in (
        "需要哪些材料",
        "办理材料",
        "操作步骤",
        "网上办理怎么操作",
        "operation_steps",
    ):
        assert forbidden not in text


def test_business_chunk_report_reuses_generic_plugin_report_builder() -> None:
    text = Path("scripts/changzhou_gov_plugin_chunk_report.py").read_text(encoding="utf-8")

    assert "from app.rag.pipeline_plugins.reports import" in text
    assert "build_pipeline_plugin_chunk_report" in text
    assert "apply_governance_python_plugin" not in text
    assert "apply_chunk_python_plugin" not in text
    assert "apply_kg_python_plugin" not in text


def test_platform_kg_paths_do_not_fallback_kg_plugin_params_to_chunk_plugin_params() -> None:
    texts = [
        Path("app/parsing/processors/processor.py").read_text(encoding="utf-8"),
        Path("app/tasks/jobs.py").read_text(encoding="utf-8"),
        Path("app/rag/kg/api/routes.py").read_text(encoding="utf-8"),
    ]
    text = "\n".join(texts)

    assert 'getattr(pipeline_effective, "chunk_python_params"' in text
    assert 'getattr(pipeline_effective, "kg_python_params"' in text
    assert 'getattr(effective, "chunk_python_params"' in text
    assert 'getattr(effective, "kg_python_params"' in text
    assert "kg_python_params = dict(getattr(pipeline_effective, \"chunk_python_params\"" not in text
    assert "kg_python_params = dict(getattr(effective, \"chunk_python_params\"" not in text
    assert "chunk_params = effective.get(\"chunk_python_params\"" not in text
