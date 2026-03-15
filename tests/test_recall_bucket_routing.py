from __future__ import annotations

import uuid

import pytest


def test_guess_recall_bucket_schema() -> None:
    from app.rag.core.text import guess_recall_bucket

    assert guess_recall_bucket("订单表有哪些字段？") == "schema"
    assert guess_recall_bucket("What columns does the orders table have?") == "schema"


def test_guess_recall_bucket_procedure() -> None:
    from app.rag.core.text import guess_recall_bucket

    assert guess_recall_bucket("如何配置单点登录？") == "procedure"
    assert guess_recall_bucket("How to reset password?") == "procedure"


def test_guess_recall_bucket_numeric() -> None:
    from app.rag.core.text import guess_recall_bucket

    assert guess_recall_bucket("总数是多少？") == "numeric"
    assert guess_recall_bucket("Count users by day") == "numeric"


def test_guess_recall_bucket_policy() -> None:
    from app.rag.core.text import guess_recall_bucket

    assert guess_recall_bucket("这个功能符合哪些条例？") == "policy"
    assert guess_recall_bucket("What is our data retention policy?") == "policy"


def test_guess_recall_bucket_definition() -> None:
    from app.rag.core.text import guess_recall_bucket

    assert guess_recall_bucket("什么是 RAG？") == "definition"
    assert guess_recall_bucket("Define least privilege") == "definition"


@pytest.mark.asyncio
async def test_rag_engine_routes_auto_mode_by_recall_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    log_records = []

    def _log_metrics(payload):  # noqa: ANN001
        log_records.append(payload)

    monkeypatch.setattr(engine_mod, "log_metrics", _log_metrics, raising=True)

    # Keep the test deterministic / single-query.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    # Use a deterministic fake LLM.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "OK", raising=False)

    monkeypatch.setattr(settings, "RAG_RECALL_BUCKETS_ENABLED", True, raising=False)

    captured_updates = []

    class _CapturingRetriever:
        _last_debug_metrics = {}

        def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
            captured_updates.append(dict((kwargs or {}).get("update") or {}))
            return self

        def invoke(self, _q):  # noqa: ANN001
            return []

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _CapturingRetriever(), raising=True)

    tenant_id = uuid.uuid4()

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question="订单表有哪些字段？",
        history=None,
        conversation_id=None,
        tenant_id=tenant_id,
        document_ids=None,
        account_id="u",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="auto",
        db=None,
    )

    done_metrics = None
    async for item in agen:
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    assert done_metrics.get("recall_bucket") == "schema"

    update = captured_updates[0]
    assert update.get("retrieval_mode") == "keyword"
    assert update.get("score_threshold") == pytest.approx(0.0)

    rag_trace = next(r for r in log_records if r.get("event") == "rag_trace")
    assert (rag_trace.get("retrieval") or {}).get("recall_bucket") == "schema"
