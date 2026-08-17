from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import starlette.status as starlette_status
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.audit_log import AuditLog
from app.models.tenant_group import TenantGroup
from app.services.table_store import format_table_id

UTC = getattr(dt, "UTC", timezone.utc)
if not hasattr(dt, "UTC"):
    vars(dt)["UTC"] = UTC
if not hasattr(starlette_status, "HTTP_413_CONTENT_TOO_LARGE"):
    vars(starlette_status)["HTTP_413_CONTENT_TOO_LARGE"] = 413
if not hasattr(starlette_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    vars(starlette_status)["HTTP_422_UNPROCESSABLE_CONTENT"] = 422


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(_type, _compiler, **_kwargs) -> str:
    return "JSON"


async def _read_streaming_response(response) -> bytes:
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    return body


class _FakeQuery:
    def __init__(self, rows: list[object], *, fail_first_filter: bool = False) -> None:
        self._rows = list(rows)
        self._offset = 0
        self._limit: int | None = None
        self._fail_first_filter = fail_first_filter

    def filter(self, *_args, **_kwargs):
        if self._fail_first_filter:
            self._fail_first_filter = False
            raise RuntimeError("json filter unavailable")
        return self

    def join(self, *_args, **_kwargs):
        return self

    def distinct(self):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def offset(self, value: int):
        self._offset = int(value)
        return self

    def limit(self, value: int):
        self._limit = int(value)
        return self

    def all(self) -> list[object]:
        rows = list(self._rows)
        if self._offset:
            rows = rows[self._offset :]
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    def first(self):
        rows = self.all()
        return rows[0] if rows else None

    def yield_per(self, _value: int):
        return iter(self.all())


class _FlakyDB:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)
        self._failed = False

    def query(self, *_entities):
        fail = not self._failed
        self._failed = True
        return _FakeQuery(self._rows, fail_first_filter=fail)


class _StaticDB:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def query(self, *_entities):
        return _FakeQuery(self._rows)


def test_export_audit_logs_gzip_sanitizes_nested_sensitive_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.audit as audit_api

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[AuditLog.__table__])
    tenant_id = uuid4()
    created_at = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)

    with Session(engine) as db:
        db.add(
            AuditLog(
                id=uuid4(),
                tenant_id=tenant_id,
                actor_id="acct-1",
                action="audit.test",
                details={
                    "safe": "value",
                    "password": "secret",
                    "nested": {"token": "hidden", "visible": 7},
                },
                created_at=created_at,
            )
        )
        db.commit()

        monkeypatch.setattr(audit_api, "_ensure_admin", lambda *_a, **_k: None, raising=True)

        response = audit_api.export_audit_logs(
            filters=audit_api.AuditLogFilterParams(),
            export=audit_api.AuditLogExportParams(limit=10, gzip=True),
            tenant_id=tenant_id,
            account_id="acct-1",
            db=db,
        )

    body = asyncio.run(_read_streaming_response(response))
    payload = json.loads(gzip.decompress(body).decode("utf-8").strip())

    assert response.headers["Content-Encoding"] == "gzip"
    assert payload["details"] == {"safe": "value", "nested": {"visible": 7}}


