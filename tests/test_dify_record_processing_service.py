import inspect
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_finalize_records_keeps_the_best_duplicate_and_returns_validated_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.dify_integration import record_processing
    from app.types.dify_integration import DifyExternalKnowledgeRecord

    monkeypatch.setattr(record_processing.settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED", False)
    records = [
        {"content": "same evidence", "title": "same.txt", "score": 0.3, "metadata": {}},
        {"content": "other evidence", "title": "other.txt", "score": 0.7, "metadata": {}},
        {"content": "same evidence", "title": "same.txt", "score": 0.9, "metadata": {}},
    ]

    result = await record_processing.finalize_records(
        records=records,
        query="neutral query",
        top_k=2,
        response_top_k=2,
        policy_plugin_refs=(),
        fast=False,
        rerank=False,
    )

    assert [record.title for record in result.records] == ["same.txt", "other.txt"]
    assert [record.score for record in result.records] == [0.9, 0.7]
    assert all(isinstance(record, DifyExternalKnowledgeRecord) for record in result.records)
    assert result.ranked_records == [records[2], records[1]]
    assert isinstance(result.policy_diagnostics, dict)


@pytest.mark.asyncio
async def test_finalize_records_applies_protected_reranking_before_compaction_and_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.dify_integration import record_processing, record_ranking

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

    def diagnostics(items, **_kwargs):
        seen.append("diagnostics")
        return {"record_count": len(items)}

    monkeypatch.setattr(record_ranking, "_dedupe_records", step("dedupe"))
    monkeypatch.setattr(record_ranking, "_sort_records_for_query", step("sort"))
    monkeypatch.setattr(record_ranking, "_final_rerank_records_for_query", rerank)
    monkeypatch.setattr(record_ranking, "_records_retrieval_policy_diagnostics", diagnostics)
    monkeypatch.setattr(record_processing, "_compact_records_for_response", step("compact"))
    monkeypatch.setattr(record_processing, "_compact_fast_records_for_response", step("fast"))

    result = await record_processing.finalize_records(
        records=records, query="neutral query", top_k=8, response_top_k=2, policy_plugin_refs=(), fast=True, rerank=True
    )

    assert seen == ["dedupe", "sort", "rerank", "diagnostics", "compact", "fast"]
    assert limits == {"rerank": 8, "compact": 2, "fast": 2}
    assert result.policy_diagnostics == {"record_count": 1}
    assert result.records[0].content == "evidence"


def test_record_operations_accept_data_instead_of_api_dependency_callbacks() -> None:
    from app.services.dify_integration import record_processing, record_ranking

    for operation in (
        record_processing._compact_fast_record_content,
        record_processing._compact_fast_records_for_response,
        record_processing._compact_records_for_response,
        record_ranking._record_rank_score,
        record_ranking._record_answerfulness_score,
        record_ranking._dedupe_records,
    ):
        assert all(
            "Callable" not in str(param.annotation) for param in inspect.signature(operation).parameters.values()
        )


def test_record_processing_executes_without_api_imports() -> None:
    code = """
import asyncio
import importlib.abc
import sys

attempts = []
class NoApi(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.api' or fullname.startswith('app.api.'):
            attempts.append(fullname)
            raise AssertionError(fullname)

sys.meta_path.insert(0, NoApi())
from app.services.dify_integration import record_processing, citation_records, chunk_hydration
result = asyncio.run(record_processing.finalize_records(
    records=[{'content': 'evidence', 'title': 'source', 'score': 0.9, 'metadata': {}}],
    query='neutral query', top_k=2, response_top_k=2, policy_plugin_refs=(), fast=False, rerank=False,
))
assert result.records[0].content == 'evidence'
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
