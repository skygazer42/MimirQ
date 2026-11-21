import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("module", ["assets", "chunk_preview", "upload"])
def test_document_child_import_does_not_load_router_aggregator(module):  # noqa: ANN001
    code = f"""
import importlib
import importlib.abc
import sys

class NoDocumentAggregator(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.api.v1.documents.routes":
            raise AssertionError("document child depends on its route aggregator")

sys.meta_path.insert(0, NoDocumentAggregator())
child = importlib.import_module("app.api.v1.documents.{module}")
assert child.router.routes
assert "app.api.v1.documents.routes" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr


def test_preview_membership_gate_runs_without_importing_the_aggregator():
    code = """
import asyncio
import importlib.abc
import io
import sys
from uuid import uuid4
from fastapi import HTTPException, Request, UploadFile
from app.api.v1.documents import preview

class NoDocumentAggregator(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.api.v1.documents.routes':
            raise AssertionError("request-time lookup through route aggregator")

def forbidden(*args):
    raise HTTPException(status_code=403, detail="membership gate")

preview.dataset_service.ensure_member = forbidden
sys.meta_path.insert(0, NoDocumentAggregator())

async def verify():
    try:
        await preview.preview_document(
            request=Request({"type": "http", "headers": []}),
            file=UploadFile(filename="input.txt", file=io.BytesIO(b"text")),
            form=preview.PreviewDocumentFormFields(),
            gov_overrides_form=preview.PreviewDocumentGovernanceOverridesFormFields(),
            tenant_id=uuid4(), account_id="member", db=object(),
        )
    except HTTPException as error:
        assert error.status_code == 403 and error.detail == "membership gate"
    else:
        raise AssertionError("membership failure was suppressed")

asyncio.run(verify())
assert 'app.api.v1.documents.routes' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", ["preview", "chunk_preview"])
def test_preview_source_has_no_api_aggregator_or_module_bag_dependency(module):  # noqa: ANN001
    source = (ROOT / "app/api/v1/documents" / f"{module}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "app.api.v1.documents.routes"
            assert not (node.module == "app.api.v1" and any(alias.name == "documents" for alias in node.names))
        if isinstance(node, ast.arg):
            assert node.arg not in {"documents_module", "docs_mod"}
