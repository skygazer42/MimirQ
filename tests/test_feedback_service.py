
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.api.v1 import feedback as feedback_api
from app.models.chat import Conversation, Message
from app.models.evaluation import RagasRegressionCase
from app.models.feedback import MessageFeedback
from app.rag.feedback_loop.candidates import build_feedback_loop_candidates
from app.rag.feedback_loop.dispatcher import dispatch_feedback_loop_batch
from app.rag.trace_schema import RagTrace, RagTraceListResponse
from app.services.feedback_service import FeedbackService


class _FakeQuery:
    def __init__(self, items, *, model=None, related_rows=None):  # noqa: ANN001
        self._items = list(items or [])
        self._model = model
        self._related_rows = related_rows or {}
        self._joined_conversations = {}
        self._limit = None

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
            if self._model is MessageFeedback and key == "owner_account_id":
                items = [
                    row
                    for row in items
                    if getattr(
                        self._joined_conversations.get((row.tenant_id, row.conversation_id)),
                        "owner_account_id",
                        None,
                    )
                    == value
                ]
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
        if self._model is MessageFeedback and self._limit is None:
            raise AssertionError("feedback queries must paginate in SQL before all()")
        return list(self._items)

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002,ANN003,D401
        if self._model is MessageFeedback:
            floor = datetime.min.replace(tzinfo=timezone.utc)

            def sort_key(row):  # noqa: ANN001
                updated_at = getattr(row, "updated_at", None)
                created_at = getattr(row, "created_at", None)
                timestamp = updated_at or created_at or floor
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                return timestamp, str(getattr(row, "id", ""))

            self._items.sort(key=sort_key, reverse=True)
        return self

    def count(self):  # noqa: D401
        return len(self._items)

    def offset(self, value):  # noqa: ANN001,D401
        self._items = self._items[max(0, int(value or 0)) :]
        return self

    def limit(self, value):  # noqa: ANN001,D401
        self._limit = max(0, int(value or 0))
        self._items = self._items[: self._limit]
        return self

    def with_for_update(self):  # noqa: D401
        return self

    def join(self, model, *_args, **_kwargs):  # noqa: ANN001,D401
        if self._model is MessageFeedback and model is Conversation:
            self._joined_conversations = {
                (row.tenant_id, row.id): row
                for row in self._related_rows.get(Conversation, [])
            }
            self._items = [
                row
                for row in self._items
                if (row.tenant_id, row.conversation_id) in self._joined_conversations
            ]
        return self


