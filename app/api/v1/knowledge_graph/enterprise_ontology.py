"""Enterprise ontology authoring routes."""

from contextlib import aclosing
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import bind_edo_authorization, get_current_account_id, get_tenant_id
from app.api.schemas.knowledge_graph import OntologyKnowledgeAnswer, OntologyKnowledgeQuestion
from app.api.schemas.knowledge_graph.enterprise_ontology import (
    DatasetOntologyView,
    DocumentPreviewSource,
    OntologyDocumentGraph,
    OntologyDocumentRequest,
    OntologyDocumentView,
    OntologyDraftUpdate,
    OntologyDraftView,
    OntologyGraphEditRequest,
    OntologyImportRequest,
    OntologyPreviewRequest,
    OntologyPublishRequest,
    OntologyVersionView,
    SamplePreviewSource,
)
from app.infrastructure.database.connection import get_db
from app.infrastructure.security.roles import UserRoles
from app.models.documents.records import DocumentChunk
from app.models.knowledge_graph.enterprise_ontology import EnterpriseOntology, EnterpriseOntologyVersion
from app.rag.kg.enterprise_ontology.action_workflows import (
    WorkflowInput,
    WorkflowOperation,
    WorkflowView,
    advance_workflow,
    create_workflow,
    read_workflow,
    workflow_view,
)
from app.rag.kg.enterprise_ontology.actions import (
    ActionInput,
    ActionView,
    advance_action,
    prepare_action,
    validate_action_targets,
)
from app.rag.kg.enterprise_ontology.activation import active_version_id, published_version, switch_dataset_version
from app.rag.kg.enterprise_ontology.behaviors import FunctionResult, RuleRequest, RuleResult, read_rule, run_function
from app.rag.kg.enterprise_ontology.consumption import OntologyAnswer, OntologyQuestion, answer_ontology_question
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition, load_ontology_definition
from app.rag.kg.enterprise_ontology.documents import (
    load_document_chunks,
    load_document_evidence,
    review_document_metadata,
    save_document_evidence,
)
from app.rag.kg.enterprise_ontology.drafts import (
    DocumentDraftRequest,
    DocumentDraftView,
    find_draft_document,
    render_draft,
    reopen_draft_document,
    save_draft_document,
)
from app.rag.kg.enterprise_ontology.graph_edits import document_graph
from app.rag.kg.enterprise_ontology.metadata import (
    DocumentMetadataReview,
    DocumentMetadataStatus,
    read_document_metadata,
)
from app.rag.kg.enterprise_ontology.metrics import MetricQuery, MetricResult, evaluate_snapshot_metric
from app.rag.kg.enterprise_ontology.objects import (
    BusinessObject,
    ObjectKey,
    RelatedObjects,
    read_business_object,
    read_related_objects,
)
from app.rag.kg.enterprise_ontology.preview import ChunkPreview, preview_ontology_extraction
from app.rag.kg.enterprise_ontology.rule_extraction import OntologyRuleCandidate, extract_rule_candidates
from app.rag.kg.enterprise_ontology.snapshots import BindingPreview, preview_bindings
from app.rag.kg.enterprise_ontology.suggestions import (
    AssetDescription,
    OntologySuggestion,
    SuggestionRequest,
    list_ontology_assets,
    suggest_ontology,
)
from app.rag.kg.enterprise_ontology.versions import (
    StaleDraftError,
    create_ontology,
    get_ontology,
    get_version,
    list_ontologies,
    list_versions,
    publish_version,
    update_draft,
)
from app.rag.llm.factory import create_llm_client
from app.services.chat.enterprise_ontology import answer_version_knowledge
from app.services.datasets.management import (
    assert_dataset_readable,
    assert_dataset_writable,
    ensure_member,
    get_dataset,
)
from app.services.documents.docx_export import render_clean_docx
from app.services.runtime.retrieval_limiter import run_blocking_call_with_managed_session

router = APIRouter(dependencies=[Depends(bind_edo_authorization)])


