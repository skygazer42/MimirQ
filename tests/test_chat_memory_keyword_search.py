from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, Uuid, create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    messages = Table(
        "messages",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid),
        Column("conversation_id", Uuid),
        Column("role", String),
        Column("content", Text),
        Column("created_at", DateTime(timezone=True)),
    )
    metadata.create_all(engine)
    with Session(engine) as db:
        yield db, messages
    engine.dispose()


def _insert(db, table, tenant, conversation, content, minute=0):
    db.execute(
        table.insert().values(
            id=uuid4(),
            tenant_id=tenant,
            conversation_id=conversation,
            role="user",
            content=content,
            created_at=datetime(2026, 11, 5, tzinfo=timezone.utc) + timedelta(minutes=minute),
        )
    )
    db.commit()


def test_memory_keyword_query_enforces_tenant_conversation_and_no_match(memory_db, monkeypatch):
    from app.core.config import settings
    from app.services.chat_memory_runtime import _retrieve_long_term_messages

    db, table = memory_db
    tenant, conversation = uuid4(), uuid4()
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_MIN_LEN", 1)
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_MAX_MESSAGES", 20)
    _insert(db, table, tenant, conversation, "apple orchard policy")
    _insert(db, table, uuid4(), conversation, "apple tenant secret")
    _insert(db, table, tenant, uuid4(), "apple other conversation")
    result = _retrieve_long_term_messages(db, conversation, tenant, "apple", top_k=5)
    assert [row["content"] for row in result] == ["apple orchard policy"]
    assert result[0]["from_long_term"] is True
    assert _retrieve_long_term_messages(db, conversation, tenant, "unrelatedword", top_k=5) == []


def test_memory_recent_window_applies_before_keyword_ranking(memory_db, monkeypatch):
    from app.core.config import settings
    from app.services.chat_memory_runtime import _retrieve_long_term_messages

    db, table = memory_db
    tenant, conversation = uuid4(), uuid4()
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_MIN_LEN", 1)
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_MAX_MESSAGES", 2)
    _insert(db, table, tenant, conversation, "apple old excluded", 0)
    _insert(db, table, tenant, conversation, "apple recent", 1)
    _insert(db, table, tenant, conversation, "river most recent", 2)
    result = _retrieve_long_term_messages(db, conversation, tenant, "apple", top_k=5)
    assert [row["content"] for row in result] == ["apple recent"]


def test_memory_chinese_matches_and_wildcards_are_literal(memory_db, monkeypatch):
    from app.core.config import settings
    from app.services import chat_memory_runtime as memory

    db, table = memory_db
    tenant, conversation = uuid4(), uuid4()
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_MIN_LEN", 1)
    monkeypatch.setattr(settings, "LONG_TERM_MEMORY_MAX_MESSAGES", 20)
    _insert(db, table, tenant, conversation, "社保缴纳办理说明")
    _insert(db, table, tenant, conversation, "100%_done marker")
    _insert(db, table, tenant, conversation, "100XXXdone marker", 1)
    assert memory._retrieve_long_term_messages(db, conversation, tenant, "社保")[0]["content"] == "社保缴纳办理说明"
    monkeypatch.setattr(memory, "tokenize_lexical_text", lambda _query: ["100%_done"])
    assert [row["content"] for row in memory._retrieve_long_term_messages(db, conversation, tenant, "literal")] == [
        "100%_done marker"
    ]


def test_empty_memory_query_does_not_open_a_database_query():
    from app.services.chat_memory_runtime import _retrieve_long_term_messages

    assert _retrieve_long_term_messages(None, uuid4(), uuid4(), " ") == []
