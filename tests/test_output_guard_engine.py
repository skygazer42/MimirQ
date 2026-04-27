from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


@pytest.mark.asyncio
async def test_engine_output_guard_blocks_unsafe_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "客户手机号是 13812345678。", raising=False)
    monkeypatch.setitem(settings.__dict__, "OUTPUT_GUARD_ENABLED", True)
    monkeypatch.setitem(settings.__dict__, "OUTPUT_GUARD_MODE", "block")
    monkeypatch.setitem(settings.__dict__, "OUTPUT_GUARD_SCORE_THRESHOLD", 0.7)

    class _OneDocRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            return [
                Document(
                    page_content="联系方式信息位于附录中。",
                    metadata={"source": "doc.txt", "page": 1},
                    id=str(uuid.uuid4()),
                )
            ]

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _OneDocRetriever(), raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="提供客户联系方式",
        history=None,
        conversation_id=None,
        tenant_id=uuid.uuid4(),
        document_ids=None,
        account_id="u",
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        db=None,
    )

    parts: list[str] = []
    done_metrics = None
    async for item in agen:
        if item.get("type") == "token":
            parts.append(str((item.get("data") or {}).get("content") or ""))
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    assert "".join(parts).strip() == "Response withheld by safety filter."
    output_guard = (done_metrics or {}).get("output_guard") or {}
    assert output_guard.get("action") == "block"
    assert "pii_phone" in list(output_guard.get("matched_rules") or [])


@pytest.mark.asyncio
async def test_engine_output_guard_warns_without_replacing_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "根据文档第 999 页可知答案成立。", raising=False)
    monkeypatch.setitem(settings.__dict__, "OUTPUT_GUARD_ENABLED", True)
    monkeypatch.setitem(settings.__dict__, "OUTPUT_GUARD_MODE", "warn")
    monkeypatch.setitem(settings.__dict__, "OUTPUT_GUARD_WARN_THRESHOLD", 0.35)
    monkeypatch.setitem(settings.__dict__, "OUTPUT_GUARD_SCORE_THRESHOLD", 0.7)

    class _OneDocRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _q):  # noqa: ANN001
            return [
                Document(
                    page_content="文档共有 10 页。",
                    metadata={"source": "doc.txt", "page": 1},
                    id=str(uuid.uuid4()),
                )
            ]

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _OneDocRetriever(), raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="引用页码是多少",
        history=None,
        conversation_id=None,
        tenant_id=uuid.uuid4(),
        document_ids=None,
        account_id="u",
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        db=None,
    )

    parts: list[str] = []
    done_metrics = None
    async for item in agen:
        if item.get("type") == "token":
            parts.append(str((item.get("data") or {}).get("content") or ""))
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    assert "第 999 页" in "".join(parts)
    output_guard = (done_metrics or {}).get("output_guard") or {}
    assert output_guard.get("action") == "warn"
    assert "citation_fabrication_risk" in list(output_guard.get("matched_rules") or [])