def test_export_access_graph_json_requires_after_kind_and_emits_next_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.audit as audit_api

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[TenantGroup.__table__])
    tenant_id = uuid4()
    first_group = TenantGroup(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Alpha",
        external_id="group-alpha",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    second_group = TenantGroup(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Beta",
        external_id="group-beta",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        updated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    first_group_id = first_group.id

    with Session(engine) as db:
        db.add_all([first_group, second_group])
        db.commit()

        monkeypatch.setattr(audit_api, "_ensure_admin", lambda *_a, **_k: None, raising=True)
        monkeypatch.setattr(audit_api, "audit_log_event", lambda *_a, **_k: None, raising=True)

        with pytest.raises(audit_api.HTTPException) as exc_info:
            audit_api.export_access_graph_ndjson(
                limit=1,
                after_created_at=first_group.created_at,
                tenant_id=tenant_id,
                account_id="acct-1",
                db=db,
            )

        response = audit_api.export_access_graph_ndjson(
            limit=1,
            export_format="json",
            tenant_id=tenant_id,
            account_id="acct-1",
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "after_kind is required when using after_created_at/after_id"

    payload = json.loads(response.body.decode("utf-8"))
    next_cursor = json.loads(response.headers["X-Next-Cursor"])

    assert payload["returned"] == 1
    assert payload["items"][0]["kind"] == "group"
    assert next_cursor == {
        "after_kind": "group",
        "after_created_at": "2026-01-01T00:00:00",
        "after_id": str(first_group_id),
    }


def test_delta_sync_jira_documents_acl_fallback_updates_matching_issue_doc_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.connectors_acl as connectors_acl

    tenant_id = uuid4()
    dataset_id = uuid4()
    matching = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        archived_at=None,
        disabled_at=None,
        doc_metadata={
            "connector": {
                "connector_id": "jira_project",
                "base_url": "https://jira.example.com",
                "project_key": "ABC",
                "issue_url": "https://jira.example.com/browse/ABC-1",
            }
        },
    )
    wrong_issue = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        archived_at=None,
        disabled_at=None,
        doc_metadata={
            "connector": {
                "connector_id": "jira_project",
                "base_url": "https://jira.example.com",
                "project_key": "ABC",
                "issue_url": "https://jira.example.com/browse/ABC-2",
            }
        },
    )
    calls: list[UUID] = []

    def _apply_acl(*_args, **kwargs) -> None:
        calls.append(kwargs["doc"].id)

    monkeypatch.setattr(
        connectors_acl,
        "_leader_module",
        SimpleNamespace(_apply_document_access_from_config=_apply_acl),
        raising=True,
    )

    updated = connectors_acl._delta_sync_jira_documents_acl_by_issue_url(
        _FlakyDB([matching, wrong_issue]),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        base_url="https://jira.example.com",
        project_key="abc",
        issue_url="https://jira.example.com/browse/ABC-1",
        requested_by="acct-1",
        access={"mode": "partial_members"},
        acl_provenance={"source": "jira"},
    )

    assert updated == 1
    assert calls == [matching.id]
    assert matching.doc_metadata["acl_provenance"] == {"source": "jira"}
    assert "acl_provenance" not in wrong_issue.doc_metadata


@pytest.mark.parametrize(
    ("func_name", "doc_kind", "url_field"),
    [
        ("_soft_disable_jira_attachment_documents_missing_from_issue", "attachment", "download_url"),
        ("_soft_disable_jira_linked_artifact_documents_missing_from_issue", "linked_artifact", "artifact_url"),
    ],
)
def test_soft_disable_jira_issue_children_fallback_filters_seen_urls(
    monkeypatch: pytest.MonkeyPatch,
    func_name: str,
    doc_kind: str,
    url_field: str,
) -> None:
    import app.api.v1.connectors_acl as connectors_acl

    tenant_id = uuid4()
    dataset_id = uuid4()
    now = datetime(2026, 2, 1, tzinfo=UTC)
    keep_url = "https://jira.example.com/file/keep"
    missing_url = "https://jira.example.com/file/missing"
    rows = [
        SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            archived_at=None,
            disabled_at=None,
            doc_metadata={
                "connector": {
                    "connector_id": "jira_project",
                    "doc_kind": doc_kind,
                    "base_url": "https://jira.example.com",
                    "project_key": "ABC",
                    "issue_url": "https://jira.example.com/browse/ABC-1",
                    url_field: keep_url,
                }
            },
        ),
        SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            archived_at=None,
            disabled_at=None,
            doc_metadata={
                "connector": {
                    "connector_id": "jira_project",
                    "doc_kind": doc_kind,
                    "base_url": "https://jira.example.com",
                    "project_key": "ABC",
                    "issue_url": "https://jira.example.com/browse/ABC-1",
                    url_field: missing_url,
                }
            },
        ),
    ]

    monkeypatch.setattr(connectors_acl, "_leader_module", SimpleNamespace(_now=lambda: now), raising=True)
    disabled = getattr(connectors_acl, func_name)(
        _FlakyDB(rows),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        base_url="https://jira.example.com",
        project_key="abc",
        issue_url="https://jira.example.com/browse/ABC-1",
        **({"seen_attachment_urls": {keep_url}} if doc_kind == "attachment" else {"seen_link_urls": {keep_url}}),
    )

    assert disabled == 1
    assert rows[0].disabled_at is None
    assert rows[1].disabled_at == now


