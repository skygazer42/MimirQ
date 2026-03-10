from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from app.models.chat import Conversation, Message
from app.models.feedback import MessageFeedback
from app.rag.trace_schema import RagTrace, RagTraceListResponse


def _load_feedback_module():
    base = Path(__file__).resolve().parents[1]
    src = base / "app" / "api" / "v1" / "feedback.py"
    name = "feedback_training_export_feedback_module"
    spec = spec_from_file_location(name, src)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_evidence_module():
    base = Path(__file__).resolve().parents[1]
    src = base / "app" / "api" / "v1" / "evidence.py"
    name = "feedback_training_export_evidence_module"
    spec = spec_from_file_location(name, src)
    assert spec is not None and spec.loader is not None
    mod = module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeQuery:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def filter(self, *args, **kwargs):  # noqa: ANN001
        try:
            from sqlalchemy.sql.elements import BinaryExpression
        except Exception:
            return self
        items = list(self._items)
        for cond in args:
            if not isinstance(cond, BinaryExpression):
                continue
            key = getattr(getattr(cond, "left", None), "key", None)
            val = getattr(getattr(cond, "right", None), "value", None)
            if not key:
                continue
            if val is not None:
                items = [row for row in items if getattr(row, key, None) == val]
        self._items = items
        return self

    def first(self):  # noqa: D401
        return self._items[0] if self._items else None


class _FakeDB:
    def __init__(self, *, messages, conversations):  # noqa: ANN001
        self._rows = {
            Message: list(messages or []),
            Conversation: list(conversations or []),
            MessageFeedback: [],
        }

    def query(self, model):  # noqa: ANN001
        return _FakeQuery(self._rows.get(model, []))

    def add(self, obj):  # noqa: ANN001
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime.now(timezone.utc)
        self._rows.setdefault(type(obj), []).append(obj)

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


@pytest.mark.asyncio
async def test_upsert_message_feedback_persists_trace_and_rag_config_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    feedback_mod = _load_feedback_module()

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    request_id = "req-feedback-export-1"
    now = datetime.now(timezone.utc)
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
    db = _FakeDB(messages=[assistant_msg], conversations=[conv])

    monkeypatch.setattr(feedback_mod.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        feedback_mod,
        "list_rag_traces",
        lambda **_kwargs: RagTraceListResponse(
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
                    retrieval={"retrieval_config_hash": "cfg-feedback-1"},
                    citations=[],
                    citations_count=0,
                )
            ],
        ),
        raising=True,
    )

    row = await feedback_mod.upsert_message_feedback(
        request=feedback_mod.MessageFeedbackCreateRequest(message_id=assistant_msg.id, rating=2, extra={"from": "test"}),
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert row.extra["dataset_id"] == str(dataset_id)
    assert row.extra["retrieval_trace_request_id"] == request_id
    assert row.extra["retrieval_trace"]["request_id"] == request_id
    assert row.extra["rag_config_snapshot"]["retrieval_config_hash"] == "cfg-feedback-1"


@pytest.mark.asyncio
async def test_export_training_dataset_jsonl_combines_feedback_and_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence_mod = _load_evidence_module()

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(evidence_mod.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(evidence_mod.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(evidence_mod.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        evidence_mod,
        "_collect_feedback_training_export_rows",
        lambda *_a, **_k: [
            {
                "schema": "mimirq.training_export_row.v1",
                "source_type": "feedback",
                "source_id": "fb-1",
                "dataset_id": str(dataset_id),
                "status": "feedback",
                "question": "What changed?",
                "expected_answer": "Answer",
                "tags": ["neg"],
                "reference_sources": [{"document_id": "doc-1", "chunk_id": "chunk-1"}],
                "trace_snapshot": {"request_id": "req-1"},
                "rag_config_snapshot": {"retrieval_config_hash": "cfg-1"},
                "source_metadata": {"rating": 2},
                "created_at": "2026-03-10T10:00:00+00:00",
                "updated_at": "2026-03-10T10:00:00+00:00",
            }
        ],
        raising=True,
    )
    monkeypatch.setattr(
        evidence_mod,
        "_collect_evidence_training_export_rows",
        lambda *_a, **_k: [
            {
                "schema": "mimirq.training_export_row.v1",
                "source_type": "evidence_item",
                "source_id": "ev-1",
                "dataset_id": str(dataset_id),
                "status": "approved",
                "question": "Where is the source?",
                "expected_answer": None,
                "tags": ["gold"],
                "reference_sources": [],
                "trace_snapshot": {"request_id": "req-2"},
                "rag_config_snapshot": {"retrieval_config_hash": "cfg-2"},
                "source_metadata": {"suite_id": "suite-1"},
                "created_at": "2026-03-10T11:00:00+00:00",
                "updated_at": "2026-03-10T11:00:00+00:00",
            }
        ],
        raising=True,
    )

    res = await evidence_mod.export_training_dataset(
        dataset_id=dataset_id,
        format="jsonl",
        include_feedback=True,
        include_evidence=True,
        include_archived_evidence=False,
        max_rows_per_source=10,
        tenant_id=tenant_id,
        account_id="u",
        db=object(),
    )

    body = res.body.decode("utf-8")
    rows = [json.loads(line) for line in body.splitlines() if line.strip()]
    assert len(rows) == 2
    assert rows[0]["source_type"] == "feedback"
    assert rows[1]["source_type"] == "evidence_item"
    assert res.headers["content-disposition"].endswith('.training_export.jsonl"')
