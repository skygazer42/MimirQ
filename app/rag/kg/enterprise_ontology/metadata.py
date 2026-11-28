"""Review typed document metadata against a single set of extracted chunks."""

import re
from datetime import date, datetime, time
from math import isfinite
from typing import TYPE_CHECKING, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.rag.kg.enterprise_ontology.definition import (
    DocumentMetadataField,
    Fact,
    OntologyDefinition,
    PropertyDefinition,
    PropertyType,
    SemanticId,
)
from app.rag.kg.extraction.evidence import EvidenceSpan

if TYPE_CHECKING:
    from app.rag.kg.enterprise_ontology.preview import ChunkPreview

_CHINESE_DATE = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
_ISO_DATE_PREFIX = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:$|[T ])")


class GroundedValue(BaseModel):
    value: Fact
    value_type: PropertyType
    evidence: EvidenceSpan

    @model_validator(mode="after")
    def restore_temporal_type(self) -> Self:
        # JSON stores dates and datetimes as strings, alongside plain string properties.
        if isinstance(self.value, str):
            if self.value_type == "date":
                self.value = date.fromisoformat(self.value)
            elif self.value_type == "datetime":
                self.value = datetime.fromisoformat(self.value)
        return self


class DocumentMetadataCandidate(GroundedValue):
    id: UUID
    field: SemanticId
    chunk_id: UUID
    page: int | None
    origin: Literal["extracted", "manual"] = "extracted"
    confirmed_by: str | None = None
    confirmed_at: AwareDatetime | None = None


class DocumentMetadataStatus(BaseModel):
    state: Literal["missing", "pending", "conflict", "confirmed"]
    candidates: list[DocumentMetadataCandidate]
    confirmed: list[DocumentMetadataCandidate]


class ManualMetadataValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: UUID
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)


class DocumentMetadataReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: SemanticId
    candidate_ids: list[UUID] = Field(default_factory=list, max_length=100)
    manual_values: list[ManualMetadataValue] = Field(default_factory=list, max_length=100)


def parse_source_value(definition: PropertyDefinition, raw: str) -> Fact:
    raw = raw.strip()
    if not raw:
        raise ValueError("An evidence value must contain source text")
    if definition.type in {"date", "datetime"}:
        match = _CHINESE_DATE.fullmatch(raw)
        if match is not None:
            year, month, day = map(int, match.groups())
            raw = date(year, month, day).isoformat()
        if _ISO_DATE_PREFIX.match(raw) is None:
            raise ValueError("A temporal evidence value must contain an explicit calendar date")
    value = definition.parse(raw)
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("A numeric evidence value must be finite")
    return value


def document_metadata_candidate(
    definition: DocumentMetadataField,
    *,
    field: str,
    chunk_id: UUID,
    page: int | None,
    raw: str,
    evidence: EvidenceSpan,
    origin: Literal["extracted", "manual"] = "extracted",
) -> DocumentMetadataCandidate:
    value = parse_source_value(definition, raw)
    identifier = uuid5(
        NAMESPACE_URL, f"{chunk_id}:{field}:{definition.type}:{evidence.start_char}:{evidence.end_char}:{value}"
    )
    return DocumentMetadataCandidate(
        id=identifier,
        field=field,
        chunk_id=chunk_id,
        page=page,
        value=value,
        value_type=definition.type,
        evidence=evidence,
        origin=origin,
    )


def read_document_metadata(
    definition: OntologyDefinition, previews: list["ChunkPreview"]
) -> dict[str, DocumentMetadataStatus]:
    candidates_by_field: dict[str, list[DocumentMetadataCandidate]] = {key: [] for key in definition.document_metadata}
    for preview in previews:
        for candidate in preview.metadata_candidates:
            candidates_by_field[candidate.field].append(candidate)

    fields = {}
    for key, candidates in candidates_by_field.items():
        confirmed = [candidate for candidate in candidates if candidate.confirmed_at is not None]
        if confirmed:
            state = "confirmed"
        elif not candidates:
            state = "missing"
        elif not definition.document_metadata[key].multiple and len({candidate.value for candidate in candidates}) > 1:
            state = "conflict"
        else:
            state = "pending"
        fields[key] = DocumentMetadataStatus(state=state, candidates=candidates, confirmed=confirmed)
    return fields


def apply_metadata_review(
    definition: OntologyDefinition,
    previews: list["ChunkPreview"],
    request: DocumentMetadataReview,
    *,
    reviewed_by: str,
    reviewed_at: datetime,
) -> None:
    field = definition.document_metadata.get(request.field)
    if field is None:
        raise ValueError(f"Unknown document metadata field {request.field}")
    candidates = {
        candidate.id: candidate
        for preview in previews
        for candidate in preview.metadata_candidates
        if candidate.field == request.field
    }
    selected = set(request.candidate_ids)
    if selected - candidates.keys():
        raise ValueError("A selected metadata candidate is unavailable in the document version")
    if not field.multiple and len({candidates[candidate_id].value for candidate_id in selected}) > 1:
        raise ValueError(f"Document metadata field {request.field} accepts a single value")
    for candidate_id, candidate in candidates.items():
        confirmed = candidate_id in selected
        candidate.confirmed_by = reviewed_by if confirmed else None
        candidate.confirmed_at = reviewed_at if confirmed else None


def document_applicability(
    fields: dict[str, DocumentMetadataStatus], observed_at: datetime
) -> Literal["applicable", "outside_window", "pending"]:
    boundaries: dict[str, datetime] = {}
    for key in ("effective_at", "expires_at"):
        field = fields.get(key)
        if field is None or not field.confirmed:
            continue
        value = field.confirmed[0].value
        if isinstance(value, datetime):
            boundary = value if value.tzinfo is not None else value.replace(tzinfo=observed_at.tzinfo)
        elif isinstance(value, date):
            boundary = datetime.combine(value, time.min, tzinfo=observed_at.tzinfo)
        else:
            raise ValueError(f"Document metadata field {key} requires a date or datetime")
        boundaries[key] = boundary
    start, end = boundaries.get("effective_at"), boundaries.get("expires_at")
    if start is not None and end is not None and start >= end:
        return "pending"
    if (start is not None and observed_at < start) or (end is not None and observed_at >= end):
        return "outside_window"
    if start is None or ("expires_at" in fields and end is None):
        return "pending"
    return "applicable"
