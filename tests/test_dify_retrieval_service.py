import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from starlette.requests import Request


@pytest.mark.asyncio
async def test_dify_retrieval_route_passes_request_data_to_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import integrations_dify
    from app.services.dify_integration import retrieval
    from app.types.dify_integration import DifyActor, DifyExternalKnowledgeRequest, DifyExternalKnowledgeResponse

    seen = {}

    async def retrieve(**kwargs):
        seen.update(kwargs)
        return DifyExternalKnowledgeResponse(records=[])

    monkeypatch.setattr(retrieval, "retrieve_knowledge", retrieve)
    request = Request({"type": "http", "headers": [(b"x-request-id", b"header-id")], "client": ("127.0.0.1", 8000)})
    request.state.request_id = "middleware-id"
    body = DifyExternalKnowledgeRequest(knowledge_id="city", query="office")
    actor = DifyActor(tenant_id=uuid4(), account_id="system:dify")
    database = object()

    response = await integrations_dify.retrieve_external_knowledge(request=request, body=body, actor=actor, db=database)

    assert response.records == []
    assert seen["body"] is body
    assert seen["actor"] is actor
    assert seen["db"] is database
    assert seen["request_headers"].get("x-request-id") == "header-id"
    assert seen["request_id"] == "middleware-id"
    assert seen["client_ip"] == "127.0.0.1"
    assert "request" not in seen


@pytest.mark.parametrize(
    ("body_id", "headers", "middleware_id", "expected"),
    [
        ("body-id", {"X-Request-ID": "header-id"}, "middleware-id", "body-id"),
        (None, {"X-Request-ID": "header-id"}, "middleware-id", "header-id"),
        (None, {}, "middleware-id", "middleware-id"),
    ],
)
def test_dify_trace_request_id_keeps_body_header_and_middleware_precedence(
    body_id, headers, middleware_id, expected
) -> None:
    from app.services.dify_integration import tracing
    from app.types.dify_integration import DifyExternalKnowledgeRequest

    body = DifyExternalKnowledgeRequest(knowledge_id="city", query="office", request_id=body_id)
    assert tracing._dify_trace_request_id(headers, body, request_id=middleware_id) == expected


def test_dify_citation_trace_keys_share_one_owner() -> None:
    from app.services.dify_integration import common, conversation_turns, tracing

    assert tracing._DIFY_TRACE_CITATION_METADATA_KEYS is common._DIFY_TRACE_CITATION_METADATA_KEYS
    assert conversation_turns._DIFY_TRACE_CITATION_METADATA_KEYS is common._DIFY_TRACE_CITATION_METADATA_KEYS


def test_dify_retrieval_and_warmup_execute_without_api_imports() -> None:
    code = """
import asyncio
import importlib.abc
import json
import sys
from uuid import uuid4

attempts = []
class NoApi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.api' or fullname.startswith('app.api.'):
            attempts.append(fullname)
            raise AssertionError(fullname)

sys.meta_path.insert(0, NoApi())
from app.services.dify_integration import evidence_adapter, retrieval, warmup
from app.types.dify_integration import DifyActor, DifyExternalKnowledgeRequest, DifyRetrievalSetting
settings = retrieval.settings
dataset_id = uuid4()
settings.DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON = json.dumps({'isolated': str(dataset_id)})
settings.DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED = False
settings.DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED = False
settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED = False
settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED = False
settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED = False
settings.DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED = False
async def citations(**kwargs):
    assert kwargs['dataset_ids'] == [dataset_id]
    return [{'chunk_content': 'evidence', 'document_name': 'source', 'relevance_score': 0.9}]
evidence_adapter.retrieve_dataset_citations = citations
result = asyncio.run(retrieval.retrieve_knowledge(
    body=DifyExternalKnowledgeRequest(knowledge_id='isolated', query='neutral question', retrieval_setting=DifyRetrievalSetting(
        enable_kg_query_expansion=False, enable_kg_chunk_injection=False, enable_kg_chunk_boost=False,
    )),
    actor=DifyActor(tenant_id=uuid4(), account_id='system:dify'),
    request_headers={}, request_id=None, client_ip=None, db=object(),
))
assert result.records[0].content == 'evidence'
settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED = False
assert asyncio.run(warmup.warmup_dify_external_knowledge())['reason'] == 'external_knowledge_disabled'
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
