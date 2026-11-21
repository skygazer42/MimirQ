import inspect
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


def _finalization_context(records, *, top_k=2, response_top_k=2, fast=False, rerank=False):
    from starlette.requests import Request

    from app.api.schemas.integrations import DifyExternalKnowledgeRequest
    from app.api.v1.integrations.dify import _DifyExternalRetrievalContext
    from app.rag.retrieval.planning.dataset_routes import DatasetScopePlan
    from app.types.dify_integration import DifyActor, DifyKGFlags

    flags = DifyKGFlags(False, False, 0, False, 0.0, 0)
    scope = DatasetScopePlan((), (), (), (), (), (), False, 0, 0, 0)
    return _DifyExternalRetrievalContext(
        request=Request({"type": "http", "headers": []}),
        body=DifyExternalKnowledgeRequest(knowledge_id="fixture", query="neutral query"),
        actor=DifyActor(tenant_id=uuid4(), account_id="reader"),
        db=SimpleNamespace(rollback=lambda: None),
        started=time.perf_counter(),
        scope_plan=scope,
        dataset_ids=[],
        primary_dataset_ids=[],
        expansion_dataset_ids=[],
        top_k=top_k,
        candidate_top_k=top_k,
        response_top_k=response_top_k,
        latency_profile="fast" if fast else "standard",
        fast_latency_profile=fast,
        policy_fallback_multiplier=1,
        policy_plugin_refs=(),
        external_reranker_enabled=rerank,
        score_threshold=0.0,
        metadata_filter=None,
        metadata_anchor_dataset_ids=[],
        requested_kg_flags=flags,
        kg_on_demand_enabled=False,
        primary_kg_flags=flags,
        log_extra_base={"client_ip_hash": "fixture", "knowledge_id_hash": "fixture", "query_hash": "fixture"},
        trace_conversation_id=None,
        trace_request_id=None,
        response_cache_key=None,
        response_cache_ttl_sec=0,
        response_cache_max_entries=0,
        response_cache_enabled=False,
        singleflight_enabled=False,
        records=records,
    )


@pytest.mark.asyncio
async def test_finalize_retrieval_keeps_the_best_duplicate_and_returns_validated_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.schemas.integrations import DifyExternalKnowledgeRecord
    from app.api.v1.integrations import dify

    monkeypatch.setattr(dify.settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED", False)
    monkeypatch.setattr(dify, "_log_dify_external_rag_trace", lambda **_kwargs: None)
    records = [
        {"content": "same evidence", "title": "same.txt", "score": 0.3, "metadata": {}},
        {"content": "other evidence", "title": "other.txt", "score": 0.7, "metadata": {}},
        {"content": "same evidence", "title": "same.txt", "score": 0.9, "metadata": {}},
    ]

    context = _finalization_context(records)
    result = await dify._finalize_dify_external_retrieval(context)

    assert [record.title for record in result.records] == ["same.txt", "other.txt"]
    assert [record.score for record in result.records] == [0.9, 0.7]
    assert all(isinstance(record, DifyExternalKnowledgeRecord) for record in result.records)
    assert context.records == [records[2], records[1]]
    assert context.stage_timings_ms["postprocess_ms"] >= 0


@pytest.mark.asyncio
async def test_finalize_retrieval_applies_protected_reranking_before_compaction_and_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.integrations import dify

    seen: list[str] = []
    limits: dict[str, int] = {}
    records = [{"content": "evidence", "title": "source", "score": 0.9, "metadata": {}}]

    def step(name):
        def apply(items, **_kwargs):
            seen.append(name)
            if "top_k" in _kwargs:
                limits[name] = _kwargs["top_k"]
            return items

        return apply

    async def rerank(items, **_kwargs):
        seen.append("rerank")
        limits["rerank"] = _kwargs["top_k"]
        return items

    real_diagnostics = dify._records_retrieval_policy_diagnostics

    def diagnostics(items, **kwargs):
        seen.append("diagnostics")
        return real_diagnostics(items, **kwargs)

    monkeypatch.setattr(dify, "_dedupe_records", step("dedupe"))
    monkeypatch.setattr(dify, "_sort_records_for_query", step("sort"))
    monkeypatch.setattr(dify, "_final_rerank_records_for_query", rerank)
    monkeypatch.setattr(dify, "_records_retrieval_policy_diagnostics", diagnostics)
    monkeypatch.setattr(dify, "_compact_records_for_response", step("compact"))
    monkeypatch.setattr(dify, "_compact_fast_records_for_response", step("fast"))

    monkeypatch.setattr(dify, "_log_dify_external_rag_trace", lambda **_kwargs: None)
    context = _finalization_context(records, top_k=8, response_top_k=2, fast=True, rerank=True)
    result = await dify._finalize_dify_external_retrieval(context)

    assert seen == ["dedupe", "sort", "rerank", "diagnostics", "compact", "fast"]
    assert limits == {"rerank": 8, "compact": 2, "fast": 2}
    assert result.records[0].content == "evidence"


def test_record_operations_accept_data_instead_of_api_dependency_callbacks() -> None:
    from app.services.dify import compaction, record_ranking

    for operation in (
        compaction._compact_fast_record_content,
        compaction._compact_fast_records_for_response,
        compaction._compact_exact_anchor_answer_record,
        record_ranking._record_rank_score,
        record_ranking._record_answerfulness_score,
        record_ranking._dedupe_records,
    ):
        assert all(
            "Callable" not in str(param.annotation) for param in inspect.signature(operation).parameters.values()
        )


def test_record_service_leaves_execute_without_api_imports() -> None:
    code = """
import importlib.abc
import sys

attempts = []
class NoApi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.api' or fullname.startswith('app.api.'):
            attempts.append(fullname)
            raise AssertionError(fullname)

sys.meta_path.insert(0, NoApi())
from app.services.dify import record_ranking, compaction
records = record_ranking._dedupe_records(
    [{'content': 'evidence', 'title': 'source', 'score': 0.9, 'metadata': {}}],
    query='neutral query', policy_plugin_refs=(),
)
record_ranking._sort_records_for_query(records, query='neutral query', policy_plugin_refs=())
result = compaction._compact_fast_records_for_response(
    records, query='neutral query', top_k=2, policy_plugin_refs=(),
)
assert result[0]['content'] == 'evidence'
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