class _FakeDB:
    def __init__(self, *, feedback_rows, messages, conversations):  # noqa: ANN001
        self._rows = {
            MessageFeedback: list(feedback_rows or []),
            Message: list(messages or []),
            Conversation: list(conversations or []),
        }

    def query(self, model):  # noqa: ANN001
        return _FakeQuery(self._rows.get(model, []), model=model, related_rows=self._rows)

    def add(self, obj):  # noqa: ANN001
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        self._rows.setdefault(type(obj), []).append(obj)

    def commit(self) -> None:
        return None

    def flush(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def test_upsert_message_feedback_persists_trace_and_snapshot_metadata() -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    request_id = "req-feedback-service-1"
    now = datetime.now(timezone.utc)
    user_msg = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="user",
        content="How should I configure this?",
        citations=[],
        message_metadata={},
        created_at=now - timedelta(seconds=1),
    )
    assistant_msg = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="assistant",
        content="hello",
        citations=[],
        message_metadata={
            "dataset_id": str(dataset_id),
            "request_id": request_id,
            "retrieval_profile": "balanced",
        },
        created_at=now,
    )
    conv = Conversation(
        id=conversation_id,
        tenant_id=tenant_id,
        user_id=None,
        owner_account_id="u",
        dataset_id=None,
        title="demo",
        document_ids=[],
        message_count=2,
        created_at=now,
        updated_at=now,
    )
    db = _FakeDB(feedback_rows=[], messages=[user_msg, assistant_msg], conversations=[conv])

    row = FeedbackService.upsert_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id="u",
        message_id=assistant_msg.id,
        rating=2,
        reason="missing detail",
        tags=["negative"],
        expected_answer="expected",
        category="retrieval_miss",
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
    assert row.category == "retrieval_miss"
    assert row.category_source == "user"
    assert len(row.query_hash) == 64
    assert row.retrieval_trace_ref == request_id
    assert row.profile == "balanced"
    assert row.extra["dataset_id"] == str(dataset_id)
    assert row.extra["retrieval_trace_request_id"] == request_id
    assert row.extra["retrieval_trace"]["request_id"] == request_id
    assert row.extra["rag_config_snapshot"]["retrieval_config_hash"] == "cfg-feedback-service-1"
    assert len(db._rows[MessageFeedback]) == 1

    row.category = "wrong_answer"
    row.category_source = "reviewer"
    row.extra = {
        **row.extra,
        "archived": True,
        "eval_case_status": "promoted",
        "eval_case_id": "case-1",
    }
    updated = FeedbackService.upsert_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id="u",
        message_id=assistant_msg.id,
        rating=3,
        reason="updated",
        tags=[],
        expected_answer=None,
        extra={},
        ensure_member_fn=lambda *_args, **_kwargs: None,
        list_rag_traces_fn=lambda **_kwargs: RagTraceListResponse(
            enabled=True,
            path="/tmp/fake.jsonl",
            window_minutes=60,
            truncated=False,
            returned=0,
            items=[],
        ),
    )
    assert updated.category == "wrong_answer"
    assert updated.category_source == "reviewer"
    assert updated.extra["archived"] is True
    assert updated.extra["eval_case_status"] == "promoted"
    assert updated.extra["eval_case_id"] == "case-1"

    user_retry = FeedbackService.upsert_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id="u",
        message_id=assistant_msg.id,
        rating=2,
        reason="retry",
        tags=[],
        expected_answer=None,
        category="retrieval_miss",
        extra={},
        ensure_member_fn=lambda *_args, **_kwargs: None,
        list_rag_traces_fn=lambda **_kwargs: RagTraceListResponse(
            enabled=True,
            path="/tmp/fake.jsonl",
            window_minutes=60,
            truncated=False,
            returned=0,
            items=[],
        ),
    )
    assert user_retry.category == "wrong_answer"
    assert user_retry.category_source == "reviewer"


def test_upsert_message_feedback_rejects_other_accounts_conversation() -> None:
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    user_msg = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="user",
        content="owner question",
        citations=[],
        message_metadata={},
        created_at=now - timedelta(seconds=1),
    )
    assistant_msg = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="assistant",
        content="owner answer",
        citations=[],
        message_metadata={},
        created_at=now,
    )
    conv = Conversation(
        id=conversation_id,
        tenant_id=tenant_id,
        user_id=None,
        owner_account_id="owner",
        dataset_id=None,
        title="private",
        document_ids=[],
        message_count=2,
        created_at=now,
        updated_at=now,
    )
    db = _FakeDB(feedback_rows=[], messages=[user_msg, assistant_msg], conversations=[conv])

    with pytest.raises(HTTPException) as exc_info:
        FeedbackService.upsert_message_feedback(
            db=db,
            tenant_id=tenant_id,
            account_id="intruder",
            message_id=assistant_msg.id,
            rating=1,
            reason="spy",
            tags=[],
            expected_answer=None,
            extra={},
            ensure_member_fn=lambda *_args, **_kwargs: None,
        )

    assert exc_info.value.status_code == 403


