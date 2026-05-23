from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest


def _decode_sse_payloads(chunks: list[str]) -> list[dict]:
    import json

    payloads: list[dict] = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if not line.startswith("data: "):
                continue
            payloads.append(json.loads(line.removeprefix("data: ")))
    return payloads


def test_model_provider_unavailable_detection_is_narrow() -> None:
    from app.services.chat_execution_runtime import is_model_provider_unavailable_error

    assert is_model_provider_unavailable_error(RuntimeError("HTTP 400 Arrearage: account overdue"))
    assert is_model_provider_unavailable_error(RuntimeError("rate_limit from provider"))
    assert is_model_provider_unavailable_error(RuntimeError("Model does not exist. Please check it carefully."))
    assert not is_model_provider_unavailable_error(ValueError("local schema validation bug"))


def test_model_provider_unavailable_circuit_opens_temporarily() -> None:
    import app.services.chat_execution_runtime as runtime_mod

    runtime_mod._MODEL_PROVIDER_CIRCUIT_KEY = ""  # noqa: SLF001
    runtime_mod._MODEL_PROVIDER_UNAVAILABLE_UNTIL = 0.0  # noqa: SLF001

    assert not runtime_mod.is_model_provider_unavailable_circuit_open()
    runtime_mod.mark_model_provider_unavailable(ttl_sec=1.0)
    assert runtime_mod.is_model_provider_unavailable_circuit_open()


def test_model_provider_circuit_resets_when_provider_config_changes(monkeypatch) -> None:
    import app.services.chat_execution_runtime as runtime_mod

    runtime_mod._MODEL_PROVIDER_CIRCUIT_KEY = ""  # noqa: SLF001
    runtime_mod._MODEL_PROVIDER_UNAVAILABLE_UNTIL = 0.0  # noqa: SLF001
    runtime_mod._MODEL_PROVIDER_AVAILABLE_UNTIL = 0.0  # noqa: SLF001
    monkeypatch.setattr(runtime_mod.settings, "LLM_API_KEY", "key-a", raising=False)
    monkeypatch.setattr(runtime_mod.settings, "LLM_API_BASE", "https://provider-a.example/v1", raising=False)
    monkeypatch.setattr(runtime_mod.settings, "LLM_MODEL", "model-a", raising=False)

    runtime_mod.mark_model_provider_unavailable(ttl_sec=60.0)
    assert runtime_mod.is_model_provider_unavailable_circuit_open()

    monkeypatch.setattr(runtime_mod.settings, "LLM_API_KEY", "key-b", raising=False)
    monkeypatch.setattr(runtime_mod.settings, "LLM_API_BASE", "https://provider-b.example/v1", raising=False)

    assert not runtime_mod.is_model_provider_unavailable_circuit_open()


@pytest.mark.asyncio
async def test_preflight_opens_circuit_when_llm_config_missing(monkeypatch) -> None:
    import app.services.chat_execution_runtime as runtime_mod

    runtime_mod._MODEL_PROVIDER_CIRCUIT_KEY = ""  # noqa: SLF001
    runtime_mod._MODEL_PROVIDER_UNAVAILABLE_UNTIL = 0.0  # noqa: SLF001
    runtime_mod._MODEL_PROVIDER_AVAILABLE_UNTIL = 0.0  # noqa: SLF001
    monkeypatch.setattr(runtime_mod.settings, "LLM_API_KEY", "", raising=False)

    available, reason = await runtime_mod.preflight_model_provider_fast()

    assert available is False
    assert "LLM_API_KEY" in str(reason)
    assert runtime_mod.is_model_provider_unavailable_circuit_open()


