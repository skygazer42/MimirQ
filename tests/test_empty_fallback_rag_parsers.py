import pytest

from app.rag.industry_rules.loaders.yaml_loader import RulesetFormatError, _normalize_glossary
from app.rag.llm.factory import _normalize_fallback_spec
from app.rag.llm.prompt_cache import message_content_to_text


@pytest.mark.parametrize("alias", [None, 0, False])
def test_glossary_rejects_nontext_aliases(alias):
    with pytest.raises(RulesetFormatError, match="aliases must be strings"):
        _normalize_glossary({"term": [alias, "valid"]})


def test_glossary_preserves_zero_and_false_as_explicit_text():
    assert _normalize_glossary({"term": ["0", "False", "valid"]}) == {"term": ["0", "False", "valid"]}


def test_fallback_model_candidate_preserves_zero_and_skips_only_absent_name():
    assert _normalize_fallback_spec({"model": 0}) == {"model": "0"}
    assert _normalize_fallback_spec({}) is None


def test_prompt_text_preserves_real_falsy_content_and_absent_content():
    assert message_content_to_text(0) == "0"
    assert message_content_to_text(False) == "False"
    assert message_content_to_text(None) is None
