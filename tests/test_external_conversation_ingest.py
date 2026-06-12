from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.integrations_conversations as conversations_integration
from app.api.schemas.external_conversation import ExternalConversationIngestResponse
from app.services.external_conversation_ingest import _mimirq_citations_for_storage, _next_message_created_at

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


def test_external_message_created_at_preserves_request_order():
    imported_at = datetime(2026, 6, 12, 3, 0, 0, tzinfo=UTC)
    older_external_time = imported_at - timedelta(hours=1)

    first = _next_message_created_at(None, imported_at=imported_at, previous_at=None)
    second = _next_message_created_at(None, imported_at=imported_at, previous_at=first)
    third = _next_message_created_at(older_external_time, imported_at=imported_at, previous_at=second)

    assert first == imported_at
    assert second == first + timedelta(microseconds=1)
    assert third == second + timedelta(microseconds=1)
