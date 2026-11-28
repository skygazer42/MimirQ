import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


class Query:
    def __init__(self, db):
        self.db = db

    def join(self, *args):
        return self

    def filter(self, *conditions):
        self.db.conditions.extend(conditions)
        return self

    def add_columns(self, *columns):
        return self

    def order_by(self, *columns):
        return self

    def limit(self, value):
        self.db.limits.append(value)
        return self

    def all(self):
        self.db.reads += 1
        value = self.db.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class DB:
    def __init__(self, responses):
        self.responses = list(responses)
        self.conditions, self.limits, self.columns = [], [], []
        self.reads = 0
        self.closed = self.committed = self.rolled_back = False

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def query(self, *columns):
        self.columns.append(columns)
        return Query(self)

    def close(self):
        self.closed = True

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _request():
    from app.rag.retrieval.recall.lexical_search import LexicalRequest
    from app.rag.retrieval.recall.runtime_scope import RetrievalScope

    return LexicalRequest(
        "orchard", 2, RetrievalScope(uuid4(), "actor", dataset_ids=(uuid4(),), document_ids=(uuid4(),))
    )


def _configure(monkeypatch):
    from app.infrastructure.config import settings

    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", True)
    monkeypatch.setattr(settings, "LEXICAL_DB_TRGM_ENABLED", False)
    monkeypatch.setattr(settings, "LEXICAL_DB_CJK_TOKEN_CONTAINMENT_ENABLED", False)


def test_lexical_operation_preserves_scope_rows_and_the_callers_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.models.documents.records import Document as DBDocument
    from app.rag.retrieval.recall.lexical_search import search_lexical

    _configure(monkeypatch)
    request = _request()
    chunk_id, document_id, dataset_id = uuid4(), request.scope.document_ids[0], request.scope.dataset_ids[0]
    row = (chunk_id, "orchard result", {}, request.scope.tenant_id, document_id, 0, 2, dataset_id, 0.9)
    db = DB([[row]])
    outcome = search_lexical(db, request)
    assert outcome.failure is None
    assert outcome.records[0]["metadata"]["dataset_id"] == str(dataset_id)
    assert outcome.records[0]["metadata"]["tenant_id"] == str(request.scope.tenant_id)
    assert outcome.records[0]["metadata"]["page"] == 2
    assert DBDocument.dataset_id in db.columns[0]
    conditions = {
        str(condition.left): condition.right.value
        for condition in db.conditions
        if hasattr(condition, "left") and hasattr(condition, "right") and hasattr(condition.right, "value")
    }
    assert conditions["document_chunks.tenant_id"] == request.scope.tenant_id
    assert conditions["documents.dataset_id"] == [dataset_id]
    assert not db.closed and not db.committed and not db.rolled_back


def test_lexical_database_failure_is_not_a_successful_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall.lexical_search import search_lexical

    _configure(monkeypatch)
    failure = RuntimeError("database unavailable")
    db = DB([failure])
    result = search_lexical(db, _request())
    assert result.failure is failure and result.records == []
    assert db.reads == 1
    assert not db.closed and not db.rolled_back


def test_zero_websearch_hits_keep_the_plain_query_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall.lexical_search import search_lexical

    _configure(monkeypatch)
    request = _request()
    row = (
        uuid4(),
        "plain result",
        {},
        request.scope.tenant_id,
        request.scope.document_ids[0],
        0,
        None,
        request.scope.dataset_ids[0],
        0.5,
    )
    db = DB([[], [row]])
    result = search_lexical(db, request)
    assert result.failure is None
    assert result.records[0]["metadata"]["lexical_method"] == "fts_plain"
    assert db.reads == 2


def test_malformed_database_projection_is_an_explicit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall.lexical_search import search_lexical

    _configure(monkeypatch)
    result = search_lexical(DB([[("malformed",)]]), _request())
    assert isinstance(result.failure, ValueError)
    assert result.records == []


