import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BLOCK_DOCUMENT_ROUTER_IMPORT = """
import importlib.abc
import sys

class BlockDocumentRouter(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.api.v1.documents":
            raise AssertionError("chunk operations must not import the document router")

sys.meta_path.insert(0, BlockDocumentRouter())
"""


def _run_without_document_router(script: str) -> None:
    env = os.environ.copy()
    env["SECRET_KEY"] = "test-only-signing-key-not-for-production"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", _BLOCK_DOCUMENT_ROUTER_IMPORT + textwrap.dedent(script)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "module_name",
    ["app.services.document_chunk_operations", "app.api.v1.document_chunks_write"],
)
def test_chunk_operations_import_without_document_router(module_name: str) -> None:
    _run_without_document_router(
        f"""
        import importlib

        importlib.import_module({module_name!r})
        assert "app.api.v1.documents" not in sys.modules
        """
    )


def test_chunk_http_write_gates_and_contracts_work_without_document_router() -> None:
    _run_without_document_router(
        """
        import uuid

        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from app.api.dependencies.auth import get_current_account_id
        from app.api.dependencies.tenant import get_tenant_id
        from app.api.v1 import document_chunks_write
        from app.core.database import get_db
        from app.services import dataset_service

        tenant_id = uuid.uuid4()
        document_id = uuid.uuid4()
        chunk_id = uuid.uuid4()

        def deny_membership(*args, **kwargs):
            raise HTTPException(status_code=403, detail="membership required")

        dataset_service.ensure_member = deny_membership
        app = FastAPI()
        app.include_router(document_chunks_write.router, prefix="/documents")
        app.dependency_overrides[get_tenant_id] = lambda: tenant_id
        app.dependency_overrides[get_current_account_id] = lambda: "member"
        app.dependency_overrides[get_db] = lambda: object()
        root = f"/documents/{document_id}/chunks"
        cases = [
            ("POST", root, {"content": "new chunk"}, 201, "DocumentChunkSchema"),
            ("PATCH", f"{root}/{chunk_id}", {"content": "updated"}, 200, "DocumentChunkSchema"),
            ("DELETE", f"{root}/{chunk_id}", None, 204, None),
            ("POST", f"{root}/{chunk_id}/disable", None, 200, "DocumentChunkSchema"),
            ("POST", f"{root}/{chunk_id}/enable", None, 200, "DocumentChunkSchema"),
            ("POST", f"{root}/reembed", {"chunk_ids": [str(chunk_id)]}, 200, "DocumentChunkReembedResponse"),
        ]
        with TestClient(app) as client:
            for method, path, payload, success_status, response_model in cases:
                response = client.request(method, path, json=payload)
                assert response.status_code == 403, (method, path, response.text)
                assert response.json() == {"detail": "membership required"}
            response = client.post(root, json={"content": ""})
            assert response.status_code == 422

        paths = app.openapi()["paths"]
        for method, path, payload, success_status, response_model in cases:
            schema_path = path.replace(str(document_id), "{document_id}").replace(str(chunk_id), "{chunk_id}")
            operation = paths[schema_path][method.lower()]
            assert {"400", "403", "404", "409", "416", "422"} <= operation["responses"].keys()
            success = operation["responses"][str(success_status)]
            if response_model:
                assert success["content"]["application/json"]["schema"]["$ref"] == (
                    f"#/components/schemas/{response_model}"
                )
            else:
                assert "content" not in success
        assert "app.api.v1.documents" not in sys.modules
        """
    )


@pytest.mark.parametrize(
    ("operation_name", "method", "suffix", "status_code"),
    [
        ("create_chunk", "POST", "", 201),
        ("patch_chunk", "PATCH", "/{chunk_id}", 200),
        ("delete_chunk", "DELETE", "/{chunk_id}", 204),
        ("disable_chunk", "POST", "/{chunk_id}/disable", 200),
        ("enable_chunk", "POST", "/{chunk_id}/enable", 200),
        ("reembed_chunks", "POST", "/reembed", 200),
    ],
)
def test_chunk_http_adapter_preserves_operation_inputs_and_response(
    monkeypatch: pytest.MonkeyPatch,
    operation_name: str,
    method: str,
    suffix: str,
    status_code: int,
) -> None:
    import uuid

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.dependencies.auth import get_current_account_id
    from app.api.dependencies.tenant import get_tenant_id
    from app.api.v1 import document_chunks_write
    from app.core.database import get_db
    from app.services import document_chunk_operations

    assert callable(getattr(document_chunk_operations, operation_name, None))
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    database = object()
    captured: dict[str, object] = {}
    chunk_result = {
        "id": str(chunk_id),
        "content": "updated chunk",
        "chunk_index": 3,
        "metadata": {"source": "manual"},
    }
    reembed_result = {"reembedded": 1, "not_found": [], "denied": [], "conflicts": []}
    payloads = {
        "create_chunk": {"content": "new chunk", "page_number": 1, "metadata": {"source": "manual"}},
        "patch_chunk": {"content": "updated chunk", "page_number": None, "metadata": {"obsolete": None}},
        "reembed_chunks": {"chunk_ids": [str(chunk_id)]},
    }

    def operation(**kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        if operation_name == "delete_chunk":
            return None
        if operation_name == "reembed_chunks":
            return reembed_result
        return chunk_result

    async def async_operation(**kwargs):  # noqa: ANN003, ANN202
        return operation(**kwargs)

    monkeypatch.setattr(
        document_chunk_operations,
        operation_name,
        async_operation if operation_name in {"delete_chunk", "disable_chunk"} else operation,
    )
    app = FastAPI()
    app.include_router(document_chunks_write.router, prefix="/documents")
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "editor"
    app.dependency_overrides[get_db] = lambda: database
    path = f"/documents/{document_id}/chunks" + suffix.format(chunk_id=chunk_id)
    with TestClient(app) as client:
        response = client.request(method, path, json=payloads.get(operation_name))

    assert response.status_code == status_code, response.text
    assert captured["document_id"] == document_id
    assert captured["tenant_id"] == tenant_id
    assert captured["account_id"] == "editor"
    assert captured["db"] is database
    expected_arguments = {"document_id", "tenant_id", "account_id", "db"}
    if "{chunk_id}" in suffix:
        expected_arguments.add("chunk_id")
        assert captured["chunk_id"] == chunk_id
    if operation_name in payloads:
        expected_arguments.add("payload")
        payload = captured["payload"]
        assert payload.model_dump(mode="json", exclude_unset=True) == payloads[operation_name]
        assert payload.model_fields_set == payloads[operation_name].keys()
    assert captured.keys() == expected_arguments
    if operation_name == "delete_chunk":
        assert response.content == b""
    elif operation_name == "reembed_chunks":
        assert response.json() == reembed_result
    else:
        body = response.json()
        assert {key: body[key] for key in chunk_result} == chunk_result
