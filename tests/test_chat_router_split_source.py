from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_chat_summary_checkpoint_routes_are_split_from_main_router() -> None:
    chat_source = _source("app/api/v1/chat.py")
    split_source = _source("app/api/v1/chat_conversation_memory.py")

    assert "from app.api.v1 import chat_conversation_memory" in chat_source
    assert "router.include_router(chat_conversation_memory.router)" in chat_source

    split_route_paths = (
        "/conversations/{conversation_id}/summary",
        "/conversations/{conversation_id}/summary/update",
        "/conversations/{conversation_id}/rag-traces",
        "/conversations/{conversation_id}/checkpoints",
        "/conversations/{conversation_id}/checkpoints/{checkpoint_id}",
    )
    for route_path in split_route_paths:
        quoted_path = f'"{route_path}"'
        assert quoted_path not in chat_source
        assert quoted_path in split_source


def test_chat_conversation_read_routes_are_split_from_main_router() -> None:
    chat_source = _source("app/api/v1/chat.py")
    split_source = _source("app/api/v1/chat_conversations.py")

    assert "chat_conversations" in chat_source
    assert "router.include_router(chat_conversations.router)" in chat_source

    split_route_decorators = (
        '@router.post(\n    "/conversations",',
        '@router.patch(\n    "/conversations/{conversation_id}",',
        '@router.get("/conversations",',
        '"/conversations/{conversation_id}/messages",',
        '"/conversations/{conversation_id}/export",',
        '@router.delete(\n    "/conversations/{conversation_id}",',
    )
    for decorator in split_route_decorators:
        assert decorator not in chat_source
        assert decorator in split_source


def test_chat_router_still_exposes_split_conversation_routes() -> None:
    from app.api.v1.chat import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/conversations/{conversation_id}/summary", ("GET",)) in routes
    assert ("/conversations/{conversation_id}/summary/update", ("POST",)) in routes
    assert ("/conversations/{conversation_id}/summary", ("DELETE",)) in routes
    assert ("/conversations/{conversation_id}/rag-traces", ("GET",)) in routes
    assert ("/conversations/{conversation_id}/checkpoints", ("GET",)) in routes
    assert ("/conversations/{conversation_id}/checkpoints/{checkpoint_id}", ("GET",)) in routes
    assert ("/conversations/{conversation_id}/checkpoints", ("DELETE",)) in routes
    assert ("/conversations", ("GET",)) in routes
    assert ("/conversations", ("POST",)) in routes
    assert ("/conversations/{conversation_id}", ("PATCH",)) in routes
    assert ("/conversations/{conversation_id}/messages", ("GET",)) in routes
    assert ("/conversations/{conversation_id}/export", ("GET",)) in routes
    assert ("/conversations/{conversation_id}", ("DELETE",)) in routes


def test_chat_runtime_helper_cluster_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    memory_source = _source("app/services/chat_memory_runtime.py")

    split_helpers = (
        "_retrieve_long_term_messages",
        "_retrieve_structured_memory_records",
        "_touch_conversation_after_turn",
    )

    for helper in split_helpers:
        assert f"def {helper}(" not in chat_source
        assert f"def {helper}(" not in runtime_source
        assert f"def {helper}(" in memory_source


def test_chat_request_runtime_preparation_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    bootstrap_source = _source("app/services/chat_bootstrap_runtime.py")

    assert "prepare_chat_request_runtime as _prepare_chat_request_runtime" in chat_source
    assert "def prepare_chat_request_runtime(" not in runtime_source
    assert "def prepare_chat_request_runtime(" in bootstrap_source

    duplicated_runtime_calls = (
        "merge_prompt_defaults_with_dataset(",
        "merge_rag_config_template_defaults_with_dataset(",
        "get_conversation_summary(",
        "build_structured_memory_context(",
    )
    for snippet in duplicated_runtime_calls:
        assert snippet not in chat_source
        assert snippet in bootstrap_source


def test_chat_turn_session_bootstrap_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    bootstrap_source = _source("app/services/chat_bootstrap_runtime.py")

    assert "prepare_chat_turn_session as _prepare_chat_turn_session" in chat_source
    assert "def prepare_chat_turn_session(" not in runtime_source
    assert "def prepare_chat_turn_session(" in bootstrap_source
    assert "resolved_scope = resolve_chat_conversation_scope(" not in chat_source
    assert "db.add(user_message)" not in chat_source


