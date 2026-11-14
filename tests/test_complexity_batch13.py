import datetime as dt
import uuid
from datetime import datetime, timedelta, timezone

import pytest

if not hasattr(dt, "UTC"):
    dt.UTC = timezone.utc

from app.api.v1 import evidence as evidence_api
from app.api.v1 import feedback as feedback_api
from app.models.chat import Conversation, Message
from app.models.evidence import EvidenceItem, EvidenceSuite
from app.models.feedback import MessageFeedback


class _FakeQuery:
    def __init__(self, items):
        self._items = list(items or [])

    def filter(self, *args, **_kwargs):
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
            elif op_name == "ne":
                items = [row for row in items if getattr(row, key, None) != value]
            elif op_name == "ge":
                items = [row for row in items if getattr(row, key, None) >= value]
            elif op_name == "le":
                items = [row for row in items if getattr(row, key, None) <= value]
            elif op_name == "in_op":
                values = set(value or [])
                items = [row for row in items if getattr(row, key, None) in values]
        self._items = items
        return self

    def first(self):
        return self._items[0] if self._items else None

    def all(self):
        return list(self._items)

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, value):
        self._items = self._items[: max(0, int(value or 0))]
        return self

    def with_for_update(self):
        return self


class _FakeDB:
    def __init__(
        self,
        *,
        feedback_rows=None,
        messages=None,
        conversations=None,
        evidence_items=None,
        evidence_suites=None,
    ) -> None:
        self._rows = {
            MessageFeedback: list((feedback_rows if feedback_rows is not None else [])),
            Message: list((messages if messages is not None else [])),
            Conversation: list((conversations if conversations is not None else [])),
            EvidenceItem: list((evidence_items if evidence_items is not None else [])),
            EvidenceSuite: list((evidence_suites if evidence_suites is not None else [])),
        }
        self.commit_calls = 0
        self.rollback_calls = 0

    def query(self, model):
        return _FakeQuery(self._rows.get(model, []))

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        self._rows.setdefault(type(obj), []).append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def refresh(self, _obj) -> None:
        return None


def test_extract_reference_sources_sanitizes_dedupes_and_caps_fields() -> None:
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    out = feedback_api._extract_reference_sources(
        [
            "ignore-me",
            {"document_id": "not-a-uuid", "chunk_id": str(chunk_id)},
            {
                "document_id": str(doc_id),
                "chunk_id": str(chunk_id),
                "page_number": "2",
                "start_char": "0",
                "end_char": "12",
                "chunk_index": "3",
                "doc_pipeline_key": " pipeline-key ",
                "pipeline_hash": " pipeline-hash ",
                "quote": "q" * 2100,
                "label": "L" * 140,
            },
            {
                "document_id": str(doc_id),
                "chunk_id": str(chunk_id),
                "page_number": 99,
            },
        ]
    )

    assert out == [
        {
            "document_id": str(doc_id),
            "chunk_id": str(chunk_id),
            "page_number": 2,
            "start_char": 0,
            "end_char": 12,
            "chunk_index": 3,
            "doc_pipeline_key": "pipeline-key",
            "pipeline_hash": "pipeline-hash",
            "quote": "q" * 2000,
            "label": "L" * 128,
        }
    ]


def test_create_evidence_item_from_feedback_keeps_trace_refs_when_finalize_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    feedback_id = uuid.uuid4()
    assistant_id = uuid.uuid4()
    request_id = "req-b13"
    now = datetime.now(timezone.utc)

    suite = EvidenceSuite(
        id=suite_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        name="suite",
        archived_at=None,
    )
    feedback = MessageFeedback(
        id=feedback_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=assistant_id,
        account_id="reviewer",
        rating=2,
        reason="  needs evidence  ",
        tags=["needs-work"],
        expected_answer="expected",
        extra={"origin": "feedback"},
        created_at=now,
        updated_at=now,
    )
    user_message = Message(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="user",
        content="Where is the evidence?",
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
        message_metadata={"dataset_id": str(dataset_id), "request_id": request_id},
        created_at=now,
    )
    conversation = Conversation(
        id=conversation_id,
        tenant_id=tenant_id,
        user_id=None,
        owner_account_id="reviewer",
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
        evidence_suites=[suite],
    )
    trace_payload = {
        "request_id": request_id,
        "retrieval": {"retrieval_mode": "hybrid", "top_k": 8},
        "citations": [
            {
                "document_id": str(uuid.uuid4()),
                "chunk_id": str(uuid.uuid4()),
                "page_number": 4,
            }
        ],
    }

    monkeypatch.setattr(feedback_api.dataset_service, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(feedback_api.dataset_service, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(
        feedback_api.dataset_service,
        "assert_dataset_readable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(feedback_api, "audit_log_event", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        feedback_api,
        "_find_trace_by_request_id",
        lambda **_kwargs: trace_payload,
        raising=True,
    )

    import app.api.v1.evaluations as evaluations_api

    monkeypatch.setattr(
        evaluations_api,
        "_finalize_reference_sources",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("normalize failed")),
        raising=True,
    )

    row = feedback_api.create_evidence_item_from_feedback(
        feedback_id,
        feedback_api.FeedbackToEvidenceItemRequest(suite_id=suite_id),
        tenant_id=tenant_id,
        account_id="reviewer",
        db=db,
    )

    assert isinstance(row, EvidenceItem)
    assert row.reference_sources == feedback_api._extract_reference_sources(trace_payload["citations"])
    assert row.retrieval_snapshot == trace_payload
    assert row.rag_config_snapshot == trace_payload["retrieval"]
    assert row.source_metadata["source"] == "feedback"
    assert row.source_metadata["feedback_id"] == str(feedback_id)
    assert row.source_metadata["conversation_id"] == str(conversation_id)
    assert row.source_metadata["request_id"] == request_id
    assert row.notes == "needs evidence"


def test_patch_evidence_item_only_updates_selected_fields_and_finalizes_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    item_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    suite = EvidenceSuite(
        id=suite_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        name="suite",
        archived_at=None,
        created_at=now,
        updated_at=now,
    )
    row = EvidenceItem(
        id=item_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        suite_id=suite_id,
        status="draft",
        query="before",
        expected_answer="expected",
        tags=["keep"],
        source_metadata={"keep": True},
        reference_sources=[{"chunk_id": "old"}],
        notes="old note",
        created_at=now,
        updated_at=now,
    )
    db = _FakeDB(evidence_items=[row], evidence_suites=[suite])

    monkeypatch.setattr(evidence_api.dataset_service, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(evidence_api.dataset_service, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(
        evidence_api.dataset_service,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    import app.api.v1.evaluations as evaluations_api

    finalized_refs = [{"chunk_id": "new", "document_id": str(uuid.uuid4())}]
    monkeypatch.setattr(
        evaluations_api, "_finalize_reference_sources", lambda *_args, **_kwargs: finalized_refs, raising=True
    )

    payload = evidence_api.EvidenceItemPatchRequest(
        query="after",
        notes="new note",
        source_metadata=None,
        reference_sources=[{"document_id": uuid.uuid4(), "chunk_id": uuid.uuid4()}],
    )

    result = evidence_api.patch_evidence_item(
        item_id,
        payload,
        tenant_id=tenant_id,
        account_id="editor",
        db=db,
    )

    assert result is row
    assert row.query == "after"
    assert row.notes == "new note"
    assert row.expected_answer == "expected"
    assert row.tags == ["keep"]
    assert row.source_metadata == {"keep": True}
    assert row.reference_sources == finalized_refs
    assert db.commit_calls == 1
