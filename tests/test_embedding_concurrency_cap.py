from __future__ import annotations

import concurrent.futures
import threading

from tests.helpers.async_utils import yield_control


def test_embedding_concurrency_cap_limits_in_flight_requests(monkeypatch):  # noqa: ANN001
    """
    O20 regression test: concurrent embedding requests should obey a cap.

    Why:
    - Ingest can enqueue multiple embedding calls concurrently (workers / retries / multi-doc).
    - Without a cap, we can spike outbound requests and trigger 429s.
    """
    import app.rag.embedding.providers.openai as provider
    from app.core.config import settings

    # Keep the test fully local/deterministic.
    monkeypatch.setattr(settings, "EMBEDDING_API_MAX_CONCURRENCY", 2, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_MAX_RETRIES", 0, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_BATCH_SIZE", 1000, raising=False)

    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()
    two_started = threading.Event()
    release = threading.Event()

    class _DummyResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload
            self.status_code = 200
            self.headers: dict[str, str] = {}

        def raise_for_status(self) -> None:
            return None

        def json(self):  # noqa: ANN201
            return self._payload

        def close(self) -> None:
            return None

    class _DummySyncClient:
        def post(self, _url: str, *, json: dict, headers: dict, timeout=None):  # noqa: ANN201, ANN001
            _ = json
            _ = headers
            _ = timeout

            nonlocal in_flight, max_in_flight
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
                if in_flight == 2:
                    two_started.set()

            # Block until the test releases all in-flight calls.
            release.wait(timeout=5)

            with lock:
                in_flight -= 1

            return _DummyResponse({"data": [{"embedding": [0.1, 0.2]}]})

    class _DummyAsyncClient:
        async def post(self, _url: str, *, json: dict, headers: dict, timeout=None):  # noqa: ANN201, ANN001
            await yield_control()
            _ = json
            _ = headers
            _ = timeout
            raise RuntimeError("Async client should not be used in this sync test")

    dummy_sync = _DummySyncClient()
    dummy_async = _DummyAsyncClient()

    class _FakePool:
        def get_external_sync_client(self):  # noqa: ANN201
            return dummy_sync

        def get_external_async_client(self):  # noqa: ANN201
            return dummy_async

    monkeypatch.setattr(provider, "get_http_client_pool", lambda: _FakePool(), raising=False)

    model = provider.OpenAICompatibleEmbedding(
        model="m",
        base_url="https://example.com/v1/embeddings",
        api_key="no_api_key",
    )

    def _run_one():  # noqa: ANN202
        return model.encode("hello")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_run_one) for _ in range(5)]
        assert two_started.wait(timeout=5), "Expected at least 2 in-flight embedding calls"
        release.set()
        results = [f.result(timeout=5) for f in futures]

    assert max_in_flight <= 2, f"Expected cap=2, saw max_in_flight={max_in_flight}"
    assert all(r == [[0.1, 0.2]] for r in results)

