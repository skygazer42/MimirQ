"""Assemble document routes in registration order."""

from fastapi import APIRouter

from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.api.v1.documents import access as document_access
from app.api.v1.documents import assets as document_assets
from app.api.v1.documents import batch_upload as document_batch_upload
from app.api.v1.documents import batches as document_batches
from app.api.v1.documents import batches_lifecycle as document_batches_lifecycle
from app.api.v1.documents import chunk_preview as document_chunk_preview
from app.api.v1.documents import chunks_read as document_chunks_read
from app.api.v1.documents import chunks_write as document_chunks_write
from app.api.v1.documents import content as document_content
from app.api.v1.documents import dead_letters as document_dead_letters
from app.api.v1.documents import detail as document_detail
from app.api.v1.documents import duplicates as document_duplicates
from app.api.v1.documents import folders as document_folders
from app.api.v1.documents import health as document_health
from app.api.v1.documents import lifecycle as document_lifecycle
from app.api.v1.documents import listing as document_listing
from app.api.v1.documents import manual as document_manual
from app.api.v1.documents import mutations as document_mutations
from app.api.v1.documents import preview as document_preview
from app.api.v1.documents import processing as document_processing
from app.api.v1.documents import stats as document_stats
from app.api.v1.documents import timeline as document_timeline
from app.api.v1.documents import upload as document_upload
from app.api.v1.documents import versions as document_versions

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
router.include_router(document_upload.router)
router.include_router(document_chunks_write.router)
router.include_router(document_chunk_preview.router)