def test_extension_probe_failure_keeps_prior_hits_and_is_not_cached_as_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.infrastructure.config import settings
    from app.rag.retrieval.recall.lexical_search import search_lexical

    _configure(monkeypatch)
    monkeypatch.setattr(settings, "LEXICAL_DB_TRGM_ENABLED", True)
    monkeypatch.setattr(settings, "LEXICAL_DB_TRGM_MIN_QUERY_CHARS", 1)
    request = _request()
    row = (
        uuid4(),
        "fts result",
        {},
        request.scope.tenant_id,
        request.scope.document_ids[0],
        0,
        None,
        request.scope.dataset_ids[0],
        1.0,
    )
    db = DB([[row]])
    failure = RuntimeError("extension lookup unavailable")

    def fail(statement):
        raise failure

    db.execute = fail
    result = search_lexical(db, request)
    assert result.failure is failure
    assert result.records[0]["content"] == "fts result"
    assert result.pg_trgm_available is None
    assert db.reads == 1


def test_metadata_exact_database_failure_is_returned_with_its_original_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from app.rag.retrieval.recall.lexical_search import search_metadata_exact

    _configure(monkeypatch)
    failure = RuntimeError("metadata lookup unavailable")
    db = DB([failure])
    result = search_metadata_exact(db, replace(_request(), query="优抚对象医疗保障"), enabled=True)
    assert result.failure is failure
    assert result.records == []
    assert not db.closed and not db.committed and not db.rolled_back


def test_expired_supplement_budget_keeps_hits_and_skips_following_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from app.infrastructure.config import settings
    from app.rag.retrieval.recall import lexical_search

    _configure(monkeypatch)
    monkeypatch.setattr(settings, "LEXICAL_DB_TRGM_ENABLED", True)
    request = replace(_request(), deadline=10.5)
    row = (
        uuid4(),
        "first query hit",
        {},
        request.scope.tenant_id,
        request.scope.document_ids[0],
        0,
        None,
        request.scope.dataset_ids[0],
        0.8,
    )
    db = DB([[row], []])
    timeouts = []
    ticks = iter([10.0, 10.5])
    monkeypatch.setattr(lexical_search, "perf_counter", lambda: next(ticks))

    def set_timeout(statement, params):
        assert "statement_timeout" in str(statement)
        timeouts.append(params["timeout"])

    db.execute = set_timeout
    result = lexical_search.search_lexical(db, request, pg_trgm_available=True)

    assert db.reads == 1 and timeouts == ["500ms"]
    assert isinstance(result.failure, TimeoutError)
    assert result.records[0]["content"] == "first query hit"


def test_lexical_operation_executes_without_importing_the_reader_adapter() -> None:
    script = """
import importlib.abc
import sys
from types import SimpleNamespace
from uuid import uuid4
class NoReader(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.rag.retrieval.recall.retriever':
            raise AssertionError('Lexical owner imports reader')
sys.meta_path.insert(0, NoReader())
from app.infrastructure.config import settings
from app.rag.retrieval.recall.runtime_scope import RetrievalScope
from app.rag.retrieval.recall.lexical_search import LexicalRequest, search_lexical
settings.LEXICAL_DB_ENABLED = True
settings.LEXICAL_DB_TRGM_ENABLED = False
settings.LEXICAL_DB_CJK_TOKEN_CONTAINMENT_ENABLED = False
class Query:
    def join(self, *args): return self
    def filter(self, *args): return self
    def add_columns(self, *args): return self
    def order_by(self, *args): return self
    def limit(self, *args): return self
    def all(self): return []
class DB:
    def get_bind(self): return SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))
    def query(self, *args): return Query()
result = search_lexical(DB(), LexicalRequest('query',1,RetrievalScope(uuid4(),'actor')))
assert result.records == [] and result.failure is None
assert 'app.rag.retrieval.recall.retriever' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
