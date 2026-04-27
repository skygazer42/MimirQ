from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_output_guard_blocks_pii_like_answer_when_block_mode_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.safety.output_guard as module
    from app.rag.safety.output_guard import OutputGuard

    monkeypatch.setattr(module, "_OUTPUT_GUARD_MODE_DEFAULT", "block", raising=True)
    monkeypatch.setattr(module, "_OUTPUT_GUARD_SCORE_THRESHOLD_DEFAULT", 0.7, raising=True)

    guard = OutputGuard()
    result = await guard.check("客户身份证号是 110101199001011234。")

    assert result.action == "block"
    assert result.score >= 0.7
    assert "pii_id_card" in (result.matched_rules or [])


@pytest.mark.asyncio
async def test_output_guard_warns_on_citation_fabrication_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.safety.output_guard as module
    from app.rag.safety.output_guard import OutputGuard

    monkeypatch.setattr(module, "_OUTPUT_GUARD_MODE_DEFAULT", "warn", raising=True)
    monkeypatch.setattr(module, "_OUTPUT_GUARD_SCORE_THRESHOLD_DEFAULT", 0.7, raising=True)
    monkeypatch.setattr(module, "_OUTPUT_GUARD_WARN_THRESHOLD_DEFAULT", 0.35, raising=True)

    guard = OutputGuard()
    result = await guard.check("根据文档第 999 页可知答案成立。")

    assert result.action == "warn"
    assert "citation_fabrication_risk" in (result.matched_rules or [])


@pytest.mark.asyncio
async def test_output_guard_warns_when_answer_entities_are_missing_from_context() -> None:
    from app.rag.safety.output_guard import OutputGuard

    guard = OutputGuard()
    result = await guard.check(
        "华北仓储中心发生故障。",
        context_chunks=["本次告警仅影响华东仓储中心。"],
        question="哪里发生故障？",
    )

    assert result.action == "warn"
    assert "citation_consistency" in (result.matched_rules or [])


@pytest.mark.asyncio
async def test_output_guard_blocks_when_llama_guard_response_disallows_output(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.safety.output_guard as module
    from app.rag.safety.output_guard import OutputGuard

    class _FakeGuard:
        async def guard_agent_response(self, _text: str):
            return type("Res", (), {"action": "block"})()

    monkeypatch.setattr(module, "LlamaGuard", lambda: _FakeGuard(), raising=True)
    monkeypatch.setattr(module, "_OUTPUT_GUARD_MODE_DEFAULT", "block", raising=True)

    guard = OutputGuard()
    result = await guard.check(
        "客户身份证号是 110101199001011234。",
        context_chunks=["客户身份证号是 110101199001011234。"],
        question="身份证号是什么？",
    )

    assert result.action == "block"
    assert "llama_guard_response" in (result.matched_rules or [])
