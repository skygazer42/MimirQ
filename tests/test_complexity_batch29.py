from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from langchain_core.documents import Document

from app.rag.core import vision_reader
from app.rag.embedding.providers import _embedding_http
from app.rag.kg.search.graph_embeddings import (
    WalkHashParams,
    build_entity_event_adjacency,
    compute_walkhash_embeddings,
)


@dataclass
class _EventLink:
    entity_id: str


def _import_kg_pipeline():
    return importlib.import_module("app.rag.kg.pipeline")


def test_compute_walkhash_embeddings_is_deterministic_and_normalized() -> None:
    neighbors = [[1, 2], [0, 2], [0, 1], []]
    params = WalkHashParams(dim=8, num_walks=3, walk_length=4, window_size=2, seed=11)

    first = compute_walkhash_embeddings(neighbors=neighbors, params=params)
    second = compute_walkhash_embeddings(neighbors=neighbors, params=params)

    assert first.shape == (4, 8)
    assert first.tolist() == second.tolist()
    assert pytest.approx(float((first[0] ** 2).sum()), rel=1e-6) == 1.0
    assert first[3].tolist() == [0.0] * 8


def test_build_entity_event_adjacency_keeps_seed_nodes_and_filters_links() -> None:
    adjacency = build_entity_event_adjacency(
        seed_entity_ids=["seed", ""],
        event_ids=["evt-1", "evt-2", ""],
        event_entity_links={
            "evt-1": [_EventLink(entity_id="seed"), _EventLink(entity_id="drop")],
            "ev:evt-2": [_EventLink(entity_id="kept")],
        },
        kept_entity_ids={"seed", "kept"},
        relation_edges=[("seed", "kept"), ("seed", "drop")],
    )

    assert adjacency == {
        "ent:kept": ["ent:seed", "ev:evt-2"],
        "ent:seed": ["ent:kept", "ev:evt-1"],
        "ev:evt-1": ["ent:seed"],
        "ev:evt-2": ["ent:kept"],
    }


class _StaticQuery:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def filter(self, *args: object, **kwargs: object) -> "_StaticQuery":
        return self

    def all(self) -> list[object]:
        return list(self._rows)


class _StaticDB:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows
        self.closed = False

    def query(self, *args: object, **kwargs: object) -> _StaticQuery:
        return _StaticQuery(self._rows)

    def close(self) -> None:
        self.closed = True


def test_merge_kg_dataset_shard_results_prefers_highest_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    kg_pipeline = _import_kg_pipeline()
    monkeypatch.setattr(kg_pipeline.settings, "KG_SEARCH_MULTI_DATASET_MAX_EVENTS", 3, raising=False)
    monkeypatch.setattr(kg_pipeline.settings, "KG_SEARCH_MULTI_DATASET_MAX_ENTITIES", 2, raising=False)

    dataset_a = uuid4()
    dataset_b = uuid4()
    merged = kg_pipeline._merge_kg_dataset_shard_results(
        [
            (
                dataset_a,
                {
                    "events": [{"id": "evt-1", "score": 0.4}, {"id": "evt-2", "score": 0.3}],
                    "entities": [{"entity_id": "ent-1", "score": 0.2}],
                    "clues": ["alpha"],
                    "community_reports": ["report-a"],
                    "global_summary": "summary-a",
                },
                None,
            ),
            (
                dataset_b,
                {
                    "events": [{"id": "evt-1", "score": 0.9}],
                    "entities": [{"entity_id": "ent-1", "score": 0.6}, {"entity_id": "ent-2", "score": 0.5}],
                    "clues": ["alpha", "beta"],
                    "community_reports": ["report-b"],
                    "global_summary": "summary-b",
                },
                None,
            ),
        ]
    )

    assert [item["id"] for item in merged["events"]] == ["evt-1", "evt-2"]
    assert merged["events"][0]["dataset_id"] == str(dataset_b)
    assert [item["entity_id"] for item in merged["entities"]] == ["ent-1", "ent-2"]
    assert merged["clues"] == ["alpha", "beta"]
    assert merged["community_reports"] == ["report-a", "report-b"]
    assert merged["global_summary"] == "summary-a\n\nsummary-b"
    assert merged["stats"]["dataset_shards_with_events"] == 2
    assert merged["stats"]["dataset_shard_errors"] == 0


