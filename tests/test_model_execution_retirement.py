"""Retired model requests must fail before loading weights or changing models."""

import pytest
from pydantic import ValidationError

from app.api.schemas.settings import EmbeddingConfig, RAGConfig, UpdateSettingsRequest
from app.rag.embedding.adapter import create_langchain_embeddings_from_config
from app.rag.preprocessing.keyword import get_keyword_extractor
from app.rag.reranker.factory import get_reranker
from app.rag.retrieval.sparse import resolve_sparse_provider_capability


def test_saved_local_embedding_is_readable_but_cannot_be_submitted() -> None:
    saved = EmbeddingConfig(provider="local", model="BAAI/bge-m3")
    assert saved.provider == "local"
    with pytest.raises(ValidationError, match="retired"):
        UpdateSettingsRequest(embedding=saved)


def test_local_embedding_factory_rejects_before_loading_a_model() -> None:
    with pytest.raises(ValueError, match="retired"):
        create_langchain_embeddings_from_config(provider="local", model="BAAI/bge-m3")


@pytest.mark.parametrize(
    "provider", ["cross_encoder", "cross-encoder", "sentence-transformers", "local_bge_v2_m3", "bge_v2_m3"]
)
def test_local_reranker_cannot_be_submitted_or_constructed(provider: str) -> None:
    with pytest.raises(ValidationError, match="retired"):
        UpdateSettingsRequest(rag=RAGConfig(reranker_provider=provider))
    with pytest.raises(ValueError, match="retired"):
        get_reranker(provider)


def test_hanlp_is_rejected_before_import_or_model_download() -> None:
    with pytest.raises(ValueError, match="retired"):
        get_keyword_extractor("hanlp")


def test_retired_splade_is_not_replaced_by_test_vectors() -> None:
    with pytest.raises(ValueError, match="retired"):
        resolve_sparse_provider_capability(requested_provider="splade", sparse_enabled=True)


def test_regression_request_rejects_retired_reranking_before_running_cases() -> None:
    from uuid import uuid4

    from app.api.schemas.regression import RagasRegressionRunCreateRequest

    with pytest.raises(ValidationError, match="retired"):
        RagasRegressionRunCreateRequest(dataset_id=uuid4(), reranker_provider="cross_encoder")


@pytest.mark.parametrize("kind", ["retrieval", "rerank"])
def test_hf_colbert_cannot_fall_back_to_test_vectors(kind: str) -> None:
    from app.rag.reranker.colbert import get_token_embedder
    from app.rag.retrieval.colbert_ann import get_dense_embedder

    with pytest.raises(ValueError, match="retired"):
        if kind == "retrieval":
            get_dense_embedder(provider="hf")
        else:
            get_token_embedder(provider_name="hf")


def test_legacy_image_query_is_explicitly_rejected() -> None:
    from app.api.v1.rag import RetrievePreviewRequest

    with pytest.raises(ValidationError, match="retired"):
        RetrievePreviewRequest(query="chart", query_image="find a chart")


@pytest.mark.asyncio
async def test_retrieved_local_image_still_loads_after_metadata_normalization(tmp_path, monkeypatch) -> None:
    from uuid import uuid4

    from app.rag.core import vision_reader

    tenant_id, image_id = uuid4(), uuid4()
    folder = tmp_path / str(tenant_id) / "images"
    folder.mkdir(parents=True)
    payload = b"\x89PNG\r\n\x1a\nlocal-image-content"
    (folder / f"{image_id.hex}.png").write_bytes(payload)
    monkeypatch.setattr(vision_reader.settings, "UPLOAD_DIR", str(tmp_path))
    data, reason = await vision_reader._load_image_bytes(
        meta={"image_id": str(image_id), "img_id": str(image_id)}, tenant_id=tenant_id, max_bytes=1000
    )
    assert data == payload
    assert reason == "local"


@pytest.mark.parametrize("provider", ["gliner", "hybrid"])
def test_kg_model_extraction_is_not_silently_replaced_by_llm(provider: str) -> None:
    from app.rag.kg.extraction.backend_router import resolve_extraction_backend

    with pytest.raises(ValueError, match="retired"):
        resolve_extraction_backend(llm_processor=object(), requested_backend=provider)


def test_auto_annotation_does_not_accept_gliner() -> None:
    from app.api.schemas.pipeline import AutoAnnotationRequest

    with pytest.raises(ValidationError):
        AutoAnnotationRequest(text="policy", providers=["gliner"])


