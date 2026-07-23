from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.schemas.evaluation import (
    RagasConversationReadinessRequest,
    RagasRunCreateRequest,
)
from app.api.schemas.evaluation import (
    TestGenFromConversationsRequest as ConversationsTestGenRequest,
)
from app.models.chat import Conversation, Message
from app.models.evaluation import RagasEvaluationRun


def _criterion_value(expr):  # noqa: ANN001
    right = getattr(expr, "right", None)
    if hasattr(right, "value"):
        return right.value
    if hasattr(right, "effective_value"):
        return right.effective_value
    return None


def _matches(row: object, expr) -> bool:  # noqa: ANN001
    operator = getattr(getattr(expr, "operator", None), "__name__", "")
    left = getattr(expr, "left", None)
    key = getattr(left, "key", None)
    if not key:
        return True
    value = getattr(row, key, None)
    candidate = _criterion_value(expr)
    if operator == "eq":
        return value == candidate
    if operator == "in_op":
        return value in list(candidate or [])
    return True


class _FakeQuery:
    def __init__(self, rows: list[object], entities: tuple[object, ...]) -> None:
        self._rows = list(rows)
        self._entities = entities
        self._filters = []
        self._offset = 0
        self._limit: int | None = None

    def filter(self, *criteria):  # noqa: ANN001
        self._filters.extend(criteria)
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def offset(self, value: int):
        self._offset = int(value)
        return self

    def limit(self, value: int):
        self._limit = int(value)
        return self

    def _filtered(self) -> list[object]:
        rows = list(self._rows)
        for expr in self._filters:
            rows = [row for row in rows if _matches(row, expr)]
        return rows

    def _materialize(self, row: object):  # noqa: ANN001
        first = self._entities[0] if self._entities else None
        if first is None or first in {Conversation, Message, RagasEvaluationRun}:
            return row
        values = []
        for entity in self._entities:
            key = getattr(entity, "key", None)
            values.append(getattr(row, key, None))
        return tuple(values)

    def count(self) -> int:
        return len(self._filtered())

    def first(self):
        rows = self._filtered()
        if not rows:
            return None
        return self._materialize(rows[0])

    def all(self) -> list[object]:
        rows = self._filtered()
        if self._offset:
            rows = rows[self._offset :]
        if self._limit is not None:
            rows = rows[: self._limit]
        return [self._materialize(row) for row in rows]


class _FakeDB:
    def __init__(
        self,
        *,
        conversations: list[Conversation] | None = None,
        runs: list[RagasEvaluationRun] | None = None,
        messages: list[Message] | None = None,
    ) -> None:
        self.conversations = list(conversations or [])
        self.runs = list(runs or [])
        self.messages = list(messages or [])
        self.message_query_count = 0
        self.commits = 0
        self.rollbacks = 0

    def query(self, *entities):  # noqa: ANN001
        first = entities[0] if entities else None
        model = first if first in {Conversation, Message, RagasEvaluationRun} else getattr(first, "class_", None)
        if model is Conversation:
            return _FakeQuery(list(self.conversations), entities)
        if model is Message:
            self.message_query_count += 1
            return _FakeQuery(list(self.messages), entities)
        if model is RagasEvaluationRun:
            return _FakeQuery(list(self.runs), entities)
        return _FakeQuery([], entities)

    def add(self, value: object) -> None:
        if isinstance(value, RagasEvaluationRun):
            if getattr(value, "id", None) is None:
                value.id = uuid4()
            self.runs.append(value)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _value: object) -> None:
        return None

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        return None


def _conversation(*, tenant_id, owner_account_id: str, conversation_id=None) -> Conversation:  # noqa: ANN001
    return Conversation(
        id=conversation_id or uuid4(),
        tenant_id=tenant_id,
        owner_account_id=owner_account_id,
        document_ids=[],
    )


