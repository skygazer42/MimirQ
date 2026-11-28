"""Resolve a question against one published ontology and its authorized evidence."""

import asyncio
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import Row, select
from sqlalchemy.orm import Session

from app.infrastructure.exceptions import MimirQError
from app.models.documents.records import Document, DocumentChunk
from app.models.knowledge_graph.enterprise_ontology import EnterpriseOntologyDocument
from app.rag.ingestion.parsing.utils.markdown_table import build_markdown_table
from app.rag.kg.enterprise_ontology.activation import active_version_id
from app.rag.kg.enterprise_ontology.behaviors import FunctionResult, RuleRequest, RuleResult, read_rule, run_function
from app.rag.kg.enterprise_ontology.definition import Fact, MetricDefinition, OntologyDefinition, Scalar
from app.rag.kg.enterprise_ontology.documents import current_document_previews, span_matches
from app.rag.kg.enterprise_ontology.edo_source import EdoSourceError
from app.rag.kg.enterprise_ontology.metadata import document_applicability, read_document_metadata
from app.rag.kg.enterprise_ontology.metrics import MetricQuery, MetricResult, evaluate_snapshot_metric
from app.rag.kg.enterprise_ontology.objects import (
    BusinessObject,
    RelatedObjects,
    find_objects_by_name,
    primary_binding,
    read_business_object,
    read_related_objects,
)
from app.rag.kg.enterprise_ontology.preview import ChunkPreview, PreviewEntity, PreviewRelation
from app.rag.kg.enterprise_ontology.queries import NamedQueryResult, run_named_query
from app.rag.kg.extraction.evidence import EvidenceSpan
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMRole
from app.services.datasets.management import assert_dataset_readable, get_dataset
from app.services.documents.read_scope import list_accessible_document_ids

_CHINESE_DATE = r"([0-9]{4})\s{0,3}年\s{0,3}([0-9]{1,2})\s{0,3}月\s{0,3}([0-9]{1,2})\s{0,3}日"
_ISO_DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
_ISO_TIME = r"[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?"
_AS_OF_PREFIX = r"(?:\bas\s+(?:of|at)\b|截至|截止(?:到|至)?)\s*[:：]?\s*"
_AS_OF_BOUNDARY = r"(?![0-9A-Za-z_+:/-])"
_AS_OF = re.compile(
    rf"{_AS_OF_PREFIX}(?P<date>{_ISO_DATE}(?:{_ISO_TIME})?|{_CHINESE_DATE}){_AS_OF_BOUNDARY}",
    re.IGNORECASE,
)
_CURRENT_AS_OF = {"now", "right now", "today", "现在", "目前", "当前", "今天", "今日", "此刻", "当下"}
_AS_OF_NOW = re.compile(
    rf"(?:{_AS_OF_PREFIX}(?:{'|'.join(sorted(_CURRENT_AS_OF))}){_AS_OF_BOUNDARY}|(?:现在|当前|目前)逾期)",
    re.IGNORECASE,
)
_COUNT_REQUEST = re.compile(
    r"\b(?:how\s+many|count|number\s+of)\b|多少|几(?:个|件|条|张|单|项|台|行|人|次|份|笔)|数量|总数|计数",
    re.IGNORECASE,
)
_POLICY_VERSION_REQUEST = re.compile(r"(?:依据|根据|适用)哪一?版")
_CONFIRMED_POLICY_REQUEST = re.compile(r"已生效|当前有效|仍有效")
_POLICY_OBSERVATION_DAY = re.compile(
    rf"(?P<date>{_ISO_DATE}|{_CHINESE_DATE})\s*(?:当天|当日|那天)(?!\s*(?:到期|发生|新增))"
)
_GROUP_REQUEST = re.compile(r"分组|拆[开分]|分别|分维度|分布|\b(?:group(?:ed)? by|breakdown|per)\b", re.IGNORECASE)
_ACTION_PREVIEW_DECLINED = re.compile(
    r"(?:不要|不必|无需|禁止|先别)(?:为[^，。！？；\n]{1,80})?\s*(?:预演|准备)"
    r"|只(?:是)?(?:我)?(?:想)?(?:了解|说明|查询|核对|查看)"
    r"|\b(?:do not|don't)\s+(?:preview|prepare)\b",
    re.IGNORECASE,
)
_ACTION_REQUEST = re.compile(r"写入|新增|创建|修改|更新|删除|移除|关闭|提交|批准|审批|执行|派发|标记为")
_CONCEPT_POLICY_REQUEST = re.compile(
    r"依据|政策|制度|规定|标准|流程|条件|资格|例外|限期|截止|条款|如何|怎么|怎样|能否|能不能|可不可以|是否允许|是否需要"
)
_CONCEPT_STRUCTURED_REQUEST = re.compile(
    r"总价|总成本|报价|价格|金额|费用|成本|数量|多少|几(?:个|件|条|张|单|项|台|行|人|次|份|笔)|"
    r"计算|统计|占比|比例|比率|总额|营收|回款|对比|比较|选择|挑选|选哪|选谁"
)
_BUSINESS_IDENTIFIER = re.compile(
    r"\b[A-Z]{2,}[-_][A-Za-z0-9-]+\b|(?:工单|订单|采购单|维修单|服务单|变更)\s*[-#]?\s*[0-9]"
)
_HISTORICAL_STATE_UNAVAILABLE = "缺少对应观察时点的历史状态"
_PLANNER_TIMEOUT_SECONDS = 8
MULTIPLE_OBSERVATION_TIMES_DETAIL = "一次查询仅支持一个历史观察时点"
ONTOLOGY_PLANNER_TIMEOUT_DETAIL = "本体查询规划超时，请稍后重试。"
QueryParameters = dict[str, Scalar | None]
QueryParameterBatch = Annotated[list[QueryParameters], Field(min_length=1, max_length=6)]


class InvalidOntologyPlanError(MimirQError):
    def __init__(self) -> None:
        super().__init__("本体查询规划未返回有效结构", error_code="ONTOLOGY_PLANNER_INVALID", status_code=502)


class OntologyPlannerTimeoutError(MimirQError):
    def __init__(self) -> None:
        super().__init__(ONTOLOGY_PLANNER_TIMEOUT_DETAIL, error_code="ONTOLOGY_PLANNER_TIMEOUT", status_code=504)


class MultipleObservationTimes(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=422, detail=MULTIPLE_OBSERVATION_TIMES_DETAIL)


class OntologyQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    history: list[LLMMessage] = Field(default_factory=list, max_length=20)
    dataset_ids: list[UUID] = Field(default_factory=list, max_length=20)
    document_ids: list[UUID] | None = Field(default=None, max_length=500)
    observed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class QuestionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str | None = None
    business_key: str | None = None
    object_name: str | None = None
    object_filters: dict[str, Scalar] = Field(default_factory=dict, max_length=16, exclude_if=lambda value: not value)
    metric_id: str | None = None
    metric_ids: list[str] = Field(default_factory=list, max_length=10)
    query_ids: list[str] = Field(default_factory=list, max_length=6)
    concept_ids: list[str] = Field(default_factory=list, max_length=8, exclude_if=lambda value: not value)
    query_parameters: dict[str, QueryParameters | QueryParameterBatch] = Field(default_factory=dict, max_length=6)
    metric_candidates: list[str] = Field(default_factory=list, max_length=10)
    metric_query: MetricQuery | None = None
    metric_period: Literal["current_month"] | None = None
    as_of: str | None = Field(
        default=None,
        max_length=80,
        exclude_if=lambda value: value is None,
        description="An explicit as-of date or timestamp copied from the question.",
    )
    function_id: str | None = None
    rule_id: str | None = None
    action_id: str | None = None
    action_parameters: dict[str, Scalar] = Field(default_factory=dict, max_length=32)
    include_object: bool = False
    relation_id: str | None = None
    relation_path: list[str] | None = Field(
        default=None,
        min_length=2,
        max_length=4,
        exclude_if=lambda value: value is None,
        description="Two to four declared relation IDs in forward traversal order.",
    )
    include_documents: bool = False

    def parameter_sets(self, query_id: str) -> list[QueryParameters]:
        parameters = self.query_parameters.get(query_id, {})
        return parameters if isinstance(parameters, list) else [parameters]

    @model_validator(mode="after")
    def bound_query_invocations(self) -> Self:
        if sum(len(self.parameter_sets(query_id)) for query_id in self.query_ids) > 6:
            raise ValueError("A plan supports at most six named query invocations")
        return self

    @model_validator(mode="before")
    @classmethod
    def bind_single_query_parameters(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        query_ids, parameters = value.get("query_ids", []), value.get("query_parameters")
        if (
            isinstance(query_ids, list)
            and len(query_ids) == 1
            and isinstance(query_ids[0], str)
            and isinstance(parameters, dict)
            and parameters
            and all(not isinstance(item, (dict, list)) for item in parameters.values())
        ):
            return {**value, "query_parameters": {query_ids[0]: parameters}}
        return value

    @model_validator(mode="before")
    @classmethod
    def normalize_nested_metric_period(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        query = value.get("metric_query")
        if not isinstance(query, dict) or query.get("metric_period") != "current_month":
            return value
        data = value.copy()
        query = query.copy()
        period = query.pop("metric_period")
        if data.get("metric_period") is None:
            data["metric_period"] = period
        data["metric_query"] = query
        return data

    @field_validator("include_object", "include_documents", mode="before")
    @classmethod
    def normalize_optional_flags(cls, value: object) -> object:
        return False if value is None else value

    @field_validator("action_parameters", "object_filters", "metric_candidates", mode="before")
    @classmethod
    def normalize_optional_parameters(cls, value: object, info) -> object:
        if value is None:
            return [] if info.field_name == "metric_candidates" else {}
        if info.field_name in {"action_parameters", "object_filters"} and isinstance(value, dict):
            return {name: item for name, item in value.items() if item is not None}
        return value

    @field_validator("metric_query", mode="before")
    @classmethod
    def normalize_metric_hint(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        query = value.copy()
        for field in ("filters", "group_by", "historical_state"):
            if query.get(field) is None:
                query.pop(field, None)
        filters, dimensions = query.get("filters"), query.get("group_by")
        if isinstance(filters, dict) and isinstance(dimensions, list) and dimensions:
            query["filters"] = {key: item for key, item in filters.items() if item is not None}
        query.pop("observed_at", None)
        return query


class OntologyCitation(BaseModel):
    document_id: UUID
    filename: str
    pipeline_hash: str
    chunk_id: UUID
    page: int | None
    evidence: EvidenceSpan
    applicability: Literal["applicable", "pending"] = "applicable"
    metadata: dict[str, list[Fact]] = Field(default_factory=dict)


class OntologyAnswer(BaseModel):
    ontology_version_id: UUID
    plan: QuestionPlan
    metric: MetricResult | None = None
    metrics: list[MetricResult] = Field(default_factory=list)
    queries: list[NamedQueryResult] = Field(default_factory=list)
    object: BusinessObject | None = None
    related: RelatedObjects | None = None
    object_choices: list[BusinessObject] = Field(default_factory=list)
    metric_choices: list[str] = Field(default_factory=list)
    rule: RuleResult | None = None
    function: FunctionResult | None = None
    citations: list[OntologyCitation] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)
    answer: str


def _key_pattern(value: str) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(value) + r"(?![A-Za-z0-9_-])", re.IGNORECASE)


def asks_for_ontology_metric(definition: OntologyDefinition, question: str) -> bool:
    return _COUNT_REQUEST.search(question) is not None or any(
        _key_pattern(name).search(question)
        for catalog in (definition.metrics, definition.functions)
        for key, item in catalog.items()
        for name in (key, item.label)
        if name
    )


def _explicit_subject(definition: OntologyDefinition, question: str) -> tuple[str, str] | None:
    matches = set()
    for type_id, obj in definition.object_types.items():
        if obj.key_prefix is not None:
            pattern = re.escape(obj.key_prefix) + r"[A-Za-z0-9_-]+"
            matches.update((type_id, match[0]) for match in re.finditer(pattern, question))
        for label in (obj.label or type_id, *obj.aliases):
            pattern = re.escape(label) + r"\s+([A-Za-z0-9_-]*[0-9][A-Za-z0-9_-]*)(?![A-Za-z0-9_-])"
            matches.update((type_id, match[1]) for match in re.finditer(pattern, question, re.IGNORECASE))
    return next(iter(matches)) if len(matches) == 1 else None


def _grounded_as_of(question: str, candidate: str | None) -> str | None:
    dates = {match["date"] for match in _AS_OF.finditer(question)}
    if _CONFIRMED_POLICY_REQUEST.search(question):
        dates.update(match["date"] for match in _POLICY_OBSERVATION_DAY.finditer(question))
    if len(dates) > 1:
        raise MultipleObservationTimes()
    if dates:
        return dates.pop()
    if (
        candidate
        and candidate.casefold() not in _CURRENT_AS_OF
        and re.search(rf"{_AS_OF_PREFIX}{re.escape(candidate)}{_AS_OF_BOUNDARY}", question, re.IGNORECASE)
    ):
        return candidate
    return None


def _question_observation_time(
    definition: OntologyDefinition, plan: QuestionPlan, reference_time: datetime
) -> datetime:
    if plan.as_of is None:
        return reference_time
    function = definition.functions.get(plan.function_id)
    metric = definition.metrics.get(plan.metric_id or (function.metric if function else None))
    timezone = ZoneInfo(metric.timezone) if metric else reference_time.tzinfo
    chinese_date = re.fullmatch(_CHINESE_DATE, plan.as_of)
    if chinese_date:
        return datetime(*map(int, chinese_date.groups()), tzinfo=timezone)
    value = datetime.fromisoformat(plan.as_of.upper())
    return value.replace(tzinfo=timezone) if value.tzinfo is None else value.astimezone(timezone)


def grounded_citation(
    preview: ChunkPreview,
    text: str,
    *,
    object_type: str,
    business_key: str,
    relation_id: str | None = None,
) -> EvidenceSpan | None:
    key = _key_pattern(business_key)
    for entity in preview.entities:
        span = entity.evidence
        if entity.object_type != object_type or not span_matches(text, span):
            continue
        if entity.key_fields:
            extracted = entity.business_key
            if len(entity.key_fields) != 1:
                continue
            if extracted is not None:
                if str(next(iter(extracted.values()))).casefold() != business_key.casefold():
                    continue
                matched = next(
                    (
                        item.evidence
                        for item in entity.attributes[entity.key_fields[0]]
                        if key.search(item.evidence.quote) and span_matches(text, item.evidence)
                    ),
                    None,
                )
                if matched is not None:
                    span = matched
                elif not key.search(span.quote):
                    continue
            elif not (re.fullmatch(r"[A-Za-z0-9_-]*[0-9][A-Za-z0-9_-]*", business_key) and key.search(entity.name)):
                continue
        elif not key.search(entity.name):
            continue
        if not key.search(span.quote):
            continue
        if relation_id is not None:
            match = next(
                (
                    relation.evidence
                    for relation in preview.relations
                    if relation.predicate == relation_id
                    and entity.id in {relation.subject_id, relation.object_id}
                    and span_matches(text, relation.evidence)
                ),
                None,
            )
            if match is not None:
                return match
        else:
            start, end = max(0, span.start_char - 160), min(len(text), span.end_char + 300)
            return EvidenceSpan(quote=text[start:end], start_char=start, end_char=end, source="quote")
    return None


def _legacy_applicability(doc: Document, observed_at: datetime) -> Literal["applicable", "outside_window", "pending"]:
    metadata = doc.doc_metadata or {}
    for key, after in (("effective_at", False), ("expires_at", True)):
        value = metadata.get(key)
        if value is None:
            continue
        try:
            boundary = datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return "pending"
        if boundary.tzinfo is None:
            boundary = boundary.replace(tzinfo=observed_at.tzinfo)
        if (after and observed_at >= boundary) or (not after and observed_at < boundary):
            return "outside_window"
    return "applicable" if metadata.get("effective_at") else "pending"


@dataclass(frozen=True)
class _CitationSource:
    preview: ChunkPreview
    chunk: DocumentChunk
    filename: str
    pipeline_hash: str
    applicability: Literal["applicable", "pending"]
    metadata: dict[str, list[Fact]]

    def cite(self, span: EvidenceSpan) -> OntologyCitation:
        return OntologyCitation(
            document_id=self.preview.document_id,
            filename=self.filename,
            pipeline_hash=self.pipeline_hash,
            chunk_id=self.chunk.id,
            page=self.chunk.page_number,
            evidence=span,
            applicability=self.applicability,
            metadata=self.metadata,
        )


def _citation_sources(
    db: Session,
    rows: Iterable[Row[tuple[EnterpriseOntologyDocument, Document]]],
    definition: OntologyDefinition,
    observed_at: datetime,
) -> Iterator[_CitationSource]:
    for row, document in rows:
        previews = current_document_previews(db, row, document)
        if not previews:
            continue
        metadata = read_document_metadata(definition, [preview for preview, _chunk in previews])
        applicability = (
            document_applicability(metadata, observed_at)
            if {"effective_at", "expires_at"} & metadata.keys()
            else _legacy_applicability(document, observed_at)
        )
        if applicability == "outside_window":
            continue
        confirmed = {
            key: [value.value for value in field.confirmed] for key, field in metadata.items() if field.confirmed
        }
        for preview, chunk in previews:
            yield _CitationSource(preview, chunk, document.filename, row.pipeline_hash, applicability, confirmed)


def _entity_identity(entity: PreviewEntity, key_fields: list[str]) -> tuple[Fact, ...] | None:
    key = entity.business_key
    if key is None or not key.keys() >= set(key_fields):
        return None
    return tuple(key[field] for field in key_fields)


def _path_citations(
    sources: Iterable[_CitationSource],
    definition: OntologyDefinition,
    *,
    path: list[str],
    object_type: str,
    business_key: str,
) -> tuple[list[OntologyCitation], str | None]:
    object_types = [object_type]
    for predicate in path:
        relation = definition.relations.get(predicate)
        if relation is None or relation.source_type != object_types[-1]:
            return [], "关系路径的方向或对象类型不符合已发布本体"
        object_types.append(relation.target_type)
    root = definition.object_types[object_type]
    if len(root.key) != 1:
        return [], "关系路径查询需要一个单字段起点主键"
    try:
        root_identity = (root.properties[root.key[0]].parse(business_key),)
    except ValueError:
        return [], "起点主键与已发布本体的属性类型不符"

    key_fields = [definition.object_types[name].key for name in object_types]
    steps_by_relation: dict[str, list[int]] = defaultdict(list)
    for step, predicate in enumerate(path):
        steps_by_relation[predicate].append(step)
    edges: list[dict[tuple[Fact, ...], list[tuple[tuple[Fact, ...], _CitationSource, PreviewRelation]]]] = [
        defaultdict(list) for _ in path
    ]
    for source in sources:
        if not source.preview.relations:
            continue
        entities = {item.id: item for item in source.preview.entities}
        for edge in source.preview.relations:
            subject, target = entities[edge.subject_id], entities[edge.object_id]
            for step in steps_by_relation.get(edge.predicate, ()):
                if (subject.object_type, target.object_type) != (object_types[step], object_types[step + 1]):
                    continue
                subject_key = _entity_identity(subject, key_fields[step])
                # The terminal mention has original evidence and does not participate in another join.
                target_key = () if step + 1 == len(path) else _entity_identity(target, key_fields[step + 1])
                if subject_key is not None and target_key is not None and (step > 0 or subject_key == root_identity):
                    edges[step][subject_key].append((target_key, source, edge))

    def follow(
        step: int, identity: tuple[Fact, ...], used: set[tuple[UUID, str, str, str]]
    ) -> list[OntologyCitation] | None:
        if step == len(path):
            return []
        for target_key, source, edge in edges[step].get(identity, ()):
            marker = (source.chunk.id, edge.predicate, edge.subject_id, edge.object_id)
            if marker not in used:
                tail = follow(step + 1, target_key, used | {marker})
                if tail is not None:
                    return [source.cite(edge.evidence), *tail]
        return None

    return follow(0, root_identity, set()) or [], None


def _document_citations(sources: Iterable[_CitationSource], *, confirmed_only: bool) -> list[OntologyCitation]:
    citations = []
    for source in sources:
        if confirmed_only and source.applicability != "applicable":
            continue
        text = source.chunk.content
        citations.append(source.cite(EvidenceSpan(quote=text, start_char=0, end_char=len(text), source="quote")))
        if len(citations) == 8:
            break
    return citations


def read_ontology_citations(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    version_id: UUID,
    request: OntologyQuestion,
    plan: QuestionPlan,
    definition: OntologyDefinition,
    observed_at: datetime,
    require_active: bool = True,
) -> tuple[list[OntologyCitation], list[str]]:
    concept_sources = {source for name in plan.concept_ids for source in definition.concepts[name].sources}
    query_sources = concept_sources | {
        source for query_id in plan.query_ids for source in definition.named_queries[query_id].sources
    }
    if not query_sources and (not plan.business_key or not plan.object_type):
        return [], ["请选择明确的业务对象"]
    datasets = list(dict.fromkeys(request.dataset_ids))
    document_ids: set[UUID] = set()
    unavailable: list[str] = []
    for dataset_id in datasets:
        try:
            assert_dataset_readable(db, get_dataset(db, tenant_id, dataset_id), account_id)
        except HTTPException as exc:
            if exc.status_code not in {403, 404}:
                raise
            unavailable.append("知识库不可读")
            continue
        if require_active and active_version_id(db, tenant_id, dataset_id) != version_id:
            unavailable.append("知识库的本体版本不可用")
            continue
        document_ids.update(list_accessible_document_ids(db, tenant_id, account_id, dataset_id=dataset_id, limit=None))
    if request.document_ids is not None:
        document_ids.intersection_update(request.document_ids)
    if not document_ids:
        return [], unavailable
    statement = (
        select(EnterpriseOntologyDocument, Document)
        .join(Document, Document.id == EnterpriseOntologyDocument.document_id)
        .where(
            EnterpriseOntologyDocument.tenant_id == tenant_id,
            EnterpriseOntologyDocument.version_id == version_id,
            EnterpriseOntologyDocument.document_id.in_(document_ids),
            Document.tenant_id == tenant_id,
            Document.archived_at.is_(None),
        )
        .order_by(Document.updated_at.desc())
    )
    if plan.relation_path is not None:
        statement = statement.order_by(Document.id)
    metric = definition.metrics.get(plan.metric_id)
    document_time = observed_at.astimezone(ZoneInfo(metric.timezone)) if metric else observed_at
    confirmed_only = _CONFIRMED_POLICY_REQUEST.search(request.question) is not None
    if not plan.business_key or not plan.object_type:
        rows = db.execute(statement.where(EnterpriseOntologyDocument.document_id.in_(query_sources)))
        sources = _citation_sources(db, rows, definition, document_time)
        return _document_citations(sources, confirmed_only=confirmed_only), unavailable

    concept_citations = []
    if concept_sources:
        rows = db.execute(statement.where(EnterpriseOntologyDocument.document_id.in_(concept_sources)))
        concept_citations = _document_citations(
            _citation_sources(db, rows, definition, document_time), confirmed_only=confirmed_only
        )
    rows = db.execute(statement)
    sources = _citation_sources(db, rows, definition, document_time)
    if confirmed_only:
        sources = (source for source in sources if source.applicability == "applicable")
    if plan.relation_path is not None:
        citations, issue = _path_citations(
            sources, definition, path=plan.relation_path, object_type=plan.object_type, business_key=plan.business_key
        )
        if issue is not None:
            unavailable.append(issue)
        return [*concept_citations, *citations], unavailable

    citations = []
    seen: set[UUID] = set()
    relation_id = plan.relation_id if not (plan.metric_id or plan.function_id) else None
    for source in sources:
        if source.chunk.id in seen:
            continue
        evidence = grounded_citation(
            source.preview,
            source.chunk.content,
            object_type=plan.object_type,
            business_key=plan.business_key,
            relation_id=relation_id if relation_id in definition.relations else None,
        )
        if evidence is not None:
            seen.add(source.chunk.id)
            citations.append(source.cite(evidence))
            if len(citations) >= 8:
                break
    return [*concept_citations, *citations], unavailable


async def plan_question(
    definition: OntologyDefinition, request: OntologyQuestion, llm_client: BaseLLMClient
) -> QuestionPlan:
    explicit_as_of = _grounded_as_of(request.question, None)
    concept_ids = [
        concept_id
        for concept_id, concept in definition.concepts.items()
        if any(phrase in request.question for phrase in (concept.label, *concept.aliases) if phrase)
    ]
    names_objects = any(
        phrase in request.question
        for object_id, definition_object in definition.object_types.items()
        for phrase in (object_id, definition_object.label, *definition_object.aliases)
        if phrase
    )
    names_query = any(
        phrase in request.question
        for query_id, query in definition.named_queries.items()
        for phrase in (query_id, query.label)
    )
    names_relation_or_rule = any(
        _key_pattern(phrase).search(request.question)
        for catalog in (definition.relations, definition.rules)
        for item_id, item in catalog.items()
        for phrase in (item_id, item.label)
        if phrase
    )
    if (
        concept_ids
        and _CONCEPT_POLICY_REQUEST.search(request.question)
        and not _CONCEPT_STRUCTURED_REQUEST.search(request.question)
        and not _BUSINESS_IDENTIFIER.search(request.question)
        and not _COUNT_REQUEST.search(request.question)
        and not asks_for_ontology_metric(definition, request.question)
        and _explicit_subject(definition, request.question) is None
        and not names_objects
        and not names_query
        and not names_relation_or_rule
        and not _ACTION_REQUEST.search(request.question)
    ):
        return QuestionPlan(concept_ids=concept_ids, include_documents=True, as_of=explicit_as_of)
    catalog = {
        "object_types": {
            name: {
                "label": value.label or name,
                "business_key_fields": value.key,
                "business_key_prefix": value.key_prefix,
                "display_property": value.display_property or ("name" if "name" in value.properties else None),
                "properties": {
                    field: prop.model_dump(include={"type", "label", "enum"}, exclude_defaults=True)
                    for field, prop in value.properties.items()
                },
            }
            for name, value in definition.object_types.items()
        },
        "metrics": {
            name: {
                **metric.model_dump(exclude={"required_filters"}, exclude_defaults=True),
                "dimension_labels": {
                    field: definition.object_types[metric.object_type].properties[field].label or field
                    for field in metric.dimensions
                },
            }
            for name, metric in definition.metrics.items()
        },
        "named_queries": {
            name: query.model_dump(exclude={"sql", "sources"}, exclude_defaults=True)
            for name, query in definition.named_queries.items()
        },
        "concepts": {
            name: concept.model_dump(exclude={"sources"}, exclude_defaults=True)
            for name, concept in definition.concepts.items()
        },
        "rules": {key: item.model_dump(exclude_defaults=True) for key, item in definition.rules.items()},
        "relations": {
            key: item.model_dump(by_alias=True, exclude_defaults=True) for key, item in definition.relations.items()
        },
        "functions": {key: item.model_dump(exclude_defaults=True) for key, item in definition.functions.items()},
        "actions": {
            key: {"object_type": item.object_type, "label": item.label, "parameters": item.model_dump()["parameters"]}
            for key, item in definition.actions.items()
        },
    }
    messages = [
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=(
                "Map the question to this enterprise ontology. Return JSON only. "
                "Use recent user messages to resolve follow-up identifiers, never invent an identifier. "
                "For each explicitly requested metric, fill metric_ids; do not ask the user to choose when "
                "they need several metrics together. metric_candidates is only for genuine ambiguity. "
                "Prefer declared named_queries for their documented business calculations. Select relevant query_ids "
                "and query_parameters keyed by query ID. Use only user-provided parameter values. "
                "Preserve every user-specified filter using its declared property and vocabulary. "
                "Never replace a requested subset with an unfiltered total. "
                "Copy timestamp parameters with their original precision and timezone; do not add seconds or an offset. "
                "For hypothetical inputs, select a declared parameterized calculation rather than aggregating "
                "unrelated records. Do not select database totals merely because they have similar field names. "
                "A parameter ending in percent takes the explicit percentage number, not a fraction. "
                "Omit missing optional parameters. Copy complete identifiers, including their prefix. "
                "A business identifier and a display name are different. Never invent an identifier by adding "
                "a key prefix to a display name. If only a name is provided, copy that name to the object-bound "
                "parameter and object_name so the authorized lookup can resolve its actual identifier. "
                "Never substitute an object key for an unrelated query parameter. "
                "For the same query with different requested groups, provide a list of parameter objects under "
                "that query ID. Do not choose just one group or concatenate group values into a scalar. "
                'Exact example: {"query_ids":["total"],"query_parameters":{"total":{"id":"PO-1"}}}. '
                'Multiple groups: {"query_ids":["total"],"query_parameters":{"total":[{"id":"PO-1"},{"id":"PO-2"}]}}. '
                "Select only relevant queries, leave unrelated rules/metrics unset. "
                "Select relevant concept_ids to retrieve their published source policies, including pure policy "
                "questions without a business object. A concept selects evidence, not a calculation or an action. "
                "Do not invent a business key or query merely to retrieve a concept's policy. "
                "Select only configured metric IDs. Use only the metric's allowed_filters, with values from the user. "
                "For grouping or breakdown requests, use metric_query.group_by with the declared dimension IDs. "
                "A grouped dimension is not a request to look up one object. "
                "Omit filters without a user-specified value, including dimensions that are only used for grouping. "
                "Set object_type to the type whose business key the user names (not the type being counted). "
                "For example, an equipment identifier stays equipment when counting its work orders. "
                "Copy the exact identifier to business_key. If the user names an object by its display name "
                "without a business identifier, fill object_name and keep business_key null. "
                "Preserve explicit location or other object qualifiers in object_filters using declared property IDs "
                "and literal values from the user. A name plus its qualifiers must be resolved together. "
                "Return metric_candidates when multiple configured metrics are plausible and the user did not specify one. "
                "Set include_documents for requests asking for a document, source policy, quote or original text. "
                "Set include_object only when the user explicitly asks for the named object's own attributes. "
                "Leave it false when the user asks which other object is linked by a relation, even when quoting evidence. "
                "Set relation_id to a declared relation for listing related objects from the named identifier. "
                "Keep the named identifier's object type even when traversing the relation in reverse. "
                "For a requested path of two to four hops, set relation_path to the declared relation IDs in order. "
                "Both hops must go from the declared source type to the target type. Omit relation_id for a path. "
                "Select rule_id for a request to evaluate one declared rule about a specific object. "
                "Select function_id only when the user asks to call a declared function by name. "
                "For a metric query, select metric_id even if a function wraps that metric. "
                "For an explicit write request, propose a declared action_id, exact object identifier and "
                "action_parameters the user supplied. Copy textual values verbatim and omit missing parameters. "
                "Leave action_id unset for explanations, read-only checks, or requests to keep the object unchanged. "
                "A user-requested preview counts as an action proposal. "
                "Use metric_period=current_month for 本月/this month and omit start/end. "
                "Use ISO datetimes in the metric timezone for explicit date ranges. Omit metric_query.observed_at. "
                "For a requested period comparison, set metric_query.start and end for the newer interval and "
                "metric_query.comparison with start and end for the earlier interval, without grouping. "
                "For an explicit historical as-of time (截至 or as of), copy the user's date or timestamp "
                "verbatim to as_of. An as-of time is separate from the metric window. "
                "Use metric_query.historical_state only when the user asks what the status was at a past timestamp. "
                f"Observation time: {request.observed_at.isoformat()}\n"
                + json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
            ),
        ),
        *request.history,
        LLMMessage(role=LLMRole.USER, content=request.question),
    ]
    try:
        async with asyncio.timeout(_PLANNER_TIMEOUT_SECONDS):
            plan = await _request_question_plan(llm_client, messages, definition=definition, request=request)
    except TimeoutError as exc:
        raise OntologyPlannerTimeoutError() from exc
    plan.as_of = explicit_as_of or _grounded_as_of(request.question, plan.as_of)
    for field in ("rule_id", "metric_id", "function_id"):
        selected = getattr(plan, field)
        if selected in definition.named_queries:
            plan.query_ids = list(dict.fromkeys([*plan.query_ids, selected]))
            setattr(plan, field, None)
    if plan.as_of is None and plan.metric_query is not None and _AS_OF_NOW.search(request.question):
        plan.metric_query.historical_state = False
    explicit_subject = _explicit_subject(definition, request.question)
    if explicit_subject:
        plan.object_type, plan.business_key = explicit_subject
        plan.object_name = None
    for field, catalog in (
        ("relation_id", definition.relations),
        ("rule_id", definition.rules),
        ("function_id", definition.functions),
        ("metric_id", definition.metrics),
    ):
        explicit = [key for key in catalog if _key_pattern(key).search(request.question)]
        if len(explicit) == 1:
            setattr(plan, field, explicit[0])
    if _ACTION_PREVIEW_DECLINED.search(request.question):
        plan.action_id = None
        plan.action_parameters = {}
    action = definition.actions.get(plan.action_id)
    if action is not None:
        parameters = {}
        for name, value in plan.action_parameters.items():
            parameter = action.parameters.get(name)
            if parameter is None:
                continue
            if parameter.type == "string" and (
                not isinstance(value, str) or not value.strip() or not _key_pattern(value).search(request.question)
            ):
                continue
            parameters[name] = value
        plan.action_parameters = parameters
    function = definition.functions.get(plan.function_id)
    if function and not (plan.rule_id or plan.action_id):
        candidates = {metric_id for metric_id in plan.metric_candidates if metric_id in definition.metrics}
        names = (plan.function_id, function.label)
        if (
            candidates == {function.metric}
            and plan.metric_id in (None, function.metric)
            and not any(name and _key_pattern(name).search(request.question) for name in names)
        ):
            plan.metric_id = function.metric
            plan.function_id = None
    user_context = "\n".join(
        [message.content for message in request.history if message.role == LLMRole.USER] + [request.question]
    )
    if plan.business_key and not _key_pattern(plan.business_key).search(user_context):
        plan.business_key = None
    if plan.object_type in definition.object_types and not (plan.business_key or plan.object_name):
        object_definition = definition.object_types[plan.object_type]
        name_property = object_definition.display_property or "name"
        name = plan.object_filters.get(name_property)
        if name_property in object_definition.properties and isinstance(name, str):
            plan.object_name = name
            del plan.object_filters[name_property]
    if plan.object_name and plan.object_name not in user_context:
        plan.object_name = None
    if plan.object_type not in definition.object_types or not (plan.business_key or plan.object_name):
        plan.object_type = None
        plan.business_key = None
        plan.object_name = None
        plan.object_filters = {}
    for name, value in plan.object_filters.items():
        prop = definition.object_types[plan.object_type].properties.get(name)
        if prop is None or prop.multiple or not _key_pattern(str(value)).search(user_context):
            raise InvalidOntologyPlanError()
        try:
            prop.parse(value)
        except ValueError as exc:
            raise InvalidOntologyPlanError() from exc
    if plan.business_key and plan.metric_query is not None and not _GROUP_REQUEST.search(request.question):
        plan.metric_query.group_by = [
            field for field in plan.metric_query.group_by if plan.metric_query.filters.get(field) != plan.business_key
        ]
    if plan.rule_id and (
        plan.rule_id not in definition.rules or definition.rules[plan.rule_id].object_type != plan.object_type
    ):
        plan.rule_id = None
    if _POLICY_VERSION_REQUEST.search(request.question) or _CONFIRMED_POLICY_REQUEST.search(request.question):
        plan.include_documents = True
    if plan.relation_path is not None:
        plan.relation_id = None
        plan.include_documents = True
    elif plan.relation_id in definition.relations and plan.relation_id not in definition.relation_bindings:
        plan.include_documents = True
    return plan


