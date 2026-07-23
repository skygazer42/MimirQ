import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.integrations_conversations as conversations_integration
from app.api.schemas.external_conversation import (
    ExternalConversationIngestRequest,
    ExternalConversationIngestResponse,
    ExternalConversationMessageIn,
)
from app.models.chat import Conversation, Message
from app.services.external_conversation_ingest import (
    _create_external_conversation,
    _existing_source_message_ids,
    _external_message_citation_candidates,
    _find_conversation_by_external_id,
    _mimirq_citations_for_storage,
    _next_message_created_at,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000000")


def _criterion_value(expr):  # noqa: ANN001
    right = getattr(expr, "right", None)
    if hasattr(right, "value"):
        return right.value
    if hasattr(right, "effective_value"):
        return right.effective_value
    return right


def _matches(row: object, expr) -> bool:  # noqa: ANN001
    if isinstance(expr, tuple):
        op, key, value = expr
        if op == "eq":
            return getattr(row, key, None) == value
        if op == "in":
            return getattr(row, key, None) in value
        return True

    operator = getattr(getattr(expr, "operator", None), "__name__", "")
    left = getattr(expr, "left", None)
    key = getattr(left, "key", None)
    if not key:
        return True
    if operator == "eq":
        return getattr(row, key, None) == _criterion_value(expr)
    if operator == "in_op":
        return getattr(row, key, None) in set(_criterion_value(expr) or [])
    return True


class _FieldRef:
    def __init__(self, key: str) -> None:
        self.key = key

    def __eq__(self, other):  # noqa: ANN001
        return ("eq", self.key, other)

    def in_(self, values):  # noqa: ANN001
        return ("in", self.key, set(values))


class _FakeExternalQuery:
    def __init__(self, rows: list[object], *, selected_key: str | None = None) -> None:
        self._rows = list(rows)
        self._filters = []
        self._selected_key = selected_key

    def filter(self, *criteria):  # noqa: ANN001
        self._filters.extend(criteria)
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def _filtered(self) -> list[object]:
        rows = list(self._rows)
        for expr in self._filters:
            rows = [row for row in rows if _matches(row, expr)]
        return rows

    def first(self):
        rows = self._filtered()
        if not rows:
            return None
        row = rows[0]
        if self._selected_key is None:
            return row
        return (getattr(row, self._selected_key),)

    def all(self) -> list[object]:
        rows = self._filtered()
        if self._selected_key is None:
            return rows
        return [(getattr(row, self._selected_key),) for row in rows]


class _FakeExternalDB:
    def __init__(self, *, conversations: list[Conversation], messages: list[object]) -> None:
        self.conversations = list(conversations)
        self.messages = list(messages)
        self.commits = 0

    def query(self, *entities):  # noqa: ANN001
        first = entities[0] if entities else None
        if first is Conversation:
            return _FakeExternalQuery(self.conversations)
        if first is Message:
            return _FakeExternalQuery(self.messages)
        key = getattr(first, "key", None)
        if key in {"conversation_id"}:
            return _FakeExternalQuery(self.messages, selected_key=key)
        if isinstance(first, _FieldRef):
            return _FakeExternalQuery(self.messages, selected_key=first.key)
        return _FakeExternalQuery([])

    def add(self, value: object) -> None:
        if isinstance(value, Conversation):
            if getattr(value, "id", None) is None:
                value.id = uuid4()
            self.conversations.append(value)
            return
        if isinstance(value, Message):
            if getattr(value, "id", None) is None:
                value.id = uuid4()
            self.messages.append(value)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _value: object) -> None:
        return None


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


def test_create_external_conversation_sets_owner_account_id() -> None:
    class _DB:
        def add(self, _value) -> None:  # noqa: ANN001
            return None

        def flush(self) -> None:
            return None

    request = ExternalConversationIngestRequest(
        source="coze",
        source_conversation_id="coze-conv-1",
        messages=[ExternalConversationMessageIn(role="user", content="hello")],
    )

    conversation = _create_external_conversation(
        _DB(),
        tenant_id=TENANT_ID,
        account_id="acct-1",
        request=request,
        dataset_id=None,
        document_ids=[],
    )

    assert conversation.owner_account_id == "acct-1"