def test_soft_disable_jira_documents_missing_from_full_sync_fallback_reconciles_issue_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.connectors_jira as connectors_jira

    tenant_id = uuid4()
    dataset_id = uuid4()
    now = datetime(2026, 3, 1, tzinfo=UTC)
    seen_url = "https://jira.example.com/browse/ABC-1"
    missing_url = "https://jira.example.com/browse/ABC-2"
    rows = [
        SimpleNamespace(
            id=uuid4(),
            archived_at=None,
            disabled_at=None,
            doc_metadata={
                "connector": {
                    "connector_id": "jira_project",
                    "base_url": "https://jira.example.com",
                    "project_key": "ABC",
                    "issue_url": seen_url,
                }
            },
        ),
        SimpleNamespace(
            id=uuid4(),
            archived_at=None,
            disabled_at=None,
            doc_metadata={
                "connector": {
                    "connector_id": "jira_project",
                    "base_url": "https://jira.example.com",
                    "project_key": "ABC",
                    "issue_url": missing_url,
                }
            },
        ),
    ]

    monkeypatch.setattr(
        connectors_jira,
        "_leader_module",
        SimpleNamespace(_now=lambda: now),
        raising=False,
    )

    reconciled, disabled = connectors_jira._soft_disable_jira_documents_missing_from_full_sync(
        _FlakyDB(rows),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        base_url="https://jira.example.com",
        project_key="abc",
        seen_issue_urls={seen_url},
    )

    assert reconciled == 1
    assert disabled == 1
    assert rows[0].disabled_at is None
    assert rows[1].disabled_at == now


def test_process_jira_project_issues_tracks_progress_and_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.connectors_jira as connectors_jira

    async def _fetch_page(*_args, **_kwargs):
        return 1, [{"key": "ABC-1"}]

    async def _process_issue(*_args, **kwargs) -> None:
        kwargs["progress"]["processed"] += 1
        kwargs["observed_issue_urls"].add("https://jira.example.com/browse/ABC-1")

    monkeypatch.setattr(connectors_jira, "_jira_project_fetch_issue_page", _fetch_page, raising=True)
    monkeypatch.setattr(
        connectors_jira,
        "_leader_module",
        SimpleNamespace(
            get_http_client_pool=lambda: object(),
            _jira_project_run_cancelled=lambda *_a, **_k: False,
            _process_jira_project_issue=_process_issue,
        ),
        raising=False,
    )

    progress, observed_issue_urls, listing_complete = asyncio.run(
        connectors_jira._process_jira_project_issues(
            db=object(),
            run=SimpleNamespace(),
            run_id=uuid4(),
            tenant_id=uuid4(),
            requested_by="acct-1",
            settings_map={
                "base_url": "https://jira.example.com",
                "project_key": "ABC",
                "cursor_last_modified": "",
                "cursor_last_modified_ids": set(),
                "effective_mode": "full",
                "max_issues": 5,
                "page_size": 5,
                "include_comments": False,
                "max_comments_per_issue": 0,
                "custom_fields": [],
                "include_attachments": False,
                "max_attachments_per_issue": 0,
                "max_total_attachments": 0,
                "include_linked_artifacts": False,
                "max_linked_artifacts_per_issue": 0,
                "max_total_linked_artifacts": 0,
                "parser_backend": "auto",
                "chunk_strategy": "jira_ticket",
                "pipeline": object(),
                "access": None,
                "user_agent": None,
                "auth_headers": {},
                "search_url": "https://jira.example.com/rest/api/3/search",
                "headers": {"Authorization": "Bearer token"},
                "jql": "project = ABC",
                "source_acl_mode": "disabled",
                "source_acl_fallback_mode": "partial_members",
                "enable_source_acl": False,
            },
        )
    )

    assert progress["processed"] == 1
    assert observed_issue_urls == {"https://jira.example.com/browse/ABC-1"}
    assert listing_complete is True


