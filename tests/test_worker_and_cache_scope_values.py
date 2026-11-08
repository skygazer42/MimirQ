from types import SimpleNamespace

import pytest

from app.rag.embedding import adapter
from app.rag.kg.extraction_job_options import build_kg_extraction_job_options
from app.rag.pipelines.langgraph import _retrieve_cache_key
from app.tasks import jobs


def _frozen_options():
    return build_kg_extraction_job_options(
        pipeline_hash=None,
        prompt_template_id=None,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        extraction_backend="llm",
        kg_python_plugin=None,
        kg_python_params={},
        replace_existing=True,
        prune_orphan_entities=True,
        extract_relations=False,
        extract_skills=False,
    )


@pytest.mark.asyncio
async def test_worker_keeps_the_frozen_unversioned_selection() -> None:
    frozen = _frozen_options()
    result, selected = await jobs._normalize_kg_job_options_or_result(
        {}, started_at=0, tenant_id="tenant", document_id="document", effective_options=frozen, pipeline_hash="legacy"
    )
    assert selected is None
    state = jobs._resolve_kg_job_state(
        doc=SimpleNamespace(doc_metadata={"pipeline_hash": "legacy"}),
        document_id="document",
        requested_pipeline_hash=selected,
        replace_existing=True,
        prune_orphan_entities=True,
        extract_relations=False,
        extract_skills=False,
        frozen_options=result,
    )
    assert state["selected_pipeline_hash"] is None
    unversioned = SimpleNamespace(doc_metadata={})
    versioned = SimpleNamespace(doc_metadata={"pipeline_hash": "legacy"})
    assert jobs._scope_kg_chunks(
        [unversioned, versioned],
        selected_pipeline_hash=state["selected_pipeline_hash"],
        document_key=state["document_key"],
        pipeline_scope_required=state["pipeline_scope_required"],
    ) == [unversioned]


def test_retrieval_cache_distinguishes_open_and_empty_document_scope() -> None:
    args = {"question": "policy", "tenant_id": "tenant", "account_id": "reader", "dataset_id": "dataset"}
    assert _retrieve_cache_key({**args, "document_ids": None}) != _retrieve_cache_key({**args, "document_ids": []})


def test_embedding_cache_does_not_replace_a_supplied_empty_space(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter, "current_embedding_space_hash", lambda: "global")
    client = adapter.LangChainEmbeddingsAdapter(SimpleNamespace(dimension=2), cache_space_hash="")
    assert client._cache_key("text") == adapter._embed_cache_key("text", space="")
    assert client._cache_key("text") != adapter._embed_cache_key("text", space=None)
