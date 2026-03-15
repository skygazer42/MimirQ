from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from app.models.chat import Conversation, Message
from app.models.feedback import MessageFeedback
from app.rag.trace_schema import RagTrace, RagTraceCitation, RagTraceListResponse


def _load_feedback_module():
    base = Path(__file__).resolve().parents[1]
    src = base / "app" / "api" / "v1" / "feedback.py"
    name = "task30_feedback_module"
    spec = spec_from_file_location(name, src)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


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
            val = getattr(getattr(cond, "right", None), "value", None)
            if not key:
                continue
            if isinstance(val, (list, tuple, set)):
                items = [d for d in items if getattr(d, key, None) in val]
            elif val is not None:
                items = [d for d in items if getattr(d, key, None) == val]
        self._items = items
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN001,D401
        return self

    def first(self):  # noqa: D401
        return self._items[0] if self._items else None


class _FakeDB:
    def __init__(self, *, feedback_rows, messages, conversations):  # noqa: ANN001
        self._rows = {
            MessageFeedback: list(feedback_rows or []),
            Message: list(messages or []),
            Conversation: list(conversations or []),
        }
        self._added = []

    def query(self, model):  # noqa: ANN001
        return _FakeQuery(self._rows.get(model, []))

    def add(self, obj):  # noqa: ANN001
        self._added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(UTC)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


@pytest.mark.asyncio
async def test_feedback_to_regression_case_includes_reference_sources_and_trace(monkeypatch):  # noqa: ANN001
    feedback_mod = _load_feedback_module()

    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    request_id = "req-30"
    now = datetime.now(UTC)

    conv = Conversation(
        id=conversation_id,
        tenant_id=tenant_id,
        user_id=None,
        dataset_id=dataset_id,
        title="demo",
        document_ids=[document_id],
        message_count=2,
        created_at=now,
        updated_at=now,
    )
    user_msg = Message(
        id=user_message_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="user",
        content="What is total revenue?",
        citations=[],
        message_metadata={},
        created_at=now,
    )
    assistant_msg = Message(
        id=assistant_message_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="assistant",
        content="Revenue is 123.",
        citations=[
            {
                "document_id": str(document_id),
                "chunk_id": str(chunk_id),
                "page_number": 3,
                "start_char": 12,
                "end_char": 42,
                "chunk_index": 9,
            }
        ],
        message_metadata={"dataset_id": str(dataset_id), "request_id": request_id},
        created_at=now,
    )
    fb = MessageFeedback(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        account_id="u",
        rating=2,
        reason="bad",
        tags=["neg"],
        expected_answer="Revenue is 120.",
        extra={"from": "test"},
    )

    db = _FakeDB(feedback_rows=[fb], messages=[assistant_msg, user_msg], conversations=[conv])

    monkeypatch.setattr(feedback_mod.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        feedback_mod,
        "list_rag_traces",
        lambda **_kwargs: RagTraceListResponse(
            enabled=True,
            path="/tmp/fake.jsonl",
            window_minutes=60,
            truncated=False,
            returned=2,
            items=[
                RagTrace(
                    ts_ms=1,
                    request_id="other",
                    conversation_id=str(conversation_id),
                    citations=[],
                    citations_count=0,
                ),
                RagTrace(
                    ts_ms=2,
                    request_id=request_id,
                    conversation_id=str(conversation_id),
                    citations=[RagTraceCitation(document_id=str(document_id), chunk_id=str(chunk_id), chunk_index=9)],
                    citations_count=1,
                ),
            ],
        ),
        raising=True,
    )

    row = await feedback_mod.create_regression_case_from_feedback(
        feedback_id=fb.id,
        body=feedback_mod.FeedbackToRegressionCaseRequest(),
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert str(row.dataset_id) == str(dataset_id)
    assert [str(x) for x in (row.document_ids or [])] == [str(document_id)]
    assert row.question == "What is total revenue?"
    assert isinstance(row.reference_sources, list) and len(row.reference_sources) == 1
    assert row.reference_sources[0]["document_id"] == str(document_id)
    assert row.reference_sources[0]["chunk_id"] == str(chunk_id)
    assert row.reference_sources[0]["page_number"] == 3
    assert row.reference_sources[0]["start_char"] == 12
    assert row.reference_sources[0]["end_char"] == 42
    assert row.reference_sources[0]["chunk_index"] == 9
    assert (row.extra or {}).get("retrieval_trace", {}).get("request_id") == request_id
    assert (row.extra or {}).get("retrieval_trace", {}).get("citations_count") == 1
