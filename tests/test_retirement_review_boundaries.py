from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

from app.api.schemas.chat import ChatRAGConfig, ChatRequest, ConversationDetail
from app.core.model_execution import RetiredModelProviderError


@pytest.mark.parametrize("provider", ["cross_encoder", "local_bge_v2_m3"])
def test_conversation_response_keeps_historical_reranker_provenance(provider):
    history = ConversationDetail(
        conversation_id=uuid4(),
        messages=[
            {
                "id": uuid4(),
                "role": "assistant",
                "content": "saved answer",
                "created_at": datetime.now(timezone.utc),
                "citations": [
                    {
                        "document_id": uuid4(),
                        "document_name": "history.pdf",
                        "chunk_id": uuid4(),
                        "chunk_content": "saved evidence",
                        "reranker_provider": provider,
                    }
                ],
            }
        ],
    )
    assert history.messages[0].citations[0].reranker_provider == provider


@pytest.mark.parametrize("flow", ["chat-dataset", "preview-dataset", "chat-template", "preview-template"])
@pytest.mark.parametrize("patch", [{"reranker_provider": "cross_encoder"}, {"retrieval_profile": "sparse_splade"}])
def test_real_bootstrap_and_preview_boundaries_propagate_retirement(flow, patch, monkeypatch):
    from app.api.v1 import rag
    from app.services import chat_bootstrap_runtime as bootstrap

    dataset_id, tenant_id, template_id = uuid4(), uuid4(), uuid4()
    config = ChatRAGConfig()
    db = _DB()
    if flow.endswith("dataset"):
        module = bootstrap if flow.startswith("chat") else rag
        monkeypatch.setattr(module, "load_dataset_metadata", lambda *_args, **_kwargs: {"rag_defaults": patch})
    else:
        module = bootstrap if flow.startswith("chat") else rag
        chosen = _template(patch)
        monkeypatch.setattr(module, "resolve_rag_config_template", lambda **_kwargs: (chosen, {}))

    with pytest.raises(RetiredModelProviderError):
        if flow == "chat-dataset":
            bootstrap._resolve_dataset_rag_defaults(
                db=db,
                tenant_id=tenant_id,
                request=ChatRequest(message="question"),
                scope_dataset_id=dataset_id,
                document_ids=[],
            )
        elif flow == "preview-dataset":
            rag._resolve_dataset_defaults_rag_config(
                db=db,
                tenant_id=tenant_id,
                scope_dataset_id=dataset_id,
                scope_document_ids=[],
                rag_config=config,
                request_fields_set=set(),
            )
        elif flow == "chat-template":
            bootstrap._resolve_rag_template_runtime(
                db=db,
                tenant_id=tenant_id,
                account_id="member",
                request_id="test",
                effective_rag_config=config,
                rag_fields_set=set(),
                effective_rag_config_template_id=template_id,
                effective_rag_config_template_key=None,
                effective_rag_config_ab_experiment_key=None,
            )
        else:
            body = rag.RetrievePreviewRequest(query="question", rag_config_template_id=template_id)
            rag._resolve_preview_rag_template_meta(
                db=db,
                tenant_id=tenant_id,
                account_id="member",
                body=body,
                request_fields_set={"rag_config_template_id"},
                dataset_defaults_meta=None,
                effective_rag_config=config,
                rag_fields_set=set(),
            )
    assert db.mutations == []


def _template(patch, *, active=True):
    return SimpleNamespace(
        id=uuid4(),
        template_key="test-template",
        name="saved",
        description=None,
        config_patch=patch,
        is_active=active,
        usage_count=0,
        version=1,
        ab_experiment_key=None,
        ab_variant=None,
    )