def test_extract_table_assets_filters_wrong_doc_and_caps_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.dataset_tables as dataset_tables

    doc_id = uuid4()
    valid_table_id = format_table_id(document_id=doc_id, sheet_index=2)
    other_table_id = format_table_id(document_id=uuid4(), sheet_index=3)
    doc = SimpleNamespace(
        id=doc_id,
        filename="sales.csv",
        doc_metadata={
            "table_store": {
                "tables": [
                    {"table_id": "invalid"},
                    {"table_id": other_table_id},
                    {
                        "table_id": valid_table_id,
                        "sheet_index": 2,
                        "sheet_name": "Quarterly",
                        "row_count": 12,
                        "col_count": 2105,
                        "columns": [{"name": f"col_{index}", "dtype": "text"} for index in range(2105)],
                        "sample_rows": [{"secret": f"value-{index}"} for index in range(250)],
                    },
                ]
            }
        },
    )

    monkeypatch.setattr(
        dataset_tables,
        "_redact_sample_rows",
        lambda rows: [{"masked": len(rows)}],
        raising=True,
    )

    assets = dataset_tables._extract_table_assets(
        doc=doc,
        include_columns=True,
        include_sample_rows=True,
        redact_sample_rows=True,
    )

    assert [asset.table_id for asset in assets] == [valid_table_id]
    assert len(assets[0].columns) == 2000
    assert assets[0].sample_rows == [{"masked": 200}]


def test_list_dataset_tables_filters_docs_and_audits_fls_masking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.dataset_tables as dataset_tables

    dataset_id = uuid4()
    allowed_doc_id = uuid4()
    denied_doc_id = uuid4()
    allowed_doc = SimpleNamespace(
        id=allowed_doc_id,
        filename="allowed.csv",
        doc_metadata={
            "table_store": {
                "tables": [
                    {
                        "table_id": format_table_id(document_id=allowed_doc_id, sheet_index=0),
                        "columns": [{"name": "secret", "dtype": "text"}],
                        "sample_rows": [{"secret": "top-secret"}],
                    }
                ]
            }
        },
    )
    denied_doc = SimpleNamespace(
        id=denied_doc_id,
        filename="denied.csv",
        doc_metadata={"table_store": {"tables": []}},
    )
    audits: list[dict[str, object]] = []

    monkeypatch.setattr(dataset_tables.DatasetService, "get_dataset", lambda *_a, **_k: SimpleNamespace(dataset_metadata={}), raising=True)
    monkeypatch.setattr(dataset_tables.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dataset_tables.DatasetService, "ensure_member", lambda *_a, **_k: SimpleNamespace(role="member"), raising=True)
    monkeypatch.setattr(dataset_tables, "get_allowed_document_id_sets", lambda *_a, **_k: ({allowed_doc_id}, set()), raising=True)
    monkeypatch.setattr(dataset_tables, "parse_fls_policy_from_metadata", lambda *_a, **_k: {"policy": True}, raising=True)
    monkeypatch.setattr(dataset_tables, "build_fls_column_mask_map", lambda *_a, **_k: {"secret": "[MASK]"}, raising=True)
    monkeypatch.setattr(dataset_tables, "redact_row_dicts", lambda rows, **_k: [{"secret": "[MASKED]"} for _ in rows], raising=True)
    monkeypatch.setattr(dataset_tables, "_audit_fls_redaction", lambda **kwargs: audits.append(kwargs), raising=True)

    response = dataset_tables.list_dataset_tables(
        dataset_id=dataset_id,
        include_sample_rows=True,
        tenant_id=uuid4(),
        account_id="acct-1",
        db=_StaticDB([allowed_doc, denied_doc]),
    )

    assert response.total == 1
    assert response.items[0].document_id == allowed_doc_id
    assert response.items[0].sample_rows == [{"secret": "[MASKED]"}]
    assert audits[0]["details"]["table_count"] == 1


