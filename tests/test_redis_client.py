import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from app.core.redis_client import LazyRedisClient


def test_lazy_redis_client_builds_once_and_rebuilds_after_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redis

    calls: list[tuple[str, dict[str, object]]] = []

    def from_url(url: str, **kwargs: object) -> object:
        client = object()
        calls.append((url, dict(kwargs)))
        return client

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(from_url))
    slot = LazyRedisClient(
        url=lambda: "redis://cache/4",
        kwargs={"decode_responses": False, "socket_timeout": 1},
    )

    first = slot.get()
    assert slot.get() is first
    assert calls == [("redis://cache/4", {"decode_responses": False, "socket_timeout": 1})]

    slot.invalidate()
    assert slot.get() is not first
    assert len(calls) == 2


def test_lazy_redis_client_serializes_concurrent_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redis

    calls = 0
    calls_lock = threading.Lock()
    client = object()

    def from_url(_url: str, **_kwargs: object) -> object:
        nonlocal calls
        with calls_lock:
            calls += 1
        return client

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(from_url))
    slot = LazyRedisClient(url=lambda: "redis://cache/0")

    with ThreadPoolExecutor(max_workers=8) as executor:
        clients = list(executor.map(lambda _index: slot.get(), range(32)))

    assert all(item is client for item in clients)
    assert calls == 1


def test_lazy_redis_client_respects_gate_and_suppresses_init_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import redis

    errors: list[Exception] = []
    enabled = False

    def from_url(_url: str, **_kwargs: object) -> object:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(from_url))
    slot = LazyRedisClient(
        url=lambda: "redis://cache/0",
        enabled=lambda: enabled,
        on_error=errors.append,
    )

    assert slot.get() is None
    enabled = True
    assert slot.get() is None
    assert [str(error) for error in errors] == ["redis unavailable"]


def test_lazy_redis_client_can_propagate_init_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import redis

    monkeypatch.setattr(
        redis.Redis,
        "from_url",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))),
    )
    slot = LazyRedisClient(
        url=lambda: "redis://cache/0",
        suppress_errors=False,
    )

    with pytest.raises(RuntimeError, match="boom"):
        slot.get()


@pytest.mark.parametrize(
    ("module_name", "expected_kwargs"),
    [
        (
            "app.api.v1.health",
            {"socket_timeout": 1, "socket_connect_timeout": 1, "decode_responses": True},
        ),
        (
            "app.rag.retrieval_candidate_cache",
            {"socket_timeout": 1, "socket_connect_timeout": 1, "decode_responses": False},
        ),
        (
            "app.rag.rerank_result_cache",
            {"socket_timeout": 1, "socket_connect_timeout": 1, "decode_responses": False},
        ),
        (
            "app.rag.embedding.adapter",
            {"socket_timeout": 1, "socket_connect_timeout": 1, "decode_responses": False},
        ),
        (
            "app.services.chat_response_cache",
            {"socket_timeout": 1, "socket_connect_timeout": 1, "decode_responses": False},
        ),
        (
            "app.services.semantic_cache",
            {"socket_timeout": 1, "socket_connect_timeout": 1, "decode_responses": False},
        ),
        ("app.services.saml_replay_service", {"decode_responses": False}),
        (
            "app.services.embedding_migration",
            {"socket_timeout": 1, "socket_connect_timeout": 1, "decode_responses": False},
        ),
    ],
)
def test_redis_consumers_preserve_connection_options(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    expected_kwargs: dict[str, Any],
) -> None:
    import redis

    module = importlib.import_module(module_name)
    slot = module._redis_client_slot
    slot.invalidate()
    monkeypatch.setattr(module.settings, "REDIS_URL", "redis://cache/7", raising=False)
    if module_name == "app.services.saml_replay_service":
        monkeypatch.setattr(module.settings, "SAML_REPLAY_REDIS_ENABLED", True, raising=False)

    calls: list[tuple[str, dict[str, Any]]] = []
    client = object()

    def from_url(url: str, **kwargs: Any) -> object:
        calls.append((url, kwargs))
        return client

    monkeypatch.setattr(redis.Redis, "from_url", staticmethod(from_url))

    try:
        assert module._get_redis_client() is client
        assert module._get_redis_client() is client
        assert calls == [("redis://cache/7", expected_kwargs)]
    finally:
        slot.invalidate()