@pytest.mark.asyncio
async def test_kg_search_classifier_disabled_annotates_query_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kg_pipeline = _import_kg_pipeline()

    class _Engine:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def search(self, **kwargs: object) -> dict[str, object]:
            self.calls.append(kwargs)
            return {"stats": {"existing": True}}

    engine = _Engine()
    monkeypatch.setattr(kg_pipeline, "_load_engine", lambda: engine)
    monkeypatch.setattr(kg_pipeline.settings, "KG_SEARCH_QUERY_MODE_DEFAULT", "auto", raising=False)
    monkeypatch.setattr(
        kg_pipeline.settings,
        "KG_SEARCH_QUERY_MODE_CLASSIFIER_ENABLED",
        False,
        raising=False,
    )
    monkeypatch.setattr(kg_pipeline.settings, "KG_SEARCH_CACHE_ENABLED", False, raising=False)

    result = await kg_pipeline.kg_search(query="overall status", query_mode="auto")

    assert engine.calls[0]["query_mode"] == "auto"
    assert engine.calls[0]["query_mode_confidence"] == "disabled"
    assert engine.calls[0]["query_mode_reason_codes"] == ["query_mode_classifier_disabled"]
    assert result["query_mode"] == {
        "requested": "auto",
        "resolved": "auto",
        "confidence": "disabled",
        "reason_codes": ["query_mode_classifier_disabled"],
    }
    assert result["stats"]["query_mode"] == "auto"


