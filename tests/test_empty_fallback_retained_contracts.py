from contextlib import nullcontext
import importlib
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
import sqlalchemy
import yaml
from langchain_core.documents import Document
from docx import Document as DocxDocument

from app.connectors.db import catalog_runner
from app.parsing.processors.support.recovery import (
    _checkpoint_matches_current_document,
    _validate_retry_cleanup_scope,
    checkpoint_stage,
    upsert_ingest_checkpoint,
)
from app.parsing.processors import processor as processor_module
from app.parsing.processors.support import process_document_flow
from app.parsing.models.manifest import load_small_model_manifest
from app.parsing.output.docx_writer import render_clean_docx_bytes
from app.parsing.output.markdown_writer import write_clean_markdown
from app.parsing.utils.document_elements import _clean_element_text, _normalize_string, normalize_document_elements
from app.storage.object.runtime import (
    SOURCE_STORAGE_REGION_KEY,
    ObjectStorageRef,
    _resolve_stored_object_region,
)


@pytest.mark.parametrize("value", [0, False])
def test_element_scalar_text_preserves_provided_falsy_values(value):
    assert _clean_element_text(value) == str(value)
    assert _normalize_string(value) is None


def test_snapshot_column_names_keep_provided_falsy_scalar_values():
    assert catalog_runner._snapshot_columns([], [None, 0, False], max_cols=10) == ["0", "False"]


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
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: engine)
    with pytest.raises(AttributeError):
        with catalog_runner._connect_sqlserver(
            {"host": "host", "database": "db", "username": "user", "password": "", "odbc_driver": driver}
        ):
            pass


def test_absent_odbc_driver_selects_existing_driver_18_default(monkeypatch):
    drivers = []
    engine = SimpleNamespace(connect=lambda: nullcontext(object()), dispose=lambda: None)

    def create(url, **kwargs):
        drivers.append(url.query["driver"])
        return engine

    monkeypatch.setattr(sqlalchemy, "create_engine", create)
    with catalog_runner._connect_sqlserver({"host": "host", "database": "db", "username": "user", "password": ""}):
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
    assert _validate_retry_cleanup_scope({}, request={"version": "1", "scope": "document"}, document_id=UUID(int=1)) is None


@pytest.mark.parametrize("value", [0, False])
@pytest.mark.parametrize("module_name", ["header_footer_remover", "watermark_detector"])
def test_element_detection_text_preserves_scalar_content(module_name, value):
    module = importlib.import_module(f"app.parsing.enrich.{module_name}")
    assert module._text_value({"text": value}) == str(value)


@pytest.mark.parametrize("value", [0, False])
def test_small_model_manifest_preserves_scalar_model_identifier(tmp_path, value):
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump({"ocr": {"default": value, "models": {value: {"kind": "onnx"}}}}), encoding="utf-8")
    manifest = load_small_model_manifest(path)
    assert manifest.defaults["ocr"] == str(value)


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
    processor_module.DocumentProcessorService._rollback_and_cleanup_indexes(
        None,
        SimpleNamespace(rollback=lambda: None),
        db_document=SimpleNamespace(
            doc_metadata={"active_pipeline_ready": True, "active_pipeline_hash": "active", "pipeline_hash": False}
        ),
        tenant_id=UUID(int=1),
        document_id=UUID(int=2),
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
        None,
        db=SimpleNamespace(query=lambda model: Query()),
        db_document=SimpleNamespace(
            doc_metadata={"parser_backend": "basic", "chunk_strategy": "fixed", "ingest_checkpoint": {"version": "1", "stage": "indexed"}}
        ),
        tenant_id=UUID(int=1),
        document_id=UUID(int=2),
        parser_backend=None,
        chunk_strategy=None,
        prepared_state=None,
        with_stage_durations=lambda metadata: metadata,
    )
    assert result is None
    assert filters
    assert len(filters) == 2


@pytest.mark.parametrize("value", [0, False])
def test_docx_writer_keeps_scalar_paragraph_content(value):
    result = render_clean_docx_bytes(title=None, blocks=[{"text": value}])
    document = DocxDocument(BytesIO(result))
    assert [paragraph.text for paragraph in document.paragraphs] == [str(value)]


@pytest.mark.parametrize("value", [0, False])
def test_markdown_writer_keeps_scalar_paragraph_and_alt_text(tmp_path, value):
    path = write_clean_markdown(
        tmp_path / "output.md", title=None, blocks=[{"text": value}, {"type": "image", "alt": value, "path": "image.png"}]
    )
    rendered = path.read_text(encoding="utf-8")
    assert rendered.startswith(str(value) + "\n")
    assert f"![{value}](image.png)" in rendered
