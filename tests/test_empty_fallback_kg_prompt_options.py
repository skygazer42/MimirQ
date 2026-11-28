import pytest

from app.api.v1.knowledge_graph.routes_support.extraction import _effective_kg_extraction_options
from app.api.v1.knowledge_graph.routes_support.types import KGExtractionOptions
from app.infrastructure.config import settings
from app.models.documents.records import Document


@pytest.mark.parametrize("field", ["prompt_template_key", "prompt_ab_experiment_key"])
@pytest.mark.parametrize("value", ["", " supplied-key "])
def test_kg_effective_prompt_options_forward_the_provided_value(monkeypatch, field, value):
    monkeypatch.setattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "")
    monkeypatch.setattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "configured-key")
    monkeypatch.setattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "configured-experiment")
    document = Document(doc_metadata={})

    effective = _effective_kg_extraction_options(document, KGExtractionOptions(**{field: value}))

    assert getattr(effective, field) == value


def test_kg_effective_prompt_options_resolve_defaults_only_for_none(monkeypatch):
    monkeypatch.setattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "")
    monkeypatch.setattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "configured-key")
    monkeypatch.setattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "configured-experiment")

    effective = _effective_kg_extraction_options(Document(doc_metadata={}), KGExtractionOptions())

    assert effective.prompt_template_key == "configured-key"
    assert effective.prompt_ab_experiment_key == "configured-experiment"
