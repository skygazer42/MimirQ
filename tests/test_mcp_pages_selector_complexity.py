from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.rag.agents.tools import mcp_tools
from app.rag.agents.tools.mcp_client import DocumentToolScope, MCPToolError
from app.rag.agents.tools.mcp_tools import _parse_pages_selector, calculate


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        (3, [3]),
        (0, []),
        ("", []),
        ("1, 3, 2, 3", [1, 2, 3]),
        ("5-3", [3, 4, 5]),
        ("bad, 2-x, -1, 4", [4]),
    ],
)
def test_parse_pages_selector_preserves_normalization(value, expected: list[int]) -> None:
    assert _parse_pages_selector(value) == expected


def test_parse_pages_selector_preserves_per_range_and_total_caps() -> None:
    assert _parse_pages_selector("1-200") == list(range(1, 101))
    assert _parse_pages_selector("200-1") == list(range(1, 101))


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 3 * 4", 14),
        ("2 ^ 5", 32),
        ("pow(5, 2, 7)", 4),
        ("sum([1, 2, 3])", 6),
        ("round(sqrt(2), 3)", 1.414),
    ],
)
def test_calculate_preserves_supported_math(expression: str, expected) -> None:
    assert calculate(expression) == {
        "expression": expression,
        "result": expected,
        "success": True,
    }


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "unknown + 1",
        "math.sqrt(4)",
        "round(number=2)",
        "True + 1",
        "[x for x in [1]]",
        "2 ** 5000",
        "pow(2, 3, 0)",
    ],
)
def test_calculate_preserves_rejection_boundary(expression: str) -> None:
    with pytest.raises(MCPToolError, match=r"\S"):
        calculate(expression)


class _Query:
    def __init__(self, result) -> None:
        self.result = result

    def filter(self, *_criteria):
        return self

    def order_by(self, *_criteria):
        return self

    def first(self):
        return self.result

    def all(self):
        return list(self.result)


class _DocumentDB:
    def __init__(self, document, chunks) -> None:
        self.document = document
        self.chunks = chunks

    def query(self, model):
        return _Query(self.document if model.__name__ == "Document" else self.chunks)


def test_get_document_content_sync_preserves_scope_page_and_content_contract(monkeypatch) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        disabled_at=None,
        access_mode="inherit",
        owner_id=None,
        doc_metadata={},
        filename="guide.md",
        file_type="md",
    )
    chunks = [
        SimpleNamespace(id=uuid4(), content="page one", page_number=1, chunk_index=0),
        SimpleNamespace(id=uuid4(), content="page two", page_number=2, chunk_index=1),
    ]
    db = _DocumentDB(document, chunks)

    @contextmanager
    def fake_session():
        yield db

    monkeypatch.setattr(mcp_tools, "_db_session", fake_session)
    account_id = "authorized-reader"
    scope = DocumentToolScope(tenant_id, account_id, frozenset({dataset_id}), frozenset({document_id}))

    def allowed_document_ids(session, requested_tenant, requested_account, requested_document_ids):
        assert session is db
        assert requested_tenant == tenant_id
        assert requested_account == account_id
        assert requested_document_ids == [document_id]
        return {document_id}, set()

    monkeypatch.setattr("app.services.documents.read_scope.get_allowed_document_id_sets", allowed_document_ids)

    result = mcp_tools._get_document_content_sync(
        str(document_id),
        page=2,
        dataset_id=str(dataset_id),
        _scope=scope,
    )

    assert result == {
        "document_id": str(document_id),
        "dataset_id": str(dataset_id),
        "filename": "guide.md",
        "file_type": "md",
        "page": 2,
        "chunk_count": 1,
        "returned_chunks": 1,
        "pages": [2],
        "truncated": False,
        "content": "page two",
    }


def test_get_document_content_sync_preserves_validation_errors() -> None:
    document_id = str(uuid4())
    scope = DocumentToolScope(uuid4(), "authorized-reader")
    assert mcp_tools._get_document_content_sync(document_id, _scope=scope)["error"] == "dataset_id is required"
    assert mcp_tools._get_document_content_sync(document_id, dataset_id="bad", _scope=scope)["error"] == (
        "dataset_id must be a UUID"
    )
    assert mcp_tools._get_document_content_sync("bad", dataset_id=str(uuid4()), _scope=scope)["error"] == (
        "document_id must be a UUID"
    )
    assert mcp_tools._get_document_content_sync(document_id, dataset_id=str(uuid4()))["error"] == (
        "Document tool scope with a tenant is required"
    )