def _validate_query_parameters(definition: OntologyDefinition, request: OntologyQuestion, plan: QuestionPlan) -> None:
    if set(plan.concept_ids) - definition.concepts.keys():
        raise InvalidOntologyPlanError()
    referenced = set(plan.query_ids) | plan.query_parameters.keys()
    if referenced - definition.named_queries.keys():
        raise InvalidOntologyPlanError()
    user_context = "\n".join(
        [message.content for message in request.history if message.role == LLMRole.USER] + [request.question]
    )
    normalized = re.sub(
        _CHINESE_DATE,
        lambda match: f"{int(match[1]):04}-{int(match[2]):02}-{int(match[3]):02}",
        user_context,
    )
    normalized = re.sub(
        r"([0-9]{4})年([0-9]{1,2})月",
        lambda match: f"{int(match[1]):04}-{int(match[2]):02}",
        normalized,
    )
    for query_id in plan.query_parameters:
        for parameters in plan.parameter_sets(query_id):
            for name, value in parameters.items():
                if not isinstance(value, str):
                    continue
                parameter = definition.named_queries[query_id].parameters.get(name)
                if value in user_context:
                    if (
                        parameter is not None
                        and parameter.object_type is not None
                        and not _key_pattern(value).search(user_context)
                    ):
                        raise InvalidOntologyPlanError()
                    continue
                if value not in normalized and not (
                    re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?", value)
                    and value.replace("T", "") in normalized.replace(" ", "")
                ):
                    raise InvalidOntologyPlanError()
    for query_id in plan.query_ids:
        configured = definition.named_queries[query_id]
        for name, parameter in configured.parameters.items():
            requested_values = [value for value in parameter.enum if _key_pattern(value).search(user_context)]
            if requested_values and any(
                parameters.get(name) not in requested_values for parameters in plan.parameter_sets(query_id)
            ):
                raise InvalidOntologyPlanError()