def test_chat_stream_bootstrap_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    bootstrap_source = _source("app/services/chat_bootstrap_runtime.py")

    assert "def prepare_stream_chat_runtime(" not in runtime_source
    assert "def prepare_stream_chat_runtime(" in bootstrap_source
    assert "_prepare_stream_chat_runtime(" not in chat_source
    assert chat_source.count("request_runtime = _prepare_chat_request_runtime(") == 1
    assert "cache_feature_enabled, cache_key, cache_skip_reason = _prepare_chat_cache_lookup(" not in chat_source


def test_chat_stream_orchestration_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    stream_source = _source("app/services/chat_stream_orchestrator.py")

    assert "stream_chat_sse_events as _stream_chat_sse_events" in chat_source
    assert "def stream_chat_sse_events(" in stream_source
    assert "async def event_stream():" not in chat_source
    assert 'yield ": keepalive\\n\\n"' not in chat_source
    assert "async for cached_event in _stream_cached_chat_events(" not in chat_source
    assert "async for graph_event in _stream_graph_chat_session_events(" not in chat_source
    assert "async for stream_chunk in _stream_langchain_chat_session_events(" not in chat_source
    assert "def stream_graph_chat_session_events(" not in stream_source
    assert "def stream_langchain_chat_session_events(" not in stream_source


def test_chat_non_streaming_graph_execution_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    execution_source = _source("app/services/chat_execution_runtime.py")

    assert "execute_graph_chat_once as _execute_graph_chat_once" in chat_source
    assert "def execute_graph_chat_once(" not in runtime_source
    assert "def execute_graph_chat_once(" in execution_source
    assert "rag_workflow.invoke(" not in chat_source
    assert "rag_workflow.invoke(" in execution_source


def test_chat_non_streaming_langchain_execution_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    execution_source = _source("app/services/chat_execution_runtime.py")

    assert "execute_langchain_chat_once as _execute_langchain_chat_once" in chat_source
    assert "def execute_langchain_chat_once(" not in runtime_source
    assert "def execute_langchain_chat_once(" in execution_source
    assert "async for event in engine.stream_chat(" not in chat_source
    assert "async for event in engine.stream_chat(" in execution_source


def test_chat_streaming_graph_execution_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    stream_source = _source("app/services/chat_stream_graph.py")
    orchestrator_source = _source("app/services/chat_stream_orchestrator.py")

    assert "def stream_graph_chat_session_events(" in stream_source
    assert "def stream_graph_chat_events(" in stream_source
    assert 'stream_mode=["custom", "values"]' not in chat_source
    assert "rag_workflow.stream(" not in chat_source
    assert "graph_stream_state" not in chat_source
    assert 'stream_mode=["custom", "values"]' in stream_source
    assert "rag_workflow.stream(" in stream_source
    assert "def stream_graph_chat_session_events(" not in runtime_source
    assert "def stream_graph_chat_events(" not in runtime_source
    assert "def stream_graph_chat_session_events(" not in orchestrator_source


def test_chat_streaming_langchain_producer_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    stream_source = _source("app/services/chat_stream_langchain.py")

    assert "def produce_langchain_stream_events(" in stream_source
    assert "bind_stream_emitter(" not in chat_source
    assert "reset_stream_emitter(" not in chat_source
    assert "engine.stream_chat(" in stream_source
    assert "bind_stream_emitter(" in stream_source
    assert "reset_stream_emitter(" in stream_source
    assert "def produce_langchain_stream_events(" not in runtime_source


def test_chat_streaming_langchain_session_wrapper_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    stream_source = _source("app/services/chat_stream_langchain.py")
    orchestrator_source = _source("app/services/chat_stream_orchestrator.py")

    assert "def stream_langchain_chat_session_events(" in stream_source
    assert "producer_task = asyncio.create_task(" not in chat_source
    assert "asyncio.wait_for(q.get()" not in chat_source
    assert "def stream_langchain_chat_session_events(" not in runtime_source
    assert "def stream_langchain_chat_session_events(" not in orchestrator_source


