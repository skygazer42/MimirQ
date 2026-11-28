import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException


def test_evidence_models_are_shared_with_api_and_preserve_explicit_fields() -> None:
    from app.api.schemas.conversations.chat import ChatRAGConfig, HistoryMessage
    from app.api.schemas.conversations.chat import ChatRAGConfig as ApiConfig
    from app.api.schemas.conversations.chat import HistoryMessage as ApiHistory
    from app.api.schemas.conversations.retrieval import EvidenceRetrieveRequest, EvidenceRetrieveResponse
    from app.api.schemas.datasets.dataset import DatasetRAGDefaults
    from app.api.schemas.datasets.dataset import DatasetRAGDefaults as ApiDefaults
    from app.api.v1.retrieval.routes import EvidenceRetrieveRequest as ApiRequest
    from app.api.v1.retrieval.routes import EvidenceRetrieveResponse as ApiResponse

    assert (ApiConfig, ApiHistory, ApiDefaults, ApiRequest, ApiResponse) == (
        ChatRAGConfig,
        HistoryMessage,
        DatasetRAGDefaults,
        EvidenceRetrieveRequest,
        EvidenceRetrieveResponse,
    )
    omitted = EvidenceRetrieveRequest(query="where is the office")
    explicit = EvidenceRetrieveRequest(query="where is the office", rag_config={"enable_reranker": False})
    assert "rag_config" not in omitted.model_fields_set
    assert explicit.model_fields_set == {"query", "rag_config"}
    assert "enable_reranker" in explicit.rag_config.model_fields_set
    assert explicit.rag_config.enable_reranker is False


