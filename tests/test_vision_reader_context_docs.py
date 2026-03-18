from __future__ import annotations

import json
import uuid

import httpx
import pytest
from langchain_core.documents import Document


@pytest.mark.asyncio
async def test_vision_reader_injects_docs_and_keeps_image_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.core.vision_reader import build_vision_reader_context_docs

    monkeypatch.setattr(settings, "VISION_RAG_READER_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_API_BASE", "http://test/v1", raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_MODEL", "gpt-4o-mini", raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_TIMEOUT_SEC", 10, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_MAX_TOKENS", 64, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(settings, "VISION_RAG_READER_MAX_IMAGES", 2, raising=False)
    monkeypatch.setattr(settings, "VISION_RAG_READER_MAX_IMAGE_BYTES", 1_000_000, raising=False)
    monkeypatch.setattr(settings, "VISION_RAG_READER_MAX_OUTPUT_CHARS", 500, raising=False)

    async def _fake_load_image_bytes(*, meta, tenant_id, max_bytes):  # noqa: ANN001
        # Minimal PNG-ish header so MIME guessing is deterministic.
        return b"\x89PNG\r\n\x1a\n" + b"123", "mock"

    monkeypatch.setattr("app.rag.core.vision_reader._load_image_bytes", _fake_load_image_bytes)

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads((request.content or b"{}").decode("utf-8", "ignore") or "{}")
        assert body["model"] == "gpt-4o-mini"
        content = body["messages"][0]["content"]
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        return httpx.Response(200, json={"choices": [{"message": {"content": "The chart indicates 42 kWh."}}]})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        origin_chunk_id = "00000000-0000-0000-0000-000000000001"
        image_docs = [
            Document(
                page_content="image",
                metadata={
                    "retrieval_role": "image",
                    "doc_type_kwd": "image",
                    "img_id": "t:d:d:1",
                    "document_id": "00000000-0000-0000-0000-000000000010",
                    "chunk_id": origin_chunk_id,
                    "chunk_index": 1,
                    "source": "foo.pdf",
                },
                id=origin_chunk_id,
            )
        ]

        out, meta = await build_vision_reader_context_docs(
            image_docs=image_docs,
            question="What does the chart show?",
            tenant_id=None,
            http_client=client,
        )

    assert meta["enabled"] is True
    assert meta["used"] is True
    assert meta["attempted"] == 1
    assert meta["returned"] == 1
    assert meta["model"] == "gpt-4o-mini"

    assert len(out) == 1
    vdoc = out[0]
    assert "42" in vdoc.page_content
    assert vdoc.metadata["retrieval_role"] == "vision_reader"
    assert vdoc.metadata["doc_type_kwd"] == "image"
    assert vdoc.metadata["img_id"] == "t:d:d:1"
    assert vdoc.metadata["origin_chunk_id"] == origin_chunk_id
    # Synthetic chunk id should still be UUID-like.
    uuid.UUID(str(vdoc.id))


@pytest.mark.asyncio
async def test_vision_reader_skips_no_relevant_info(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.core.vision_reader import build_vision_reader_context_docs

    monkeypatch.setattr(settings, "VISION_RAG_READER_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_API_BASE", "http://test/v1", raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_MODEL", "gpt-4o-mini", raising=False)

    async def _fake_load_image_bytes(*, meta, tenant_id, max_bytes):  # noqa: ANN001
        return b"\xff\xd8\xff" + b"123", "mock"

    monkeypatch.setattr("app.rag.core.vision_reader._load_image_bytes", _fake_load_image_bytes)

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "NO_RELEVANT_INFO"}}]})

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        image_docs = [
            Document(page_content="image", metadata={"retrieval_role": "image", "img_id": "t:d:d:1"}, id="x")
        ]
        out, meta = await build_vision_reader_context_docs(
            image_docs=image_docs,
            question="irrelevant",
            tenant_id=None,
            http_client=client,
        )

    assert meta["enabled"] is True
    assert meta["used"] is False
    assert out == []