def test_get_dataset_table_masks_sample_rows_for_matching_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.dataset_tables as dataset_tables

    dataset_id = uuid4()
    document_id = uuid4()
    table_id = format_table_id(document_id=document_id, sheet_index=0)
    doc = SimpleNamespace(
        id=document_id,
        tenant_id=uuid4(),
        dataset_id=dataset_id,
        filename="table.csv",
        doc_metadata={
            "table_store": {
                "tables": [
                    {
                        "table_id": table_id,
                        "columns": [{"name": "secret", "dtype": "text"}],
                        "sample_rows": [{"secret": "value"}],
                    }
                ]
            }
        },
    )
    audits: list[dict[str, object]] = []

    monkeypatch.setattr(dataset_tables.DatasetService, "get_dataset", lambda *_a, **_k: SimpleNamespace(dataset_metadata={}), raising=True)
    monkeypatch.setattr(dataset_tables.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dataset_tables.DatasetService, "ensure_member", lambda *_a, **_k: SimpleNamespace(role="member"), raising=True)
    monkeypatch.setattr(dataset_tables, "filter_allowed_document_ids", lambda *_a, **_k: [document_id], raising=True)
    monkeypatch.setattr(dataset_tables, "parse_fls_policy_from_metadata", lambda *_a, **_k: {"policy": True}, raising=True)
    monkeypatch.setattr(dataset_tables, "build_fls_column_mask_map", lambda *_a, **_k: {"secret": "[MASK]"}, raising=True)
    monkeypatch.setattr(dataset_tables, "redact_row_dicts", lambda rows, **_k: [{"secret": "[MASKED]"} for _ in rows], raising=True)
    monkeypatch.setattr(dataset_tables, "_audit_fls_redaction", lambda **kwargs: audits.append(kwargs), raising=True)

    asset = dataset_tables.get_dataset_table(
        dataset_id=dataset_id,
        table_id=table_id,
        tenant_id=doc.tenant_id,
        account_id="acct-1",
        db=_StaticDB([doc]),
    )

    assert asset.table_id == table_id
    assert asset.sample_rows == [{"secret": "[MASKED]"}]
    assert audits[0]["details"]["table_id"] == table_id


