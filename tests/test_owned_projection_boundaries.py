from uuid import uuid4

import pytest

from app.rag.ingestion.parsing.utils.document_elements import _resolve_source_fields
from app.rag.retrieval.configuration.fingerprint import _normalize_rag_config_template
from app.rag.retrieval.recall.runtime_scope import build_vector_filter
from app.rag.retrieval.stages.knowledge_graph import _safe_kg_path_provenance as safe_kg_path_provenance
from app.rag.runtime.streaming import evidence as standard_stream_evidence
from app.rag.runtime.streaming.state import StandardStreamState
from app.rag.tracing.retrieval_debug import _sanitize_retriever_debug


@pytest.mark.parametrize("builder", [build_vector_filter])
def test_projected_empty_vector_filters_stay_dictionaries(builder) -> None:
    assert builder({}, embedding_space="") == {}
    assert builder({"document_user.secret": "private"}, embedding_space="") == {}


@pytest.mark.parametrize("builder", [build_vector_filter])
def test_vector_filter_projection_keeps_restrictive_predicates(builder) -> None:
    tenant, dataset = str(uuid4()), uuid4()
    filters = {"tenant_id": tenant, "document_id": {"$in": []}, "page": 0, "document_user.secret": "private"}
    assert builder(filters, embedding_space="space", dataset_ids=(dataset,)) == {
        "tenant_id": tenant,
        "document_id": {"$in": []},
        "page_number": 0,
        "dataset_id": str(dataset),
        "embedding_space_hash": {"$in": ["space", ""]},
    }


@pytest.mark.parametrize(
    "project", [_normalize_rag_config_template, standard_stream_evidence._rag_config_template_fingerprint]
)
def test_template_projection_preserves_values_and_limits_fields(project) -> None:
    assert project(None) is None
    assert project({}) == {}
    assert project({"template_key": "", "version": 0, "ab_variant": None, "private": "secret"}) == {
        "template_key": "",
        "version": 0,
        "ab_variant": None,
    }


@pytest.mark.parametrize("project", [_sanitize_retriever_debug, safe_kg_path_provenance])
def test_safe_diagnostic_projection_preserves_supplied_empty_maps(project) -> None:
    assert project(None) is None
    assert project({}) == {}
    assert project({"private_text": "secret"}) == {}


@pytest.mark.parametrize("value", ["", 0, False])
def test_element_source_fields_do_not_replace_present_values_from_attributes(value) -> None:
    assert _resolve_source_fields(
        {"source_backend": value, "source_element_id": value},
        attributes={"source_backend": "fallback", "source_element_id": "fallback"},
    ) == (value, value)


@pytest.mark.asyncio
async def test_required_trace_configuration_failure_is_observable(monkeypatch: pytest.MonkeyPatch) -> None:
    class InvalidPipelineStage:
        def model_dump(self):
            raise ValueError("invalid pipeline configuration")

    monkeypatch.setattr(standard_stream_evidence.settings, "EVIDENCE_POST_RERANK_PIPELINE", [InvalidPipelineStage()])
    runtime = StandardStreamState(engine=None, payload={})
    with pytest.raises(ValueError, match="invalid pipeline configuration"):
        await standard_stream_evidence.build_retrieval_config_trace(runtime)
