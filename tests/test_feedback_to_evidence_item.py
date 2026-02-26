from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from app.models.chat import Conversation, Message
from app.models.evidence import EvidenceSuite
from app.models.feedback import MessageFeedback
from app.rag.trace_schema import RagTrace, RagTraceListResponse


def _load_feedback_module():
    base = Path(__file__).resolve().parents[1]
    src = base / "app" / "api" / "v1" / "feedback.py"
    name = "feedback_to_evidence_item_module"
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
    def __init__(self, *, feedback_rows, messages, conversations, suites):  # noqa: ANN001
        from app.models.evidence import EvidenceItem

        self._rows = {
            MessageFeedback: list(feedback_rows or []),
            Message: list(messages or []),
            Conversation: list(conversations or []),
            EvidenceSuite: list(suites or []),
            EvidenceItem: [],
        }
        self._added = []

    def query(self, model):  # noqa: ANN001
        return _FakeQuery(self._rows.get(model, []))

    def add(self, obj):  # noqa: ANN001
        self._added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
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
async def test_feedback_to_evidence_item_creates_item_with_pointers_and_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    feedback_mod = _load_feedback_module()

    tenant_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    user_message_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    request_id = "req-evi-1"
    now = datetime.now(timezone.utc)

    suite = EvidenceSuite(
        id=suite_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        name="suite",
        description=None,
        tags=[],
        config={},
        created_by="u",
        created_at=now,
        updated_at=now,
        archived_at=None,
    )

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

    db = _FakeDB(feedback_rows=[fb], messages=[assistant_msg, user_msg], conversations=[conv], suites=[suite])

    monkeypatch.setattr(feedback_mod.DatasetService, "ensure_member", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(feedback_mod.DatasetService, "get_dataset", lambda *args, **kwargs: object(), raising=True)
    monkeypatch.setattr(feedback_mod.DatasetService, "assert_dataset_readable", lambda *args, **kwargs: None, raising=True)

    monkeypatch.setattr(
        feedback_mod,
        "list_rag_traces",
        lambda **kwargs: RagTraceListResponse(
            enabled=True,
            path="/tmp/fake.jsonl",
            window_minutes=60,
            truncated=False,
            returned=1,
            items=[
                RagTrace(
                    ts_ms=2,
                    request_id=request_id,
                    conversation_id=str(conversation_id),
                    retrieval={"retrieval_config_hash": "cfg-evi-1"},
                    citations=[],
                    citations_count=0,
                )
            ],
        ),
        raising=True,
    )

    row = await feedback_mod.create_evidence_item_from_feedback(
        feedback_id=fb.id,
        body=feedback_mod.FeedbackToEvidenceItemRequest(suite_id=suite_id),
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert str(row.dataset_id) == str(dataset_id)
    assert str(row.suite_id) == str(suite_id)
    assert row.query == "What is total revenue?"
    assert row.expected_answer == "Revenue is 120."
    assert isinstance(row.reference_sources, list) and len(row.reference_sources) == 1
    assert row.reference_sources[0]["document_id"] == str(document_id)
    assert row.reference_sources[0]["chunk_id"] == str(chunk_id)
    assert row.retrieval_snapshot.get("request_id") == request_id
    assert row.rag_config_snapshot.get("retrieval_config_hash") == "cfg-evi-1"

