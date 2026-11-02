"""
Document management API.
"""

import importlib
import os
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Form

from app.api.schemas.document import (
    DocumentPipelineOptions as DocumentPipelineOptions,
)
from app.api.schemas.document import (
    LocalHtmlIngestRequest as LocalHtmlIngestRequest,
)
from app.api.schemas.document import (
    UrlUploadRequest as UrlUploadRequest,
)
from app.api.utils.pipeline_options import (
    CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL as CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL,
)
from app.api.utils.pipeline_options import (
    PipelineOptionOverrides as PipelineOptionOverrides,
)
from app.api.utils.pipeline_options import (
    _parse_pipeline_json as _parse_pipeline_json,
)
from app.api.utils.pipeline_options import (
    _validate_chunk_params as _validate_chunk_params,
)
from app.api.utils.upload import FILENAME_INVALID_CHARS_DETAIL as FILENAME_INVALID_CHARS_DETAIL
from app.api.utils.upload import _normalize_upload_key as _normalize_upload_key
from app.api.utils.upload import _normalize_upload_path_parts as _normalize_upload_path_parts
from app.api.utils.upload import (
    save_upload_file_with_hash,
)
from app.api.v1 import (
    document_access,
    document_assets,
    document_batch_upload,
    document_batches,
    document_batches_lifecycle,
    document_chunks_read,
    document_content,
    document_dead_letters,
    document_detail,
    document_duplicates,
    document_folders,
    document_health,
    document_lifecycle,
    document_listing,
    document_manual,
    document_mutations,
    document_preview,
    document_processing,
    document_stats,
    document_timeline,
    document_versions,
)
from app.api.v1.document_access import (
    get_document_access as get_document_access,
)
from app.api.v1.document_access import (
    put_document_access as put_document_access,
)
from app.api.v1.document_assets import (
    DOCUMENT_FILE_ACCESS_DENIED_DETAIL as DOCUMENT_FILE_ACCESS_DENIED_DETAIL,
)
from app.api.v1.document_assets import (
    DOCUMENT_FILE_NOT_FOUND_DETAIL as DOCUMENT_FILE_NOT_FOUND_DETAIL,
)
from app.api.v1.document_assets import (
    IMAGE_JPEG_MEDIA_TYPE as IMAGE_JPEG_MEDIA_TYPE,
)
from app.api.v1.document_assets import (
    IMAGE_NOT_FOUND_DETAIL as IMAGE_NOT_FOUND_DETAIL,
)
from app.api.v1.document_assets import (
    INVALID_RANGE_HEADER_DETAIL as INVALID_RANGE_HEADER_DETAIL,
)
from app.api.v1.document_assets import (
    download_document as download_document,
)
from app.api.v1.document_assets import (
    get_image as get_image,
)
from app.api.v1.document_assets import (
    get_image_url as get_image_url,
)
from app.api.v1.document_batches import (
    batch_move_documents as batch_move_documents,
)
from app.api.v1.document_batches import (
    batch_patch_document_user_metadata as batch_patch_document_user_metadata,
)
from app.api.v1.document_batches import (
    batch_reingest_documents as batch_reingest_documents,
)
from app.api.v1.document_batches import (
    batch_retry_documents as batch_retry_documents,
)
from app.api.v1.document_batches import (
    batch_update_document_access as batch_update_document_access,
)
from app.api.v1.document_batches_lifecycle import (
    batch_archive_documents as batch_archive_documents,
)
from app.api.v1.document_batches_lifecycle import (
    batch_delete_documents as batch_delete_documents,
)
from app.api.v1.document_batches_lifecycle import (
    batch_disable_documents as batch_disable_documents,
)
from app.api.v1.document_batches_lifecycle import (
    batch_enable_documents as batch_enable_documents,
)
from app.api.v1.document_batches_lifecycle import (
    batch_unarchive_documents as batch_unarchive_documents,
)
from app.api.v1.document_chunks_read import (
    get_document_chunk as get_document_chunk,
)
from app.api.v1.document_chunks_read import (
    list_document_chunk_matches as list_document_chunk_matches,
)
from app.api.v1.document_chunks_read import (
    list_document_chunks as list_document_chunks,
)
from app.api.v1.document_content import (
    download_document_clean_docx as download_document_clean_docx,
)
from app.api.v1.document_content import (
    get_document_parsed_content as get_document_parsed_content,
)
from app.api.v1.document_detail import (
    get_document as get_document,
)
from app.api.v1.document_health import (
    get_document_health_card as get_document_health_card,
)
from app.api.v1.document_listing import (
    ListDocumentsQueryFields as ListDocumentsQueryFields,
)
from app.api.v1.document_listing import (
    _source_path_prefix_expr as _source_path_prefix_expr,
)
from app.api.v1.document_listing import (
    list_documents as list_documents,
)
from app.api.v1.document_manual import (
    create_document_with_manual_chunks as create_document_with_manual_chunks,
)
from app.api.v1.document_mutations import (
    generate_document_qa as generate_document_qa,
)
from app.api.v1.document_mutations import (
    patch_document_pipeline as patch_document_pipeline,
)
from app.api.v1.document_mutations import (
    patch_document_user_metadata as patch_document_user_metadata,
)
from app.api.v1.document_processing import (
    cancel_document_processing as cancel_document_processing,
)
from app.api.v1.document_processing import (
    delete_document as delete_document,
)
from app.api.v1.document_processing import (
    get_document_status as get_document_status,
)
from app.api.v1.document_processing import (
    retry_document_processing as retry_document_processing,
)
from app.api.v1.document_source_ingestion import (
    HTML_FILE_EXTENSION as HTML_FILE_EXTENSION,
)
from app.api.v1.document_source_ingestion import (
    LocalHtmlIngestFile as LocalHtmlIngestFile,
)
from app.api.v1.document_source_ingestion import (
    PreparedDocumentIngestion as PreparedDocumentIngestion,
)
from app.api.v1.document_source_ingestion import (
    ResolvedDocumentIngestionPolicy as ResolvedDocumentIngestionPolicy,
)
from app.api.v1.document_source_ingestion import (
    ResolvedDocumentPipeline as ResolvedDocumentPipeline,
)
from app.api.v1.document_source_ingestion import (
    UrlIngestFile as UrlIngestFile,
)
from app.api.v1.document_source_ingestion import (
    UrlSourceMetadata as UrlSourceMetadata,
)
from app.api.v1.document_source_ingestion import (
    _ingest_local_html_request as _ingest_local_html_request,
)
from app.api.v1.document_source_ingestion import (
    _ingest_url_upload_request as _ingest_url_upload_request,
)
from app.api.v1.document_timeline import (
    get_document_timeline as get_document_timeline,
)
from app.api.v1.document_versions import (
    activate_document_version as activate_document_version,
)
from app.api.v1.document_versions import (
    delete_document_version as delete_document_version,
)
from app.api.v1.document_versions import (
    diff_document_versions as diff_document_versions,
)
from app.api.v1.document_versions import (
    list_document_versions as list_document_versions,
)
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.parsing.artifact_stats import POSITION_TAG_RE as POSITION_TAG_RE
from app.parsing.subprocess_runner import run_subprocess_worker
from app.rag.core.logging import get_logger
from app.rag.kg.pipeline import extract_events
from app.rag.preprocessing.processor import governance_processor
from app.rag.preprocessing.rules import build_governance_rules
from app.services import document_access_service
from app.services.dataset_precheck_ingestion_suggestion import apply_ingestion_policy_suggestion
from app.services.dataset_precheck_scan_runner import run_dataset_precheck_scan
from app.services.document_dedup_service import (
    DOCUMENT_DEDUP_CONSTRAINT_NAME as DOCUMENT_DEDUP_CONSTRAINT_NAME,
)
from app.services.document_dedup_service import (
    DUPLICATE_DOCUMENT_PROCESSING_DETAIL as DUPLICATE_DOCUMENT_PROCESSING_DETAIL,
)
from app.services.document_dedup_service import (
    _find_duplicate_document as _find_duplicate_document,
)
from app.services.document_dedup_service import _find_duplicate_document_by_sha as _find_duplicate_document_by_sha
from app.services.document_dedup_service import (
    _find_duplicate_document_for_persist_conflict as _find_duplicate_document_for_persist_conflict,
)
from app.services.document_preview_utils import (
    DATA_IMAGE_PREFIX as DATA_IMAGE_PREFIX,
)
from app.services.document_preview_utils import (
    IMAGE_FILE_EXT_JPEG as IMAGE_FILE_EXT_JPEG,
)
from app.services.document_preview_utils import (
    IMAGE_FILE_EXT_WEBP as IMAGE_FILE_EXT_WEBP,
)
from app.services.document_preview_utils import (
    MINIO_IMAGE_REF_RE as MINIO_IMAGE_REF_RE,
)
from app.services.document_preview_utils import (
    PREVIEW_IMAGE_EXTENSIONS as PREVIEW_IMAGE_EXTENSIONS,
)
from app.services.document_preview_utils import (
    PREVIEW_IMAGE_REF_RE as PREVIEW_IMAGE_REF_RE,
)
from app.services.document_preview_utils import (
    UUID_PATTERN as UUID_PATTERN,
)
from app.services.document_preview_utils import (
    _compute_chunk_preview_quality,
    _materialize_extracted_images_for_preview,
    _materialize_local_images_for_preview,
)
from app.services.document_preview_utils import (
    _rewrite_preview_images_to_minio as _rewrite_preview_images_to_minio,
)
from app.services.pipeline_config import (
    build_indexing_options,
)
from app.storage.object.minio import minio_service as minio_service
from app.storage.object.runtime import (
    document_object_storage_enabled,
)
from app.storage.object.runtime import resolve_document_object_reference as resolve_document_object_reference