class _DB:
    def __init__(self, current=None):
        self.current = current
        self.mutations = []

    def query(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def first(self):
        return self.current

    def scalar(self):
        return 1

    def update(self, _values):
        self.mutations.append("deactivate")
        self.current.is_active = False

    def add(self, row):
        self.mutations.append(("add", row.config_patch))

    def commit(self):
        self.mutations.append("commit")

    def refresh(self, _row):
        pass

    def rollback(self):
        pass


@pytest.mark.parametrize("operation", ["create", "reactivate", "copy-version"])
@pytest.mark.parametrize("patch", [{"reranker_provider": "cross_encoder"}, {"retrieval_profile": "sparse_splade"}])
def test_template_writes_validate_inherited_patch_before_any_mutation(operation, patch, monkeypatch):
    from app.api.schemas.rag_config_template import (
        RagConfigTemplateCreate,
        RagConfigTemplateNewVersion,
        RagConfigTemplateUpdate,
    )
    from app.api.v1 import rag_config_templates as routes

    current = _template(patch, active=operation != "reactivate")
    db = _DB(current)
    monkeypatch.setattr(routes.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(routes, "_ensure_write", lambda *_args: None)
    initial_active = current.is_active
    with pytest.raises(RetiredModelProviderError):
        args = {"tenant_id": uuid4(), "account_id": "owner", "db": db}
        if operation == "create":
            routes.create_rag_config_template(RagConfigTemplateCreate(name="bad", config_patch=patch), **args)
        elif operation == "reactivate":
            routes.update_rag_config_template(current.id, RagConfigTemplateUpdate(is_active=True), **args)
        else:
            routes.create_rag_config_template_version(current.id, RagConfigTemplateNewVersion(), **args)
    assert current.is_active is initial_active
    assert db.mutations == []


def _image_state(doc, *, account_id="member"):
    return SimpleNamespace(
        data=SimpleNamespace(
            docs=[doc],
            multimodal_modality="image",
            enable_kg_chunk_boost=False,
            kg_chunk_boost_weight=None,
            kg_chunk_boost_max_promoted=None,
            db=object(),
            tenant_id=doc.metadata["request_tenant"],
            account_id=account_id,
        ),
        module=SimpleNamespace(
            Document=Document,
            _apply_kg_chunk_boost=lambda docs, **_kwargs: (docs, {"enabled": False}),
            _release_request_session=lambda _db: None,
        ),
    )


@pytest.mark.asyncio
async def test_stream_checks_referenced_document_acl_not_carrier_chunk(monkeypatch):
    from app.rag.engine_support.standard_stream_retrieval import boost_kg_and_select_images
    from app.services import document_asset_access as access

    tenant, dataset, carrier, private, readable = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    seen = []

    def lookup(*, document_id, account_id, **_kwargs):
        seen.append((document_id, account_id))
        if document_id == private:
            raise HTTPException(status_code=404, detail="not readable")
        return SimpleNamespace(dataset_id=dataset)

    monkeypatch.setattr(access, "authorize_document_asset", lookup)
    for reference, expected in [(private, False), (readable, True)]:
        doc = Document(
            page_content="carrier OCR",
            metadata={
                "document_id": str(carrier),
                "img_id": f"{tenant}:{dataset}:{reference}:figure",
                "request_tenant": tenant,
            },
        )
        state = _image_state(doc)
        await boost_kg_and_select_images(state)
        assert state.data.image_docs == ([doc] if expected else [])
    assert seen == [(private, "member"), (readable, "member")]


@pytest.mark.asyncio
async def test_stream_checks_preview_account_ownership_and_keeps_valid_reuse(monkeypatch, tmp_path):
    from app.rag.engine_support.standard_stream_retrieval import boost_kg_and_select_images
    from app.services import document_asset_access as access

    tenant, image = uuid4(), uuid4()

    def resolve(*, db, tenant_id, account_id, image_id):
        access.assert_preview_binding_access(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            binding={"account_id": "preview-owner"},
            legacy_authorized=False,
        )
        return tmp_path / image_id

    monkeypatch.setattr(access, "resolve_preview_image", resolve)
    doc = Document(page_content="OCR", metadata={"image_id": str(image), "request_tenant": tenant})
    for account, expected in [("other-member", False), ("preview-owner", True)]:
        state = _image_state(doc, account_id=account)
        await boost_kg_and_select_images(state)
        assert state.data.image_docs == ([doc] if expected else [])


@pytest.mark.asyncio
async def test_image_permission_lookup_failure_is_not_treated_as_no_images(monkeypatch):
    from app.rag.engine_support.standard_stream_retrieval import boost_kg_and_select_images
    from app.services import document_asset_access as access

    tenant = uuid4()

    def unavailable(**_kwargs):
        raise RuntimeError("permission database unavailable")

    monkeypatch.setattr(access, "authorize_document_asset", unavailable)
    doc = Document(
        page_content="OCR", metadata={"img_id": f"{tenant}:{uuid4()}:{uuid4()}:figure", "request_tenant": tenant}
    )
    with pytest.raises(RuntimeError, match="permission database"):
        await boost_kg_and_select_images(_image_state(doc))


def test_explicit_supported_request_override_wins_over_retired_stored_default():
    from app.services.rag_config_template_apply import apply_rag_config_patch
    from app.services.rag_defaults import merge_rag_config_with_dataset_defaults

    request = ChatRAGConfig(reranker_provider="openai")
    patch = {"reranker_provider": "cross_encoder"}
    effective, _ = merge_rag_config_with_dataset_defaults(
        rag_config=request, request_fields_set={"reranker_provider"}, raw_dataset_defaults=patch
    )
    assert effective.reranker_provider == "openai"
    effective, _ = apply_rag_config_patch(rag_config=request, patch=patch, request_fields_set={"reranker_provider"})
    assert effective.reranker_provider == "openai"


def test_legacy_template_can_be_disabled_and_replaced_explicitly(monkeypatch):
    from app.api.schemas.rag_config_template import RagConfigTemplateNewVersion, RagConfigTemplateUpdate
    from app.api.v1 import rag_config_templates as routes

    current = _template({"reranker_provider": "cross_encoder"})
    db = _DB(current)
    monkeypatch.setattr(routes.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(routes, "_ensure_write", lambda *_args: None)
    args = {"tenant_id": uuid4(), "account_id": "owner", "db": db}
    routes.update_rag_config_template(current.id, RagConfigTemplateUpdate(is_active=False), **args)
    assert current.is_active is False
    current.is_active = True
    replacement = routes.create_rag_config_template_version(
        current.id, RagConfigTemplateNewVersion(config_patch={"reranker_provider": "openai"}), **args
    )
    assert replacement.config_patch == {"reranker_provider": "openai"}
    assert current.is_active is False


@pytest.mark.parametrize("model", ["dataset", "regression"])
def test_retired_sparse_profile_is_rejected_before_write_or_enqueue(model):
    from pydantic import ValidationError

    from app.api.schemas.dataset import DatasetUpdate
    from app.api.schemas.regression import RagasRegressionRunCreateRequest

    with pytest.raises(ValidationError, match="retired"):
        if model == "dataset":
            DatasetUpdate(rag_defaults={"retrieval_profile": "sparse_splade"})
        else:
            RagasRegressionRunCreateRequest(dataset_id=uuid4(), retrieval_profile="sparse_splade")


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["db", "tenant_id", "account_id"])
async def test_image_evidence_requires_an_authenticated_asset_scope(missing):
    from app.rag.engine_support.standard_stream_retrieval import boost_kg_and_select_images

    doc = Document(page_content="OCR", metadata={"image_id": str(uuid4()), "request_tenant": uuid4()})
    state = _image_state(doc)
    setattr(state.data, missing, None)
    await boost_kg_and_select_images(state)
    assert state.data.image_docs == []