def test_extractive_fallback_answer_uses_retrieved_evidence() -> None:
    from app.services.chat_execution_runtime import build_extractive_fallback_answer

    answer = build_extractive_fallback_answer(
        question="QUIC 有什么特点？",
        citations=[
            {
                "document_name": "rfc9000.txt",
                "chunk_content": "QUIC provides secure transport over UDP and multiplexed streams.",
            }
        ],
    )

    assert "模型服务当前不可用" in answer
    assert "rfc9000.txt" in answer
    assert "QUIC provides secure transport" in answer


def test_extractive_fallback_answer_surfaces_direct_multi_hop_evidence() -> None:
    from app.services.chat_execution_runtime import build_extractive_fallback_answer

    answer = build_extractive_fallback_answer(
        question="Who led the integration program that followed Project Atlas's acquisition of Blue Harbor?",
        citations=[
            {
                "document_name": "integration-lead.md",
                "chunk_content": (
                    "# Integration Lead\n\n"
                    "After the acquisition, Mira Chen led the Blue Harbor integration program."
                ),
            },
            {
                "document_name": "atlas-acquisition.md",
                "chunk_content": "# Atlas Acquisition\n\nProject Atlas acquired Blue Harbor on 2026-01-10.",
            },
        ],
        reason="explicit_extractive_answer_mode",
    )

    assert "Mira Chen led the Blue Harbor integration program" in answer


def test_extractive_fallback_answer_can_pull_relevant_sentence_from_late_chunk_content() -> None:
    from app.services.chat_execution_runtime import build_extractive_fallback_answer

    long_prefix = "intro " * 120
    answer_sentence = "After the acquisition, Mira Chen led the Blue Harbor integration program."
    answer = build_extractive_fallback_answer(
        question="Who led the integration program that followed Project Atlas's acquisition of Blue Harbor?",
        citations=[
            {
                "document_name": "integration-lead.md",
                "chunk_content": f"# Integration Lead\n\n{long_prefix}\n\n{answer_sentence}",
            }
        ],
        reason="explicit_extractive_answer_mode",
    )

    assert answer_sentence in answer


