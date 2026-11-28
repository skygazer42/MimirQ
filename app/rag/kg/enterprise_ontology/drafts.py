"""Render saved ontology drafts from currently authorized evidence."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_graph.enterprise_ontology import EnterpriseOntologyDraftDocument
from app.rag.kg.enterprise_ontology.consumption import OntologyAnswer, OntologyQuestion, execute_question_plan
from app.rag.kg.enterprise_ontology.definition import DocumentTemplate, OntologyDefinition, PropertyDefinition


class DocumentDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    question: OntologyQuestion
    manual_fields: dict[str, str] = Field(default_factory=dict)


class DraftContent(BaseModel):
    title: str
    markdown: str
    missing_required: list[str]


class DocumentDraftView(DraftContent):
    id: UUID
    version_id: UUID


def render_draft(template: DocumentTemplate, answer: OntologyAnswer, manual_fields: dict[str, str]) -> DraftContent:
    allowed = {key for key, item in template.fields.items() if item.source == "manual"}
    if manual_fields.keys() - allowed:
        raise ValueError("Only template manual fields can be supplied")
    text = [f"# {template.title}"]
    missing = []
    citations = "\n".join(
        f"《{item.filename}》" + (f"第 {item.page} 页" if item.page is not None else "") + " " + item.evidence.quote
        for item in answer.citations
        if item.applicability == "applicable"
    )
    metric = answer.metric
    values = {
        "object_key": answer.plan.business_key
        if metric is not None or answer.object is not None or answer.related is not None or citations
        else None,
        "metric": str(metric.value) if metric is not None and metric.complete and metric.value is not None else None,
        "citations": citations,
    }
    for key in template.field_order:
        field = template.fields[key]
        if field.source == "metadata":
            candidates = {
                str(value)
                for item in answer.citations
                if item.applicability == "applicable"
                for value in item.metadata.get(field.metadata_field, [])
            }
            value = next(iter(candidates)) if len(candidates) == 1 else None
        elif field.source == "manual":
            value = manual_fields.get(key)
        else:
            value = values[field.source]
        if value and field.type != "string":
            value = str(PropertyDefinition(type=field.type).parse(value))
        if not value and field.required:
            missing.append(key)
        text.append(f"## {field.label}\n\n" + (value or "待确认"))
    return DraftContent(title=template.title, markdown="\n\n".join(text), missing_required=missing)


def save_draft_document(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    version_id: UUID,
    request: DocumentDraftRequest,
    answer: OntologyAnswer,
) -> EnterpriseOntologyDraftDocument:
    row = EnterpriseOntologyDraftDocument(
        tenant_id=tenant_id,
        owner_id=account_id,
        version_id=version_id,
        request=request.model_dump(mode="json"),
        answer=answer.model_dump(mode="json"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def find_draft_document(
    db: Session, *, tenant_id: UUID, account_id: str, draft_id: UUID, version_id: UUID
) -> EnterpriseOntologyDraftDocument | None:
    return db.scalar(
        select(EnterpriseOntologyDraftDocument).where(
            EnterpriseOntologyDraftDocument.tenant_id == tenant_id,
            EnterpriseOntologyDraftDocument.owner_id == account_id,
            EnterpriseOntologyDraftDocument.id == draft_id,
            EnterpriseOntologyDraftDocument.version_id == version_id,
        )
    )


def reopen_draft_document(
    db: Session, *, row: EnterpriseOntologyDraftDocument, definition: OntologyDefinition
) -> DraftContent:
    stored = OntologyAnswer.model_validate(row.answer)
    request = DocumentDraftRequest.model_validate(row.request)
    current = execute_question_plan(
        db,
        definition=definition,
        version_id=row.version_id,
        tenant_id=row.tenant_id,
        account_id=row.owner_id,
        request=request.question,
        plan=stored.plan,
        require_active=False,
    )
    if (
        stored.metric is None
        or current.metric is None
        or (stored.metric.asset_id, stored.metric.value, stored.metric.complete)
        != (current.metric.asset_id, current.metric.value, current.metric.complete)
    ):
        stored.metric = None
    current_citations = [item.model_dump(mode="json") for item in current.citations]
    stored.citations = [item for item in stored.citations if item.model_dump(mode="json") in current_citations]
    stored.object = current.object if stored.object is not None else None
    stored.related = current.related if stored.related is not None else None
    if stored.metric is None and not stored.citations:
        stored.plan = stored.plan.model_copy(update={"business_key": None})
    return render_draft(definition.document_templates[request.template_id], stored, request.manual_fields)
