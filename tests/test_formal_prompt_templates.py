from __future__ import annotations


def test_formal_prompt_template_fragments_are_shared_across_operational_templates() -> None:
    from app.rag.llm.prompts.formal_templates import (
        FORMAL_PLAN_SOURCES,
        FORMAL_PROMPT_TAGS,
        render_formal_xml_prompt,
    )

    rendered = render_formal_xml_prompt(
        role="企业知识库助手",
        objective="回答用户问题",
        documents_slot="{context}",
        task_sections=[("question", "{question}")],
        output_contract="输出有引用的答案。",
    )

    assert "plans/rag-prompts-mainstream-research-2026-q2.md" in FORMAL_PLAN_SOURCES
    assert {"formal", "prompt-as-code", "plans-derived"}.issubset(set(FORMAL_PROMPT_TAGS))
    assert "<instructions>" in rendered
    assert "<documents>" in rendered
    assert "<citation_policy>" in rendered
    assert "<refusal_policy>" in rendered
    assert "<conflict_policy>" in rendered