def test_list_message_feedback_enriched_filters_sorts_and_truncates() -> None:
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    conversation_a = uuid.uuid4()
    conversation_b = uuid.uuid4()
    now = datetime.now(timezone.utc)
    long_content = "x" * 5000

    conv_a = Conversation(
        id=conversation_a,
        tenant_id=tenant_id,
        user_id=None,
        owner_account_id="u",
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
        owner_account_id="other-user",
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
    feedback_orphan = MessageFeedback(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=None,
        message_id=uuid.uuid4(),
        account_id="u",
        rating=4,
        reason="system",
        tags=["system"],
        expected_answer=None,
        extra={"source": "non-conversation"},
        created_at=now - timedelta(seconds=30),
        updated_at=now - timedelta(seconds=30),
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
        feedback_rows=[feedback_old, feedback_new, feedback_orphan, feedback_other],
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

    assert listed["total"] == 1
    assert [row.id for row in listed["items"]] == [feedback_old.id]
    assert enriched["total"] == 1
    assert [row.id for row in enriched["items"]] == [feedback_old.id]
    assert enriched["items"][0].conversation_title == "Conversation A"
    assert enriched["items"][0].message_created_at == assistant_a.created_at
    assert len(enriched["items"][0].message_content or "") == 4000
    assert all(row.id != feedback_new.id for row in listed["items"])


def test_list_message_feedback_uses_stable_sql_page_boundaries() -> None:
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    def feedback(row_id: int) -> MessageFeedback:
        return MessageFeedback(
            id=uuid.UUID(int=row_id),
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message_id=message_id,
            account_id="u",
            rating=3,
            extra={},
            created_at=now,
            updated_at=now,
        )

    older_id = feedback(1)
    newer_id = feedback(2)
    conversation = Conversation(
        id=conversation_id,
        tenant_id=tenant_id,
        user_id=None,
        owner_account_id="u",
        dataset_id=None,
        title="paged",
        document_ids=[],
        message_count=0,
        created_at=now,
        updated_at=now,
    )
    db = _FakeDB(feedback_rows=[older_id, newer_id], messages=[], conversations=[conversation])
    args = {
        "db": db,
        "tenant_id": tenant_id,
        "account_id": "u",
        "conversation_id": None,
        "message_id": None,
        "min_rating": None,
        "max_rating": None,
        "limit": 1,
        "ensure_member_fn": lambda *_args, **_kwargs: None,
    }

    first = FeedbackService.list_message_feedback(skip=0, **args)
    second = FeedbackService.list_message_feedback(skip=1, **args)

    assert first["total"] == second["total"] == 2
    assert [row.id for row in first["items"]] == [newer_id.id]
    assert [row.id for row in second["items"]] == [older_id.id]


def test_build_feedback_loop_candidates_uses_negative_feedback_context() -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
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
        owner_account_id="u",
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
        category="retrieval_miss",
        category_source="reviewer",
        query_hash="query-hash-loop",
        retrieval_trace_ref="req-loop-1",
        profile="balanced",
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
    assert out["summary"]["eval_case_candidates"] == 1
    assert out["eval_case_candidates"][0] == {
        "schema": "mimirq.feedback_eval_case.v1",
        "status": "pending_review",
        "question": "MCU 没数据",
        "expected_answer": "请检查 MCU 通讯和采集配置。",
        "reference_sources": [{"chunk_id": "chunk-positive", "document_id": "doc-good"}],
        "tags": ["negative", "retrieval_miss"],
        "category": "retrieval_miss",
        "category_source": "reviewer",
        "query_hash": "query-hash-loop",
        "retrieval_trace_ref": "req-loop-1",
        "retrieval_config_hash": "cfg-loop",
        "profile": "balanced",
        "judge_score_ref": None,
        "source_feedback_id": str(feedback.id),
        "source_conversation_id": str(conversation_id),
        "source_message_id": str(assistant_message_id),
        "dataset_id": str(dataset_id),
    }
    assert {item["token"] for item in out["rules_suggestions"]["glossary_suggestions"]} >= {"MCU"}


def test_eval_case_candidate_falls_back_to_trace_citations() -> None:
    out = build_feedback_loop_candidates(
        [
            {
                "id": "feedback-1",
                "rating": 1,
                "question": "What changed?",
                "retrieval_trace": {
                    "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1"}],
                },
            }
        ]
    )

    assert out["eval_case_candidates"][0]["reference_sources"] == [
        {"document_id": "doc-1", "chunk_id": "chunk-1"}
    ]

    promoted = build_feedback_loop_candidates(
        [
            {
                "id": "feedback-1",
                "rating": 1,
                "question": "What changed?",
                "extra": {"eval_case_status": "promoted"},
            }
        ]
    )
    assert promoted["eval_case_candidates"] == []


def test_feedback_loop_dispatcher_exposes_eval_case_review_queue() -> None:
    out = dispatch_feedback_loop_batch(
        rows=[
            {
                "id": "feedback-1",
                "rating": 1,
                "question": "What changed?",
                "expected_answer": "The MCU configuration changed.",
            }
        ],
        dry_run=True,
    )

    assert out["candidates"]["eval_case_candidates"] == 1
    assert out["eval_case_candidates"][0]["status"] == "pending_review"