def test_saved_dataset_reranker_is_not_ignored_as_an_invalid_default() -> None:
    from app.api.schemas.chat import ChatRAGConfig
    from app.services.rag_defaults import merge_rag_config_with_dataset_defaults

    with pytest.raises(ValueError, match="retired"):
        merge_rag_config_with_dataset_defaults(
            rag_config=ChatRAGConfig(),
            request_fields_set=set(),
            raw_dataset_defaults={"reranker_provider": "cross_encoder"},
        )


def test_saved_dataset_embedding_requires_an_explicit_service_choice(monkeypatch) -> None:
    from app.core.config import settings
    from app.services.dataset_embedding_config import resolve_dataset_embedding_runtime

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    with pytest.raises(ValueError, match="retired"):
        resolve_dataset_embedding_runtime({"embedding_defaults": {"provider": "local", "model": "BAAI/bge-m3"}})
    runtime = resolve_dataset_embedding_runtime(
        {"embedding_defaults": {"provider": "openai_compatible", "model": "BAAI/bge-m3"}}
    )
    assert runtime.provider == "openai_compatible"
    assert runtime.model == "BAAI/bge-m3"


@pytest.mark.parametrize("flag", ["IMAGE_EMBEDDING_ENABLED", "KG_GLINER_ENABLED"])
def test_enabled_legacy_model_flags_fail_configuration_validation(flag: str) -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError, match="retired"):
        Settings(_env_file=None, **{flag: True})


def test_old_image_index_endpoint_reports_retirement() -> None:
    from uuid import uuid4

    from fastapi import HTTPException

    from app.api.v1.rag import index_image_embeddings

    with pytest.raises(HTTPException) as failure:
        index_image_embeddings(tenant_id=uuid4(), account_id="test-member")
    assert failure.value.status_code == 410
    assert failure.value.detail["code"] == "feature_retired"


def test_image_reader_uses_existing_document_evidence() -> None:
    from langchain_core.documents import Document

    from app.rag.core.vision_reader import select_image_evidence

    text = Document(page_content="text", metadata={"chunk_type": "text"})
    image = Document(page_content="chart OCR", metadata={"image_id": "a" * 32})
    documents = [text, image]
    assert select_image_evidence(documents) == [image]
    assert documents == [text, image]


@pytest.mark.asyncio
@pytest.mark.parametrize("modality", ["image", "text"])
async def test_stream_selects_existing_image_evidence_without_duplicate_retrieval(
    modality: str, monkeypatch, tmp_path
) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from langchain_core.documents import Document

    from app.rag.engine_support.standard_stream_retrieval import boost_kg_and_select_images
    from app.services import document_asset_access

    monkeypatch.setattr(
        document_asset_access, "resolve_preview_image", lambda **_kwargs: tmp_path / "owned-preview.png"
    )

    image = Document(page_content="chart OCR", metadata={"image_id": "a" * 32})
    text = Document(page_content="normal evidence", metadata={})
    documents = [text, image]
    state = SimpleNamespace(
        data=SimpleNamespace(
            docs=documents,
            multimodal_modality=modality,
            enable_kg_chunk_boost=False,
            kg_chunk_boost_weight=None,
            kg_chunk_boost_max_promoted=None,
            db=object(),
            tenant_id=uuid4(),
            account_id="preview-owner",
        ),
        module=SimpleNamespace(
            Document=Document,
            _apply_kg_chunk_boost=lambda docs, **_kwargs: (docs, {"enabled": False}),
            _release_request_session=lambda _db: None,
        ),
    )
    await boost_kg_and_select_images(state)
    assert state.data.docs == documents
    assert state.data.image_docs == ([image] if modality == "image" else [])


def test_reranking_profile_requires_an_explicit_provider() -> None:
    from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides

    with pytest.raises(ValueError, match="explicitly configured"):
        apply_retrieval_profile_overrides(profile="hybrid_ce", top_k=5, score_threshold=0.0)
    selected = apply_retrieval_profile_overrides(
        profile="hybrid_ce", top_k=5, score_threshold=0.0, reranker_provider="openai"
    )
    assert selected["reranker_provider"] == "openai"
    assert selected["enable_reranker"] is True