logger = get_logger("api.documents")

NO_DOCUMENT_ACCESS_DETAIL = document_access_service.NO_DOCUMENT_ACCESS_DETAIL
_assert_document_acl_readable = document_access_service.assert_document_acl_readable
_assert_document_readable_for_lifecycle = document_access_service.assert_document_readable_for_lifecycle
_assert_document_writable_for_lifecycle = document_access_service.assert_document_writable_for_lifecycle
_assert_document_writable_for_unassigned_target = document_access_service.assert_document_writable_for_unassigned_target
_get_document_for_lifecycle = document_access_service.get_document_for_lifecycle

__all__ = [
    "DBDatasetPrecheckScanRun",
    "SessionLocal",
    "_compute_chunk_preview_quality",
    "_materialize_extracted_images_for_preview",
    "_materialize_local_images_for_preview",
    "_rewrite_preview_images_to_minio",
    "apply_ingestion_policy_suggestion",
    "build_governance_rules",
    "build_indexing_options",
    "extract_events",
    "governance_processor",
    "os",
    "run_dataset_precheck_scan",
    "run_subprocess_worker",
    "save_upload_file_with_hash",
]

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
router.include_router(document_access.router)
router.include_router(document_assets.router)
router.include_router(document_batches.router)
router.include_router(document_batches_lifecycle.router)
router.include_router(document_batch_upload.router)
router.include_router(document_duplicates.router)
router.include_router(document_folders.router)
router.include_router(document_stats.router)
router.include_router(document_chunks_read.router)
router.include_router(document_content.router)
router.include_router(document_dead_letters.router)
router.include_router(document_listing.router)
router.include_router(document_manual.router)
router.include_router(document_preview.router)
router.include_router(document_detail.router)
router.include_router(document_health.router)
router.include_router(document_lifecycle.router)
router.include_router(document_mutations.router)
router.include_router(document_processing.router)
router.include_router(document_timeline.router)
router.include_router(document_versions.router)

