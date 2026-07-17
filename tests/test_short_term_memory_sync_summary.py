"""Regression tests for ShortTermMemoryManager.process() async bridging.

Guards the fix where the synchronous process() path degraded to a simple
truncation summary whenever an event loop was already running (i.e. every
async FastAPI request path). It should now offload to the shared async bridge
and return a real LLM summary.
"""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from app.rag.memory.short_term import ShortTermMemoryManager


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Records invocation and returns a marker so we can prove the LLM ran."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, prompt: str) -> _FakeResponse:
        self.calls += 1
        return _FakeResponse("REAL_LLM_SUMMARY")


def _many_messages(n: int) -> list:
    msgs = []
    for i in range(n):
        msgs.append(HumanMessage(content=f"user turn {i}"))
        msgs.append(AIMessage(content=f"assistant turn {i}"))
    return msgs


def _make_manager(llm) -> ShortTermMemoryManager:
    return ShortTermMemoryManager(
        max_tokens=100_000,
        summarization_threshold=2,
        enable_summarization=True,
        llm=llm,
    )


def test_process_uses_real_llm_summary_without_running_loop():
    llm = _FakeLLM()
    manager = _make_manager(llm)

    result = manager.process(_many_messages(10))

    assert llm.calls == 1
    summary_text = str(result[0].content)
    assert "REAL_LLM_SUMMARY" in summary_text


def test_process_uses_real_llm_summary_inside_running_loop():
    """The core regression: a running loop must NOT force the simple fallback."""

    async def _run() -> list:
        llm = _FakeLLM()
        manager = _make_manager(llm)
        # process() is sync but called from within a running event loop,
        # exactly like a synchronous helper invoked inside an async request.
        result = manager.process(_many_messages(10))
        assert llm.calls == 1
        return result

    result = asyncio.run(_run())
    summary_text = str(result[0].content)
    assert "REAL_LLM_SUMMARY" in summary_text


def test_process_falls_back_when_summarizer_raises():
    class _BoomLLM:
        async def ainvoke(self, prompt: str):
            raise RuntimeError("llm down")

    manager = _make_manager(_BoomLLM())
    # summarize_messages swallows the llm error internally and returns a
    # truncation summary, so process() still produces a usable summary message
    # rather than propagating.
    result = manager.process(_many_messages(10))
    assert result  # does not raise, still returns processed messages
