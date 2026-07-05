from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.integrations_conversations as conversations_integration
from app.api.schemas.external_conversation import ExternalConversationIngestResponse
from app.services.external_conversation_ingest import (
    _external_message_citation_candidates,
    _mimirq_citations_for_storage,
    _next_message_created_at,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000000")


def _client(monkeypatch):
    app = FastAPI()
    app.include_router(conversations_integration.router, prefix="/api/v1/integrations/conversations")
    app.dependency_overrides[conversations_integration.get_tenant_id] = lambda: TENANT_ID
    app.dependency_overrides[conversations_integration.get_current_account_id] = lambda: "demo"
    app.dependency_overrides[conversations_integration.get_db] = lambda: object()

    captured = {}

    def fake_ingest_external_conversation(**kwargs):  # noqa: ANN001
        request = kwargs["request"]
        captured["request"] = request
        return ExternalConversationIngestResponse(
            conversation_id=uuid4(),
            created_conversation=True,
            source=request.source,
            source_conversation_id=request.source_conversation_id,
            inserted_messages=len(request.messages),
            skipped_messages=0,
            message_ids=[uuid4() for _ in request.messages],
            skipped_source_message_ids=[],
        )

    monkeypatch.setattr(
        conversations_integration,
        "ingest_external_conversation",
        fake_ingest_external_conversation,
    )
    return TestClient(app), captured


def test_external_conversation_ingest_is_source_generic(monkeypatch):
    client, captured = _client(monkeypatch)

    response = client.post(
        "/api/v1/integrations/conversations/ingest",
        json={
            "source": "Coze",
            "source_conversation_id": "coze-conv-1",
            "title": "外部机器人会话",
            "messages": [
                {
                    "role": "user",
                    "content": "怎么办理公积金缓缴？",
                    "source_message_id": "m-user-1",
                },
                {
                    "role": "assistant",
                    "content": "请准备申请材料并按流程提交。",
                    "source_message_id": "m-assistant-1",
                    "citations": [{"document_name": "公积金知识"}],
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "coze"
    assert body["source_conversation_id"] == "coze-conv-1"
    assert body["inserted_messages"] == 2
    assert captured["request"].source == "coze"


def test_external_conversation_ingest_can_ack_async_for_dify(monkeypatch):
    client, captured = _client(monkeypatch)
    queued_calls = []

    def fake_enqueue(**kwargs):  # noqa: ANN001
        queued_calls.append(kwargs)

    monkeypatch.setattr(
        conversations_integration,
        "_enqueue_external_conversation_ingest",
        fake_enqueue,
    )

    response = client.post(
        "/api/v1/integrations/conversations/ingest",
        headers={"X-MimirQ-Async-Ingest": "true"},
        json={
            "source": "dify",
            "source_conversation_id": "dify-conv-1",
            "source_run_id": "run-1",
            "messages": [
                {
                    "role": "user",
                    "content": "普通话考试要带什么？",
                    "source_message_id": "m-user-1",
                },
                {
                    "role": "assistant",
                    "content": "请携带身份证、准考证等材料。",
                    "source_message_id": "m-assistant-1",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["queued"] is True
    assert body["source"] == "dify"
    assert body["source_conversation_id"] == "dify-conv-1"
    assert "request_id" in body
    assert "conversation_id" not in body
    assert captured == {}
    assert len(queued_calls) == 1
    assert queued_calls[0]["request_body"].source == "dify"


def test_external_conversation_ingest_rejects_unsafe_source(monkeypatch):
    client, _ = _client(monkeypatch)

    response = client.post(
        "/api/v1/integrations/conversations/ingest",
        json={
            "source": "dify/drop table",
            "source_conversation_id": "conv-1",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 422


def test_external_citations_are_stored_only_when_mimirq_schema_compatible():
    valid = {
        "document_id": "00000000-0000-0000-0000-000000000001",
        "chunk_id": "00000000-0000-0000-0000-000000000002",
        "chunk_content": "evidence",
        "document_name": "doc",
    }
    external_only = {"document_name": "外部引用", "url": "https://example.invalid"}

    assert _mimirq_citations_for_storage([valid, external_only]) == [valid]


def test_external_conversation_ingest_normalizes_dify_http_records_from_metadata():
    record = {
        "content": "排污许可证办理、环保税税源采集、自动监测设备联网。",
        "title": "重点排污单位税费缴纳一件事",
        "score": 0.92,
        "metadata": {
            "document_id": "00000000-0000-0000-0000-000000000001",
            "chunk_id": "00000000-0000-0000-0000-000000000002",
            "chunk_index": 7,
            "page_number": 2,
            "header_path": "02高效办成一件事 / 重点排污单位税费缴纳",
            "hit_type": "hybrid",
        },
    }

    candidates = _external_message_citation_candidates([], {"retrieval_records": [record]})
    stored = _mimirq_citations_for_storage(candidates)

    assert stored == [
        {
            "document_id": "00000000-0000-0000-0000-000000000001",
            "chunk_id": "00000000-0000-0000-0000-000000000002",
            "chunk_content": "排污许可证办理、环保税税源采集、自动监测设备联网。",
            "document_name": "重点排污单位税费缴纳一件事",
            "chunk_index": 7,
            "page_number": 2,
            "header_path": "02高效办成一件事 / 重点排污单位税费缴纳",
            "hit_type": "hybrid",
            "relevance_score": 0.92,
        }
    ]


def test_external_conversation_ingest_accepts_serialized_retrieval_records():
    record = {
        "content": "网上申请调解后，不影响当事人依法行使诉权。",
        "title": "常州市本级12345QA.txt",
        "metadata": {
            "document_id": "00000000-0000-0000-0000-000000000011",
            "chunk_id": "00000000-0000-0000-0000-000000000012",
            "mimirq_score": 0.84,
            "source_record_id": "qa-1",
        },
    }

    candidates = _external_message_citation_candidates([], {"retrieval_records": json.dumps([record])})
    stored = _mimirq_citations_for_storage(candidates)

    assert stored[0]["document_id"] == "00000000-0000-0000-0000-000000000011"
    assert stored[0]["chunk_id"] == "00000000-0000-0000-0000-000000000012"
    assert stored[0]["chunk_content"] == "网上申请调解后，不影响当事人依法行使诉权。"
    assert stored[0]["document_name"] == "常州市本级12345QA.txt"
    assert stored[0]["relevance_score"] == 0.84


def test_external_message_created_at_preserves_request_order():
    imported_at = datetime(2026, 6, 12, 3, 0, 0, tzinfo=UTC)
    older_external_time = imported_at - timedelta(hours=1)

    first = _next_message_created_at(None, imported_at=imported_at, previous_at=None)
    second = _next_message_created_at(None, imported_at=imported_at, previous_at=first)
    third = _next_message_created_at(older_external_time, imported_at=imported_at, previous_at=second)

    assert first == imported_at
    assert second == first + timedelta(microseconds=1)
    assert third == second + timedelta(microseconds=1)
