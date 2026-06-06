from __future__ import annotations

import pytest

LEGACY_IMPORT_GOVERNANCE_REF = "tests.fixtures.python_pipeline_import_plugin:govern_documents"


def test_shared_plugin_ref_helper_accepts_registered_stage_refs() -> None:
    from app.rag.pipeline_plugins.refs import clean_python_plugin_ref

    assert (
        clean_python_plugin_ref(
            "plugin:demo-service@1.0.0:chunk",
            field_name="chunk_python_plugin",
            expected_stage="chunk",
        )
        == "plugin:demo-service@1.0.0:chunk"
    )

    with pytest.raises(ValueError, match="chunk_python_plugin registered ref must target the chunk stage"):
        clean_python_plugin_ref(
            "plugin:demo-service@1.0.0:governance",
            field_name="chunk_python_plugin",
            expected_stage="chunk",
        )


def test_shared_plugin_ref_helper_blocks_legacy_import_refs_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.pipeline_plugins.refs import clean_python_plugin_ref, sanitize_python_plugin_ref

    monkeypatch.setattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES", "", raising=False)

    with pytest.raises(ValueError, match="python plugin import refs are disabled"):
        clean_python_plugin_ref(LEGACY_IMPORT_GOVERNANCE_REF)

    assert sanitize_python_plugin_ref(LEGACY_IMPORT_GOVERNANCE_REF) is None


def test_shared_plugin_ref_helper_allows_legacy_import_refs_when_prefix_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.pipeline_plugins.refs import clean_python_plugin_ref, sanitize_python_plugin_ref

    monkeypatch.setattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES", "tests.fixtures.", raising=False)

    ref = LEGACY_IMPORT_GOVERNANCE_REF

    assert clean_python_plugin_ref(ref) == ref
    assert sanitize_python_plugin_ref(ref) == ref
