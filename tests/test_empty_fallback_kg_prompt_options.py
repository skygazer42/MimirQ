import pytest

from app.core.config import settings
from app.models.document import Document
from app.rag.kg.api.routes_support.extraction import _effective_kg_extraction_options
from app.rag.kg.api.routes_support.schemas import KGExtractionOptions


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
