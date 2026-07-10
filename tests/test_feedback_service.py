
import uuid
from datetime import UTC, datetime, timedelta

from app.models.chat import Conversation, Message
from app.models.feedback import MessageFeedback
from app.rag.trace_schema import RagTrace, RagTraceListResponse
from app.services.feedback_service import FeedbackService


class _FakeQuery:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def filter(self, *args, **kwargs):  # noqa: ANN001,D401
        try:
            from sqlalchemy.sql.elements import BinaryExpression
        except Exception:  # pragma: no cover
            return self
        items = list(self._items)
        for cond in args:
            if not isinstance(cond, BinaryExpression):
                continue
            key = getattr(getattr(cond, "left", None), "key", None)
            value = getattr(getattr(cond, "right", None), "value", None)
            op_name = getattr(getattr(cond, "operator", None), "__name__", "")
            if not key:
                continue
            if op_name == "eq":
                items = [row for row in items if getattr(row, key, None) == value]
            elif op_name == "ge":
                items = [row for row in items if getattr(row, key, None) >= value]
            elif op_name == "le":
                items = [row for row in items if getattr(row, key, None) <= value]
            elif op_name == "in_op":
                values = set(value or [])
                items = [row for row in items if getattr(row, key, None) in values]
        self._items = items
        return self

    def first(self):  # noqa: D401
        return self._items[0] if self._items else None

    def all(self):  # noqa: D401
        return list(self._items)


class _FakeDB:
    def __init__(self, *, feedback_rows, messages, conversations):  # noqa: ANN001
        self._rows = {
            MessageFeedback: list(feedback_rows or []),
            Message: list(messages or []),
            Conversation: list(conversations or []),
        }

    def query(self, model):  # noqa: ANN001
        return _FakeQuery(self._rows.get(model, []))

    def add(self, obj):  # noqa: ANN001
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        self._rows.setdefault(type(obj), []).append(obj)

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def test_upsert_message_feedback_persists_trace_and_snapshot_metadata() -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    request_id = "req-feedback-service-1"
    now = datetime.now(UTC)
    assistant_msg = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="assistant",
        content="hello",
        citations=[],
        message_metadata={"dataset_id": str(dataset_id), "request_id": request_id},
        created_at=now,
    )
    conv = Conversation(
        id=conversation_id,
        tenant_id=tenant_id,
        user_id=None,
        dataset_id=dataset_id,
        title="demo",
        document_ids=[],
        message_count=1,
        created_at=now,
        updated_at=now,
    )
    db = _FakeDB(feedback_rows=[], messages=[assistant_msg], conversations=[conv])

    row = FeedbackService.upsert_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id="u",
        message_id=assistant_msg.id,
        rating=2,
        reason="missing detail",
        tags=["negative"],
        expected_answer="expected",
        extra={"from": "test"},
        ensure_member_fn=lambda *_args, **_kwargs: None,
        list_rag_traces_fn=lambda **_kwargs: RagTraceListResponse(
            enabled=True,
            path="/tmp/fake.jsonl",
            window_minutes=60,
            truncated=False,
            returned=1,
            items=[
                RagTrace(
                    ts_ms=1,
                    request_id=request_id,
                    conversation_id=str(conversation_id),
                    retrieval={"retrieval_config_hash": "cfg-feedback-service-1"},
                    citations=[],
                    citations_count=0,
                )
            ],
        ),
    )

    assert row.rating == 2
    assert row.reason == "missing detail"
    assert row.extra["dataset_id"] == str(dataset_id)
    assert row.extra["retrieval_trace_request_id"] == request_id
    assert row.extra["retrieval_trace"]["request_id"] == request_id
    assert row.extra["rag_config_snapshot"]["retrieval_config_hash"] == "cfg-feedback-service-1"
    assert len(db._rows[MessageFeedback]) == 1


