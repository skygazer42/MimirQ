from uuid import uuid4

import pytest

from app.models.connector import ConnectorRun
from app.models.document import Document
from app.services.connector_execution.confluence import _confluence_attachment_connector_metadata
from app.services.connector_execution.jira import (
    _jira_attachment_connector_metadata,
    _jira_linked_artifact_connector_metadata,
)
from app.services.connector_execution.shared.artifacts import _apply_connector_identity_metadata


@pytest.mark.parametrize("value", ["", None])
def test_confluence_attachment_preserves_supplied_page_identity(value: str | None) -> None:
    metadata = _confluence_attachment_connector_metadata(
        base_url="https://example.invalid",
        space_key="DOC",
        page_id=value,
        page_title=value,
        page_url="https://example.invalid/page",
        attachment_id="attachment-1",
        filename="sample.pdf",
        download_url="https://example.invalid/attachment",
        run_id="run-1",
        mode="all",
        ingest_method="url",
    )

    assert metadata["page_id"] == value
    assert metadata["page_title"] == value


@pytest.mark.parametrize("kind", ["attachment", "linked_artifact"])
@pytest.mark.parametrize("value", ["", None])
def test_jira_artifact_preserves_supplied_issue_identity(kind: str, value: str | None) -> None:
    parameters = {
        "base_url": "https://example.invalid",
        "project_key": "DOC",
        "issue_id": value,
        "issue_key": value,
        "issue_url": "https://example.invalid/issue",
        "run_id": "run-1",
        "mode": "all",
    }
    if kind == "attachment":
        metadata = _jira_attachment_connector_metadata(
            **parameters,
            attachment_id="attachment-1",
            filename="sample.pdf",
            download_url="https://example.invalid/file",
        )
    else:
        metadata = _jira_linked_artifact_connector_metadata(**parameters, link_url="https://example.invalid/file")

    assert metadata["issue_id"] == value
    assert metadata["issue_key"] == value


def test_connector_identity_patch_keeps_explicit_empty_values() -> None:
    document = Document(doc_metadata={"connector": {"source_ref": "old-ref", "source_id": "old-id"}})
    run = ConnectorRun(id=uuid4(), dataset_id=None, stats={})

    _apply_connector_identity_metadata(doc=document, run=run, connector_id="generic", source_ref="", source_id="")

    assert document.doc_metadata["connector"]["source_ref"] == ""
    assert document.doc_metadata["connector"]["source_id"] == ""


def test_connector_identity_patch_keeps_the_reference_length_cap() -> None:
    document = Document(doc_metadata={})
    run = ConnectorRun(id=uuid4(), dataset_id=None, stats={})

    _apply_connector_identity_metadata(doc=document, run=run, connector_id="generic", source_ref="a" * 1100)

    assert document.doc_metadata["connector"]["source_ref"] == "a" * 1000
    assert document.doc_metadata["connector"]["source_id"] == "a" * 1000


@pytest.mark.parametrize("value", [0, False])
def test_connector_identity_exposes_invalid_internal_reference_types(value) -> None:
    original = {"connector": {"source_ref": "old-ref"}}
    document = Document(doc_metadata=original)
    run = ConnectorRun(id=uuid4(), dataset_id=None, stats={})

    with pytest.raises(AttributeError):
        _apply_connector_identity_metadata(doc=document, run=run, connector_id="generic", source_ref=value)

    assert document.doc_metadata == {"connector": {"source_ref": "old-ref"}}


def test_excluded_table_diagnostics_expose_the_actual_content_type_fields() -> None:
    from app.parsing.processors.processor import DocumentProcessorService

    metadata = {"content_type": False, "doc_type_kwd": "", "page": 0}

    sample = DocumentProcessorService._table_sidecar_excluded_sample(index=0, meta=metadata)

    assert sample == {"chunk_index": 0, "page": 0, "content_type": False, "doc_type_kwd": ""}
