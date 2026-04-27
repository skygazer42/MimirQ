from __future__ import annotations

from app.rag.llm.prompts import get_prompt_bundle


def test_kb_assistant_prompt_bundle_snapshot_is_stable() -> None:
    bundle = get_prompt_bundle("kb_assistant")
    rendered = bundle.render()

    assert rendered.startswith("[System Prompt]")
    assert "You are a retrieval-grounded enterprise knowledge assistant." in rendered
    assert "{context}" in rendered
    assert "{question}" in rendered
    assert "answer" in rendered.lower()
