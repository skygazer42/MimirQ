from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas.chat import ChatRAGConfig
from app.api.v1 import rag, retrieval_explain


class _NoDocumentsQuery:
    def __init__(self, rows=()) -> None:
        self.rows = rows

    def filter(self, *_args):
        return self

    def all(self):
        return list(self.rows)


class _NoDocumentsDB:
    def query(self, *_args):
        return _NoDocumentsQuery()


class _DeniedDocumentDB:
    def __init__(self, document_id) -> None:
        self.document_id = document_id

    def query(self, *_args):
        return _NoDocumentsQuery([(self.document_id, None, "only_me", "different-owner")])


@pytest.fixture
def allow_real_open_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag.settings, "CHAT_ALLOW_OPEN_SCOPE", True)
    monkeypatch.setattr(rag.settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True)
    monkeypatch.setattr(rag.dataset_service, "ensure_member", lambda *_args: None)


def test_unavailable_explicit_documents_do_not_become_open_retrieval(allow_real_open_scope) -> None:
    document_id = uuid4()
    with pytest.raises(HTTPException) as error:
        rag._resolve_retrieval_scope(
            db=_DeniedDocumentDB(document_id),
            tenant_id=uuid4(),
            account_id="reader",
            document_ids=[document_id],
            dataset_id=None,
        )

    assert error.value.status_code == 403


def test_genuinely_unselected_document_scope_keeps_the_open_scope_policy(allow_real_open_scope) -> None:
    assert rag._resolve_retrieval_scope(
        db=_NoDocumentsDB(),
        tenant_id=uuid4(),
        account_id="reader",
        document_ids=[],
        dataset_id=None,
    ) == (None, [], None)


@pytest.mark.asyncio
async def test_explain_rejects_unavailable_selection_before_building_graph_state(
    allow_real_open_scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_graph_state(**_kwargs):
        pytest.fail("A rejected document selection must not reach graph state construction")

    monkeypatch.setattr(retrieval_explain, "build_rag_state", unexpected_graph_state)
    document_id = uuid4()
    with pytest.raises(HTTPException) as error:
        await retrieval_explain.explain_retrieval(
            retrieval_explain.RetrievalExplainRequest(
                query="policy", document_ids=[document_id], rag_config=ChatRAGConfig(retrieval_profile="fast")
            ),
            tenant_id=uuid4(),
            account_id="reader",
            db=_DeniedDocumentDB(document_id),
        )

    assert error.value.status_code == 403
