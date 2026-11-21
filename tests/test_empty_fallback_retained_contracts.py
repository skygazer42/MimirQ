from contextlib import nullcontext
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
import yaml
from docx import Document as DocxDocument
from langchain_core.documents import Document

from app.connectors import catalog
from app.rag.ingestion import pipeline as process_document_flow
from app.rag.ingestion.indexing import processor as processor_module
from app.rag.ingestion.indexing.support.recovery import (
    _checkpoint_matches_current_document,
    _validate_retry_cleanup_scope,
    checkpoint_stage,
    upsert_ingest_checkpoint,
)
from app.rag.ingestion.parsing.models.manifest import load_small_model_manifest
from app.rag.ingestion.parsing.output.docx_writer import render_clean_docx_bytes
from app.rag.ingestion.parsing.utils.block_schema import block_text
from app.rag.ingestion.parsing.utils.document_elements import (
    _clean_element_text,
    _normalize_string,
    normalize_document_elements,
)
from app.storage.object.runtime import (
    SOURCE_STORAGE_REGION_KEY,
    ObjectStorageRef,
    _resolve_stored_object_region,
)


@pytest.mark.parametrize("value", [0, False])
def test_element_scalar_text_preserves_provided_falsy_values(value):
    assert _clean_element_text(value) == str(value)
    assert _normalize_string(value) is None


def test_snapshot_column_names_preserve_numeric_and_boolean_labels():
    table = catalog.CatalogTableInput(
        engine="sqlserver",
        db_name="db",
        schema_name="dbo",
        table_name="table",
        table_type="table",
        comment=None,
        fingerprint="fixture",
        columns=[catalog.CatalogColumnInput(ordinal=1, name="0"), catalog.CatalogColumnInput(ordinal=2, name="False")],
    )
    snapshot = catalog._snapshot_payload(source_table="dbo.table", table=table, rows_raw=[], max_rows=10, max_cols=10)
    assert snapshot["columns"] == ["0", "False", "__row_pk_hash"]


def test_checkpoint_creation_preserves_absent_optional_fingerprints():
    checkpoint = upsert_ingest_checkpoint({}, stage="parsed", source="parser")["ingest_checkpoint"]
    assert checkpoint["pipeline_hash"] is None
    assert checkpoint["file_sha256"] is None
    assert checkpoint_stage({}) is None


@pytest.mark.parametrize("value", [0, False])
def test_invalid_checkpoint_fingerprint_does_not_match_absent_fingerprint(value):
    metadata = {
        "pipeline_hash": value,
        "ingest_checkpoint": {"version": "1", "stage": "parsed"},
    }
    assert not _checkpoint_matches_current_document(metadata, expected_stage="parsed")


@pytest.mark.parametrize("driver", [0, False])
def test_malformed_odbc_driver_cannot_select_named_default(monkeypatch, driver):
    engine = SimpleNamespace(connect=lambda: nullcontext(object()), dispose=lambda: None)
    monkeypatch.setattr(catalog, "create_engine", lambda *args, **kwargs: engine)
    with pytest.raises(AttributeError):
        with catalog._connect_catalog(
            engine_name="sqlserver",
            config={"host": "host", "database": "db", "username": "user", "password": "", "odbc_driver": driver},
        ):
            pass


def test_absent_odbc_driver_selects_existing_driver_18_default(monkeypatch):
    drivers = []
    engine = SimpleNamespace(connect=lambda: nullcontext(object()), dispose=lambda: None)

    def create(url, **kwargs):
        drivers.append(url.query["driver"])
        return engine

    monkeypatch.setattr(catalog, "create_engine", create)
    with catalog._connect_catalog(
        engine_name="sqlserver", config={"host": "host", "database": "db", "username": "user", "password": ""}
    ):
        pass
    assert drivers == ["ODBC Driver 18 for SQL Server"]


@pytest.mark.parametrize("value", [0, False])
def test_invalid_stored_object_region_is_not_treated_as_absent(value):
    with pytest.raises(AttributeError):
        _resolve_stored_object_region(
            ObjectStorageRef("minio", "bucket", "object"),
            region=None,
            document_metadata={SOURCE_STORAGE_REGION_KEY: value},
        )


def test_retry_cleanup_cannot_authorize_a_missing_pipeline_fingerprint():
    assert (
        _validate_retry_cleanup_scope({}, request={"version": "1", "scope": "document"}, document_id=UUID(int=1))
        is None
    )


@pytest.mark.parametrize("value", [0, False])
def test_element_detection_text_preserves_scalar_content(value):
    assert block_text({"text": value}) == str(value)


@pytest.mark.parametrize("value", [0, False])
def test_small_model_manifest_rejects_scalar_model_identifier(tmp_path, value):
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump({"ocr": {"default": value, "models": {value: {"kind": "onnx"}}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="Small-model default must be a nonempty string"):
        load_small_model_manifest(path)


def test_invalid_optional_visual_hint_stays_no_match_and_preserves_raw_attribute():
    elements = normalize_document_elements(
        [Document(page_content="an ordinary image", metadata={"doc_type_kwd": "image", "visual_kind": False})]
    )
    assert elements[0]["visual_kind"] is None
    assert elements[0]["attributes"]["visual_kind"] is False


def test_malformed_rollback_scope_cannot_trigger_document_wide_cleanup(monkeypatch):
    deleted = []

    class Indexer:
        def __init__(self, db):
            pass

        def delete_chunk_indexes(self, **kwargs):
            deleted.append(kwargs)

    monkeypatch.setattr(processor_module, "Indexer", Indexer)
    db_document = SimpleNamespace(
        doc_metadata={"active_pipeline_ready": True, "active_pipeline_hash": "active", "pipeline_hash": False}
    )

    class Query:
        def populate_existing(self):
            return self

        def filter(self, *_clauses):
            return self

        def first(self):
            return db_document

    processor_module._rollback_and_cleanup_indexes(
        SimpleNamespace(rollback=lambda: None, refresh=lambda _document: None, query=lambda _model: Query()),
        db_document=db_document,
        tenant_id=UUID(int=1),
        document_id=UUID(int=2),
        cleanup_indexes=True,
    )
    assert deleted == []


@pytest.mark.asyncio
async def test_legacy_indexed_checkpoint_does_not_invent_an_empty_pipeline_key():
    filters = []

    class Query:
        def filter(self, *clauses):
            filters.extend(str(clause) for clause in clauses)
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return []

    result = await process_document_flow._resume_from_indexed_checkpoint(
        db=SimpleNamespace(query=lambda model: Query()),
        db_document=SimpleNamespace(
            doc_metadata={
                "parser_backend": "basic",
                "chunk_strategy": "fixed",
                "ingest_checkpoint": {"version": "1", "stage": "indexed"},
            }
        ),
        tenant_id=UUID(int=1),
        document_id=UUID(int=2),
        prepared_state=None,
        with_stage_durations=lambda metadata: metadata,
    )
    assert result is None
    assert filters == []


@pytest.mark.parametrize("value", [0, False])
def test_docx_writer_keeps_scalar_paragraph_content(value):
    result = render_clean_docx_bytes(title=None, blocks=[{"text": value}])
    document = DocxDocument(BytesIO(result))
    assert [paragraph.text for paragraph in document.paragraphs] == [str(value)]
