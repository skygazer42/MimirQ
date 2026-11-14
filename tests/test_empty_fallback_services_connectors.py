import pytest
from fastapi import HTTPException
from types import SimpleNamespace
from uuid import uuid4

from app.services import db_catalog_observability
from app.services.connector_execution import confluence, db_catalog, jira, minio_bucket, url_batch
from app.services.connector_execution.plans.github_repo import _github_repo_listed_files_and_observed_paths
from app.services.connector_execution.shared.artifacts import _build_db_row_source_manifest, _normalize_connector_string_list
from app.services.connector_execution.shared.external import _build_auth_headers
from app.services.connector_execution.shared.common import _classify_connector_error


def test_confluence_attachment_consumer_requires_the_parsed_download_url():
    with pytest.raises(KeyError, match="download_url"):
        confluence._confluence_attachment_ref_skipped(
            attachment_ref={"attachment_id": "1", "filename": "notes.txt"},
        )


def test_minio_execution_plan_does_not_silently_drop_a_missing_object_name():
    with pytest.raises(KeyError, match="name"):
        minio_bucket._build_minio_bucket_execution_plan(
            run_stats={}, state={}, listed_objects=[{"token": "etag"}], include_set={""},
            max_objects=10, scope_hash="scope",
        )


@pytest.mark.parametrize("render", [jira._jira_adf_to_text, jira._jira_adf_text_node_html])
def test_jira_text_nodes_require_their_text_payload(render):
    with pytest.raises(KeyError, match="text"):
        render({"type": "text"})


def test_connector_error_reporting_keeps_a_zero_http_detail():
    code, message = _classify_connector_error(HTTPException(status_code=400, detail=0))
    assert code == "bad_request"
    assert message == "0"


@pytest.mark.parametrize("run", [None, SimpleNamespace(dataset_id=None, connector_id="postgres_catalog")])
def test_failed_catalog_telemetry_keeps_a_real_missing_dataset(run, monkeypatch):
    events = []
    monkeypatch.setattr(db_catalog_observability, "log_metrics", events.append)
    db_catalog._emit_db_catalog_sync_failed(tenant_id=uuid4(), run_id=uuid4(), run=run, exc=RuntimeError("failed"))
    assert events[0]["dataset_id"] is None
    assert events[0]["connector_id"] == (None if run is None else "postgres_catalog")


def test_failed_catalog_telemetry_exposes_an_invalid_loaded_run():
    with pytest.raises(AttributeError, match="connector_id"):
        db_catalog._emit_db_catalog_sync_failed(
            tenant_id=uuid4(), run_id=uuid4(), run=SimpleNamespace(dataset_id=None), exc=RuntimeError("failed")
        )


def test_confluence_listing_requires_the_page_identifier():
    with pytest.raises(KeyError, match="id"):
        confluence._parse_confluence_listing_page(page={"title": "Page"}, link_base="https://wiki.test", base_url="https://wiki.test")


def test_github_blob_listing_requires_its_sync_fingerprint():
    with pytest.raises(KeyError, match="sha"):
        _github_repo_listed_files_and_observed_paths(
            tree_items=[{"type": "blob", "path": "readme.md"}], tracked_paths=set(), include_set={".md"}, max_files=10
        )


def test_connector_string_lists_reject_a_nonstring_instead_of_dropping_zero():
    with pytest.raises(AttributeError):
        _normalize_connector_string_list([0])


def test_minio_listing_requires_the_sdk_object_name():
    client = SimpleNamespace(list_objects=lambda **kwargs: [SimpleNamespace()])
    with pytest.raises(AttributeError, match="object_name"):
        minio_bucket._list_minio_bucket_objects(client, bucket_name="bucket", prefix=None)


def test_url_batch_does_not_silently_drop_a_missing_required_document_id():
    with pytest.raises(ValueError, match="document_id"):
        url_batch._url_batch_document_ids(stats={}, documents=[SimpleNamespace(document_id=None)])


def test_row_snapshot_manifest_requires_the_produced_sync_token():
    with pytest.raises(KeyError, match="source_sync_token"):
        _build_db_row_source_manifest([{"source_table": "public.items"}])


@pytest.mark.parametrize("auth,missing", [
    ({"type": "cookie"}, "cookie"),
    ({"type": "bearer"}, "token"),
    ({"type": "basic", "username": "reader"}, "password"),
])
def test_active_connector_auth_requires_its_validated_credential(auth, missing):
    with pytest.raises(KeyError, match=missing):
        _build_auth_headers({"auth": auth})


@pytest.mark.parametrize("fields,principal", [
    ({"security": {"id": 0}}, "jira:policy:security-level/0"),
    ({"comment": {"comments": [{"visibility": {"type": "role", "value": 0}}]}}, "jira:role:0"),
])
def test_jira_scalar_restriction_identifier_is_not_discarded_as_missing(fields, principal):
    restricted, principals = jira._jira_issue_acl_principal_keys(
        {"fields": fields}, include_comments=True, max_comments=10
    )
    assert restricted is True
    assert principal in principals


def test_confluence_attachment_keeps_a_provided_zero_identifier():
    attachment = confluence._confluence_attachment_ref(
        {"id": 0, "title": "notes.txt", "_links": {"download": "/download/notes.txt"}},
        link_base="https://wiki.test",
    )
    assert attachment is not None
    assert attachment["attachment_id"] == "0"


def test_jira_attachment_keeps_a_provided_zero_identifier():
    attachment = jira._jira_attachment_ref({"id": 0, "content": "https://jira.test/notes.txt"})
    assert attachment is not None
    assert attachment["attachment_id"] == "0"