def test_list_message_feedback_enriched_filters_sorts_and_truncates() -> None:
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    conversation_a = uuid.uuid4()
    conversation_b = uuid.uuid4()
    now = datetime.now(UTC)
    long_content = "x" * 5000

    conv_a = Conversation(
        id=conversation_a,
        tenant_id=tenant_id,
        user_id=None,
        dataset_id=None,
        title="Conversation A",
        document_ids=[],
        message_count=2,
        created_at=now,
        updated_at=now,
    )
    conv_b = Conversation(
        id=conversation_b,
        tenant_id=tenant_id,
        user_id=None,
        dataset_id=None,
        title="Conversation B",
        document_ids=[],
        message_count=1,
        created_at=now,
        updated_at=now,
    )
    assistant_a = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_a,
        role="assistant",
        content=long_content,
        citations=[],
        message_metadata={},
        created_at=now - timedelta(minutes=2),
    )
    assistant_b = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_b,
        role="assistant",
        content="short",
        citations=[],
        message_metadata={},
        created_at=now - timedelta(minutes=1),
    )
    assistant_other = Message(
        id=uuid.uuid4(),
        tenant_id=other_tenant_id,
        conversation_id=uuid.uuid4(),
        role="assistant",
        content="other",
        citations=[],
        message_metadata={},
        created_at=now,
    )

    feedback_old = MessageFeedback(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_a,
        message_id=assistant_a.id,
        account_id="u",
        rating=2,
        reason="bad",
        tags=["negative"],
        expected_answer=None,
        extra={},
        created_at=now - timedelta(minutes=2),
        updated_at=now - timedelta(minutes=2),
    )
    feedback_new = MessageFeedback(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_b,
        message_id=assistant_b.id,
        account_id="u",
        rating=5,
        reason="good",
        tags=["positive"],
        expected_answer=None,
        extra={},
        created_at=now - timedelta(minutes=1),
        updated_at=now - timedelta(minutes=1),
    )
    feedback_other = MessageFeedback(
        id=uuid.uuid4(),
        tenant_id=other_tenant_id,
        conversation_id=assistant_other.conversation_id,
        message_id=assistant_other.id,
        account_id="u",
        rating=1,
        reason="other",
        tags=[],
        expected_answer=None,
        extra={},
        created_at=now,
        updated_at=now,
    )

    db = _FakeDB(
        feedback_rows=[feedback_old, feedback_new, feedback_other],
        messages=[assistant_a, assistant_b, assistant_other],
        conversations=[conv_a, conv_b],
    )

    listed = FeedbackService.list_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id="u",
        conversation_id=None,
        message_id=None,
        min_rating=2,
        max_rating=5,
        skip=0,
        limit=10,
        ensure_member_fn=lambda *_args, **_kwargs: None,
    )
    enriched = FeedbackService.list_message_feedback_enriched(
        db=db,
        tenant_id=tenant_id,
        account_id="u",
        conversation_id=None,
        message_id=None,
        min_rating=2,
        max_rating=5,
        skip=0,
        limit=10,
        ensure_member_fn=lambda *_args, **_kwargs: None,
    )

    assert listed["total"] == 2
    assert [row.id for row in listed["items"]] == [feedback_new.id, feedback_old.id]
    assert enriched["total"] == 2
    assert [row.id for row in enriched["items"]] == [feedback_new.id, feedback_old.id]
    assert enriched["items"][0].conversation_title == "Conversation B"
    assert enriched["items"][1].conversation_title == "Conversation A"
    assert enriched["items"][1].message_created_at == assistant_a.created_at
    assert len(enriched["items"][1].message_content or "") == 4000


def test_build_feedback_loop_candidates_uses_negative_feedback_context() -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    now = datetime.now(UTC)
    user_msg = Message(
        id=user_message_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="user",
        content="MCU 没数据",
        citations=[],
        message_metadata={},
        created_at=now - timedelta(seconds=5),
    )
    assistant_msg = Message(
        id=assistant_message_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="assistant",
        content="请检查采集配置。",
        citations=[{"chunk_id": "chunk-positive", "document_id": "doc-good"}],
        message_metadata={"dataset_id": str(dataset_id), "request_id": "req-loop-1"},
        created_at=now,
    )
    conv = Conversation(
        id=conversation_id,
        tenant_id=tenant_id,
        user_id=None,
        dataset_id=dataset_id,
        title="Loop",
        document_ids=[],
        message_count=2,
        created_at=now,
        updated_at=now,
    )
    feedback = MessageFeedback(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        account_id="u",
        rating=1,
        reason="召回错",
        tags=["negative"],
        expected_answer="请检查 MCU 通讯和采集配置。",
        extra={
            "retrieval_trace": {
                "retrieval": {"retrieval_config_hash": "cfg-loop"},
                "citations": [
                    {"chunk_id": "chunk-hard", "document_id": "doc-bad"},
                    {"chunk_id": "chunk-positive", "document_id": "doc-good"},
                ],
            }
        },
        created_at=now,
        updated_at=now,
    )
    db = _FakeDB(feedback_rows=[feedback], messages=[user_msg, assistant_msg], conversations=[conv])

    out = FeedbackService.build_feedback_loop_candidates(
        db=db,
        tenant_id=tenant_id,
        account_id="u",
        max_rating=2,
        limit=20,
        ensure_member_fn=lambda *_args, **_kwargs: None,
    )

    assert out["schema"] == "mimirq.feedback_loop_candidates.v1"
    assert out["summary"]["negative_feedback_total"] == 1
    assert out["hard_negative_records"][0]["hard_negatives"][0]["chunk_id"] == "chunk-hard"
    assert out["training_triples"][0]["positive_chunk_ids"] == ["chunk-positive"]
    assert {item["token"] for item in out["rules_suggestions"]["glossary_suggestions"]} >= {"MCU"}


def test_patch_message_feedback_archive_state_persists_in_extra() -> None:
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    now = datetime.now(UTC)

    feedback_row = MessageFeedback(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=uuid.uuid4(),
        account_id="owner",
        rating=2,
        reason="bad",
        tags=["negative"],
        expected_answer=None,
        extra={"from": "test"},
        created_at=now,
        updated_at=now,
    )
    db = _FakeDB(feedback_rows=[feedback_row], messages=[], conversations=[])

    archived = FeedbackService.patch_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id="reviewer",
        feedback_id=feedback_row.id,
        archived=True,
        ensure_member_fn=lambda *_args, **_kwargs: None,
    )
    assert archived.extra["archived"] is True
    assert archived.extra["archived_by"] == "reviewer"
    assert isinstance(archived.extra["archived_at"], str)

    unarchived = FeedbackService.patch_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id="reviewer",
        feedback_id=feedback_row.id,
        archived=False,
        ensure_member_fn=lambda *_args, **_kwargs: None,
    )
    assert unarchived.extra["archived"] is False
    assert "archived_at" not in unarchived.extra
    assert "archived_by" not in unarchived.extra
