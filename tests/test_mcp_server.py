from __future__ import annotations

from fastapi.testclient import TestClient


def test_mcp_server_lists_default_tools() -> None:
    from app.rag.tools.mcp_server import create_mcp_app

    client = TestClient(create_mcp_app())
    res = client.get("/tools")

    assert res.status_code == 200, res.text
    body = res.json()
    assert "tools" in body
    names = {str(item.get("name") or "") for item in body["tools"] if isinstance(item, dict)}
    assert {"search_documents", "get_document_content", "calculate"}.issubset(names)


def test_mcp_server_executes_local_tool() -> None:
    from app.rag.tools.mcp_server import create_mcp_app

    client = TestClient(create_mcp_app())
    res = client.post(
        "/tools/execute",
        json={"name": "calculate", "arguments": {"expression": "2 + 3 * 4"}},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    assert body["data"]["result"] == 14