async def _request_question_plan(
    llm_client: BaseLLMClient,
    messages: list[LLMMessage],
    *,
    definition: OntologyDefinition,
    request: OntologyQuestion,
) -> QuestionPlan:
    schema = QuestionPlan.model_json_schema()
    try:
        plan = QuestionPlan.model_validate(
            await llm_client.chat_with_schema(messages, response_schema=schema, temperature=0.1)
        )
        _validate_query_parameters(definition, request, plan)
        return plan
    except (ValueError, InvalidOntologyPlanError) as error:
        if isinstance(error, ValidationError):
            invalid = ", ".join(".".join(map(str, item["loc"])) for item in error.errors(include_input=False))
        elif isinstance(error, InvalidOntologyPlanError):
            invalid = (
                "concept_ids/query_ids must be declared; preserve explicit enum filters and copy user values "
                "without adding a timezone"
            )
        else:
            invalid = "JSON object"
    messages.insert(
        1,
        LLMMessage(
            role=LLMRole.SYSTEM,
            content=f"Correct these invalid fields: {invalid}. Omit optional fields you cannot fill. Return JSON only.",
        ),
    )
    try:
        plan = QuestionPlan.model_validate(
            await llm_client.chat_with_schema(messages, response_schema=schema, temperature=0)
        )
        _validate_query_parameters(definition, request, plan)
        return plan
    except (ValueError, InvalidOntologyPlanError) as exc:
        raise InvalidOntologyPlanError() from exc