class _SyncSequenceClient:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        outcome = self._outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _AsyncSequenceClient:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        outcome = self._outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _http_response(status_code: int, *, json_body: dict[str, object] | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://example.invalid/embeddings")
    if json_body is None:
        json_body = {"status": status_code}
    return httpx.Response(status_code, json=json_body, request=request)


def test_post_with_retries_sync_retries_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    response_429 = _http_response(429)
    response_429.headers["Retry-After"] = "1.25"
    response_200 = _http_response(200, json_body={"ok": True})
    client = _SyncSequenceClient([response_429, response_200])
    slept: list[float] = []

    monkeypatch.setattr(_embedding_http.settings, "EMBEDDING_API_MAX_RETRIES", 2, raising=False)
    monkeypatch.setattr(_embedding_http.settings, "EMBEDDING_API_RETRY_BACKOFF_SEC", 0.5, raising=False)
    monkeypatch.setattr(_embedding_http.settings, "EMBEDDING_API_RETRY_JITTER_SEC", 0.0, raising=False)
    monkeypatch.setattr(_embedding_http, "secure_jitter", lambda _value: 0.0)
    monkeypatch.setattr(_embedding_http.time, "sleep", slept.append)

    parsed = _embedding_http.post_with_retries_sync(
        client=client,
        url="https://example.invalid/embeddings",
        request_kwargs={},
        parse_response=lambda resp: resp.json()["ok"],
        concurrency=_embedding_http.EmbeddingHTTPConcurrency("test"),
        schema_errors=(ValueError,),
    )

    assert parsed is True
    assert client.calls == 2
    assert slept == [1.25]
    assert response_429.is_closed is True


@pytest.mark.asyncio
async def test_post_with_retries_async_retries_request_error(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://example.invalid/embeddings")
    response_200 = _http_response(200, json_body={"ok": "done"})
    client = _AsyncSequenceClient([httpx.ReadTimeout("timeout", request=request), response_200])
    slept: list[float] = []

    monkeypatch.setattr(_embedding_http.settings, "EMBEDDING_API_MAX_RETRIES", 1, raising=False)
    monkeypatch.setattr(_embedding_http.settings, "EMBEDDING_API_RETRY_BACKOFF_SEC", 0.25, raising=False)
    monkeypatch.setattr(_embedding_http.settings, "EMBEDDING_API_RETRY_JITTER_SEC", 0.0, raising=False)
    monkeypatch.setattr(_embedding_http, "secure_jitter", lambda _value: 0.0)

    async def _sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(_embedding_http.asyncio, "sleep", _sleep)

    parsed = await _embedding_http.post_with_retries_async(
        client=client,
        url="https://example.invalid/embeddings",
        request_kwargs={},
        parse_response=lambda resp: resp.json()["ok"],
        concurrency=_embedding_http.EmbeddingHTTPConcurrency("test"),
        schema_errors=(ValueError,),
    )

    assert parsed == "done"
    assert client.calls == 2
    assert slept == [0.25]


class _StreamResponse:
    def __init__(self, lines: list[str], *, status_code: int = 200) -> None:
        self.status_code = status_code
        self._lines = lines

    async def __aenter__(self) -> "_StreamResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _VisionHTTPClient:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.calls: list[dict[str, object]] = []

    def stream(self, method: str, url: str, **kwargs: object) -> _StreamResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return _StreamResponse(self.lines)


@pytest.mark.asyncio
async def test_stream_vision_chat_completions_tokens_ignores_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vision_reader.settings, "VISION_LLM_API_KEY", "vision-key", raising=False)
    monkeypatch.setattr(vision_reader.settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(vision_reader.settings, "VISION_LLM_API_BASE", "https://vision.example/v1", raising=False)
    monkeypatch.setattr(vision_reader.settings, "LLM_API_BASE", "", raising=False)
    monkeypatch.setattr(vision_reader.settings, "VISION_LLM_MODEL", "vision-model", raising=False)
    monkeypatch.setattr(vision_reader.settings, "VISION_LLM_MAX_TOKENS", 128, raising=False)
    monkeypatch.setattr(vision_reader.settings, "VISION_LLM_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(vision_reader.settings, "VISION_LLM_TIMEOUT_SEC", 30, raising=False)

    client = _VisionHTTPClient(
        [
            "",
            "event: ping",
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            "data: not-json",
            'data: {"choices":[{"delta":{"content":" world"}}]}',
            "data: [DONE]",
        ]
    )

    chunks = [
        token
        async for token in vision_reader.stream_vision_chat_completions_tokens(
            http_client=client,
            messages=[{"role": "user", "content": "hi"}],
        )
    ]

    assert chunks == ["Hello", " world"]
    assert client.calls[0]["method"] == "POST"
    assert client.calls[0]["url"] == "https://vision.example/v1/chat/completions"


@pytest.mark.asyncio
async def test_build_vision_reader_context_docs_truncates_and_preserves_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vision_reader.settings, "VISION_RAG_READER_ENABLED", True, raising=False)
    monkeypatch.setattr(vision_reader.settings, "VISION_LLM_ENABLED", True, raising=False)
    monkeypatch.setattr(vision_reader.settings, "VISION_RAG_READER_MAX_IMAGES", 2, raising=False)
    monkeypatch.setattr(
        vision_reader.settings,
        "VISION_RAG_READER_MAX_IMAGE_BYTES",
        100,
        raising=False,
    )
    monkeypatch.setattr(
        vision_reader.settings,
        "VISION_RAG_READER_MAX_OUTPUT_CHARS",
        12,
        raising=False,
    )
    monkeypatch.setattr(vision_reader.settings, "VISION_LLM_MODEL", "vision-model", raising=False)

    async def _load_image_bytes(**kwargs: object) -> tuple[bytes | None, str]:
        meta = kwargs["meta"]
        if meta.get("image_id") == "missing":
            return None, "local_missing_or_too_large"
        return b"\xff\xd8\xffdemo", "local"

    async def _describe(**kwargs: object) -> str:
        return "important extracted content"

    monkeypatch.setattr(vision_reader, "_load_image_bytes", _load_image_bytes)
    monkeypatch.setattr(vision_reader, "_describe_with_vision_llm", _describe)

    docs, meta = await vision_reader.build_vision_reader_context_docs(
        image_docs=[
            Document(
                page_content="",
                metadata={"image_id": "img-1", "chunk_id": "orig-1", "source": "chart.png"},
                id="orig-1",
            ),
            Document(page_content="", metadata={"image_id": "missing"}, id="orig-2"),
        ],
        question="What changed?",
        tenant_id=uuid4(),
        http_client=SimpleNamespace(),
    )

    assert len(docs) == 1
    assert docs[0].page_content == "important ex\n\n(truncated)"
    assert docs[0].metadata["retrieval_role"] == "vision_reader"
    assert docs[0].metadata["origin_chunk_id"] == "orig-1"
    assert docs[0].metadata["neighbor_of"] == "orig-1"
    assert meta["used"] is True
    assert meta["attempted"] == 2
    assert meta["succeeded"] == 1
    assert meta["skipped"] == 1
    assert meta["errors"] == ["skip:local_missing_or_too_large"]
