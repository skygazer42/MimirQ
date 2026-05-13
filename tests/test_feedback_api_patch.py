from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.feedback import MessageFeedback


class _FakeQuery:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def filter(self, *args, **kwargs):  # noqa: ANN001, D401
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
        self._items = items
        return self

    def first(self):  # noqa: D401
        return self._items[0] if self._items else None


class _FakeDB:
    def __init__(self, rows):  # noqa: ANN001
        self._rows = {MessageFeedback: list(rows or [])}

    def query(self, model):  # noqa: ANN001
        return _FakeQuery(self._rows.get(model, []))

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def _override_get_db(rows):  # noqa: ANN001
    def _gen():  # noqa: ANN202
        yield _FakeDB(rows)

    return _gen


def test_patch_feedback_endpoint_updates_archive_state(monkeypatch) -> None:  # noqa: ANN001
    from app.api.v1.feedback import patch_message_feedback as patch_message_feedback_endpoint
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    feedback_id = uuid.uuid4()
    row = MessageFeedback(
        id=feedback_id,
        tenant_id=tenant_id,
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        account_id="owner",
        rating=2,
        reason="bad",
        tags=["negative"],
        expected_answer=None,
        extra={},
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db([row])
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "reviewer"
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    app.patch("/api/v1/feedback/messages/{feedback_id}")(patch_message_feedback_endpoint)

    client = TestClient(app)
    res = client.patch(f"/api/v1/feedback/messages/{feedback_id}", json={"archived": True})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["extra"]["archived"] is True
    assert body["extra"]["archived_by"] == "reviewer"
