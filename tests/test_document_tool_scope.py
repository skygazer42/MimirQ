from uuid import uuid4

import pytest

from app.rag.agents.tools.mcp_client import DocumentToolScope, MCPToolError
from app.rag.agents.tools.mcp_tools import _document_tool_result, _require_document_scope


def test_document_tools_require_an_explicit_tenant_and_account():
    with pytest.raises(MCPToolError, match="tenant"):
        _require_document_scope(None)
    with pytest.raises(MCPToolError, match="account"):
        _require_document_scope(DocumentToolScope(tenant_id=uuid4(), account_id=""))


def test_document_tools_preserve_the_trusted_request_scope():
    scope = DocumentToolScope(tenant_id=uuid4(), account_id="member", dataset_ids=frozenset({uuid4()}))
    assert _require_document_scope(scope) is scope


def test_document_tool_errors_do_not_become_successful_results():
    with pytest.raises(MCPToolError, match="store unavailable"):
        _document_tool_result({"error": "store unavailable"})