def test_find_conversation_by_external_id_is_scoped_to_owner(monkeypatch) -> None:  # noqa: ANN001
    import app.services.external_conversation_ingest as ingest

    monkeypatch.setattr(ingest, "_metadata_text_field", lambda field: _FieldRef(field), raising=True)
    tenant_id = uuid4()
    conversation_a = Conversation(id=uuid4(), tenant_id=tenant_id, owner_account_id="acct-1", document_ids=[])
    conversation_b = Conversation(id=uuid4(), tenant_id=tenant_id, owner_account_id="acct-2", document_ids=[])
    db = _FakeExternalDB(
        conversations=[conversation_a, conversation_b],
        messages=[
            SimpleNamespace(
                tenant_id=tenant_id,
                conversation_id=conversation_a.id,
                source="coze",
                source_conversation_id="shared-conv",
                source_message_id="m-a",
            ),
            SimpleNamespace(
                tenant_id=tenant_id,
                conversation_id=conversation_b.id,
                source="coze",
                source_conversation_id="shared-conv",
                source_message_id="m-b",
            ),
        ],
    )

    found = _find_conversation_by_external_id(
        db,
        tenant_id=tenant_id,
        account_id="acct-2",
        source="coze",
        source_conversation_id="shared-conv",
    )

    assert found is conversation_b


def test_existing_source_message_ids_are_scoped_to_conversation(monkeypatch) -> None:  # noqa: ANN001
    import app.services.external_conversation_ingest as ingest

    monkeypatch.setattr(ingest, "_metadata_text_field", lambda field: _FieldRef(field), raising=True)
    tenant_id = uuid4()
    conversation_a = Conversation(id=uuid4(), tenant_id=tenant_id, owner_account_id="acct-1", document_ids=[])
    conversation_b = Conversation(id=uuid4(), tenant_id=tenant_id, owner_account_id="acct-2", document_ids=[])
    db = _FakeExternalDB(
        conversations=[conversation_a, conversation_b],
        messages=[
            SimpleNamespace(
                tenant_id=tenant_id,
                conversation_id=conversation_a.id,
                source="coze",
                source_conversation_id="shared-conv",
                source_message_id="m-shared",
            ),
            SimpleNamespace(
                tenant_id=tenant_id,
                conversation_id=conversation_b.id,
                source="coze",
                source_conversation_id="shared-conv",
                source_message_id="m-other-owner",
            ),
        ],
    )

    existing = _existing_source_message_ids(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation_a.id,
        source="coze",
        source_conversation_id="shared-conv",
        source_message_ids=["m-shared", "m-other-owner"],
    )

    assert existing == {"m-shared"}


def test_ingest_external_conversation_keeps_owner_scope_for_shared_source_ids(monkeypatch) -> None:  # noqa: ANN001
    import app.services.external_conversation_ingest as ingest

    monkeypatch.setattr(ingest, "_metadata_text_field", lambda field: _FieldRef(field), raising=True)
    monkeypatch.setattr(ingest, "_resolve_document_scope", lambda *_a, **_k: (None, []), raising=True)
    monkeypatch.setattr(ingest, "audit_log_event", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(ingest, "num_tokens_from_string", lambda content: len(str(content or "")), raising=True)

    tenant_id = uuid4()
    request = ExternalConversationIngestRequest(
        source="coze",
        source_conversation_id="shared-conv",
        title="共享会话",
        messages=[
            ExternalConversationMessageIn(
                role="user",
                content="申请材料有哪些？",
                source_message_id="m-shared-1",
            ),
            ExternalConversationMessageIn(
                role="assistant",
                content="请准备身份证和申请表。",
                source_message_id="m-shared-2",
            ),
        ],
    )
    db = _FakeExternalDB(conversations=[], messages=[])

    first = ingest.ingest_external_conversation(
        db=db,
        tenant_id=tenant_id,
        account_id="acct-1",
        request=request,
    )
    second = ingest.ingest_external_conversation(
        db=db,
        tenant_id=tenant_id,
        account_id="acct-2",
        request=request,
    )

    assert first.created_conversation is True
    assert first.inserted_messages == 2
    assert first.skipped_source_message_ids == []
    assert second.created_conversation is True
    assert second.inserted_messages == 2
    assert second.skipped_source_message_ids == []
    assert len(db.conversations) == 2
    assert len(db.messages) == 4