# Compatibility re-export for existing imports/tests that still resolve the preview
# endpoint from `app.api.v1.documents`.
preview_document = document_preview.preview_document

DOC_NOT_FOUND_DETAIL = "Document not found"
PIPELINE_HASH_TOO_LONG_DETAIL = "pipeline_hash too long"
MANUAL_FILE_PATH_PREFIX = "manual://"


def _document_object_storage_enabled() -> bool:
    return document_object_storage_enabled()


@dataclass
class PipelineOverridesFormFields:
    governance_enabled: bool | None = Form(None)
    governance_remove_toc_lines: bool | None = Form(None)
    governance_remove_noise_lines: bool | None = Form(None)
    governance_unwrap_lines: bool | None = Form(None)
    governance_remove_common_lines: bool | None = Form(None)
    governance_unwrap_max_line_length: int | None = Form(None)
    governance_noise_min_chars: int | None = Form(None)
    governance_noise_ratio_threshold: float | None = Form(None)
    governance_common_lines_min_docs: int | None = Form(None)
    governance_common_lines_min_ratio: float | None = Form(None)
    chunk_size: int | None = Form(None)
    chunk_overlap: int | None = Form(None)
    chunk_vector_enabled: bool | None = Form(None)
    bm25_index_enabled: bool | None = Form(None)
    kg_enabled: bool | None = Form(None)
    event_vector_enabled: bool | None = Form(None)
    entity_vector_enabled: bool | None = Form(None)


@dataclass
class UploadDocumentFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: str | None = Form(None)
    dataset_id: UUID | None = Form(None)
    user_metadata: str | None = Form(None)