def test_extractive_fallback_retrieval_uses_lightweight_config(monkeypatch) -> None:
    import app.rag.pipelines.langgraph as langgraph_mod
    import app.rag.retrieval.orchestrator as orchestrator_mod
    from app.services.chat_execution_runtime import execute_extractive_fallback_once

    captured: dict = {}

    def _fake_build_rag_state(**kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        return {"question": kwargs["question"]}

    def _fake_run_retrieval(_state):  # noqa: ANN001, ANN202
        return {
            "citations": [
                {
                    "document_name": "fastapi.md",
                    "chunk_content": "FastAPI automatically generates OpenAPI documentation.",
                }
            ],
            "metrics": {"retrieval_mode": "hybrid"},
        }

    monkeypatch.setattr(langgraph_mod, "build_rag_state", _fake_build_rag_state, raising=True)
    monkeypatch.setattr(orchestrator_mod, "run_retrieval", _fake_run_retrieval, raising=True)

    result = execute_extractive_fallback_once(
        db=object(),
        tenant_id=UUID(int=1),
        account_id="demo",
        request=SimpleNamespace(message="FastAPI 文档能力？"),
        doc_ids_to_use=[UUID(int=2)],
        history_for_llm=[],
        scope_dataset_id=UUID(int=3),
        dataset_id_used=None,
        effective_rag_config=SimpleNamespace(
            top_k=50,
            score_threshold=0.0,
            retrieval_mode="hybrid",
            alpha=None,
            fusion_strategy=None,
            fusion_budgets=None,
            fusion_min_scores=None,
            fusion_weights=None,
            enable_weight_rerank=None,
            vector_weight=None,
            keyword_weight=None,
            mmr_lambda=None,
            visible_evidence_only=None,
            metadata_filter=None,
        ),
        original_error=RuntimeError("Arrearage"),
    )

    assert captured["top_k"] == 6
    assert captured["retrieval_profile"] is None
    assert captured["enable_reranker"] is False
    assert captured["enable_multi_query"] is False
    assert result.metrics["generation_fallback_used"] is True
    assert result.citations
    assert "FastAPI automatically generates" in result.content


def test_extractive_fallback_can_use_full_docs_when_citations_are_truncated(monkeypatch) -> None:
    from types import SimpleNamespace

    import app.rag.pipelines.langgraph as langgraph_mod
    import app.rag.retrieval.orchestrator as orchestrator_mod
    from app.services.chat_execution_runtime import execute_extractive_fallback_once

    def _fake_build_rag_state(**kwargs):  # noqa: ANN003, ANN202
        return {"question": kwargs["question"]}

    def _fake_run_retrieval(_state):  # noqa: ANN001, ANN202
        return {
            "docs": [
                SimpleNamespace(
                    page_content=(
                        "# Integration Lead\n\n"
                        + ("intro " * 120)
                        + "\n\nAfter the acquisition, Mira Chen led the Blue Harbor integration program."
                    ),
                    metadata={"document_name": "integration-lead.md"},
                )
            ],
            "citations": [
                {
                    "document_name": "integration-lead.md",
                    "chunk_content": "# Integration Lead ...",
                }
            ],
            "metrics": {"retrieval_mode": "hybrid"},
        }

    monkeypatch.setattr(langgraph_mod, "build_rag_state", _fake_build_rag_state, raising=True)
    monkeypatch.setattr(orchestrator_mod, "run_retrieval", _fake_run_retrieval, raising=True)

    result = execute_extractive_fallback_once(
        db=object(),
        tenant_id=UUID(int=1),
        account_id="demo",
        request=SimpleNamespace(
            message="Who led the integration program that followed Project Atlas's acquisition of Blue Harbor?"
        ),
        doc_ids_to_use=[UUID(int=2)],
        history_for_llm=[],
        scope_dataset_id=UUID(int=3),
        dataset_id_used=None,
        effective_rag_config=SimpleNamespace(
            top_k=6,
            score_threshold=0.0,
            retrieval_mode="hybrid",
            alpha=None,
            fusion_strategy=None,
            fusion_budgets=None,
            fusion_min_scores=None,
            fusion_weights=None,
            enable_weight_rerank=None,
            vector_weight=None,
            keyword_weight=None,
            mmr_lambda=None,
            visible_evidence_only=None,
            metadata_filter=None,
        ),
        original_error=RuntimeError("Arrearage"),
        reason="explicit_extractive_answer_mode",
    )

    assert "Mira Chen led the Blue Harbor integration program" in result.content


def test_chat_rag_config_accepts_explicit_extractive_answer_mode() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(answer_mode="extractive", top_k=6, retrieval_mode="hybrid")

    assert cfg.answer_mode == "extractive"


def test_graph_chat_passes_generation_max_tokens_to_rag_state(monkeypatch) -> None:
    from types import SimpleNamespace
    from uuid import UUID

    import app.rag.pipelines.langgraph as langgraph_mod
    from app.api.schemas.chat import ChatRAGConfig
    from app.services.chat_execution_runtime import execute_graph_chat_once

    captured: dict = {}

    def _fake_build_rag_state(**kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        return {"question": kwargs["question"], "max_tokens": kwargs.get("max_tokens"), "metrics": {}}

    class _FakeWorkflow:
        def invoke(self, state, **_kwargs):  # noqa: ANN001, ANN202
            return {
                "answer": "ok",
                "citations": [],
                "metrics": {"generation_max_tokens": state.get("max_tokens")},
            }

    monkeypatch.setattr(langgraph_mod, "build_rag_state", _fake_build_rag_state, raising=True)
    monkeypatch.setattr(langgraph_mod, "rag_workflow", _FakeWorkflow(), raising=True)

    result = execute_graph_chat_once(
        db=object(),
        tenant_id=UUID(int=1),
        account_id="demo",
        request=SimpleNamespace(message="q", structured_output=False, structured_preset=None),
        conversation_id=None,
        request_id="req-1",
        doc_ids_to_use=[],
        history_for_llm=[],
        scope_dataset_id=UUID(int=2),
        dataset_id_used=None,
        effective_rag_config=ChatRAGConfig(max_tokens=333, top_k=3, retrieval_mode="hybrid"),
        effective_prompt_template_id=None,
        effective_prompt_template_key=None,
        effective_prompt_ab_experiment_key=None,
        rag_config_template_meta=None,
    )

    assert captured["max_tokens"] == 333
    assert result.metrics["generation_max_tokens"] == 333


def test_rag_engine_rebuilds_when_llm_settings_change(monkeypatch) -> None:
    import app.rag.engine as engine_mod

    class _FakeEngine:
        def __init__(self) -> None:
            self.model = engine_mod.settings.LLM_MODEL

    engine_mod.reset_rag_engine()
    monkeypatch.setattr(engine_mod, "RAGEngine", _FakeEngine, raising=True)
    monkeypatch.setattr(engine_mod.settings, "LLM_API_KEY", "same-key", raising=False)
    monkeypatch.setattr(engine_mod.settings, "LLM_API_BASE", "https://provider.example/v1", raising=False)
    monkeypatch.setattr(engine_mod.settings, "LLM_MODEL", "model-a", raising=False)

    first = engine_mod.get_rag_engine()
    assert first.model == "model-a"

    monkeypatch.setattr(engine_mod.settings, "LLM_MODEL", "model-b", raising=False)
    second = engine_mod.get_rag_engine()

    assert second is not first
    assert second.model == "model-b"


def test_dynamic_route_skips_stale_provider_alias(monkeypatch) -> None:
    import app.rag.engine as engine_mod
    from app.rag.engine import RAGEngine

    monkeypatch.setattr(engine_mod.settings, "LLM_API_BASE", "https://api.siliconflow.cn/v1", raising=False)

    assert not RAGEngine._is_route_model_compatible(
        route_model_name="qwen3.6-plus",
        default_model_name="deepseek-ai/DeepSeek-V3",
    )
    assert RAGEngine._is_route_model_compatible(
        route_model_name="Qwen/Qwen2.5-7B-Instruct",
        default_model_name="deepseek-ai/DeepSeek-V3",
    )


@pytest.mark.asyncio
async def test_langchain_chat_raises_stream_error_event() -> None:
    from app.services.chat_execution_runtime import execute_langchain_chat_once

    class _Config(SimpleNamespace):
        def __getattr__(self, _name: str):  # noqa: ANN001, ANN204
            return None

    class _Engine:
        async def stream_chat(self, **_kwargs):  # noqa: ANN003, ANN202
            yield {"type": "citations", "data": []}
            yield {
                "type": "error",
                "data": {"message": "Error code: 400 - Model does not exist. Please check it carefully."},
            }

    with pytest.raises(RuntimeError, match="Model does not exist"):
        await execute_langchain_chat_once(
            engine=_Engine(),
            db=object(),
            tenant_id=UUID(int=1),
            account_id="demo",
            request=SimpleNamespace(message="test", structured_output=False, structured_preset=None),
            conversation_id=None,
            request_id="req",
            doc_ids_to_use=[],
            history_for_llm=[],
            scope_dataset_id=None,
            dataset_id_used=None,
            effective_rag_config=_Config(
                top_k=6,
                score_threshold=0.0,
                retrieval_mode="hybrid",
                enable_reranker=False,
                reranker_provider=None,
                reranker_top_n=20,
            ),
            effective_prompt_template_id=None,
            effective_prompt_template_key=None,
            effective_prompt_ab_experiment_key=None,
            rag_config_template_meta=None,
        )


@pytest.mark.asyncio
async def test_stream_chat_uses_extractive_fallback_when_provider_circuit_open(monkeypatch) -> None:
    import app.services.chat_stream_common as common_mod
    import app.services.chat_stream_orchestrator as orchestrator_mod
    from app.services.chat_execution_runtime import ExecutedGraphChatOnceResult

    tenant_id = UUID(int=1)
    conversation_id = UUID(int=2)
    assistant_message_id = UUID(int=3)
    persisted: dict = {}

    runtime = SimpleNamespace(
        effective_rag_config=SimpleNamespace(
            answer_mode="llm",
            use_graph=False,
            retrieval_mode="hybrid",
        ),
        dataset_id_used=UUID(int=4),
        dataset_rag_defaults_applied_fields=[],
        effective_prompt_template_id=None,
        effective_prompt_template_key=None,
        effective_prompt_ab_experiment_key=None,
        dataset_prompt_defaults_applied_fields=[],
        dataset_rag_config_template_defaults_applied_fields=[],
        rag_config_template_meta=None,
        history_for_llm=[],
        cache_feature_enabled=False,
        cache_key=None,
        cache_skip_reason=None,
        cache_eligible=False,
        cache_hit=False,
        full_response="",
        citations_data=[],
        metrics_data={},
        structured_data=None,
    )

    class _Request(SimpleNamespace):
        message = "总结当前文档"
        structured_output = False
        structured_preset = None
        enable_summary_memory = False
        enable_structured_memory = False

    class _HttpRequest(SimpleNamespace):
        headers = {}
        client = SimpleNamespace(host="127.0.0.1")
        state = SimpleNamespace(request_id="req-stream-fallback")

        async def is_disconnected(self) -> bool:
            return False

    class _Engine:
        async def stream_chat(self, **_kwargs):  # noqa: ANN003, ANN202
            raise AssertionError("model engine should not be called while provider circuit is open")
            yield  # pragma: no cover

    def _persist_stub(**kwargs):  # noqa: ANN003, ANN202
        options = kwargs["options"]
        persisted["content"] = options.content
        persisted["citations"] = options.citations
        persisted["metrics"] = options.metrics

    monkeypatch.setattr(orchestrator_mod, "prepare_stream_chat_runtime", lambda **_kwargs: runtime)
    monkeypatch.setattr(orchestrator_mod, "is_model_provider_unavailable_circuit_open", lambda: True, raising=False)
    monkeypatch.setattr(orchestrator_mod, "get_rag_engine", lambda: _Engine())
    monkeypatch.setattr(
        orchestrator_mod,
        "execute_extractive_fallback_once",
        lambda **_kwargs: ExecutedGraphChatOnceResult(
            content="模型服务当前不可用，以下为基于已检索引用生成的可审计摘要。",
            citations=[{"document_name": "sample.md", "chunk_content": "测试引用"}],
            metrics={"generation_fallback_used": True},
            structured_data=None,
        ),
        raising=False,
    )
    monkeypatch.setattr(common_mod, "dispatch_chat_stream_persistence", _persist_stub)

    chunks = [
        chunk
        async for chunk in orchestrator_mod.stream_chat_sse_events(
            http_request=_HttpRequest(),
            db=object(),
            tenant_id=tenant_id,
            account_id="demo",
            request=_Request(),
            conversation_id=conversation_id,
            scope_dataset_id=None,
            allowed_doc_ids=[UUID(int=5)],
            long_term_messages=[],
            assistant_message_id=assistant_message_id,
            tenant_qps_meta=None,
            quota_meta=None,
            spawn_background_task=lambda _task: None,
        )
    ]

    payloads = _decode_sse_payloads(chunks)
    token_text = "".join(
        str((payload.get("data") or {}).get("content") or "")
        for payload in payloads
        if payload.get("type") == "token"
    )
    done = [payload for payload in payloads if payload.get("type") == "done"]

    assert "模型服务当前不可用" in token_text
    assert done
    assert persisted["content"] == token_text
    assert persisted["metrics"]["generation_fallback_used"] is True
