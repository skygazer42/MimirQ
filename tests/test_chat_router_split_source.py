from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_chat_summary_checkpoint_routes_are_split_from_main_router() -> None:
    chat_source = _source("app/api/v1/chat.py")
    split_source = _source("app/api/v1/chat_conversation_memory.py")

    assert "from app.api.v1 import chat_conversation_memory" in chat_source
    assert "router.include_router(chat_conversation_memory.router)" in chat_source

    split_route_decorators = (
        '@router.get("/conversations/{conversation_id}/summary"',
        '@router.post("/conversations/{conversation_id}/summary/update"',
        '@router.delete("/conversations/{conversation_id}/summary"',
        '@router.get("/conversations/{conversation_id}/rag-traces"',
        '@router.get("/conversations/{conversation_id}/checkpoints"',
        '@router.get("/conversations/{conversation_id}/checkpoints/{checkpoint_id}"',
        '@router.delete("/conversations/{conversation_id}/checkpoints"',
    )
    for decorator in split_route_decorators:
        assert decorator not in chat_source
        assert decorator in split_source


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
