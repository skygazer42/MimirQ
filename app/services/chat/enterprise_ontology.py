"""Serve bound ontology queries using the caller's existing chat scope."""

import hashlib
import json
import logging
from contextlib import aclosing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from langchain_core.documents import Document as ContextDocument
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas.conversations import Citation, MessageSchema
from app.api.schemas.conversations.chat import OntologyActionParameterField, OntologyActionProposal
from app.infrastructure.config import settings
from app.infrastructure.exceptions import ConfigError
from app.infrastructure.hashing import stable_json_hash
from app.infrastructure.runtime.async_bridge import run_coroutine_sync
from app.infrastructure.security.secrets import decrypt_secret, encrypt_secret
from app.models.conversations.chat import Message
from app.models.documents.records import Document
from app.rag.kg.enterprise_ontology.activation import active_version_id, published_version
from app.rag.kg.enterprise_ontology.consumption import (
    MULTIPLE_OBSERVATION_TIMES_DETAIL,
    ONTOLOGY_PLANNER_TIMEOUT_DETAIL,
    InvalidOntologyPlanError,
    MultipleObservationTimes,
    OntologyAnswer,
    OntologyPlannerTimeoutError,
    OntologyQuestion,
    QuestionPlan,
    asks_for_ontology_metric,
    execute_question_plan,
    plan_question,
)
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition
from app.rag.kg.enterprise_ontology.documents import load_document_chunks
from app.rag.llm.factory import create_llm_client
from app.rag.llm.fallback import AllProvidersFailedError, is_retryable_provider_error
from app.rag.llm.models import LLMMessage
from app.services.chat.execution import is_model_provider_unavailable_error
from app.services.documents.read_scope import get_allowed_document_id_sets

if TYPE_CHECKING:
    from app.api.schemas.knowledge_graph import OntologyKnowledgeAnswer, OntologyKnowledgeQuestion

_RECEIPT_KEY = "ontology_query"
_PLANNER_UNAVAILABLE = "本体查询规划暂不可用，无法核验所请求的指标或数量。"
ONTOLOGY_HISTORY_PLACEHOLDER = "本体查询结果随当前权限核验，打开会话可重新读取。"
logger = logging.getLogger(__name__)
_FUSION_KEY = "ontology_fusion"


def build_action_proposal(
    ontology_id: UUID, version_id: UUID, definition: OntologyDefinition, plan: QuestionPlan
) -> OntologyActionProposal | None:
    if plan.action_id is None:
        return None
    action = definition.actions.get(plan.action_id)
    if action is None or action.object_type != plan.object_type:
        return None
    obj = definition.object_types[action.object_type]
    key = {obj.key[0]: plan.business_key} if len(obj.key) == 1 and plan.business_key else {}
    return OntologyActionProposal(
        ontology_id=ontology_id,
        version_id=version_id,
        action_id=plan.action_id,
        label=action.label or plan.action_id,
        target=action.target,
        approval_required=action.approval_required,
        key_fields={name: obj.properties[name].label or name for name in obj.key},
        parameter_fields={
            name: OntologyActionParameterField(label=field.label or name, required=field.required)
            for name, field in action.parameters.items()
        },
        key=key,
        parameters={name: value for name, value in plan.action_parameters.items() if name in action.parameters},
    )


def _citations(answer: OntologyAnswer) -> list[dict]:
    return [
        Citation(
            document_id=item.document_id,
            document_name=item.filename,
            chunk_id=item.chunk_id,
            chunk_content=item.evidence.quote,
            page_number=item.page,
            evidence_start_char=item.evidence.start_char,
            evidence_end_char=item.evidence.end_char,
            pipeline_hash=item.pipeline_hash,
        ).model_dump(mode="json", exclude_none=True)
        for item in answer.citations
    ]


def _evidence_source_exclusions(fields: dict[str, bool | set[str]]) -> dict:
    return {
        "metric": fields,
        "metrics": {"__all__": fields},
        "object": fields,
        "related": {"objects": {"__all__": fields}},
        "object_choices": {"__all__": fields},
        "rule": {"evidence": fields, "functions": {"__all__": fields}},
        "function": {"result": fields},
    }