@pytest.mark.asyncio
async def test_retrieved_image_reference_cannot_read_another_tenant(monkeypatch) -> None:
    from uuid import uuid4

    from app.rag.core import vision_reader

    foreign_tenant, request_tenant = uuid4(), uuid4()
    monkeypatch.setattr(
        vision_reader,
        "_load_image_bytes_from_minio_sync",
        lambda **_kwargs: pytest.fail("foreign image reached object storage"),
    )
    data, reason = await vision_reader._load_image_bytes(
        meta={"img_id": f"{foreign_tenant}:{uuid4()}:{uuid4()}:chart"}, tenant_id=request_tenant, max_bytes=1000
    )
    assert data is None
    assert reason == "image_tenant_mismatch"


def test_saved_dataset_model_defaults_remain_visible_for_correction() -> None:
    from types import SimpleNamespace

    from app.api.v1.datasets import _dataset_embedding_defaults_out, _dataset_rag_defaults_out

    stored = SimpleNamespace(
        dataset_metadata={
            "embedding_defaults": {"provider": "local", "model": "BAAI/bge-m3"},
            "rag_defaults": {"reranker_provider": "cross_encoder"},
        }
    )
    assert _dataset_embedding_defaults_out(stored).provider == "local"
    assert _dataset_rag_defaults_out(stored).reranker_provider == "cross_encoder"


@pytest.mark.parametrize("request_name", ["DatasetCreate", "DatasetUpdate"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("embedding_defaults", {"provider": "local", "model": "BAAI/bge-m3"}),
        ("rag_defaults", {"reranker_provider": "cross_encoder"}),
    ],
)
def test_dataset_writes_reject_retired_execution(request_name: str, field: str, value: dict) -> None:
    from app.api.schemas import dataset

    request_model = getattr(dataset, request_name)
    with pytest.raises(ValidationError, match="retired"):
        request_model(name="migration-test", **{field: value})


def test_saved_hanlp_pipeline_is_readable_but_cannot_be_written_or_activated() -> None:
    from types import SimpleNamespace

    from app.api.v1.datasets import _dataset_pipeline_out
    from app.services.pipeline_config import (
        build_pipeline_metadata,
        resolve_pipeline_effective,
        upsert_pipeline_metadata,
        validate_pipeline_execution,
    )
    from app.types.pipeline import PipelineOptions

    options = PipelineOptions(governance_keywords_provider="hanlp")
    saved = {"pipeline": build_pipeline_metadata(options)}
    assert _dataset_pipeline_out(SimpleNamespace(dataset_metadata=saved)).governance_keywords_provider == "hanlp"
    destination = {"title": "unchanged"}
    with pytest.raises(ValueError, match="retired"):
        upsert_pipeline_metadata(destination, options=options)
    assert destination == {"title": "unchanged"}
    effective = resolve_pipeline_effective(document_metadata=saved)
    with pytest.raises(ValueError, match="retired"):
        validate_pipeline_execution(effective)


def test_service_retirement_errors_use_the_existing_http_error_layer() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.exceptions import register_exception_handlers
    from app.services.pipeline_config import upsert_pipeline_metadata
    from app.types.pipeline import PipelineOptions

    api = FastAPI()
    register_exception_handlers(api)

    @api.post("/pipeline")
    def save_pipeline():
        upsert_pipeline_metadata({}, options=PipelineOptions(governance_keywords_provider="hanlp"))
        return {"saved": True}

    with TestClient(api) as client:
        response = client.post("/pipeline")
    assert response.status_code == 422
    assert "retired" in response.text


def test_profile_payloads_remain_readable_and_only_reject_retired_choices_on_write() -> None:
    from app.api.schemas.governance_profile import GovernanceProfilePayload
    from app.services.governance_profiles import validate_and_normalize_payload

    assert validate_and_normalize_payload(GovernanceProfilePayload()).pipeline_patch == {}
    old = GovernanceProfilePayload(pipeline_patch={"governance_keywords_provider": "hanlp"})
    assert old.pipeline_patch["governance_keywords_provider"] == "hanlp"
    with pytest.raises(ValueError, match="retired"):
        validate_and_normalize_payload(old)


def test_hf_colbert_is_not_advertised_by_capability_discovery() -> None:
    from app.rag.reranker.capabilities import get_reranker_capabilities

    with pytest.raises(ValueError, match="retired"):
        get_reranker_capabilities("colbert", provider_name="hf")
