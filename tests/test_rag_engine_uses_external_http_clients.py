from __future__ import annotations


def test_rag_engine_uses_external_http_clients(monkeypatch):
    import app.rag.engine as eng

    class FakePool:
        def __init__(self) -> None:
            self.sync = 0
            self.async_ = 0
            self.ext_sync = 0
            self.ext_async = 0

        def get_sync_client(self):  # noqa: ANN201
            self.sync += 1
            return object()

        def get_async_client(self):  # noqa: ANN201
            self.async_ += 1
            return object()

        def get_external_sync_client(self):  # noqa: ANN201
            self.ext_sync += 1
            return object()

        def get_external_async_client(self):  # noqa: ANN201
            self.ext_async += 1
            return object()

    pool = FakePool()
    monkeypatch.setattr(eng, "get_http_client_pool", lambda: pool)

    # Avoid real LLM initialization / network calls.
    monkeypatch.setattr(eng.settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(eng.settings, "LLM_MOCK_RESPONSE", "ok", raising=False)
    monkeypatch.setattr(eng.settings, "ENABLE_DYNAMIC_MODEL_ROUTING", False, raising=False)
    monkeypatch.setattr(eng.settings, "LLM_MODEL", "dummy", raising=False)

    eng.RAGEngine()

    assert pool.ext_sync == 1
    assert pool.ext_async == 1
    assert pool.sync == 0
    assert pool.async_ == 0

