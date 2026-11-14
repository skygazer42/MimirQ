from uuid import uuid4

import pytest

from app.models.prompt_template import PromptTemplate
from app.rag.evaluation import llm_judge, test_generator
from app.rag.kg.extraction.config import ExtractConfig


def _template(**overrides) -> PromptTemplate:
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "content": "",
        "variables": [],
        "version": 0,
        "template_key": "",
        "ab_experiment_key": "",
        "ab_variant": "",
    }
    values.update(overrides)
    return PromptTemplate(**values)


def test_selected_judge_prompt_keeps_actual_empty_metadata_and_version(monkeypatch: pytest.MonkeyPatch) -> None:
    template = _template()
    monkeypatch.setattr(llm_judge, "resolve_prompt_template", lambda **_kwargs: template)

    content, variables, version, metadata = llm_judge._resolve_generation_judge_prompt(
        db=object(),
        tenant_id=template.tenant_id,
        template_id=template.id,
        template_key=None,
        ab_experiment_key=None,
        ab_user_key=None,
    )

    assert content == ""
    assert variables == []
    assert version == 0
    assert metadata == {
        "prompt_template_id": str(template.id),
        "prompt_template_key": "",
        "prompt_ab_experiment_key": "",
        "prompt_ab_variant": "",
        "prompt_template_version": 0,
    }


def test_selected_judge_prompt_exposes_missing_required_content(monkeypatch: pytest.MonkeyPatch) -> None:
    template = _template(content=None)
    monkeypatch.setattr(llm_judge, "resolve_prompt_template", lambda **_kwargs: template)

    with pytest.raises(AttributeError):
        llm_judge._resolve_generation_judge_prompt(
            db=object(),
            tenant_id=template.tenant_id,
            template_id=template.id,
            template_key=None,
            ab_experiment_key=None,
            ab_user_key=None,
        )


def test_selected_testgen_prompt_preserves_empty_optional_selection_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    template = _template(content="{text}", variables=["text"])
    monkeypatch.setattr(test_generator, "resolve_prompt_template", lambda **_kwargs: template)

    selected = test_generator._resolve_testgen_prompt_selection(
        db=object(),
        tenant_id=template.tenant_id,
        account_id="reader",
        prompt_template_id=template.id,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
    )

    assert selected.prompt_template_text == "{text}"
    assert selected.prompt_template_key == ""
    assert selected.prompt_ab_experiment_key == ""
    assert selected.prompt_ab_variant == ""


def test_kg_extraction_keeps_an_explicit_empty_parameter_map_in_serialized_options() -> None:
    options = ExtractConfig(chunk_ids=[], kg_python_params={})

    assert options.model_dump(exclude_none=True)["kg_python_params"] == {}


def test_kg_extraction_still_rejects_nested_parameters() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractConfig(chunk_ids=[], kg_python_params={"nested": {}})


@pytest.mark.parametrize("content", ["", None])
def test_selected_kg_prompt_preserves_content_or_exposes_missing_required_text(
    monkeypatch: pytest.MonkeyPatch, content: str | None
) -> None:
    from types import SimpleNamespace

    from app.rag.kg.extraction import extractor

    template = _template(content=content, usage_count=0)
    monkeypatch.setattr(extractor, "resolve_prompt_template", lambda **_kwargs: template)
    session = SimpleNamespace(commit=lambda: None, rollback=lambda: None)
    config = ExtractConfig(chunk_ids=[], prompt_template_id=template.id)

    if content is None:
        with pytest.raises(AttributeError):
            extractor._resolve_prompt_template_content(session, template.tenant_id, config)
    else:
        resolved, identifier = extractor._resolve_prompt_template_content(session, template.tenant_id, config)
        assert resolved == ""
        assert identifier == str(template.id)


@pytest.mark.parametrize("canonicalize", [True, False])
@pytest.mark.parametrize("description,expected", [("  Acme product  ", "Acme product"), ("", ""), (None, None)])
def test_kg_entity_description_is_prepared_before_alias_branch_and_embedding(
    monkeypatch: pytest.MonkeyPatch, canonicalize: bool, description: str | None, expected: str | None
) -> None:
    from types import SimpleNamespace

    from app.models.document import DocumentChunk
    from app.rag.kg.extraction import extractor

    monkeypatch.setattr(extractor.settings, "KG_ENTITY_CANONICALIZE_PARENTHESES_ALIAS", canonicalize)
    chunk = DocumentChunk(id=uuid4(), document_id=uuid4(), content="Acme product", chunk_index=0, doc_metadata={})
    raw_entity = {"name": "Acme", "type": "organization", "description": description}
    _key, event = extractor._normalize_event_payload(
        chunk=chunk,
        event_data={"title": "product", "summary": "Acme product", "entities": [raw_entity]},
        max_entities_per_event=10,
    )
    texts = []
    extractor._collect_chunk_embed_texts(chunk, event, seen_text=set(), to_embed=texts)
    state = SimpleNamespace(chunk_key_by_id={}, chunk_hash_by_id={}, chunk_len_by_id={}, chosen_template_id=None)

    records, count = extractor._build_event_index_records(
        state=state, config=ExtractConfig(chunk_ids=[]), processed_events=[(chunk, event)], embed_cache={}
    )

    assert count == 1
    assert records[0].entities[0].description == expected
    assert event["entities"][0]["_embed_text"] == (f"Acme {expected}" if expected else "Acme")
    assert raw_entity["description"] == description


@pytest.mark.parametrize("canonicalize", [True, False])
def test_kg_entity_preparation_exposes_invalid_description_types(
    monkeypatch: pytest.MonkeyPatch, canonicalize: bool
) -> None:
    from app.models.document import DocumentChunk
    from app.rag.kg.extraction import extractor

    monkeypatch.setattr(extractor.settings, "KG_ENTITY_CANONICALIZE_PARENTHESES_ALIAS", canonicalize)
    with pytest.raises(AttributeError):
        extractor._normalize_event_payload(
            chunk=DocumentChunk(content="Acme", doc_metadata={}),
            event_data={"entities": [{"name": "Acme", "description": False}]},
            max_entities_per_event=10,
        )
