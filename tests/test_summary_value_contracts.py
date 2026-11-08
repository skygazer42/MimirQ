from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1 import chat_conversation_memory
from app.core.database import Base
from app.models.conversation_summary import ConversationSummary
from app.services.conversation_summary_service import get_conversation_summary


@pytest.fixture
def summary_db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ConversationSummary.__table__])
    with Session(engine) as db:
        yield db
    engine.dispose()


@pytest.mark.parametrize("text", ["", " preserved summary "])
def test_summary_endpoint_returns_the_actual_tenant_scoped_stored_text(
    summary_db: Session, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    tenant_id, conversation_id = uuid4(), uuid4()
    summary_db.add(ConversationSummary(tenant_id=tenant_id, conversation_id=conversation_id, summary=text))
    summary_db.commit()

    def authorize(db: Session, **scope):
        assert db is summary_db
        assert scope == {"tenant_id": tenant_id, "account_id": "reader", "conversation_id": conversation_id}

    monkeypatch.setattr(chat_conversation_memory, "_load_accessible_conversation", authorize)
    response = chat_conversation_memory.get_conversation_summary_endpoint(
        conversation_id, tenant_id=tenant_id, account_id="reader", db=summary_db
    )

    assert response == {"available": bool(text), "summary": text}
    assert get_conversation_summary(summary_db, tenant_id=uuid4(), conversation_id=conversation_id) is None


def test_summary_lookup_keeps_a_real_not_found_result(summary_db: Session) -> None:
    assert get_conversation_summary(summary_db, tenant_id=uuid4(), conversation_id=uuid4()) is None


def test_summary_endpoint_exposes_a_read_failure_after_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    def authorize(*_args, **_kwargs):
        return None

    def read_failure(*_args, **_kwargs):
        raise RuntimeError("summary storage unavailable")

    monkeypatch.setattr(chat_conversation_memory, "_load_accessible_conversation", authorize)
    monkeypatch.setattr(chat_conversation_memory, "get_conversation_summary", read_failure)

    with pytest.raises(RuntimeError, match="summary storage unavailable"):
        chat_conversation_memory.get_conversation_summary_endpoint(
            uuid4(), tenant_id=uuid4(), account_id="reader", db=object()
        )


def test_summary_endpoint_keeps_authorization_rejection_before_storage_access(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail="not allowed")

    def unexpected_read(*_args, **_kwargs):
        pytest.fail("Summary read must follow authorization")

    monkeypatch.setattr(chat_conversation_memory, "_load_accessible_conversation", denied)
    monkeypatch.setattr(chat_conversation_memory, "get_conversation_summary", unexpected_read)

    with pytest.raises(HTTPException) as error:
        chat_conversation_memory.get_conversation_summary_endpoint(
            uuid4(), tenant_id=uuid4(), account_id="reader", db=object()
        )

    assert error.value.status_code == 403