def _evidence_digest(answer: OntologyAnswer) -> str:
    public = answer.model_dump(
        mode="json",
        exclude={
            **_evidence_source_exclusions({"source_updated_at": True, "edo": {"request_id"}}),
            # The executed parameters are already signed in the plan; keep saved receipt digests stable.
            "queries": {"__all__": {"parameters"}},
        },
    )
    encoded = json.dumps(public, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class OntologyChatTurn:
    answer: OntologyAnswer
    query: OntologyQuestion
    planner_failure: (
        Literal[
            "ontology_planner_invalid",
            "ontology_planner_timeout",
            "model_provider_unavailable",
            "multiple_observation_times",
        ]
        | None
    ) = None
    action_proposal: OntologyActionProposal | None = None
    documents_only: bool = False

    @property
    def citations(self) -> list[dict]:
        return _citations(self.answer)

    @property
    def receipt_metadata(self) -> dict:
        if self.planner_failure is not None:
            return {_RECEIPT_KEY: {"planner_failure": self.planner_failure}}
        return {
            _RECEIPT_KEY: {
                "version_id": str(self.answer.ontology_version_id),
                "request": self.query.model_dump(mode="json"),
                "plan": self.answer.plan.model_dump(mode="json"),
                "digest": _evidence_digest(self.answer),
                "documents_only": self.documents_only,
            }
        }


@dataclass(frozen=True)
class OntologyEvidence:
    context: dict
    documents: list[ContextDocument]
    metrics: dict
    action_proposal: OntologyActionProposal | None


def attach_ontology_evidence(state: dict[str, Any], evidence: OntologyEvidence | None) -> dict[str, Any]:
    state = {**state, "ontology_prepared": True}
    if evidence is None:
        return state
    state.update(
        ontology_context=evidence.context,
        ontology_docs=evidence.documents,
        metrics={**state.get("metrics", {}), **evidence.metrics},
    )
    if evidence.action_proposal is not None:
        state["ontology_action"] = evidence.action_proposal.model_dump(mode="json")
    return state


def prepare_ontology_evidence(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    document_ids: list[UUID] | None,
    question: str,
    history: list[dict] | None = None,
    conversation_id: UUID | None = None,
) -> OntologyEvidence | None:
    if dataset_id is None or active_version_id(db, tenant_id, dataset_id) is None:
        return None
    user_history = [item for item in history or [] if item["role"] == "user"][-8:]
    if not user_history and conversation_id is not None:
        rows = db.scalars(
            select(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation_id,
                Message.role == "user",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(9)
        ).all()
        user_history = [{"role": "user", "content": row.content} for row in reversed(rows) if row.content != question]
    turn = run_coroutine_sync(
        lambda: answer_scoped_ontology(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            message=question,
            document_ids=document_ids,
            history=user_history,
        )
    )
    if turn is None:
        return None
    return build_ontology_evidence(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_ids=[dataset_id],
        document_ids=document_ids,
        turn=turn,
    )


def build_ontology_evidence(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID],
    document_ids: list[UUID] | None,
    turn: OntologyChatTurn,
) -> OntologyEvidence:
    answer = turn.answer
    # Source update times are operational metadata, outside the business timeline.
    evidence = answer.model_dump(
        mode="json",
        exclude={
            **_evidence_source_exclusions({"source_updated_at": True}),
            "answer": True,
            "plan": True,
            "queries": {"__all__": {"sql"}},
        },
        exclude_none=True,
    )
    citation_documents = [
        ContextDocument(
            page_content=item.evidence.quote,
            metadata={
                "document_id": str(item.document_id),
                "chunk_id": str(item.chunk_id),
                "source": item.filename,
                "pipeline_hash": item.pipeline_hash,
                "page_number": item.page,
                "retrieval_role": "ontology",
                "score": 1.0,
                "ontology_evidence": True,
                "ontology_version_id": str(answer.ontology_version_id),
                "object_type": answer.plan.object_type,
                "business_key": answer.plan.business_key,
            },
            id=str(item.chunk_id),
        )
        for item in answer.citations
    ]
    documents = []
    policy_documents: dict[UUID, list[ContextDocument]] = {}
    if answer.queries:
        version = published_version(db, tenant_id, answer.ontology_version_id)
        definition = OntologyDefinition.model_validate(version.definition)
        source_ids = {source for item in answer.queries for source in definition.named_queries[item.query].sources}
        if document_ids is not None:
            source_ids.intersection_update(document_ids)
        for source_id in sorted(source_ids):
            try:
                doc, pipeline, chunks = load_document_chunks(db, tenant_id, account_id, source_id, limit=4)
            except HTTPException as exc:
                if exc.status_code not in {403, 404}:
                    raise
                continue
            if (
                doc.dataset_id not in dataset_ids
                or doc.archived_at is not None
                or doc.publication_status != "published"
            ):
                continue
            policy_documents[source_id] = [
                ContextDocument(
                    page_content=chunk.content,
                    metadata={
                        "document_id": str(doc.id),
                        "chunk_id": str(chunk.id),
                        "source": doc.filename,
                        "pipeline_hash": pipeline,
                        "page_number": chunk.page_number,
                        "retrieval_role": "ontology",
                        "ontology_evidence": True,
                        "ontology_version_id": str(answer.ontology_version_id),
                    },
                    id=str(chunk.id),
                )
                for chunk in chunks
            ]
    usable_queries = set()
    used_policy_sources = set()
    for item in answer.queries:
        required_sources = set(definition.named_queries[item.query].sources)
        if required_sources - policy_documents.keys():
            evidence["unavailable"].append(f"{item.label}：缺少可引用的制度来源")
            continue
        usable_queries.add(item.query)
        used_policy_sources.update(required_sources)
        documents.append(
            ContextDocument(
                page_content=json.dumps(
                    {
                        "query_id": item.query,
                        "ontology_version_id": str(answer.ontology_version_id),
                        "description": item.description,
                        "parameters": item.parameters,
                        "table_id": item.asset_ids[0],
                        "records": [dict(zip(item.columns, row, strict=True)) for row in item.rows],
                        "truncated": not item.complete,
                    },
                    ensure_ascii=False,
                ),
                metadata={
                    "document_id": str(item.document_ids[0]),
                    "source": item.label,
                    "table_id": item.asset_ids[0],
                    "retrieval_role": "tag",
                    "chunk_role": "tag_sql_result",
                    "join_table_ids": item.asset_ids,
                    "sql_generation_mode": "ontology_named_query",
                    "score": 1.0,
                    "ontology_evidence": True,
                    "ontology_observation": True,
                    "ontology_version_id": str(answer.ontology_version_id),
                    "ontology_kind": "query",
                    "ontology_policy_sources": sorted(str(source) for source in required_sources),
                    "evidence_record_id": (
                        f"{answer.ontology_version_id}:query:{item.query}:{stable_json_hash(item.parameters)}"
                    ),
                },
            )
        )
    evidence["queries"] = [item for item in evidence["queries"] if item["query"] in usable_queries]
    documents.extend(document for source_id in sorted(used_policy_sources) for document in policy_documents[source_id])
    documents.extend(citation_documents)
    observations = (
        "metric",
        "metrics",
        "queries",
        "object",
        "related",
        "object_choices",
        "metric_choices",
        "rule",
        "function",
        "citations",
        "conflicts",
    )
    metrics = {
        "ontology_used": bool(turn.action_proposal or any(evidence.get(key) for key in observations)),
        "ontology_planner_failure": turn.planner_failure,
        "ontology_unavailable": evidence["unavailable"],
    }
    if not metrics["ontology_used"]:
        return OntologyEvidence(context={}, documents=[], metrics=metrics, action_proposal=None)
    # The query receipt rechecks row/field permissions when a saved generated answer is opened again.
    receipt = {**turn.receipt_metadata[_RECEIPT_KEY], "dataset_id": str(dataset_ids[0])}
    receipt["source_document_ids"] = sorted({doc.metadata["document_id"] for doc in documents})
    metrics[_FUSION_KEY] = receipt
    return OntologyEvidence(
        context=evidence,
        documents=documents,
        metrics=metrics,
        action_proposal=turn.action_proposal,
    )


def answer_version_knowledge(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    ontology_id: UUID,
    version_id: UUID,
    request: "OntologyKnowledgeQuestion",
) -> "OntologyKnowledgeAnswer":
    from app.api.schemas.conversations import ChatRAGConfig
    from app.api.schemas.knowledge_graph import OntologyKnowledgeAnswer
    from app.rag.kg.enterprise_ontology.consumption import answer_ontology_question
    from app.rag.kg.enterprise_ontology.versions import get_ontology, get_version
    from app.rag.runtime.graph.state import RAGRuntimeContext, build_rag_state
    from app.rag.runtime.graph.workflow import run_rag_workflow_functional
    from app.services.datasets.management import assert_dataset_readable, get_dataset
    from app.services.retrieval.defaults import retrieval_options

    workspace = get_ontology(db, tenant_id, ontology_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Ontology not found")
    version = get_version(db, workspace, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Ontology release not found")
    definition = OntologyDefinition.model_validate(version.definition)
    dataset_ids = list(dict.fromkeys(request.dataset_ids))
    for dataset_id in dataset_ids:
        assert_dataset_readable(db, get_dataset(db, tenant_id, dataset_id), account_id)
    if request.document_ids is not None:
        allowed, _ = get_allowed_document_id_sets(db, tenant_id, account_id, request.document_ids)
        scoped = set(
            db.scalars(
                select(Document.id).where(
                    Document.tenant_id == tenant_id,
                    Document.dataset_id.in_(dataset_ids),
                    Document.id.in_(allowed),
                )
            ).all()
        )
        if scoped != set(request.document_ids):
            raise HTTPException(status_code=403, detail="Document is outside the selected knowledge scope")
    query = OntologyQuestion(
        question=request.question,
        dataset_ids=dataset_ids,
        document_ids=request.document_ids,
        observed_at=request.observed_at,
    )
    db.rollback()

    async def read_ontology() -> OntologyAnswer:
        async with aclosing(await create_llm_client()) as client:
            return await answer_ontology_question(
                db,
                definition=definition,
                version_id=version_id,
                tenant_id=tenant_id,
                account_id=account_id,
                request=query,
                llm_client=client,
                require_active=False,
                documents_only=not settings.TABLE_LLM_ALLOW_RESULT_EGRESS,
            )

    planner_failure = None
    try:
        answer = run_coroutine_sync(read_ontology)
    except (OntologyPlannerTimeoutError, InvalidOntologyPlanError) as exc:
        planner_failure = exc.error_code.lower()
        logger.warning("Ontology query planner unavailable (%s)", planner_failure)
        answer = OntologyAnswer(
            ontology_version_id=version_id,
            plan=QuestionPlan(),
            unavailable=[str(exc)],
            answer=str(exc),
        )
    turn = OntologyChatTurn(
        answer=answer,
        query=query,
        planner_failure=planner_failure,
        documents_only=not settings.TABLE_LLM_ALLOW_RESULT_EGRESS,
        action_proposal=build_action_proposal(ontology_id, version_id, definition, answer.plan),
    )
    evidence = build_ontology_evidence(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_ids=dataset_ids,
        document_ids=request.document_ids,
        turn=turn,
    )
    request_id = uuid4().hex
    state = build_rag_state(
        question=request.question,
        history=[],
        tenant_id=tenant_id,
        account_id=account_id,
        request_id=request_id,
        dataset_ids=dataset_ids,
        document_ids=request.document_ids,
        db=db,
        **retrieval_options(ChatRAGConfig()),
    )
    state = attach_ontology_evidence(state, evidence)
    state["ontology_enabled"] = True
    db.rollback()
    result = run_rag_workflow_functional(
        state,
        thread_id=f"ontology-knowledge-{request_id}",
        context=RAGRuntimeContext(request_id=request_id, tenant_id=str(tenant_id), account_id=account_id),
    )
    return OntologyKnowledgeAnswer(
        ontology=answer,
        answer=result["answer"],
        citations=result["citations"],
        metrics=result["metrics"],
    )


def protect_fused_answer(content: str, citations: list, metrics: dict) -> tuple[str, list, dict]:
    if _FUSION_KEY not in metrics:
        return content, citations, metrics
    protected = {"generation_context"}
    response = {
        "content": content,
        "citations": citations,
        **{key: metrics[key] for key in protected if key in metrics},
    }
    payload = json.dumps(jsonable_encoder(response), ensure_ascii=False)
    receipt = {**metrics[_FUSION_KEY], "response": encrypt_secret(payload)}
    public_metrics = {key: value for key, value in metrics.items() if key not in protected}
    return ONTOLOGY_HISTORY_PLACEHOLDER, [], {**public_metrics, _FUSION_KEY: receipt}


def _visible_fused_message(
    db: Session, *, tenant_id: UUID, account_id: str, message: Message, metadata: dict
) -> MessageSchema:
    receipt = metadata[_FUSION_KEY]
    visible_metadata = {key: value for key, value in metadata.items() if key not in {_FUSION_KEY, "ontology_action"}}
    text, citations = "原查询的证据或访问范围已有变化，可重新查询。", []
    version = published_version(db, tenant_id, UUID(receipt["version_id"])) if "version_id" in receipt else None
    evidence_matches = "planner_failure" in receipt
    action_proposal = None
    if version is not None:
        definition = OntologyDefinition.model_validate(version.definition)
        query = OntologyQuestion.model_validate(receipt["request"])
        current = execute_question_plan(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            version_id=version.id,
            definition=definition,
            request=query,
            plan=QuestionPlan.model_validate(receipt["plan"]),
            require_active=False,
            documents_only=receipt.get("documents_only", False),
        )
        evidence_matches = _evidence_digest(current) == receipt["digest"]
    if evidence_matches:
        payload = json.loads(decrypt_secret(receipt["response"]))
        ids = {UUID(value) for value in receipt.get("source_document_ids", [])}
        ids.update(UUID(item["document_id"]) for item in payload["citations"] if item.get("document_id"))
        allowed, _ = get_allowed_document_id_sets(db, tenant_id, account_id, sorted(ids))
        if allowed == ids:
            text, citations = payload["content"], payload["citations"]
            if "generation_context" in payload:
                visible_metadata["generation_context"] = payload["generation_context"]
            if version is not None and active_version_id(db, tenant_id, UUID(receipt["dataset_id"])) == version.id:
                action_proposal = build_action_proposal(version.ontology_id, version.id, definition, current.plan)
    return MessageSchema(
        id=message.id,
        role=message.role,
        content=text,
        citations=citations,
        created_at=message.created_at,
        ontology_action=action_proposal,
        message_metadata=visible_metadata,
    )


async def answer_scoped_ontology(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    message: str,
    document_ids: list[UUID] | None,
    history: list[dict] | None = None,
) -> OntologyChatTurn | None:
    if dataset_id is None:
        return None
    if document_ids:
        scoped = set(
            db.scalars(
                select(Document.id).where(
                    Document.tenant_id == tenant_id, Document.dataset_id == dataset_id, Document.id.in_(document_ids)
                )
            )
        )
        if scoped != set(document_ids):
            return None
    version_id = active_version_id(db, tenant_id, dataset_id)
    version = published_version(db, tenant_id, version_id) if version_id else None
    if version is None:
        return None
    query = OntologyQuestion(
        question=message,
        dataset_ids=[dataset_id],
        document_ids=document_ids,
        history=[LLMMessage(role=item["role"], content=item["content"]) for item in (history or [])[-20:]],
    )
    definition = OntologyDefinition.model_validate(version.definition)
    ontology_id = version.ontology_id
    db.rollback()
    try:
        async with aclosing(await create_llm_client()) as client:
            plan = await plan_question(definition, query, client)
    except Exception as exc:
        message_text = _PLANNER_UNAVAILABLE
        if isinstance(exc, OntologyPlannerTimeoutError):
            reason = "ontology_planner_timeout"
            message_text = ONTOLOGY_PLANNER_TIMEOUT_DETAIL
        elif isinstance(exc, MultipleObservationTimes):
            reason = "multiple_observation_times"
            message_text = MULTIPLE_OBSERVATION_TIMES_DETAIL
        elif isinstance(exc, InvalidOntologyPlanError):
            reason = "ontology_planner_invalid"
        elif isinstance(exc, HTTPException) or not (
            isinstance(exc, (AllProvidersFailedError, ConfigError))
            or is_retryable_provider_error(exc)
            or is_model_provider_unavailable_error(exc)
        ):
            raise
        else:
            reason = "model_provider_unavailable"
        logger.warning("Ontology query planner unavailable (%s)", reason)
        if reason in {"ontology_planner_invalid", "model_provider_unavailable"} and not asks_for_ontology_metric(
            definition, message
        ):
            return None
        return OntologyChatTurn(
            answer=OntologyAnswer(
                ontology_version_id=version_id,
                plan=QuestionPlan(),
                unavailable=[message_text],
                answer=message_text,
            ),
            query=query,
            planner_failure=reason,
        )
    if not (
        plan.metric_id
        or plan.metric_ids
        or plan.query_ids
        or plan.concept_ids
        or plan.rule_id
        or plan.function_id
        or plan.action_id
        or plan.relation_id
        or plan.relation_path
        or plan.object_name
        or plan.metric_candidates
        or plan.include_object
        or (plan.include_documents and plan.business_key)
    ):
        return None
    documents_only = not settings.TABLE_LLM_ALLOW_RESULT_EGRESS
    if documents_only and not (plan.include_documents or plan.concept_ids or plan.relation_path or plan.action_id):
        return None
    answer = execute_question_plan(
        db,
        definition=definition,
        version_id=version_id,
        tenant_id=tenant_id,
        account_id=account_id,
        request=query,
        plan=plan,
        documents_only=documents_only,
    )
    return OntologyChatTurn(
        answer=answer,
        query=query,
        action_proposal=build_action_proposal(ontology_id, version_id, definition, plan),
        documents_only=documents_only,
    )


def visible_ontology_message(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    message: Message,
) -> Message | MessageSchema:
    metadata = getattr(message, "message_metadata", None) or {}
    if _FUSION_KEY in metadata:
        return _visible_fused_message(
            db, tenant_id=tenant_id, account_id=account_id, message=message, metadata=metadata
        )
    if _RECEIPT_KEY not in metadata:
        return message
    receipt = metadata[_RECEIPT_KEY]
    citations = []
    action_proposal = None
    if receipt.get("planner_failure") == "ontology_planner_timeout":
        text = ONTOLOGY_PLANNER_TIMEOUT_DETAIL
    elif receipt.get("planner_failure") == "multiple_observation_times":
        text = MULTIPLE_OBSERVATION_TIMES_DETAIL
    elif receipt.get("planner_failure"):
        text = _PLANNER_UNAVAILABLE
    else:
        version = published_version(db, tenant_id, UUID(receipt["version_id"]))
        text = "原查询的证据或访问范围已有变化，可重新查询。"
        if version is not None:
            definition = OntologyDefinition.model_validate(version.definition)
            query = OntologyQuestion.model_validate(receipt["request"])
            current = execute_question_plan(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                version_id=version.id,
                definition=definition,
                request=query,
                plan=QuestionPlan.model_validate(receipt["plan"]),
                require_active=False,
            )
            if _evidence_digest(current) == receipt["digest"]:
                text, citations = current.answer, _citations(current)
                proposal = build_action_proposal(version.ontology_id, version.id, definition, current.plan)
                if proposal is not None and query.dataset_ids:
                    if active_version_id(db, tenant_id, query.dataset_ids[0]) == version.id:
                        action_proposal = proposal
    return MessageSchema(
        id=message.id,
        role=message.role,
        content=text,
        citations=citations,
        created_at=message.created_at,
        ontology_action=action_proposal,
        message_metadata={key: value for key, value in metadata.items() if key != _RECEIPT_KEY},
    )
