from __future__ import annotations

from app.rag.llm.prompts import get_prompt_bundle, list_prompt_bundles


def test_prompt_bundle_registry_exposes_default_bundles() -> None:
    bundles = list_prompt_bundles()
    keys = {item.key for item in bundles}

    assert "kb_assistant" in keys
    assert "kb_summary" in keys
    assert "kb_action_items" in keys


def test_prompt_bundle_render_includes_system_prompt_schema_and_oneshot() -> None:
    bundle = get_prompt_bundle("kb_summary")
    text = bundle.render()

    assert "System Prompt" in text
    assert "Schema" in text
    assert "One-shot Example" in text
    assert "summary" in text.lower()
    assert "bullets" in text