def test_chat_stream_sync_persistence_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    persistence_source = _source("app/services/chat_persistence.py")
    stream_persistence_source = _source("app/services/chat_stream_persistence.py")

    assert "def dispatch_chat_stream_persistence(" not in persistence_source
    assert "def persist_chat_stream_turn_sync(" not in persistence_source
    assert "def dispatch_chat_stream_persistence(" in stream_persistence_source
    assert "def persist_chat_stream_turn_sync(" in stream_persistence_source
    assert "persist_chat_stream_turn_sync as _persist_chat_stream_turn_sync" not in chat_source
    assert "persist_chat_stream_turn_background as _persist_chat_stream_turn_background" not in chat_source
    assert "action=CHAT_STREAM_AUDIT_ACTION" not in chat_source
    assert 'action="chat.stream"' in stream_persistence_source
    assert "def dispatch_chat_stream_persistence(" not in runtime_source
    assert "def persist_chat_stream_turn_sync(" not in runtime_source


def test_chat_runtime_metrics_defaults_are_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")

    assert "def apply_chat_runtime_metrics_context(" in runtime_source
    assert 'metrics_data.setdefault("dataset_rag_defaults_applied", True)' not in chat_source
    assert 'metrics_data.setdefault("rag_config_template", rag_config_template_meta)' not in chat_source
    assert 'metrics_data.setdefault("dataset_prompt_defaults_applied", True)' not in chat_source


def test_chat_response_cache_store_helper_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    cache_source = _source("app/services/chat_cache_runtime.py")

    assert "def store_chat_response_cache_if_needed(" not in runtime_source
    assert "def store_chat_response_cache_if_needed(" in cache_source
    assert "cache_payload = jsonable_encoder(" not in chat_source
    assert "set_cached_chat_response(" not in chat_source


def test_chat_non_streaming_persistence_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    persistence_source = _source("app/services/chat_persistence.py")
    turn_persistence_source = _source("app/services/chat_turn_persistence.py")

    assert "def persist_chat_turn_sync(" not in persistence_source
    assert "def build_chat_message_metadata(" not in persistence_source
    assert "def persist_chat_turn_sync(" in turn_persistence_source
    assert "def build_chat_message_metadata(" in turn_persistence_source
    assert "audit_log_event(" not in chat_source
    assert "extract_structured_memory_for_turn(" not in chat_source
    assert "build_chat_audit_details(" not in chat_source
    assert "def persist_chat_turn_sync(" not in runtime_source
    assert "def build_chat_message_metadata(" not in runtime_source


def test_chat_non_streaming_success_finalize_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    persistence_source = _source("app/services/chat_persistence.py")

    assert "finalize_chat_response_sync as _finalize_chat_response_sync" in chat_source
    assert "def finalize_chat_response_sync(" in persistence_source
    assert "maybe_enqueue_online_eval(" not in chat_source
    assert "resolve_inflight_chat_response(" not in chat_source
    assert "def finalize_chat_response_sync(" not in runtime_source


def test_chat_non_streaming_cache_bootstrap_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    cache_source = _source("app/services/chat_cache_runtime.py")

    assert "prepare_non_streaming_chat_cache_state as _prepare_non_streaming_chat_cache_state" in chat_source
    assert "def prepare_non_streaming_chat_cache_state(" not in runtime_source
    assert "def prepare_non_streaming_chat_cache_state(" in cache_source
    assert "singleflight_feature_enabled =" not in chat_source
    assert "await asyncio.shield(inflight_future)" not in chat_source


def test_chat_stream_done_payload_builder_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    stream_source = _source("app/services/chat_stream_common.py")

    assert "def build_chat_stream_done_event(" in stream_source
    assert "done_payload = {" not in chat_source
    assert "def build_chat_stream_done_event(" not in runtime_source


def test_chat_stream_completion_logging_helper_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    stream_source = _source("app/services/chat_stream_common.py")

    assert "def log_chat_stream_completion_metrics(" in stream_source
    assert chat_source.count("log_metrics(") == 0
    assert "def log_chat_stream_completion_metrics(" not in runtime_source


def test_chat_cached_stream_fast_path_is_split_from_main_router_module() -> None:
    chat_source = _source("app/api/v1/chat.py")
    runtime_source = _source("app/services/chat_runtime.py")
    stream_source = _source("app/services/chat_stream_common.py")
    orchestrator_source = _source("app/services/chat_stream_orchestrator.py")

    assert "def stream_cached_chat_events(" in stream_source
    assert "缓存命中，直接返回" not in chat_source
    assert "chunk_size = 120" not in chat_source
    assert "def stream_cached_chat_events(" not in runtime_source
    assert "def stream_cached_chat_events(" not in orchestrator_source
