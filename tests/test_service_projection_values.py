from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.connectors.configs import ConnectorConfig
from app.models.connectors.runs import ConnectorRun, ConnectorRunDocument
from app.models.documents.records import DocumentIndexChannel
from app.rag.ingestion.indexing.index_channels import document_index_channel_status
from app.services.connectors.configs import _config_out
from app.services.connectors.runs import _run_out


def _saved_config(**overrides) -> ConnectorConfig:
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "dataset_id": uuid4(),
        "connector_id": "url_batch",
        "name": "source",
        "enabled": True,
        "schedule_cron": None,
        "config": {"auth": {"type": "bearer", "token": "private-token"}},
        "state": {},
        "last_error": None,
        "last_run_at": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    values.update(overrides)
    return ConnectorConfig(**values)


def _run(**overrides) -> ConnectorRun:
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "dataset_id": uuid4(),
        "connector_id": "url_batch",
        "requested_by": "",
        "status": "completed",
        "config": {"auth": {"type": "bearer", "token": "private-token"}},
        "stats": {},
        "error_message": "",
        "task_id": "",
        "created_at": datetime.now(UTC),
        "documents": [ConnectorRunDocument(document_id=uuid4(), source_ref="", status="created")],
    }
    values.update(overrides)
    return ConnectorRun(**values)


@pytest.mark.parametrize("stored", ["", None])
def test_connector_config_preserves_optional_text_and_redacts_secrets(stored: str | None) -> None:
    result = _config_out(_saved_config(last_error=stored, schedule_cron=stored))

    assert result.last_error == stored
    assert result.schedule_cron == stored
    assert "private-token" not in result.model_dump_json()


@pytest.mark.parametrize("field", ["config", "state"])
def test_connector_config_exposes_missing_required_mappings(field: str) -> None:
    with pytest.raises(TypeError):
        _config_out(_saved_config(**{field: None}))


def test_connector_run_preserves_empty_stored_text_and_redacts_secrets() -> None:
    result = _run_out(_run())

    assert result.requested_by == ""
    assert result.error_message == ""
    assert result.task_id == ""
    assert result.documents[0].source_ref == ""
    assert "private-token" not in result.model_dump_json()


def test_connector_run_keeps_an_explicit_empty_acl_summary() -> None:
    result = _run_out(_run(), acl_summary={})

    assert result.acl_summary is not None
    assert result.acl_summary.documents_total == 0


@pytest.mark.parametrize(
    ("connector_id", "supports_retry_failed", "supports_resume"),
    [
        ("url_batch", True, True),
        ("web_crawl", True, True),
        ("minio_bucket", False, True),
        ("mysql_catalog", False, True),
        ("sqlserver_catalog", False, True),
        ("confluence_space", False, False),
        ("jira_project", False, False),
        ("github_repo", False, False),
        ("drive_files", False, False),
    ],
)
def test_connector_run_exposes_only_implemented_recovery_actions(
    connector_id: str, supports_retry_failed: bool, supports_resume: bool
) -> None:
    result = _run_out(_run(connector_id=connector_id, stats={"failed_urls": ["https://example.test/failed"]}))

    assert result.supports_retry_failed is supports_retry_failed
    assert result.supports_resume is supports_resume


def test_connector_run_without_failed_urls_does_not_offer_failed_item_retry() -> None:
    assert _run_out(_run(status="failed", stats={})).supports_retry_failed is False


@pytest.mark.parametrize("owner", ["config", "run"])
def test_connector_projection_redaction_handles_stored_padded_database_connector_ids(owner: str) -> None:
    config = {"host": "private-database", "password": "private-password", "database": "private-name"}
    if owner == "config":
        result = _config_out(_saved_config(connector_id=" mysql_catalog ", config=config))
    else:
        result = _run_out(_run(connector_id=" mysql_catalog ", config=config))

    assert result.connector_id == " mysql_catalog "
    assert "private-database" not in result.model_dump_json()
    assert "private-password" not in result.model_dump_json()
    assert "private-name" not in result.model_dump_json()


def test_connector_run_exposes_an_invalid_required_status() -> None:
    with pytest.raises(ValidationError):
        _run_out(_run(status=None))


@pytest.mark.parametrize("field", ["config", "stats"])
def test_connector_run_exposes_missing_required_mappings(field: str) -> None:
    with pytest.raises(TypeError):
        _run_out(_run(**{field: None}))


@pytest.mark.parametrize("stored", ["", None, "provider error"])
def test_index_channel_status_preserves_stored_optional_error(stored: str | None) -> None:
    row = DocumentIndexChannel(channel="vector", required=False, enabled=False, status="disabled", error=stored)

    result = document_index_channel_status(row)

    assert result == {"channel": "vector", "required": False, "enabled": False, "status": "disabled", "error": stored}