def _evaluation_run(*, tenant_id, account_id: str, conversation_id, created_at=None) -> RagasEvaluationRun:  # noqa: ANN001
    return RagasEvaluationRun(
        id=uuid4(),
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=conversation_id,
        status="completed",
        metrics=[],
        params={},
        summary={},
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_ragas_conversation_readiness_rejects_cross_account_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.evaluations as evaluations_api

    tenant_id = uuid4()
    conversation = _conversation(tenant_id=tenant_id, owner_account_id="acct-1")
    db = _FakeDB(conversations=[conversation])
    monkeypatch.setattr(evaluations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await evaluations_api.get_ragas_conversation_readiness(
            RagasConversationReadinessRequest(conversation_ids=[conversation.id]),
            tenant_id=tenant_id,
            account_id="acct-2",
            db=db,
        )

    assert exc_info.value.status_code == 403
    assert db.message_query_count == 0


@pytest.mark.asyncio
async def test_create_ragas_run_rejects_cross_account_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.evaluations as evaluations_api

    tenant_id = uuid4()
    conversation = _conversation(tenant_id=tenant_id, owner_account_id="acct-1")
    db = _FakeDB(conversations=[conversation])
    monkeypatch.setattr(evaluations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await evaluations_api.create_ragas_run(
            RagasRunCreateRequest(conversation_id=conversation.id),
            BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="acct-2",
            db=db,
        )

    assert exc_info.value.status_code == 403
    assert db.runs == []


@pytest.mark.asyncio
async def test_list_ragas_runs_hides_other_accounts_conversation_runs_but_keeps_global_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.evaluations as evaluations_api

    tenant_id = uuid4()
    my_conversation = _conversation(tenant_id=tenant_id, owner_account_id="acct-1")
    their_conversation = _conversation(tenant_id=tenant_id, owner_account_id="acct-2")
    global_run = _evaluation_run(
        tenant_id=tenant_id,
        account_id="acct-any",
        conversation_id=None,
        created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    my_run = _evaluation_run(
        tenant_id=tenant_id,
        account_id="acct-1",
        conversation_id=my_conversation.id,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    their_run = _evaluation_run(
        tenant_id=tenant_id,
        account_id="acct-2",
        conversation_id=their_conversation.id,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db = _FakeDB(conversations=[my_conversation, their_conversation], runs=[global_run, my_run, their_run])
    monkeypatch.setattr(evaluations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    response = await evaluations_api.list_ragas_runs(
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert response["total"] == 2
    assert [item.id for item in response["items"]] == [global_run.id, my_run.id]


@pytest.mark.asyncio
async def test_list_ragas_runs_rejects_foreign_conversation_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.evaluations as evaluations_api

    tenant_id = uuid4()
    my_conversation = _conversation(tenant_id=tenant_id, owner_account_id="acct-1")
    their_conversation = _conversation(tenant_id=tenant_id, owner_account_id="acct-2")
    run = _evaluation_run(
        tenant_id=tenant_id,
        account_id="acct-2",
        conversation_id=their_conversation.id,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db = _FakeDB(conversations=[my_conversation, their_conversation], runs=[run])
    monkeypatch.setattr(evaluations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await evaluations_api.list_ragas_runs(
            tenant_id=tenant_id,
            account_id="acct-1",
            conversation_id=their_conversation.id,
            db=db,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_ragas_run_rejects_cross_account_conversation_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.evaluations as evaluations_api

    tenant_id = uuid4()
    conversation = _conversation(tenant_id=tenant_id, owner_account_id="acct-1")
    run = _evaluation_run(tenant_id=tenant_id, account_id="acct-1", conversation_id=conversation.id)
    db = _FakeDB(conversations=[conversation], runs=[run])
    monkeypatch.setattr(evaluations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await evaluations_api.get_ragas_run(
            run.id,
            tenant_id=tenant_id,
            account_id="acct-2",
            db=db,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_generate_test_cases_from_conversations_rejects_cross_account_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.evaluations as evaluations_api

    tenant_id = uuid4()
    conversation = _conversation(tenant_id=tenant_id, owner_account_id="acct-1")
    db = _FakeDB(conversations=[conversation])
    monkeypatch.setattr(evaluations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await evaluations_api.generate_test_cases_from_conversations(
            ConversationsTestGenRequest(
                conversation_ids=[conversation.id],
                auto_save_as_cases=False,
            ),
            tenant_id=tenant_id,
            account_id="acct-2",
            db=db,
        )

    assert exc_info.value.status_code == 403


def test_generate_questions_from_conversations_fails_closed_for_cross_account_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.evaluation.test_generator import generate_questions_from_conversations

    tenant_id = uuid4()
    conversation = _conversation(tenant_id=tenant_id, owner_account_id="acct-1")
    db = _FakeDB(conversations=[conversation])

    with pytest.raises(HTTPException) as exc_info:
        generate_questions_from_conversations(
            db=db,
            tenant_id=tenant_id,
            account_id="acct-2",
            conversation_ids=[conversation.id],
        )

    assert exc_info.value.status_code == 403
    assert db.message_query_count == 0


def test_run_conversation_ragas_evaluation_fails_closed_without_reading_messages_for_cross_account_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.evaluation.ragas as ragas_module

    tenant_id = uuid4()
    conversation = _conversation(tenant_id=tenant_id, owner_account_id="acct-1")
    run = _evaluation_run(tenant_id=tenant_id, account_id="acct-1", conversation_id=conversation.id)
    db = _FakeDB(conversations=[conversation], runs=[run])
    monkeypatch.setattr(ragas_module, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(ragas_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    ragas_module.run_conversation_ragas_evaluation(
        run_id=run.id,
        tenant_id=tenant_id,
        account_id="acct-2",
        conversation_id=conversation.id,
        metric_names=["faithfulness"],
        max_turns=10,
        skip_empty_contexts=True,
    )

    assert run.status == "failed"
    assert run.error_message == "Conversation is not accessible"
    assert db.message_query_count == 0