@dataclass
class UploadDocumentsBatchFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    pipeline: str | None = Form(None)
    dataset_id: UUID | None = Form(None)
    precheck_first: bool = Form(False)
    user_metadata_map: str | None = Form(None)
    max_concurrent: int = Form(5)


document_upload = importlib.import_module("app.api.v1.document_upload")
router.include_router(document_upload.router)

upload_document = document_upload.upload_document
upload_document_from_url = document_upload.upload_document_from_url
upload_documents_batch = document_upload.upload_documents_batch


document_chunks_write = importlib.import_module("app.api.v1.document_chunks_write")
CHUNK_NOT_FOUND_DETAIL = document_chunks_write.CHUNK_NOT_FOUND_DETAIL
CHUNK_NOT_ACTIVE_PIPELINE_DETAIL = document_chunks_write.CHUNK_NOT_ACTIVE_PIPELINE_DETAIL
CHUNK_PATCH_OPERATION = document_chunks_write.CHUNK_PATCH_OPERATION
_get_document_for_chunk_ops = document_chunks_write._get_document_for_chunk_ops
_get_chunk_for_chunk_ops = document_chunks_write._get_chunk_for_chunk_ops
_assert_document_writable_for_chunk_ops = document_chunks_write._assert_document_writable_for_chunk_ops
_resolve_active_doc_pipeline_key = document_chunks_write._resolve_active_doc_pipeline_key
_normalize_index_consistency_strictness = document_chunks_write._normalize_index_consistency_strictness
_build_index_channel_result = document_chunks_write._build_index_channel_result
_index_channel_status = document_chunks_write._index_channel_status
_index_drift_marker_rows = document_chunks_write._index_drift_marker_rows
_build_chunk_index_operation_result = document_chunks_write._build_chunk_index_operation_result
_persist_chunk_index_operation_result = document_chunks_write._persist_chunk_index_operation_result
_enqueue_index_drift_reconcile = document_chunks_write._enqueue_index_drift_reconcile
_build_chunk_drift_markers = document_chunks_write._build_chunk_drift_markers
_record_chunk_index_drift = document_chunks_write._record_chunk_index_drift
create_document_chunk = document_chunks_write.create_document_chunk
patch_document_chunk = document_chunks_write.patch_document_chunk
delete_document_chunk = document_chunks_write.delete_document_chunk
disable_document_chunk = document_chunks_write.disable_document_chunk
enable_document_chunk = document_chunks_write.enable_document_chunk
reembed_document_chunks = document_chunks_write.reembed_document_chunks
router.include_router(document_chunks_write.router)


document_lifecycle_service = importlib.import_module("app.services.document_lifecycle_service")
_get_document_for_delete = document_lifecycle_service._get_document_for_delete
_assert_document_delete_permission = document_lifecycle_service._assert_document_delete_permission
_cancel_processing_document = document_lifecycle_service._cancel_processing_document
_document_task_ids = document_lifecycle_service._document_task_ids
_abort_document_tasks_before_delete = document_lifecycle_service._abort_document_tasks_before_delete
_add_document_metadata_img_ids = document_lifecycle_service._add_document_metadata_img_ids
_add_chunk_metadata_img_ids = document_lifecycle_service._add_chunk_metadata_img_ids
_delete_document_minio_images = document_lifecycle_service._delete_document_minio_images
_delete_document_table_store = document_lifecycle_service._delete_document_table_store
_delete_minio_document_object = document_lifecycle_service._delete_minio_document_object
_delete_local_document_file = document_lifecycle_service._delete_local_document_file
_delete_document_file = document_lifecycle_service._delete_document_file
_touch_dataset_updated_after_delete = document_lifecycle_service._touch_dataset_updated_after_delete
_delete_document_record = document_lifecycle_service._delete_document_record
_cleanup_document_kg_artifacts = document_lifecycle_service._cleanup_document_kg_artifacts
_delete_document_lifecycle = document_lifecycle_service._delete_document_lifecycle

document_chunk_preview = importlib.import_module("app.api.v1.document_chunk_preview")
router.include_router(document_chunk_preview.router)

ChunkPreviewRequestFields = document_chunk_preview.ChunkPreviewRequestFields
ChunkPreviewByShaFileFields = document_chunk_preview.ChunkPreviewByShaFileFields
preview_chunking = document_chunk_preview.preview_chunking
preview_chunking_by_sha = document_chunk_preview.preview_chunking_by_sha