@router.post("/{ontology_id}/versions/{version_id}/draft-documents", response_model=DocumentDraftView, status_code=201)
async def create_document_draft_route(
    ontology_id: UUID,
    version_id: UUID,
    request: DocumentDraftRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> DocumentDraftView:
    ensure_member(db, tenant_id, account_id)
    version = _require_version(db, _require_workspace(db, tenant_id, ontology_id), version_id)
    definition = OntologyDefinition.model_validate(version.definition)
    template = definition.document_templates.get(request.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Ontology document template not found")
    async with aclosing(await create_llm_client()) as llm_client:
        answer = await answer_ontology_question(
            db,
            definition=definition,
            version_id=version.id,
            tenant_id=tenant_id,
            account_id=account_id,
            request=request.question,
            llm_client=llm_client,
        )
    try:
        content = render_draft(template, answer, request.manual_fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = save_draft_document(
        db, tenant_id=tenant_id, account_id=account_id, version_id=version.id, request=request, answer=answer
    )
    return DocumentDraftView(id=row.id, version_id=row.version_id, **content.model_dump())


def _read_document_draft(
    db: Session, tenant_id: UUID, account_id: str, ontology_id: UUID, version_id: UUID, draft_id: UUID
) -> DocumentDraftView:
    ensure_member(db, tenant_id, account_id)
    version = _require_version(db, _require_workspace(db, tenant_id, ontology_id), version_id)
    row = find_draft_document(db, tenant_id=tenant_id, account_id=account_id, draft_id=draft_id, version_id=version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ontology document draft not found")
    content = reopen_draft_document(db, row=row, definition=OntologyDefinition.model_validate(version.definition))
    return DocumentDraftView(id=row.id, version_id=row.version_id, **content.model_dump())


@router.get("/{ontology_id}/versions/{version_id}/draft-documents/{draft_id}", response_model=DocumentDraftView)
def read_document_draft_route(
    ontology_id: UUID,
    version_id: UUID,
    draft_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> DocumentDraftView:
    return _read_document_draft(db, tenant_id, account_id, ontology_id, version_id, draft_id)


@router.get("/{ontology_id}/versions/{version_id}/draft-documents/{draft_id}/docx")
def export_document_draft_route(
    ontology_id: UUID,
    version_id: UUID,
    draft_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    final: bool = False,
) -> Response:
    content = _read_document_draft(db, tenant_id, account_id, ontology_id, version_id, draft_id)
    if final and content.missing_required:
        raise HTTPException(status_code=409, detail={"missing_required": content.missing_required})
    return Response(
        content=render_clean_docx(content.markdown, title=content.title),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(content.title + ".docx")},
    )


def _require_editor(db: Session, tenant_id: UUID, account_id: str, *, publish: bool = False) -> None:
    member = ensure_member(db, tenant_id, account_id)
    roles = UserRoles.ADMIN_ROLES if publish else UserRoles.EDIT_ROLES
    if member.role.lower() not in roles:
        raise HTTPException(status_code=403, detail="No ontology management permission")


def _require_workspace(db: Session, tenant_id: UUID, ontology_id: UUID) -> EnterpriseOntology:
    workspace = get_ontology(db, tenant_id, ontology_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Ontology not found")
    return workspace


def _require_version(db: Session, workspace: EnterpriseOntology, version_id: UUID) -> EnterpriseOntologyVersion:
    version = get_version(db, workspace, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Ontology release not found")
    return version


@router.get("", response_model=list[OntologyDraftView])
def list_drafts(
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> list[EnterpriseOntology]:
    _require_editor(db, tenant_id, account_id)
    return list_ontologies(db, tenant_id)


@router.post("", response_model=OntologyDraftView, status_code=201)
def create_draft_route(
    definition: OntologyDefinition,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> EnterpriseOntology:
    _require_editor(db, tenant_id, account_id)
    try:
        return create_ontology(db, tenant_id, definition, account_id=account_id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ontology code already exists") from exc


@router.post("/validate", response_model=OntologyDefinition)
def validate_definition(
    request: OntologyImportRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> OntologyDefinition:
    ensure_member(db, tenant_id, account_id)
    try:
        return load_ontology_definition(request.content, format=request.format)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=exc.errors(include_input=False, include_context=False, include_url=False)
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/binding-preview", response_model=list[BindingPreview])
def binding_preview_route(
    definition: OntologyDefinition,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> list[BindingPreview]:
    _require_editor(db, tenant_id, account_id)
    return preview_bindings(db, tenant_id=tenant_id, account_id=account_id, definition=definition)


def _preview_chunks(
    db: Session, tenant_id: UUID, account_id: str, source: SamplePreviewSource | DocumentPreviewSource
) -> list[DocumentChunk]:
    if isinstance(source, SamplePreviewSource):
        ensure_member(db, tenant_id, account_id)
        return [DocumentChunk(id=uuid4(), document_id=uuid4(), tenant_id=tenant_id, chunk_index=0, content=source.text)]
    _, _, chunks = load_document_chunks(
        db, tenant_id, account_id, source.document_id, source.pipeline_hash, limit=source.limit
    )
    return chunks


@router.get("/assets", response_model=list[AssetDescription])
def list_ontology_assets_route(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> list[AssetDescription]:
    assert_dataset_readable(db, get_dataset(db, tenant_id, dataset_id), account_id)
    return list_ontology_assets(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)


@router.post("/suggest", response_model=OntologySuggestion)
async def suggest_ontology_route(
    request: SuggestionRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> OntologySuggestion:
    _require_editor(db, tenant_id, account_id)
    assert_dataset_readable(db, get_dataset(db, tenant_id, request.dataset_id), account_id)
    try:
        async with aclosing(await create_llm_client()) as llm_client:
            return await suggest_ontology(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                request=request,
                llm_client=llm_client,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/preview", response_model=list[ChunkPreview])
async def preview_extraction(
    request: OntologyPreviewRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> list[ChunkPreview]:
    chunks = _preview_chunks(db, tenant_id, account_id, request.source)
    return await _extract_with_model(request.definition, chunks)


async def _extract_with_model(definition: OntologyDefinition, chunks: list[DocumentChunk]) -> list[ChunkPreview]:
    async with aclosing(await create_llm_client()) as llm_client:
        try:
            return await preview_ontology_extraction(definition, chunks, llm_client=llm_client)
        except ValueError as exc:
            raise HTTPException(
                status_code=502, detail="Model returned an invalid ontology extraction response"
            ) from exc


@router.post("/preview/rules", response_model=list[OntologyRuleCandidate])
async def preview_rules(
    request: OntologyPreviewRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> list[OntologyRuleCandidate]:
    _require_editor(db, tenant_id, account_id)
    chunks = _preview_chunks(db, tenant_id, account_id, request.source)
    async with aclosing(await create_llm_client()) as llm_client:
        try:
            return await extract_rule_candidates(request.definition, chunks, llm_client=llm_client)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Model returned an invalid rule extraction response") from exc


@router.put("/{ontology_id}/draft", response_model=OntologyDraftView)
def update_draft_route(
    ontology_id: UUID,
    request: OntologyDraftUpdate,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> EnterpriseOntology:
    _require_editor(db, tenant_id, account_id)
    workspace = _require_workspace(db, tenant_id, ontology_id)
    try:
        return update_draft(db, workspace, request.definition, expected_revision=request.expected_revision)
    except StaleDraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{ontology_id}/versions", response_model=list[OntologyVersionView])
def list_versions_route(
    ontology_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> list[EnterpriseOntologyVersion]:
    _require_editor(db, tenant_id, account_id)
    return list_versions(db, _require_workspace(db, tenant_id, ontology_id))


@router.post("/{ontology_id}/versions", response_model=OntologyVersionView, status_code=201)
def publish_version_route(
    ontology_id: UUID,
    request: OntologyPublishRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> EnterpriseOntologyVersion:
    _require_editor(db, tenant_id, account_id, publish=True)
    workspace = _require_workspace(db, tenant_id, ontology_id)
    definition = OntologyDefinition.model_validate(workspace.draft)
    try:
        validate_action_targets(tenant_id, definition)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    previews = preview_bindings(db, tenant_id=tenant_id, account_id=account_id, definition=definition)
    if any(preview.issues for preview in previews):
        raise HTTPException(
            status_code=422, detail=[preview.model_dump(mode="json", exclude={"sample"}) for preview in previews]
        )
    try:
        frozen = definition.model_copy(
            update={
                "bindings": [
                    binding.model_copy(update={"asset_revision": preview.asset_revision})
                    for binding, preview in zip(definition.bindings, previews, strict=True)
                ]
            }
        )
        return publish_version(
            db,
            workspace,
            expected_revision=request.expected_revision,
            account_id=account_id,
            frozen_definition=frozen,
        )
    except StaleDraftError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{ontology_id}/versions/{version_id}/metrics/{metric_id}", response_model=MetricResult)
def query_metric_route(
    ontology_id: UUID,
    version_id: UUID,
    metric_id: str,
    request: MetricQuery,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> MetricResult:
    ensure_member(db, tenant_id, account_id)
    workspace = _require_workspace(db, tenant_id, ontology_id)
    version = _require_version(db, workspace, version_id)
    try:
        return evaluate_snapshot_metric(
            db,
            definition=OntologyDefinition.model_validate(version.definition),
            metric_id=metric_id,
            query=request,
            tenant_id=tenant_id,
            account_id=account_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _readable_definition(
    db: Session, tenant_id: UUID, account_id: str, ontology_id: UUID, version_id: UUID
) -> OntologyDefinition:
    ensure_member(db, tenant_id, account_id)
    version = _require_version(db, _require_workspace(db, tenant_id, ontology_id), version_id)
    return OntologyDefinition.model_validate(version.definition)


@router.post("/{ontology_id}/versions/{version_id}/actions/{action_id}/prepare", response_model=ActionView)
def prepare_action_route(
    ontology_id: UUID,
    version_id: UUID,
    action_id: str,
    request: ActionInput,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    authorization: Annotated[str | None, Header()] = None,
) -> ActionView:
    definition = _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    try:
        return prepare_action(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            definition=definition,
            version_id=version_id,
            action_id=action_id,
            inputs=request,
            authorization=authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ontology_id}/versions/{version_id}/action-requests/{request_id}/{operation}", response_model=ActionView)
def advance_action_route(
    ontology_id: UUID,
    version_id: UUID,
    request_id: UUID,
    operation: Literal["approve", "execute", "receipt"],
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    authorization: Annotated[str | None, Header()] = None,
) -> ActionView:
    definition = _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    if operation == "approve":
        _require_editor(db, tenant_id, account_id, publish=True)
    try:
        return advance_action(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            definition=definition,
            version_id=version_id,
            request_id=request_id,
            operation=operation,
            authorization=authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ontology_id}/versions/{version_id}/workflows/{workflow_id}/requests", response_model=WorkflowView)
def create_workflow_route(
    ontology_id: UUID,
    version_id: UUID,
    workflow_id: str,
    request: WorkflowInput,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> WorkflowView:
    definition = _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    try:
        return create_workflow(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            version_id=version_id,
            workflow_id=workflow_id,
            definition=definition,
            inputs=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{ontology_id}/versions/{version_id}/workflow-requests/{request_id}", response_model=WorkflowView)
def get_workflow_route(
    ontology_id: UUID,
    version_id: UUID,
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> WorkflowView:
    _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    return workflow_view(db, read_workflow(db, tenant_id, account_id, version_id, request_id))


@router.post(
    "/{ontology_id}/versions/{version_id}/workflow-requests/{request_id}/steps/{step_index}/{operation}",
    response_model=WorkflowView,
)
def advance_workflow_route(
    ontology_id: UUID,
    version_id: UUID,
    request_id: UUID,
    step_index: Annotated[int, Path(ge=0, le=7)],
    operation: WorkflowOperation,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    authorization: Annotated[str | None, Header()] = None,
) -> WorkflowView:
    definition = _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    if operation == "approve":
        _require_editor(db, tenant_id, account_id, publish=True)
    row = read_workflow(db, tenant_id, account_id, version_id, request_id, approve=operation == "approve", lock=True)
    try:
        return advance_workflow(
            db,
            row,
            definition=definition,
            account_id=account_id,
            operation=operation,
            step_index=step_index,
            authorization=authorization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ontology_id}/versions/{version_id}/objects/{object_type}/lookup", response_model=BusinessObject)
def lookup_object_route(
    ontology_id: UUID,
    version_id: UUID,
    object_type: str,
    request: ObjectKey,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> BusinessObject:
    definition = _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    try:
        return read_business_object(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            definition=definition,
            object_type=object_type,
            key=request.key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post(
    "/{ontology_id}/versions/{version_id}/relations/{relation_id}/from/{object_type}", response_model=RelatedObjects
)
def lookup_related_objects_route(
    ontology_id: UUID,
    version_id: UUID,
    relation_id: str,
    object_type: str,
    request: ObjectKey,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> RelatedObjects:
    definition = _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    try:
        return read_related_objects(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            definition=definition,
            relation_id=relation_id,
            from_object=object_type,
            key=request.key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ontology_id}/versions/{version_id}/rules/{rule_id}", response_model=RuleResult)
def read_rule_route(
    ontology_id: UUID,
    version_id: UUID,
    rule_id: str,
    request: RuleRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> RuleResult:
    definition = _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    try:
        return read_rule(
            db,
            version_id=version_id,
            tenant_id=tenant_id,
            account_id=account_id,
            definition=definition,
            rule_id=rule_id,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ontology_id}/versions/{version_id}/functions/{function_id}", response_model=FunctionResult)
def call_function_route(
    ontology_id: UUID,
    version_id: UUID,
    function_id: str,
    request: MetricQuery,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> FunctionResult:
    definition = _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    try:
        return run_function(
            db,
            version_id=version_id,
            tenant_id=tenant_id,
            account_id=account_id,
            definition=definition,
            function_id=function_id,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{ontology_id}/versions/{version_id}/documents", response_model=OntologyDocumentView)
async def prepare_document_route(
    ontology_id: UUID,
    version_id: UUID,
    request: OntologyDocumentRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> OntologyDocumentView:
    _require_editor(db, tenant_id, account_id)
    version = _require_version(db, _require_workspace(db, tenant_id, ontology_id), version_id)
    doc, selected, chunks = load_document_chunks(db, tenant_id, account_id, request.document_id, request.pipeline_hash)
    if doc.dataset_id is None:
        raise HTTPException(status_code=422, detail="Ontology documents must belong to a dataset")
    assert_dataset_writable(db, get_dataset(db, tenant_id, doc.dataset_id), account_id)
    previews = await _extract_with_model(OntologyDefinition.model_validate(version.definition), chunks)
    row = save_document_evidence(
        db, tenant_id=tenant_id, document=doc, version_id=version.id, pipeline_hash=selected, previews=previews
    )
    return OntologyDocumentView(
        document_id=row.document_id,
        version_id=row.version_id,
        pipeline_hash=row.pipeline_hash,
        chunk_count=len(row.chunks),
    )


@router.get(
    "/{ontology_id}/versions/{version_id}/documents/{document_id}/metadata",
    response_model=dict[str, DocumentMetadataStatus],
)
def read_document_metadata_route(
    ontology_id: UUID,
    version_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    pipeline_hash: str | None = None,
) -> dict[str, DocumentMetadataStatus]:
    definition = _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    _, _, previews = load_document_evidence(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
        version_id=version_id,
        pipeline_hash=pipeline_hash,
    )
    return read_document_metadata(definition, previews)


@router.get("/{ontology_id}/versions/{version_id}/documents/{document_id}/evidence", response_model=list[ChunkPreview])
def read_prepared_evidence_route(
    ontology_id: UUID,
    version_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    pipeline_hash: str | None = None,
) -> list[ChunkPreview]:
    _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    _, _, previews = load_document_evidence(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
        version_id=version_id,
        pipeline_hash=pipeline_hash,
    )
    return previews


@router.put(
    "/{ontology_id}/versions/{version_id}/documents/{document_id}/metadata",
    response_model=dict[str, DocumentMetadataStatus],
)
def review_document_metadata_route(
    ontology_id: UUID,
    version_id: UUID,
    document_id: UUID,
    request: DocumentMetadataReview,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    pipeline_hash: str | None = None,
) -> dict[str, DocumentMetadataStatus]:
    _require_editor(db, tenant_id, account_id)
    definition = _readable_definition(db, tenant_id, account_id, ontology_id, version_id)
    doc, selected, _ = load_document_evidence(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
        version_id=version_id,
        pipeline_hash=pipeline_hash,
    )
    assert_dataset_writable(db, get_dataset(db, tenant_id, doc.dataset_id), account_id)
    try:
        review_document_metadata(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            document_id=document_id,
            version_id=version_id,
            pipeline_hash=selected,
            definition=definition,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return read_document_metadata_route(ontology_id, version_id, document_id, db, tenant_id, account_id, selected)


@router.put("/{ontology_id}/versions/{version_id}/datasets/{dataset_id}", response_model=DatasetOntologyView)
def activate_dataset_route(
    ontology_id: UUID,
    version_id: UUID,
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> DatasetOntologyView:
    dataset = get_dataset(db, tenant_id, dataset_id)
    assert_dataset_writable(db, dataset, account_id)
    workspace = _require_workspace(db, tenant_id, ontology_id)
    version = _require_version(db, workspace, version_id)
    checks = preview_bindings(
        db, tenant_id=tenant_id, account_id=account_id, definition=OntologyDefinition.model_validate(version.definition)
    )
    if any(check.issues for check in checks):
        raise HTTPException(status_code=409, detail="Ontology version has unavailable data bindings")
    row = switch_dataset_version(db, dataset, workspace, version, account_id=account_id)
    return DatasetOntologyView(dataset_id=row.dataset_id, version_id=row.version_id)


@router.get("/datasets/{dataset_id}/documents/{document_id}/graph", response_model=OntologyDocumentGraph)
def read_document_graph_route(
    dataset_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    chunk_id: UUID | None = None,
) -> OntologyDocumentGraph:
    return document_graph(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        document_id=document_id,
        chunk_id=chunk_id,
    )


@router.put("/datasets/{dataset_id}/documents/{document_id}/graph/{chunk_id}", response_model=OntologyDocumentGraph)
def correct_document_graph_route(
    dataset_id: UUID,
    document_id: UUID,
    chunk_id: UUID,
    request: OntologyGraphEditRequest,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> OntologyDocumentGraph:
    try:
        return document_graph(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            document_id=document_id,
            chunk_id=chunk_id,
            edit=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/datasets/{dataset_id}/active", response_model=DatasetOntologyView)
def dataset_active_route(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> DatasetOntologyView:
    assert_dataset_readable(db, get_dataset(db, tenant_id, dataset_id), account_id)
    return DatasetOntologyView(dataset_id=dataset_id, version_id=active_version_id(db, tenant_id, dataset_id))


@router.post("/{ontology_id}/versions/{version_id}/ask/knowledge", response_model=OntologyKnowledgeAnswer)
async def ask_ontology_knowledge_route(
    ontology_id: UUID,
    version_id: UUID,
    request: OntologyKnowledgeQuestion,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> OntologyKnowledgeAnswer:
    ensure_member(db, tenant_id, account_id)
    return await run_blocking_call_with_managed_session(
        answer_version_knowledge,
        request_db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        ontology_id=ontology_id,
        version_id=version_id,
        request=request,
    )


@router.post("/{ontology_id}/versions/{version_id}/ask", response_model=OntologyAnswer)
async def ask_ontology_route(
    ontology_id: UUID,
    version_id: UUID,
    request: OntologyQuestion,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> OntologyAnswer:
    ensure_member(db, tenant_id, account_id)
    version = _require_version(db, _require_workspace(db, tenant_id, ontology_id), version_id)
    async with aclosing(await create_llm_client()) as llm_client:
        return await answer_ontology_question(
            db,
            definition=OntologyDefinition.model_validate(version.definition),
            version_id=version.id,
            tenant_id=tenant_id,
            account_id=account_id,
            request=request,
            llm_client=llm_client,
        )


@router.post("/datasets/{dataset_id}/ask", response_model=OntologyAnswer)
async def ask_dataset_ontology_route(
    dataset_id: UUID,
    request: OntologyQuestion,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> OntologyAnswer:
    assert_dataset_readable(db, get_dataset(db, tenant_id, dataset_id), account_id)
    version_id = active_version_id(db, tenant_id, dataset_id)
    version = published_version(db, tenant_id, version_id) if version_id else None
    if version is None:
        raise HTTPException(status_code=404, detail="知识库没有启用企业本体")
    scoped = request.model_copy(update={"dataset_ids": list(dict.fromkeys([dataset_id, *request.dataset_ids]))})
    async with aclosing(await create_llm_client()) as llm_client:
        return await answer_ontology_question(
            db,
            definition=OntologyDefinition.model_validate(version.definition),
            version_id=version.id,
            tenant_id=tenant_id,
            account_id=account_id,
            request=scoped,
            llm_client=llm_client,
        )


@router.post("/ask", response_model=OntologyAnswer)
async def ask_from_datasets_route(
    request: OntologyQuestion,
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> OntologyAnswer:
    ensure_member(db, tenant_id, account_id)
    candidates = {}
    for dataset_id in dict.fromkeys(request.dataset_ids):
        try:
            assert_dataset_readable(db, get_dataset(db, tenant_id, dataset_id), account_id)
        except HTTPException as exc:
            if exc.status_code not in {403, 404}:
                raise
            continue
        version_id = active_version_id(db, tenant_id, dataset_id)
        if version_id is not None:
            candidates[version_id] = dataset_id
    if not candidates:
        raise HTTPException(status_code=404, detail="请选择启用了企业本体的知识库")
    if len(candidates) != 1:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "请选择入口知识库或指定本体版本",
                "versions": [
                    {"version_id": str(version_id), "dataset_id": str(dataset_id)}
                    for version_id, dataset_id in candidates.items()
                ],
            },
        )
    [dataset_id] = candidates.values()
    return await ask_dataset_ontology_route(dataset_id, request, db, tenant_id, account_id)
