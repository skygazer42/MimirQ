from __future__ import annotations


def test_prompt_template_create_schema_preserves_examples_via_json_schema_extra() -> None:
    from app.api.schemas.prompt_template import PromptTemplateCreate

    schema = PromptTemplateCreate.model_json_schema()
    props = schema.get("properties") or {}

    assert (props.get("template_key") or {}).get("examples") == ["kb_assistant"]
    assert (props.get("name") or {}).get("examples") == ["Legal Consultant"]
    assert (props.get("variables") or {}).get("examples") == [["context", "question", "history"]]
