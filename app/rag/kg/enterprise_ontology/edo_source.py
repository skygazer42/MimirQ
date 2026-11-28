"""Read fixed-revision EDO skill tables with the current caller's EDO credential."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from math import isfinite
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.infrastructure.config import settings
from app.rag.kg.enterprise_ontology.definition import ObjectBinding, PropertyDefinition, Scalar

_authorization: ContextVar[str | None] = ContextVar("edo_authorization", default=None)
_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]
_COLUMN_TYPES = {
    "string": {"STRING"},
    "integer": {"INTEGER"},
    "number": {"INTEGER", "DECIMAL"},
    "boolean": {"BOOLEAN"},
    "date": {"DATE"},
    "datetime": {"DATETIME"},
}
_COVERAGE_FAILURES = {
    "SKILL_DATA_LIMIT",
    "SKILL_DATA_INCOMPLETE",
    "ONTOLOGY_CAPABILITY_BUDGET_EXCEEDED",
    "RESULT_TOO_LARGE",
}


@contextmanager
def edo_authorization(authorization: str | None) -> Iterator[None]:
    token = _authorization.set(authorization)
    try:
        yield
    finally:
        _authorization.reset(token)


class EdoSourceError(HTTPException):
    def __init__(self, code: str, status_code: int = 502):
        super().__init__(status_code=status_code, detail=code)
        self.code = code


class EdoProvenance(BaseModel):
    request_id: str
    ontology_id: str
    working_revision: int
    projection_id: str | None
    source_data_ids: list[str]
    synced_at: AwareDatetime | None
    status: str
    reason_code: str | None


class _Envelope(BaseModel):
    code: str
    sub_code: str | None = Field(default=None, validation_alias="subCode")
    data: object = None


class _SkillColumn(BaseModel):
    name: _Identifier
    type: str


class _SkillTable(BaseModel):
    name: _Identifier
    kind: Literal["OBJECT", "RELATION"]
    columns: list[_SkillColumn]


class _Skill(BaseModel):
    working_revision: int = Field(validation_alias="workingRevision", ge=0, strict=True)
    tables: list[_SkillTable]


class _SqlResult(BaseModel):
    request_id: str = Field(validation_alias="requestId", min_length=1)
    status: str
    reason_code: str | None = Field(default=None, validation_alias="reasonCode")
    working_revision: int = Field(validation_alias="workingRevision", ge=0, strict=True)
    projection_id: str | None = Field(default=None, validation_alias="projectionId")
    synced_at: AwareDatetime | None = Field(default=None, validation_alias="syncedAt")
    source_data_ids: list[str] = Field(validation_alias="sourceDataIds")
    returned_count: int = Field(validation_alias="returnedCount", ge=0, strict=True)
    truncated: bool = Field(strict=True)
    data: object


class _SqlRows(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    columns: list[str]
    rows: list[dict[str, Scalar | None]]
    tables_read: list[str] = Field(validation_alias="tablesRead")
    loaded_row_count: int = Field(validation_alias="loadedRowCount", ge=0, strict=True)
    truncated: bool = Field(strict=True)


@dataclass(frozen=True)
class EdoResult:
    rows: list[tuple[Scalar | None, ...]]
    loaded_row_count: int | None
    complete: bool
    provenance: EdoProvenance


def edo_property_matches(prop: PropertyDefinition, source_type: str) -> bool:
    return not prop.multiple and source_type in _COLUMN_TYPES[prop.type]


def _request(
    method: str, url: str, authorization: str, *, params: dict[str, int] | None = None, payload: dict | None = None
) -> object:
    try:
        with httpx.Client(timeout=httpx.Timeout(65.0, connect=5.0), follow_redirects=False, trust_env=False) as client:
            response = client.request(
                method, url, headers={"Authorization": authorization}, params=params, json=payload
            )
    except httpx.TimeoutException as exc:
        raise EdoSourceError("edo_timeout", 504) from exc
    except httpx.RequestError as exc:
        raise EdoSourceError("edo_upstream_unavailable") from exc
    if response.status_code in (401, 403):
        raise EdoSourceError("edo_access_denied", 403)
    if response.status_code == 404:
        raise EdoSourceError("edo_ontology_unavailable", 404)
    try:
        envelope = _Envelope.model_validate_json(response.content)
    except ValidationError as exc:
        raise EdoSourceError("edo_invalid_response") from exc
    if envelope.sub_code == "ONTOLOGY_REVISION_CONFLICT":
        raise EdoSourceError("edo_revision_drift", 409)
    if envelope.sub_code in {"AUTH_CONTEXT_MISSING", "ONTOLOGY_ACCESS_DENIED", "auth-check-error"}:
        raise EdoSourceError("edo_access_denied", 403)
    if envelope.sub_code in {"ONTOLOGY_GRAPH_NOT_READY", "ONTOLOGY_GRAPH_STALE"}:
        raise EdoSourceError("edo_projection_unavailable", 409)
    if envelope.sub_code == "ONTOLOGY_CAPABILITY_DISABLED":
        raise EdoSourceError("edo_capability_disabled", 409)
    if not response.is_success or envelope.code != "10000":
        raise EdoSourceError("edo_upstream_unavailable")
    return envelope.data


def _sql_literal(value: Scalar) -> str:
    if isinstance(value, str):
        if "\0" in value:
            raise ValueError("EDO SQL values cannot contain NUL")
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("EDO SQL values must be finite")
    return str(value)


def _bind_sql(sql: str, parameters: tuple[Scalar, ...]) -> str:
    # EDO accepts SQL text. Prepared table and column aliases cannot contain placeholders.
    first, *rest = sql.split("?")
    return first + "".join(_sql_literal(value) + part for value, part in zip(parameters, rest, strict=True))


@dataclass(frozen=True)
class EdoTable:
    name: str
    columns: dict[str, str]
    ontology_id: str
    working_revision: int
    _url: str = field(repr=False)
    _credential: str = field(repr=False)

    def select(self, columns: list[str], sql: str, parameters: tuple[Scalar, ...] = ()) -> EdoResult:
        selected = list(dict.fromkeys(columns))
        if not 0 < len(selected) <= 50 or set(selected) - self.columns.keys():
            raise EdoSourceError("edo_columns_unavailable", 422)
        statement = _bind_sql(sql, parameters)
        if len(statement) > 16000:
            raise ValueError("EDO SQL exceeds its length limit")
        response = _request(
            "POST",
            self._url + "/sql",
            self._credential,
            payload={
                "expectedWorkingRevision": self.working_revision,
                "tables": [{"table": self.name, "columns": selected}],
                "sql": statement,
            },
        )
        try:
            result = _SqlResult.model_validate(response)
        except ValidationError as exc:
            raise EdoSourceError("edo_invalid_response") from exc
        if result.working_revision != self.working_revision or result.reason_code == "ONTOLOGY_REVISION_CONFLICT":
            raise EdoSourceError("edo_revision_drift", 409)
        if result.status == "denied":
            raise EdoSourceError("edo_access_denied", 403)
        if result.status == "not-ready" or result.reason_code == "SKILL_PROJECTION_CHANGED":
            raise EdoSourceError("edo_projection_unavailable", 409)
        if result.reason_code in {"SKILL_COLUMN_UNMAPPED", "SKILL_COLUMN_UNKNOWN", "SKILL_TABLE_UNKNOWN"}:
            raise EdoSourceError("edo_columns_unavailable", 422)
        provenance = EdoProvenance(
            request_id=result.request_id,
            ontology_id=self.ontology_id,
            working_revision=result.working_revision,
            projection_id=result.projection_id,
            source_data_ids=result.source_data_ids,
            synced_at=result.synced_at,
            status=result.status,
            reason_code=result.reason_code,
        )
        if result.reason_code in _COVERAGE_FAILURES:
            return EdoResult([], None, False, provenance)
        if result.status not in {"success", "empty", "partial"}:
            raise EdoSourceError("edo_query_unavailable")
        try:
            data = _SqlRows.model_validate(result.data)
        except ValidationError as exc:
            raise EdoSourceError("edo_invalid_response") from exc
        column_names = set(data.columns)
        if (
            data.tables_read != [self.name]
            or not result.projection_id
            or result.synced_at is None
            or not result.source_data_ids
            or len(data.columns) != len(column_names)
            or not column_names
            or result.returned_count != len(data.rows)
            or any(row.keys() != column_names for row in data.rows)
        ):
            raise EdoSourceError("edo_invalid_response")
        rows = [tuple(row[column] for column in data.columns) for row in data.rows]
        complete = not (result.truncated or data.truncated or result.status == "partial")
        return EdoResult(rows, data.loaded_row_count, complete, provenance)


def authorized_edo_table(*, tenant_id: UUID, binding: ObjectBinding) -> EdoTable:
    source = binding.edo_binding
    if source is None:
        raise ValueError("An EDO binding is required")
    authorization = _authorization.get()
    if authorization is None or not authorization.strip():
        raise EdoSourceError("edo_authorization_required", 403)
    endpoint = settings.ONTOLOGY_EDO_ENDPOINTS.get(str(tenant_id), {}).get(source.endpoint)
    if endpoint is None:
        raise EdoSourceError("edo_endpoint_unavailable", 409)
    try:
        base_url = httpx.URL(endpoint)
    except httpx.InvalidURL as exc:
        raise EdoSourceError("edo_endpoint_unavailable", 409) from exc
    if (
        not base_url.is_absolute_url
        or base_url.scheme not in {"http", "https"}
        or base_url.userinfo
        or base_url.query
        or base_url.fragment
        or source.ontology_id in {".", ".."}
    ):
        raise EdoSourceError("edo_endpoint_unavailable", 409)
    url = str(base_url).rstrip("/") + "/api/ontology/workspaces/" + quote(source.ontology_id, safe="") + "/capabilities"
    response = _request(
        "GET",
        url + "/skill",
        authorization,
        params={"expectedWorkingRevision": source.working_revision},
    )
    try:
        skill = _Skill.model_validate(response)
    except ValidationError as exc:
        raise EdoSourceError("edo_invalid_response") from exc
    if skill.working_revision != source.working_revision:
        raise EdoSourceError("edo_revision_drift", 409)
    matches = [table for table in skill.tables if table.name == source.table]
    if len(matches) != 1:
        raise EdoSourceError("edo_table_unavailable", 422)
    [table] = matches
    columns = {column.name: column.type for column in table.columns}
    if len(columns) != len(table.columns):
        raise EdoSourceError("edo_invalid_response")
    return EdoTable(table.name, columns, source.ontology_id, source.working_revision, url, authorization)