def test_ask_dataset_table_masks_rows_before_answer_and_hides_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.dataset_tables as dataset_tables

    dataset_id = uuid4()
    document_id = uuid4()
    tenant_id = uuid4()
    table_id = format_table_id(document_id=document_id, sheet_index=1)
    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="table.csv",
        doc_metadata={
            "table_store": {
                "tables": [
                    {
                        "table_id": table_id,
                        "columns": [{"name": "secret", "dtype": "text"}],
                        "sample_rows": [{"secret": "value"}],
                        "sheet_name": "Sheet 1",
                    }
                ]
            }
        },
    )
    answer_inputs: list[dict[str, object]] = []

    monkeypatch.setattr(dataset_tables, "tag_enabled", lambda: True, raising=True)
    monkeypatch.setattr(dataset_tables.settings, "LLM_API_KEY", "key", raising=False)
    monkeypatch.setattr(dataset_tables.settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", True, raising=False)
    monkeypatch.setattr(dataset_tables.DatasetService, "get_dataset", lambda *_a, **_k: SimpleNamespace(dataset_metadata={}), raising=True)
    monkeypatch.setattr(dataset_tables.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dataset_tables.DatasetService, "ensure_member", lambda *_a, **_k: SimpleNamespace(role="member"), raising=True)
    monkeypatch.setattr(dataset_tables, "filter_allowed_document_ids", lambda *_a, **_k: [document_id], raising=True)
    monkeypatch.setattr(dataset_tables, "parse_fls_policy_from_metadata", lambda *_a, **_k: {"policy": True}, raising=True)
    monkeypatch.setattr(dataset_tables, "build_fls_column_mask_map", lambda *_a, **_k: {"secret": "[MASK]"}, raising=True)
    monkeypatch.setattr(dataset_tables, "redact_row_lists", lambda rows, **_k: [["[MASKED]"] for _ in rows], raising=True)
    monkeypatch.setattr(dataset_tables, "_audit_fls_redaction", lambda **_k: None, raising=True)
    monkeypatch.setattr(dataset_tables, "_audit_table_query", lambda **_k: None, raising=True)
    monkeypatch.setattr(
        dataset_tables,
        "generate_sql_for_table_with_metadata",
        lambda **_k: (
            "SELECT secret FROM sheet_1",
            "llm",
            {
                "schema_link": {"matched": True},
                "planner": {"sql_fingerprint": "abc123"},
                "join_provenance": [
                    {
                        "left_table": "a",
                        "left_column": "id",
                        "right_table": "b",
                        "right_column": "id",
                    }
                ],
            },
        ),
        raising=True,
    )
    monkeypatch.setattr(
        dataset_tables,
        "run_table_query",
        lambda **_k: {
            "sql": "SELECT secret FROM sheet_1",
            "columns": ["secret"],
            "rows": [["top-secret"]],
            "truncated": False,
        },
        raising=True,
    )

    def _answer_from_result(**kwargs) -> str:
        answer_inputs.append(kwargs)
        return "masked-answer"

    monkeypatch.setattr(dataset_tables, "generate_answer_from_result", _answer_from_result, raising=True)

    response = dataset_tables.ask_dataset_table(
        dataset_id=dataset_id,
        table_id=table_id,
        body=dataset_tables.TableAskRequest(question="What is the secret?", max_rows=5),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=_StaticDB([doc]),
    )

    assert answer_inputs[0]["result"]["rows"] == [["[MASKED]"]]
    assert response.answer == "masked-answer"
    assert response.sql is None
    assert response.data.sql == "<hidden>"


def test_lotus_sem_filter_dataset_table_fallback_runs_nl2sql_and_masks_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.dataset_tables as dataset_tables

    dataset_id = uuid4()
    document_id = uuid4()
    tenant_id = uuid4()
    table_id = format_table_id(document_id=document_id, sheet_index=0)
    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="table.csv",
        doc_metadata={"table_store": {"tables": []}},
    )

    monkeypatch.setattr(dataset_tables.settings, "TABLE_LOTUS_ENABLED", True, raising=False)
    monkeypatch.setattr(dataset_tables.settings, "LLM_API_KEY", "key", raising=False)
    monkeypatch.setattr(dataset_tables, "lotus_available", lambda: SimpleNamespace(ok=False, reason="missing"), raising=True)
    monkeypatch.setattr(dataset_tables, "tag_enabled", lambda: True, raising=True)
    monkeypatch.setattr(dataset_tables.DatasetService, "get_dataset", lambda *_a, **_k: SimpleNamespace(dataset_metadata={}), raising=True)
    monkeypatch.setattr(dataset_tables.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dataset_tables.DatasetService, "ensure_member", lambda *_a, **_k: SimpleNamespace(role="member"), raising=True)
    monkeypatch.setattr(dataset_tables, "filter_allowed_document_ids", lambda *_a, **_k: [document_id], raising=True)
    monkeypatch.setattr(dataset_tables, "parse_fls_policy_from_metadata", lambda *_a, **_k: {"policy": True}, raising=True)
    monkeypatch.setattr(dataset_tables, "build_fls_column_mask_map", lambda *_a, **_k: {"secret": "[MASK]"}, raising=True)
    monkeypatch.setattr(dataset_tables, "redact_row_lists", lambda rows, **_k: [["[MASKED]"] for _ in rows], raising=True)
    monkeypatch.setattr(dataset_tables, "_audit_fls_redaction", lambda **_k: None, raising=True)
    monkeypatch.setattr(dataset_tables, "generate_sql_for_table", lambda **_k: "SELECT secret FROM sheet_0", raising=True)
    monkeypatch.setattr(
        dataset_tables,
        "run_table_query",
        lambda **_k: {
            "sql": "SELECT secret FROM sheet_0",
            "columns": ["secret"],
            "rows": [["top-secret"]],
            "truncated": False,
        },
        raising=True,
    )

    response = dataset_tables.lotus_sem_filter_dataset_table(
        dataset_id=dataset_id,
        table_id=table_id,
        body=dataset_tables.LotusSemFilterRequest(user_instruction="only active rows", max_rows=5),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=_StaticDB([doc]),
    )

    assert response.sql == "SELECT secret FROM sheet_0"
    assert response.rows == [["[MASKED]"]]