def test_feedback_promotion_requires_write_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*_args, **_kwargs):  # noqa: ANN002,ANN003
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(feedback_api.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(feedback_api, "ensure_tenant_permission", deny)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            feedback_api.create_regression_case_from_feedback(
                uuid.uuid4(),
                feedback_api.FeedbackToRegressionCaseRequest(),
                tenant_id=uuid.uuid4(),
                account_id="viewer",
                db=_FakeDB(feedback_rows=[], messages=[], conversations=[]),
            )
        )

    assert exc_info.value.status_code == 403


def test_feedback_promotion_keeps_server_lineage(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    feedback = MessageFeedback(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=assistant_id,
        account_id="u",
        rating=1,
        reason="bad",
        tags=[],
        expected_answer="expected",
        extra={},
        created_at=now,
        updated_at=now,
    )
    user_message = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="user",
        content="question",
        citations=[],
        message_metadata={},
        created_at=now - timedelta(seconds=1),
    )
    assistant = Message(
        id=assistant_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="assistant",
        content="answer",
        citations=[],
        message_metadata={"dataset_id": str(dataset_id)},
        created_at=now,
    )
    conversation = Conversation(
        id=conversation_id,
        tenant_id=tenant_id,
        user_id=None,
        owner_account_id="editor",
        dataset_id=dataset_id,
        title="feedback",
        document_ids=[],
        message_count=2,
        created_at=now,
        updated_at=now,
    )
    db = _FakeDB(
        feedback_rows=[feedback],
        messages=[user_message, assistant],
        conversations=[conversation],
    )
    monkeypatch.setattr(feedback_api.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(feedback_api, "ensure_tenant_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(feedback_api.DatasetService, "get_dataset", lambda *_args, **_kwargs: object())
    writable_checks: list[tuple[object, str]] = []
    monkeypatch.setattr(
        feedback_api.DatasetService,
        "assert_dataset_writable",
        lambda _db, dataset, account_id: writable_checks.append((dataset, account_id)),
    )
    monkeypatch.setattr(feedback_api, "audit_log_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(feedback_api, "_find_trace_by_request_id", lambda **_kwargs: None)

    row = feedback_api.create_regression_case_from_feedback(
        feedback.id,
        feedback_api.FeedbackToRegressionCaseRequest(
            extra={
                "source": "spoofed",
                "feedback_id": "spoofed",
                "message_id": "spoofed",
                "rating": 5,
            }
        ),
        tenant_id=tenant_id,
        account_id="editor",
        db=db,
    )

    assert isinstance(row, RagasRegressionCase)
    assert row.extra["source"] == "feedback"
    assert row.extra["feedback_id"] == str(feedback.id)
    assert row.extra["message_id"] == str(assistant_id)
    assert row.extra["rating"] == 1
    assert row.dataset_id == dataset_id
    assert writable_checks and writable_checks[0][1] == "editor"


def test_patch_message_feedback_archive_state_persists_in_extra() -> None:
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

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
        category="wrong_answer",
        ensure_member_fn=lambda *_args, **_kwargs: None,
    )
    assert archived.extra["archived"] is True
    assert archived.extra["archived_by"] == "reviewer"
    assert isinstance(archived.extra["archived_at"], str)
    assert archived.category == "wrong_answer"
    assert archived.category_source == "reviewer"

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


@pytest.mark.parametrize(
    ("endpoint", "kwargs"),
    [
        (
            feedback_api.preview_feedback_loop_candidates,
            {"max_rating": 2, "limit": 20, "ruleset": None},
        ),
        (
            feedback_api.export_feedback_loop_hard_negatives,
            {"max_rating": 2, "limit": 20, "dry_run": True, "append": True, "ruleset": None},
        ),
    ],
)
def test_feedback_loop_endpoints_require_triage_permission(monkeypatch, endpoint, kwargs) -> None:  # noqa: ANN001
    def _deny(*_args, **_kwargs):  # noqa: ANN002,ANN003
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(feedback_api, "ensure_tenant_permission", _deny)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            endpoint(
                **kwargs,
                tenant_id=uuid.uuid4(),
                account_id="member",
                db=object(),
            )
        )

    assert exc_info.value.status_code == 403
