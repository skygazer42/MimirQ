import subprocess
import sys
import threading
from pathlib import Path
from uuid import uuid4

import pytest


def test_metadata_anchor_empty_scope_does_not_query_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dify_integration import metadata_anchor

    class Database:
        def query(self, *_args):
            pytest.fail("an empty dataset scope must not issue a query")

    monkeypatch.setattr(metadata_anchor.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED", True)
    assert (
        metadata_anchor.find_anchor_records(
            db=Database(), tenant_id=uuid4(), dataset_ids=[], query="neutral query", top_k=2
        )
        == []
    )


@pytest.mark.asyncio
async def test_metadata_anchor_offload_creates_and_closes_its_worker_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dify_integration import metadata_anchor

    calls: list[tuple[str, int]] = []

    class Database:
        def close(self):
            calls.append(("close", threading.get_ident()))

    def create_session():
        calls.append(("create", threading.get_ident()))
        return Database()

    monkeypatch.setattr(metadata_anchor, "SessionLocal", create_session)
    monkeypatch.setattr(metadata_anchor.settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED", True)
    monkeypatch.setattr(metadata_anchor.settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED", False)
    assert (
        await metadata_anchor.run_with_deadline(
            {"tenant_id": uuid4(), "dataset_ids": [], "query": "neutral query", "top_k": 2}, budget_deadline=None
        )
        == []
    )
    assert [name for name, _ in calls] == ["create", "close"]
    assert calls[0][1] == calls[1][1]
    assert calls[0][1] != threading.get_ident()


@pytest.mark.asyncio
async def test_expired_metadata_anchor_deadline_does_not_create_a_worker_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.dify_integration import metadata_anchor

    def unexpected_session():
        pytest.fail("expired budget must not create a worker session")

    monkeypatch.setattr(metadata_anchor, "SessionLocal", unexpected_session)
    assert (
        await metadata_anchor.run_with_deadline(
            {"tenant_id": uuid4(), "dataset_ids": [], "query": "neutral query", "top_k": 2}, budget_deadline=0.0
        )
        == []
    )


def test_metadata_anchor_executes_without_api_imports() -> None:
    code = """
import asyncio
import importlib.abc
import sys
from uuid import uuid4

attempts = []
class NoApi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.api' or fullname.startswith('app.api.'):
            attempts.append(fullname)
            raise AssertionError(fullname)

sys.meta_path.insert(0, NoApi())
from app.services.dify_integration import metadata_anchor
metadata_anchor.settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED = True
metadata_anchor.settings.RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED = False
result = asyncio.run(metadata_anchor.run_with_deadline(
    {'tenant_id': uuid4(), 'dataset_ids': [], 'query': 'neutral query', 'top_k': 2}, budget_deadline=None,
))
assert result == []
assert not attempts, attempts
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
