from __future__ import annotations

import pytest


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self._content = content
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str):  # noqa: ANN001
        self.prompts.append(prompt)
        return _FakeResponse(self._content)


@pytest.mark.asyncio
async def test_structured_output_generator_uses_shared_framework_for_summary_mode() -> None:
    from app.rag.llm.structured_output import build_structured_output_instructions
    from app.rag.output import OutputMode, StructuredOutputGenerator, SummaryOutput

    llm = _FakeLLM('{"answer":"Concise incident summary","bullets":["cache invalidated"]}')
    generator = StructuredOutputGenerator(llm)

    out = await generator.generate(
        query="Incident summary",
        context="Cache invalidated after deploy. Error budget stable.",
        mode=OutputMode.SUMMARY,
        sources=["doc-1"],
    )

    assert isinstance(out, SummaryOutput)
    assert out.title == "Incident summary"
    assert out.summary == "Concise incident summary"
    assert out.key_points == ["cache invalidated"]
    assert out.sources == ["doc-1"]
    assert llm.prompts and build_structured_output_instructions("summary") in llm.prompts[0]


def test_parse_structured_output_repairs_action_items_via_shared_framework() -> None:
    from app.rag.output import ActionItemsOutput, OutputMode, parse_structured_output

    out = parse_structured_output('{"answer":"done"}', mode=OutputMode.ACTION_ITEMS)

    assert isinstance(out, ActionItemsOutput)
    assert out.items == []
    assert out.total_count == 0
