from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.models.chat import Conversation
from app.models.tenant import TenantMember


def _criterion_value(expr):  # noqa: ANN001
    right = getattr(expr, "right", None)
    if hasattr(right, "value"):
        return right.value
    if hasattr(right, "effective_value"):
        return right.effective_value
    return right


def _matches(row: object, expr) -> bool:  # noqa: ANN001
    if isinstance(expr, tuple) and expr[0] == "or":
        return any(_matches(row, clause) for clause in expr[1])

    clauses = getattr(expr, "clauses", None)
    operator_name = getattr(getattr(expr, "operator", None), "__name__", "")
    if clauses is not None and operator_name == "or_":
        return any(_matches(row, clause) for clause in clauses)

    operator = getattr(getattr(expr, "operator", None), "__name__", "")
    left = getattr(expr, "left", None)
    key = getattr(left, "key", None)
    if not key:
        return True
    if operator == "eq":
        return getattr(row, key, None) == _criterion_value(expr)
    if operator == "is_":
        return getattr(row, key, None) is None
    return True


class _FakeQuery:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)
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

    def join(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def subquery(self):
        return SimpleNamespace(c=SimpleNamespace(id="id", rn="rn"))

    def update(self, values, synchronize_session=False):  # noqa: ANN001
        del synchronize_session
        rows = self._filtered()
        for row in rows:
            for key, value in values.items():
                attr = getattr(key, "key", key)
                setattr(row, attr, value)
        return len(rows)

    def _filtered(self) -> list[object]:
        rows = list(self._rows)
        for expr in self._filters:
            rows = [row for row in rows if _matches(row, expr)]
        return rows

    def count(self) -> int:
        return len(self._filtered())

    def first(self):
        rows = self._filtered()
        return rows[0] if rows else None

    def all(self) -> list[object]:
        rows = self._filtered()
        if self._offset:
            rows = rows[self._offset :]
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows


class _FakeDB:
    def __init__(
        self,
        *,
        conversations: list[Conversation] | None = None,
        tenant_members: list[TenantMember] | None = None,
    ) -> None:
        self.conversations = list(conversations or [])
        self.tenant_members = list(tenant_members or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commits = 0

    def query(self, *entities):  # noqa: ANN001
        first = entities[0] if entities else None
        if first is Conversation:
            return _FakeQuery(list(self.conversations))
        if first is TenantMember:
            return _FakeQuery(list(self.tenant_members))
        return _FakeQuery([])

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, Conversation):
            self.conversations.append(value)

    def delete(self, value: object) -> None:
        self.deleted.append(value)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _value: object) -> None:
        return None

    def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_create_conversation_sets_owner_account_id(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.chat_conversations as conversations_api

    tenant_id = uuid4()
    dataset_id = uuid4()
    db = _FakeDB()
    monkeypatch.setattr(conversations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(conversations_api.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(
        conversations_api.DatasetService,
        "assert_dataset_readable",
        lambda *_a, **_k: None,
        raising=True,
    )

    created = await conversations_api.create_conversation(
        SimpleNamespace(title="Owned", dataset_id=dataset_id, document_ids=[]),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert created.owner_account_id == "acct-1"


def test_ensure_conversation_access_fails_closed_for_ownerless_rows() -> None:
    import app.services.chat_conversation_access as conversation_access

    tenant_id = uuid4()
    conversation = Conversation(id=uuid4(), tenant_id=tenant_id, owner_account_id=None, document_ids=[])
    db = _FakeDB(
        conversations=[conversation],
        tenant_members=[
            TenantMember(tenant_id=tenant_id, user_id="acct-1", is_active=True, is_current=True),
            TenantMember(tenant_id=tenant_id, user_id="acct-2", is_active=True, is_current=True),
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        conversation_access.ensure_conversation_access(
            db=db,
            tenant_id=tenant_id,
            account_id="acct-1",
            conv=conversation,
        )

    assert exc_info.value.status_code == 403


def test_ensure_conversation_access_backfills_owner_from_legacy_user_id() -> None:
    import app.services.chat_conversation_access as conversation_access

    tenant_id = uuid4()
    legacy_user_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        user_id=legacy_user_id,
        owner_account_id=None,
        document_ids=[],
    )
    db = _FakeDB(conversations=[conversation])

    allowed = conversation_access.ensure_conversation_access(
        db=db,
        tenant_id=tenant_id,
        account_id=str(legacy_user_id),
        conv=conversation,
    )

    assert allowed == []
    assert conversation.owner_account_id is None
    assert db.commits == 0


def test_ensure_conversation_access_fails_closed_for_ownerless_row_with_single_effective_member() -> None:
    import app.services.chat_conversation_access as conversation_access

    tenant_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_account_id=None,
        document_ids=[],
    )
    db = _FakeDB(
        conversations=[conversation],
        tenant_members=[
            TenantMember(tenant_id=tenant_id, user_id="acct-1", is_active=True, is_current=True),
            TenantMember(tenant_id=tenant_id, user_id="acct-1", is_active=True, is_current=False),
            TenantMember(tenant_id=tenant_id, user_id="acct-2", is_active=False, is_current=True),
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        conversation_access.ensure_conversation_access(
            db=db,
            tenant_id=tenant_id,
            account_id="acct-1",
            conv=conversation,
        )

    assert exc_info.value.status_code == 403
    assert conversation.owner_account_id is None
    assert db.commits == 0


def test_ensure_conversation_access_rechecks_dataset_scope_readability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_conversation_access as conversation_access

    tenant_id = uuid4()
    dataset_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_account_id="acct-1",
        dataset_id=dataset_id,
        document_ids=[],
    )

    monkeypatch.setattr(conversation_access.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)

    def _deny(*_args, **_kwargs) -> None:  # noqa: ANN001
        raise HTTPException(status_code=403, detail="dataset denied")

    monkeypatch.setattr(
        conversation_access.DatasetService,
        "assert_dataset_readable",
        _deny,
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        conversation_access.ensure_conversation_access(
            db=object(),
            tenant_id=tenant_id,
            account_id="acct-1",
            conv=conversation,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "invoke"),
    [
        (
            "update",
            lambda mod, conv_id, tenant_id, db: mod.update_conversation(
                conv_id,
                SimpleNamespace(title="retitle", model_fields_set={"title"}),
                tenant_id=tenant_id,
                account_id="acct-2",
                db=db,
            ),
        ),
        (
            "messages",
            lambda mod, conv_id, tenant_id, db: mod.get_conversation_messages(
                conv_id,
                tenant_id=tenant_id,
                account_id="acct-2",
                db=db,
            ),
        ),
        (
            "export",
            lambda mod, conv_id, tenant_id, db: mod.export_conversation(
                conv_id,
                tenant_id=tenant_id,
                account_id="acct-2",
                db=db,
            ),
        ),
        (
            "delete",
            lambda mod, conv_id, tenant_id, db: mod.delete_conversation(
                conv_id,
                tenant_id=tenant_id,
                account_id="acct-2",
                db=db,
            ),
        ),
    ],
    ids=["update", "messages", "export", "delete"],
)
async def test_conversation_routes_reject_cross_account_access(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    invoke,
) -> None:
    import app.api.v1.chat_conversations as conversations_api

    tenant_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_account_id="acct-1",
        document_ids=[],
    )
    db = _FakeDB(conversations=[conversation])
    monkeypatch.setattr(conversations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await invoke(conversations_api, conversation.id, tenant_id, db)

    assert exc_info.value.status_code == 403, name


@pytest.mark.asyncio
async def test_list_conversations_hides_other_accounts_open_scope_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.chat_conversations as conversations_api

    tenant_id = uuid4()
    mine = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_account_id="acct-1",
        title="Mine",
        document_ids=[],
        message_count=1,
    )
    theirs = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_account_id="acct-2",
        title="Theirs",
        document_ids=[],
        message_count=1,
    )
    db = _FakeDB(conversations=[mine, theirs])
    monkeypatch.setattr(conversations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    response = await conversations_api.list_conversations(
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert response["total"] == 1
    assert [item["id"] for item in response["items"]] == [mine.id]


@pytest.mark.asyncio
async def test_list_conversations_hides_revoked_dataset_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.chat_conversations as conversations_api

    tenant_id = uuid4()
    allowed = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_account_id="acct-1",
        title="Open",
        document_ids=[],
        message_count=1,
    )
    revoked = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_account_id="acct-1",
        title="Revoked",
        dataset_id=uuid4(),
        document_ids=[],
        message_count=1,
    )
    db = _FakeDB(conversations=[allowed, revoked])
    monkeypatch.setattr(conversations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(conversations_api.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)

    def _deny(*_args, **_kwargs) -> None:  # noqa: ANN001
        raise HTTPException(status_code=403, detail="dataset denied")

    monkeypatch.setattr(conversations_api.DatasetService, "assert_dataset_readable", _deny, raising=True)

    response = await conversations_api.list_conversations(
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert [item["id"] for item in response["items"]] == [allowed.id]
    assert response["total"] == 1
    assert response["returned"] == 1
    assert response["next_skip"] is None


@pytest.mark.asyncio
async def test_list_conversations_includes_safe_ownerless_legacy_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.chat_conversations as conversations_api

    tenant_id = uuid4()
    legacy_user_id = uuid4()
    legacy = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        user_id=legacy_user_id,
        owner_account_id=None,
        title="Legacy",
        document_ids=[],
        message_count=1,
    )
    db = _FakeDB(conversations=[legacy])
    monkeypatch.setattr(conversations_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    response = await conversations_api.list_conversations(
        tenant_id=tenant_id,
        account_id=str(legacy_user_id),
        db=db,
    )

    assert response["total"] == 0
    assert response["items"] == []
    assert legacy.owner_account_id is None


def test_resolve_chat_conversation_scope_sets_owner_for_new_conversation() -> None:
    import app.services.chat_scope as chat_scope

    tenant_id = uuid4()
    db = _FakeDB()

    resolved = chat_scope.resolve_chat_conversation_scope(
        db=db,
        tenant_id=tenant_id,
        account_id="acct-1",
        conversation_id=None,
        request_document_ids=None,
        request_dataset_id=None,
        request_message="hello",
        allow_empty_docs=True,
        allow_open_scope=True,
        conversation_not_found_detail="missing",
        dataset_required_detail="dataset required",
        document_scope_mismatch_detail="mismatch",
        empty_scope_detail="empty",
    )

    assert resolved.conversation.owner_account_id == "acct-1"


def test_resolve_chat_conversation_scope_rejects_cross_account_continuation() -> None:
    import app.services.chat_scope as chat_scope

    tenant_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_account_id="acct-1",
        document_ids=[],
    )
    db = _FakeDB(conversations=[conversation])

    with pytest.raises(HTTPException) as exc_info:
        chat_scope.resolve_chat_conversation_scope(
            db=db,
            tenant_id=tenant_id,
            account_id="acct-2",
            conversation_id=conversation.id,
            request_document_ids=None,
            request_dataset_id=None,
            request_message="continue",
            allow_empty_docs=True,
            allow_open_scope=True,
            conversation_not_found_detail="missing",
            dataset_required_detail="dataset required",
            document_scope_mismatch_detail="mismatch",
            empty_scope_detail="empty",
        )

    assert exc_info.value.status_code == 403


def test_conversation_owner_runtime_migration_contracts_present() -> None:
    migrations_text = Path("app/core/migrations.py").read_text(encoding="utf-8")
    model_text = Path("app/models/chat.py").read_text(encoding="utf-8")
    alembic_text = Path("alembic/versions/0021_add_conversation_owner_account_id.py").read_text(encoding="utf-8")

    assert "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner_account_id VARCHAR(255);" in migrations_text
    assert "UPDATE conversations SET owner_account_id = user_id::text" in migrations_text
    assert "CREATE INDEX IF NOT EXISTS ix_conversations_tenant_owner_account_id " in migrations_text
    assert "HAVING COUNT(DISTINCT tm.user_id) = 1" not in migrations_text
    assert "HAVING COUNT(DISTINCT tm.user_id) = 1" not in alembic_text
    assert 'Index("ix_conversations_tenant_owner_account_id", "tenant_id", "owner_account_id")' in model_text
    assert "owner_account_id = Column(String(255), nullable=True, index=True)" not in model_text


def test_alembic_migration_graph_has_single_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert script.get_heads() == ["0021_conv_owner_account"]
