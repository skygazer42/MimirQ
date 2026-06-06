from __future__ import annotations

from pathlib import Path


def test_generic_pipeline_plugin_runtime_tests_do_not_embed_business_plugin() -> None:
    text = Path("tests/test_python_pipeline_plugins.py").read_text(encoding="utf-8")

    for forbidden in (
        "changzhou-gov-service-knowledge",
        "20260522政务服务智能客服知识",
        "常州",
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
        Path("tests/test_governance_profile_validation.py"),
        Path("tests/test_pipeline_plugin_boundary.py"),
        Path("tests/test_pipeline_plugin_closed_loop_docs.py"),
        Path("tests/test_plugin_corpus_closed_loop_smoke.py"),
        Path("web/components/chunk-preview/components/workbench/sidebar-client.messages.source.test.ts"),
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
        "/data/temp50/政务服务",
        "常州政务事项图谱",
        "district:cz",
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