def _planned_metric_query(
    definition: OntologyDefinition, metric_id: str, plan: QuestionPlan, observed_at: datetime
) -> MetricQuery:
    metric = definition.metrics[metric_id]
    query = plan.metric_query or MetricQuery()
    filters = {
        key: value
        for key, value in query.filters.items()
        if key not in metric.required_filters or metric.required_filters[key] != value
    }
    start, end = query.start, query.end
    if plan.metric_period == "current_month":
        start = observed_at.astimezone(ZoneInfo(metric.timezone)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        next_month = start.month % 12 + 1
        end = start.replace(year=start.year + int(next_month == 1), month=next_month)
    return MetricQuery(
        filters=filters,
        group_by=query.group_by,
        start=start,
        end=end,
        observed_at=observed_at.astimezone(UTC) if plan.as_of is not None else observed_at,
        historical_state=plan.as_of is not None or query.historical_state,
        comparison=query.comparison,
    )


def _scope_metric_to_object(
    db: Session,
    definition: OntologyDefinition,
    metric_id: str,
    plan: QuestionPlan,
    query: MetricQuery,
    *,
    tenant_id: UUID,
    account_id: str,
) -> MetricQuery:
    if plan.object_type is None or plan.business_key is None:
        return query
    metric = definition.metrics[metric_id]
    key = _planned_key(definition, plan)
    [key_field] = key
    if metric.object_type == plan.object_type:
        field = key_field
    else:
        source = primary_binding(definition, metric.object_type)
        target = primary_binding(definition, plan.object_type)
        target_key = target.columns[key_field].column
        join_columns = set()
        for name, mapping in definition.relation_bindings.items():
            rel = definition.relations[name]
            if mapping.bridge_asset_id is not None:
                continue
            if (rel.source_type, rel.target_type) == (metric.object_type, plan.object_type):
                own, foreign = mapping.source_columns, mapping.target_columns
            elif (rel.source_type, rel.target_type) == (plan.object_type, metric.object_type):
                own, foreign = mapping.target_columns, mapping.source_columns
            else:
                continue
            if foreign == [target_key]:
                join_columns.add(own[0])
        dimensions = {prop for prop in metric.allowed_filters if source.columns[prop].column in join_columns}
        if len(dimensions) != 1:
            raise ValueError("Metric needs an unambiguous authorized relation to the requested object")
        [field] = dimensions
    if field not in metric.allowed_filters:
        raise ValueError("Metric does not declare the requested object dimension")
    resolved = read_business_object(
        db,
        definition=definition,
        tenant_id=tenant_id,
        account_id=account_id,
        object_type=plan.object_type,
        key=key,
        properties=set(),
    )
    value = resolved.key[key_field]
    if isinstance(value, date):
        value = value.isoformat()
    return query.model_copy(update={"filters": {**query.filters, field: value}})


def _planned_key(definition: OntologyDefinition, plan: QuestionPlan) -> dict[str, Scalar]:
    if plan.object_type is None or plan.business_key is None:
        raise ValueError("An unambiguous object identity is required")
    definition_key = definition.object_types[plan.object_type].key
    if len(definition_key) != 1:
        raise ValueError("Supply all business key fields through object lookup")
    return {definition_key[0]: plan.business_key}


def _read_planned_behaviors(
    db: Session,
    result: OntologyAnswer,
    *,
    definition: OntologyDefinition,
    version_id: UUID,
    tenant_id: UUID,
    account_id: str,
    observed_at: datetime,
) -> list[str]:
    plan = result.plan
    parts = []
    if plan.rule_id:
        try:
            rule = definition.rules[plan.rule_id]
            if rule.object_type != plan.object_type:
                raise ValueError("The rule applies to a different object type")
            result.rule = read_rule(
                db,
                definition=definition,
                tenant_id=tenant_id,
                account_id=account_id,
                version_id=version_id,
                rule_id=plan.rule_id,
                request=RuleRequest(key=_planned_key(definition, plan), observed_at=observed_at),
            )
            outcome = {"true": "成立", "false": "不成立", "unknown": "待确认"}[result.rule.outcome]
            parts.append(f"{rule.label or plan.rule_id}：{outcome}。")
        except (HTTPException, PermissionError, ValueError, FileNotFoundError, KeyError):
            result.unavailable.append("规则或对象事实不可用")
    if plan.function_id:
        try:
            function = definition.functions[plan.function_id]
            query = _scope_metric_to_object(
                db,
                definition,
                function.metric,
                plan,
                _planned_metric_query(definition, function.metric, plan, observed_at),
                tenant_id=tenant_id,
                account_id=account_id,
            )
            result.function = run_function(
                db,
                definition=definition,
                tenant_id=tenant_id,
                account_id=account_id,
                version_id=version_id,
                function_id=plan.function_id,
                request=query,
            )
            if result.function.result.complete and result.function.result.value is not None:
                parts.append(f"{function.label or plan.function_id}为 {result.function.result.value}。")
            else:
                result.unavailable.append(
                    _HISTORICAL_STATE_UNAVAILABLE
                    if result.function.result.reason == "historical_state_unavailable"
                    else "函数所需数据覆盖不足"
                )
        except (HTTPException, PermissionError, ValueError, FileNotFoundError, KeyError):
            result.unavailable.append("函数或数据来源不可用")
    return parts


async def answer_ontology_question(
    db: Session,
    *,
    definition: OntologyDefinition,
    version_id: UUID,
    tenant_id: UUID,
    account_id: str,
    request: OntologyQuestion,
    llm_client: BaseLLMClient,
    require_active: bool = True,
    documents_only: bool = False,
) -> OntologyAnswer:
    plan = await plan_question(definition, request, llm_client)
    return execute_question_plan(
        db,
        definition=definition,
        version_id=version_id,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request,
        plan=plan,
        require_active=require_active,
        documents_only=documents_only,
    )


def _grouped_metric_table(result: MetricResult, definition: OntologyDefinition, metric: MetricDefinition) -> str:
    fields = result.query.group_by
    properties = definition.object_types[metric.object_type].properties
    label = metric.label or result.metric
    heading = f"{label}（{metric.unit}）" if metric.unit else label

    def cell(value: object) -> str:
        return re.sub(r"([\\`*_\[\]~<>])", r"\\\1", str(value)) if value is not None else "未登记"

    return build_markdown_table(
        header=[*(cell(properties[field].label or field) for field in fields), cell(heading)],
        rows=[
            [
                *(cell(group.dimensions[field]) for field in fields),
                cell(group.value) if group.value is not None else "—",
            ]
            for group in result.groups or []
        ],
    )


def execute_question_plan(
    db: Session,
    *,
    definition: OntologyDefinition,
    version_id: UUID,
    tenant_id: UUID,
    account_id: str,
    request: OntologyQuestion,
    plan: QuestionPlan,
    require_active: bool = True,
    documents_only: bool = False,
) -> OntologyAnswer:
    if documents_only:
        plan = QuestionPlan(
            object_type=plan.object_type,
            business_key=plan.business_key,
            concept_ids=plan.concept_ids,
            as_of=plan.as_of,
            relation_id=plan.relation_id,
            relation_path=plan.relation_path,
            include_documents=True,
            action_id=plan.action_id,
            action_parameters=plan.action_parameters,
        )
    result = OntologyAnswer(ontology_version_id=version_id, plan=plan, answer="")
    try:
        observed_at = _question_observation_time(definition, plan, request.observed_at)
    except ValueError:
        result.unavailable = [_HISTORICAL_STATE_UNAVAILABLE]
        result.answer = _HISTORICAL_STATE_UNAVAILABLE
        return result
    result.metric_choices = list(
        dict.fromkeys(metric_id for metric_id in plan.metric_candidates if metric_id in definition.metrics)
    )
    if (
        len(result.metric_choices) > 1
        and not plan.metric_ids
        and not plan.query_ids
        and not (plan.metric_id and _key_pattern(plan.metric_id).search(request.question))
    ):
        result.answer = "请选择指标：" + "、".join(
            definition.metrics[item].label or item for item in result.metric_choices
        )
        return result
    if plan.object_type and plan.object_name and not plan.business_key:
        try:
            choices, complete = find_objects_by_name(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                definition=definition,
                object_type=plan.object_type,
                name=plan.object_name,
                filters=plan.object_filters,
            )
        except (HTTPException, PermissionError, ValueError, FileNotFoundError):
            choices, complete = [], False
        if len(choices) == 1 and complete and len(choices[0].key) == 1:
            plan = plan.model_copy(update={"business_key": str(next(iter(choices[0].key.values())))})
            result.plan = plan
        else:
            object_definition = definition.object_types[plan.object_type]
            name_field = object_definition.display_property or "name"
            choice_fields = {*object_definition.key, name_field}
            result.object_choices = [
                item.model_copy(
                    update={
                        "attributes": {key: value for key, value in item.attributes.items() if key in choice_fields}
                    }
                )
                for item in choices
            ]
            labels = [" / ".join(map(str, item.key.values())) for item in choices]
            result.answer = "请选择业务对象：" + "、".join(labels) if labels else "请提供可核验的业务主键。"
            return result
    parts = []
    for query_id in plan.query_ids:
        if query_id not in definition.named_queries:
            raise ValueError(f"Unknown ontology business query: {query_id}")
        for parameters in plan.parameter_sets(query_id):
            try:
                query_parameters = dict(parameters)
                for name, parameter in definition.named_queries[query_id].parameters.items():
                    if (
                        parameter.object_type == plan.object_type
                        and plan.business_key
                        and query_parameters.get(name) in (None, plan.object_name)
                    ):
                        query_parameters[name] = plan.business_key
                result.queries.append(
                    run_named_query(
                        db,
                        definition=definition,
                        tenant_id=tenant_id,
                        account_id=account_id,
                        query_id=query_id,
                        parameters=query_parameters,
                        document_ids=request.document_ids,
                    )
                )
            except (HTTPException, PermissionError, FileNotFoundError) as exc:
                if isinstance(exc, HTTPException) and exc.status_code not in {403, 404}:
                    raise
                result.unavailable.append(f"{definition.named_queries[query_id].label}：无法访问查询数据来源")
            except ValueError as exc:
                result.unavailable.append(f"{definition.named_queries[query_id].label}：{exc}")
    for metric_id in dict.fromkeys(plan.metric_ids):
        if metric_id == plan.metric_id:
            continue
        item = execute_question_plan(
            db,
            definition=definition,
            version_id=version_id,
            tenant_id=tenant_id,
            account_id=account_id,
            request=request,
            require_active=require_active,
            plan=QuestionPlan(
                metric_id=metric_id,
                metric_query=plan.metric_query,
                metric_period=plan.metric_period,
                object_type=plan.object_type,
                business_key=plan.business_key,
                as_of=plan.as_of,
            ),
        )
        if item.metric is not None:
            result.metrics.append(item.metric)
        result.unavailable.extend(item.unavailable)
        parts.append(item.answer)
    if plan.metric_id is not None:
        try:
            metric_query = _planned_metric_query(definition, plan.metric_id, plan, observed_at)
            metric_query = _scope_metric_to_object(
                db,
                definition,
                plan.metric_id,
                plan,
                metric_query,
                tenant_id=tenant_id,
                account_id=account_id,
            )
            result.metric = evaluate_snapshot_metric(
                db,
                definition=definition,
                metric_id=plan.metric_id,
                query=metric_query,
                tenant_id=tenant_id,
                account_id=account_id,
            )
            configured = definition.metrics[plan.metric_id]
            label = configured.label or plan.metric_id
            prefix = "" if result.metric.complete else "在当前数据覆盖范围内，"
            if result.metric.groups:
                parts.append(f"{prefix}{label}的分组结果如下。")
                parts.append(_grouped_metric_table(result.metric, definition, configured))
                if result.metric.reason == "group_limit_reached":
                    parts.append("分组结果已达到单次返回上限。")
            elif result.metric.groups == [] and result.metric.complete:
                parts.append(f"{label}在当前授权和筛选条件下没有分组。")
            elif result.metric.value is None:
                result.unavailable.append(
                    _HISTORICAL_STATE_UNAVAILABLE
                    if result.metric.reason == "historical_state_unavailable"
                    else (
                        "除数为零，无法计算比例"
                        if result.metric.reason == "zero_formula_denominator"
                        else "指标值缺少可用数据"
                    )
                )
            else:
                parts.append(f"{prefix}{label}为 {result.metric.value}{configured.unit or ''}。")
            comparison = result.metric.comparison
            if comparison is not None:
                if comparison.change is None:
                    result.unavailable.append("对比期间缺少完整可用数据")
                else:
                    parts.append(f"对比期为 {comparison.value}{configured.unit or ''}，变化 {comparison.change:+}。")
                    if comparison.change_percent is not None:
                        parts.append(f"变化率 {comparison.change_percent:+.2f}%。")
        except EdoSourceError as exc:
            result.unavailable.append(
                "EDO 工作修订已变化，数据绑定待复核" if exc.code == "edo_revision_drift" else "EDO 数据来源不可用"
            )
        except (HTTPException, PermissionError, ValueError, FileNotFoundError, KeyError):
            result.unavailable.append("指标或数据来源不可用")
    if plan.include_object:
        try:
            key = _planned_key(definition, plan)
            result.object = read_business_object(
                db,
                definition=definition,
                tenant_id=tenant_id,
                account_id=account_id,
                object_type=plan.object_type,
                key=key,
            )
            parts.append("，".join(f"{prop}：{value}" for prop, value in result.object.attributes.items()))
        except (HTTPException, PermissionError, ValueError, FileNotFoundError, KeyError):
            result.unavailable.append("对象或数据来源不可用")
    if (
        not documents_only
        and plan.relation_id
        and (plan.relation_id in definition.relation_bindings or not plan.include_documents)
    ):
        try:
            key = _planned_key(definition, plan)
            result.related = read_related_objects(
                db,
                definition=definition,
                tenant_id=tenant_id,
                account_id=account_id,
                relation_id=plan.relation_id,
                from_object=plan.object_type,
                key=key,
            )
            label = definition.relations[plan.relation_id].label or plan.relation_id
            objects = "、".join("/".join(map(str, item.key.values())) for item in result.related.objects) or "无"
            parts.append(f"{label}：{objects}" + ("" if result.related.complete else "（部分结果）"))
        except (HTTPException, PermissionError, ValueError, FileNotFoundError, KeyError):
            result.unavailable.append("关系或数据来源不可用")
    parts.extend(
        _read_planned_behaviors(
            db,
            result,
            definition=definition,
            version_id=version_id,
            tenant_id=tenant_id,
            account_id=account_id,
            observed_at=observed_at,
        )
    )
    if plan.action_id is not None:
        action = definition.actions.get(plan.action_id)
        if action is not None and action.object_type == plan.object_type and plan.business_key:
            parts.append(f"可预演动作「{action.label or plan.action_id}」，对象 {plan.business_key}。")
        else:
            result.unavailable.append("请选择有效的业务动作和对象")
    if plan.include_documents or plan.concept_ids:
        result.citations, unavailable = read_ontology_citations(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            version_id=version_id,
            request=request,
            plan=plan,
            definition=definition,
            observed_at=observed_at,
            require_active=require_active,
        )
        result.unavailable.extend(unavailable)
        if result.citations:
            if plan.relation_path is not None:
                names = [definition.relations[item].label or item for item in plan.relation_path]
                hops = ("两", "三", "四")[len(plan.relation_path) - 2]
                parts.append(f"找到一条有原文支持的{hops}跳路径。" + " → ".join(names))
            for citation in result.citations:
                page = f"第 {citation.page} 页" if citation.page is not None else "原文"
                suffix = "（适用时间待确认）" if citation.applicability == "pending" else ""
                parts.append(f"《{citation.filename}》{page}{suffix}：{citation.evidence.quote}")
            for key, field in definition.document_metadata.items():
                if not field.compare_across_documents:
                    continue
                values = {
                    tuple(sorted(str(value) for value in citation.metadata[key]))
                    for citation in result.citations
                    if citation.applicability == "applicable" and key in citation.metadata
                }
                if len(values) > 1:
                    result.conflicts.append(key)
                    parts.append(f"同时生效的文件中「{field.label or key}」存在冲突。")
        else:
            result.unavailable.append(
                f"未找到{'两' if len(plan.relation_path) == 2 else '各'}跳均有原文依据的关系路径"
                if plan.relation_path is not None
                else "未找到可核验的文档证据"
            )
    result.answer = "\n\n".join(parts + result.unavailable) or "请明确要查询的业务对象或指标。"
    return result