def test_evidence_defaults_do_not_hide_a_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.schemas.conversations.chat import ChatRAGConfig
    from app.services.retrieval import requests as evidence_retrieval

    failure = RuntimeError("dataset metadata query failed")

    def fail_metadata_query(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(evidence_retrieval, "load_dataset_metadata", fail_metadata_query)
    with pytest.raises(RuntimeError, match="dataset metadata query failed") as result:
        evidence_retrieval._resolve_dataset_defaults_rag_config(
            db=object(),
            tenant_id=uuid4(),
            scope_dataset_id=uuid4(),
            scope_document_ids=[],
            rag_config=ChatRAGConfig(),
            request_fields_set=set(),
            default_profile="recall50",
        )
    assert result.value is failure


@pytest.mark.asyncio
@pytest.mark.parametrize("caller", ["service", "api", "dify"])
@pytest.mark.parametrize(("denial", "status"), [("membership", 403), ("quota", 429), ("scope", 403)])
async def test_all_evidence_entrypoints_keep_membership_quota_and_scope_rejections(
    monkeypatch: pytest.MonkeyPatch, caller: str, denial: str, status: int
) -> None:
    from app.api.schemas.conversations.retrieval import EvidenceRetrieveRequest
    from app.api.v1.integrations import dify
    from app.api.v1.retrieval import routes as rag
    from app.services.identity import tenant_quotas as tenant_quota_service
    from app.services.retrieval import requests as evidence_retrieval
    from app.services.retrieval import scope
    from app.services.runtime import retrieval_limiter

    monkeypatch.setattr(retrieval_limiter, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    tenant_id, dataset_id = uuid4(), uuid4()
    seen: list[str] = []

    def guard(stage: str) -> None:
        seen.append(stage)
        if stage == denial:
            raise HTTPException(status_code=status, detail=f"denied by {stage}")

    async def quota(**kwargs):
        assert kwargs == {"tenant_id": tenant_id, "key": "retrieval"}
        guard("quota")
        return {}

    monkeypatch.setattr(evidence_retrieval.dataset_service, "ensure_member", lambda *_args: guard("membership"))
    monkeypatch.setattr(tenant_quota_service, "enforce_tenant_qps_quota_async", quota)
    monkeypatch.setattr(scope, "get_readable_datasets_map", lambda *_args, **_kwargs: guard("scope"))
    kwargs = {"db": object(), "tenant_id": tenant_id, "account_id": "member"}
    with pytest.raises(HTTPException) as failure:
        if caller == "dify":
            await dify._retrieve_dataset_citations(
                **kwargs,
                dataset_ids=[dataset_id],
                query="office",
                top_k=5,
                requested_top_k=5,
                score_threshold=0.0,
                enable_kg_query_expansion=False,
                enable_kg_chunk_injection=False,
                enable_kg_chunk_boost=False,
                enable_reranker=False,
            )
        else:
            operation = evidence_retrieval.retrieve_evidence if caller == "service" else rag.retrieve_evidence
            await operation(body=EvidenceRetrieveRequest(query="office", dataset_ids=[dataset_id]), **kwargs)
    assert failure.value.status_code == status
    assert failure.value.detail == f"denied by {denial}"
    assert seen == ["membership", "quota", "scope"][: ["membership", "quota", "scope"].index(denial) + 1]


@pytest.mark.asyncio
@pytest.mark.parametrize(("explicit_top_k", "expected_top_k"), [(7, 7), (None, 13)])
async def test_evidence_operation_applies_defaults_and_uses_a_worker_owned_session(
    monkeypatch: pytest.MonkeyPatch,
    explicit_top_k: int | None,
    expected_top_k: int,
) -> None:
    from app.api.schemas.conversations.retrieval import EvidenceRetrieveRequest
    from app.rag.retrieval import orchestrator
    from app.rag.retrieval.evidence import document_structure
    from app.services.retrieval import requests as evidence_retrieval
    from app.services.retrieval import scope
    from app.services.runtime import retrieval_limiter as rag_runtime_limiter

    tenant_id, dataset_id, document_id = uuid4(), uuid4(), uuid4()
    request_db = SimpleNamespace(rollback=lambda: None)
    worker_sessions = []

    class VersionQuery:
        def filter(self, *_conditions):
            return self

        def all(self):
            return [(document_id, "completed", {})]

    def open_worker_session():
        worker = SimpleNamespace(
            created_in=threading.get_ident(), closed_in=None, query=lambda *_columns: VersionQuery()
        )

        def close():
            worker.closed_in = threading.get_ident()

        worker.close = close
        worker_sessions.append(worker)
        return worker

    observed: dict[str, object] = {}

    def retrieve(state):
        observed.update(state)
        observed["thread_id"] = threading.get_ident()
        return {
            "query_for_retrieval": "office",
            "citations": [{"chunk_content": "office address", "relevance_score": 0.9}],
            "metrics": {},
        }

    monkeypatch.setattr(evidence_retrieval.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(scope, "filter_allowed_document_ids", lambda *_args: [document_id])
    monkeypatch.setattr(
        evidence_retrieval, "resolve_single_dataset_id_for_documents", lambda *_args, **_kwargs: dataset_id
    )
    monkeypatch.setattr(
        evidence_retrieval,
        "load_dataset_metadata",
        lambda *_args, **_kwargs: {"rag_defaults": {"top_k": 13, "enable_reranker": True}},
    )
    monkeypatch.setattr(orchestrator, "run_retrieval", retrieve)
    monkeypatch.setattr(document_structure, "load_structures_for_citations", lambda **_kwargs: {})
    monkeypatch.setattr(rag_runtime_limiter, "SessionLocal", open_worker_session)
    monkeypatch.setattr(evidence_retrieval.settings, "TENANT_QPS_QUOTA_ENABLED", False)
    monkeypatch.setattr(evidence_retrieval.settings, "CHAT_DEFAULT_RETRIEVAL_PROFILE", "")
    monkeypatch.setattr(evidence_retrieval.settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED", False)
    monkeypatch.setattr(evidence_retrieval.settings, "EVIDENCE_ITERATIVE_RETRIEVE_ENABLED", False)
    monkeypatch.setattr(evidence_retrieval.settings, "RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE", 0.0)
    request_config = {"enable_reranker": False}
    if explicit_top_k is not None:
        request_config["top_k"] = explicit_top_k
    body = EvidenceRetrieveRequest(query="office", document_ids=[document_id], rag_config=request_config, seed=0)

    result = await evidence_retrieval.retrieve_evidence(
        body=body, db=request_db, tenant_id=tenant_id, account_id="member"
    )

    assert any(observed["db"] is session for session in worker_sessions)
    assert observed["thread_id"] != threading.get_ident()
    assert len(worker_sessions) == 4
    assert all(session.created_in == session.closed_in != threading.get_ident() for session in worker_sessions)
    assert observed["db"].created_in == observed["thread_id"]
    assert observed["top_k"] == expected_top_k
    assert observed["enable_reranker"] is False
    assert observed["seed"] == 0
    assert "enable_reranker" in body.rag_config.model_fields_set
    assert ("top_k" in body.rag_config.model_fields_set) is (explicit_top_k is not None)
    assert result.has_evidence is True
    assert result.citations[0]["chunk_content"] == "office address"


def test_evidence_runtime_and_quota_do_not_import_api_routes() -> None:
    code = """
import asyncio
import importlib.abc
import sys
from uuid import uuid4

attempted_route_imports = []
class NoApiRoutes(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.api.v1' or fullname.startswith('app.api.v1.'):
            attempted_route_imports.append(fullname)
            raise AssertionError(f'Evidence service imported API routes: {fullname}')

sys.meta_path.insert(0, NoApiRoutes())
from app.services.retrieval import requests
from app.services.identity import tenant_quotas
from app.rag.runtime.graph.state import build_rag_state
from app.rag.retrieval.orchestrator import run_retrieval
from app.services.datasets.profile import build_dataset_documents_query
from app.api.schemas.conversations import EvidenceRetrieveRequest

assert requests.EvidenceRetrieveRequest is EvidenceRetrieveRequest
settings = requests.settings
settings.TENANT_QPS_QUOTA_ENABLED = True
settings.TENANT_QPS_QUOTA_REQUESTS_PER_SECOND = 10
settings.TENANT_QPS_QUOTA_BURST_SIZE = 10
settings.RATE_LIMIT_REDIS_ENABLED = False
assert asyncio.run(tenant_quotas.enforce_tenant_qps_quota_async(tenant_id=uuid4(), key='retrieval'))['allowed']
assert not attempted_route_imports, attempted_route_imports
assert not any(name == 'app.api.v1' or name.startswith('app.api.v1.') for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
