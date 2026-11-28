import pytest
from langchain_core.documents import Document

from app.rag.pipeline_plugins.runtime import PythonPipelinePluginError, _coerce_kg_event


@pytest.mark.parametrize("field", ["description", "role", "evidence_quote", "evidence_source"])
@pytest.mark.parametrize("value", ["", None, "  source text  "])
def test_kg_plugin_optional_text_preserves_empty_and_missing_values(field: str, value: str | None) -> None:
    raw = {"title": "event", "entities": [{"name": "Acme", field: value}]}

    event = _coerce_kg_event(
        raw, documents=[Document(page_content="source")], plugin_ref="plugin.test:extract", index=0
    )

    assert len(event.entities) == 1
    assert getattr(event.entities[0], field) == (value.strip() if value is not None else None)
    assert raw["entities"][0][field] == value


@pytest.mark.parametrize("field", ["description", "role", "evidence_quote", "evidence_source"])
@pytest.mark.parametrize("value", [False, 0])
def test_kg_plugin_exposes_invalid_optional_text_types(field: str, value) -> None:
    with pytest.raises(PythonPipelinePluginError, match=field):
        _coerce_kg_event(
            {"title": "event", "entities": [{"name": "Acme", field: value}]},
            documents=[Document(page_content="source")],
            plugin_ref="plugin.test:extract",
            index=0,
        )
