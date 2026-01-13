"""
Document processing service - core processing flow.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from uuid import UUID
from io import BytesIO
from PIL import Image as PILImage
import asyncio
import base64
import hashlib
import re
import shutil
import time
import uuid
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document as DBDocument, DocumentChunk
from app.models.dataset import Dataset
from app.rag.chunking.factory import chunker_factory
from app.storage.object.minio import minio_service
from app.types.indexing import IndexKind, IndexRecord
from app.types.pipeline import PipelineEffective
from app.services.indexer import Indexer
from app.services.pipeline_config import (
    build_indexing_options,
    resolve_pipeline_effective,
)
from app.rag.preprocessing.processor import governance_processor, GovernanceStats
from app.rag.preprocessing.normalization import normalize_text
from app.rag.kg.pipeline import extract_events
from app.parsing.routing import route_pdf_backend
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.rag.core.logging import get_logger
from app.rag.core.metadata import normalize_image_metadata
from app.services.metrics_logger import log_metrics, metrics_span, set_metrics_context


logger = get_logger("parsing.document_processor")


class DocumentCancelledError(Exception):
    pass


@dataclass(frozen=True)
class ParseResult:
    resolved_backend: str
    resolved_chunk_strategy: str
    documents: Optional[List[Document]] = None
    chunks: Optional[List[Document]] = None


@dataclass(frozen=True)
class InlineAssetResult:
    documents: List[Document]
    uploaded_img_ids: List[str]
    next_asset_index: int


@dataclass(frozen=True)
class GovernanceResult:
    items: List[Document]
    stats: Optional[GovernanceStats] = None


@dataclass(frozen=True)
class ChunkingResult:
    chunks: List[Document]


@dataclass(frozen=True)
class ChunkAssetResult:
    chunks: List[Document]
    img_ids: List[str]


@dataclass(frozen=True)
class IndexResult:
    chunk_ids: List[UUID]
    total_characters: int
    db_chunks: List[DocumentChunk]


class ParsingStage:
    def __init__(self, service: "DocumentProcessorService"):
        self._svc = service

    async def run(
        self,
        *,
        db: Session,
        db_document: DBDocument,
        file_path: Path,
        document_id: UUID,
        tenant_id: UUID,
        dataset_id: str,
        parser_backend: Optional[str],
        chunk_strategy: Optional[str],
        html_xpath: Optional[str] = None,
    ) -> ParseResult:
        # IMPORTANT: resolve strategy first so defaults (e.g. DEFAULT_CHUNK_STRATEGY)
        # are honored consistently (including ragflow_* strategies).
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
        if resolved_chunk_strategy in self._svc.RAGFLOW_STRATEGIES:
            resolved_backend = "ragflow"
            self._svc._record_processing_metadata(
                db,
                tenant_id,
                document_id,
                parser_backend=resolved_backend,
                chunk_strategy=resolved_chunk_strategy,
            )
            artifact_root = (
                Path(settings.UPLOAD_DIR)
                / str(tenant_id)
                / ".mimirq_parse"
                / f"{str(document_id)}-ragflow-{uuid.uuid4().hex}"
            )

            last_check = 0.0
            cached_cancel = False

            async def cancel_check() -> bool:
                nonlocal last_check, cached_cancel
                now = time.monotonic()
                if now - last_check < 1.0:
                    return cached_cancel
                last_check = now
                db_doc = (
                    db.query(DBDocument)
                    .populate_existing()
                    .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
                    .first()
                )
                if not db_doc:
                    cached_cancel = True
                    return True
                status = str(db_doc.status or "").lower()
                if status == "cancelled":
                    cached_cancel = True
                    return True
                meta = db_doc.doc_metadata or {}
                if isinstance(meta, dict) and bool(meta.get("cancel_requested")):
                    cached_cancel = True
                    return True
                cached_cancel = False
                return False

            try:
                result = await run_subprocess_worker(
                    tenant_id=tenant_id,
                    payload={
                        "action": "ragflow_chunk",
                        "tenant_id": str(tenant_id),
                        "file_path": str(file_path),
                        "strategy": resolved_chunk_strategy,
                        "mode": "ingest",
                        "artifact_root": str(artifact_root),
                    },
                    cancel_check=cancel_check,
                    timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
                )
            except SubprocessCancelled as exc:
                try:
                    shutil.rmtree(artifact_root, ignore_errors=True)
                except Exception:
                    pass
                raise DocumentCancelledError(str(exc))
            except asyncio.CancelledError:
                try:
                    shutil.rmtree(artifact_root, ignore_errors=True)
                except Exception:
                    pass
                raise
            except SubprocessWorkerError as exc:
                raise RuntimeError(f"Ragflow parsing failed: {str(exc)[:200]}") from exc

            chunks = [
                Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    id=item.get("id") if isinstance(item.get("id"), str) else None,
                )
                for item in (result.get("documents") or [])
                if isinstance(item, dict)
            ]
            return ParseResult(
                resolved_backend=resolved_backend,
                resolved_chunk_strategy=resolved_chunk_strategy,
                chunks=chunks,
            )

        logger.info("Parsing document: %s", file_path)
        effective_parser_backend = parser_backend
        file_ext = file_path.suffix.lower()
        pdf_quality = None
        if file_ext == ".pdf":
            requested = (parser_backend or "").strip().lower()
            if not requested or requested == "auto":
                effective_parser_backend, pdf_quality = route_pdf_backend(
                    file_path,
                    parser_backend,
                    sample_pages=3,
                    use_ocr_validation=settings.RAPIDOCR_ENABLED,
                )
                if isinstance(pdf_quality, dict):
                    metadata = dict(db_document.doc_metadata or {})
                    metadata["pdf_quality"] = pdf_quality
                    db_document.doc_metadata = metadata
                    db.commit()
                    db.refresh(db_document)

        artifact_root = (
            Path(settings.UPLOAD_DIR)
            / str(tenant_id)
            / ".mimirq_parse"
            / f"{str(document_id)}-parse-{uuid.uuid4().hex}"
        )

        last_check = 0.0
        cached_cancel = False

        async def cancel_check() -> bool:
            nonlocal last_check, cached_cancel
            now = time.monotonic()
            if now - last_check < 1.0:
                return cached_cancel
            last_check = now
            db_doc = (
                db.query(DBDocument)
                .populate_existing()
                .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
                .first()
            )
            if not db_doc:
                cached_cancel = True
                return True
            status = str(db_doc.status or "").lower()
            if status == "cancelled":
                cached_cancel = True
                return True
            meta = db_doc.doc_metadata or {}
            if isinstance(meta, dict) and bool(meta.get("cancel_requested")):
                cached_cancel = True
                return True
            cached_cancel = False
            return False

        try:
            payload = {
                "action": "parse_documents",
                "tenant_id": str(tenant_id),
                "file_path": str(file_path),
                "parser_backend": effective_parser_backend,
                "mode": "ingest",
                "dataset_id": dataset_id,
                "document_id": str(document_id),
                "pdf_quality": pdf_quality,
                "artifact_root": str(artifact_root),
            }
            if isinstance(html_xpath, str) and html_xpath.strip():
                payload["html_xpath"] = html_xpath.strip()
            parsed = await run_subprocess_worker(
                tenant_id=tenant_id,
                payload=payload,
                cancel_check=cancel_check,
                timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
            )
        except SubprocessCancelled as exc:
            try:
                shutil.rmtree(artifact_root, ignore_errors=True)
            except Exception:
                pass
            raise DocumentCancelledError(str(exc))
        except asyncio.CancelledError:
            try:
                shutil.rmtree(artifact_root, ignore_errors=True)
            except Exception:
                pass
            raise
        except SubprocessWorkerError as exc:
            raise RuntimeError(f"Parsing failed: {str(exc)[:200]}") from exc

        documents = [
            Document(
                page_content=str(item.get("page_content") or ""),
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                id=item.get("id") if isinstance(item.get("id"), str) else None,
            )
            for item in (parsed.get("documents") or [])
            if isinstance(item, dict)
        ]
        resolved_backend = str(parsed.get("resolved_backend") or effective_parser_backend or parser_backend or "auto")
        self._svc._record_processing_metadata(
            db,
            tenant_id,
            document_id,
            parser_backend=resolved_backend,
            chunk_strategy=resolved_chunk_strategy,
        )
        return ParseResult(
            resolved_backend=resolved_backend,
            resolved_chunk_strategy=resolved_chunk_strategy,
            documents=documents,
        )


class InlineAssetStage:
    def __init__(self, service: "DocumentProcessorService"):
        self._svc = service

    def run(
        self,
        *,
        documents: List[Document],
        tenant_id: UUID,
        dataset_id: str,
        document_id: UUID,
        origin_path: Path,
        start_index: int = 0,
    ) -> InlineAssetResult:
        if not settings.MINIO_ENABLED:
            return InlineAssetResult(documents=documents, uploaded_img_ids=[], next_asset_index=int(start_index or 0))

        inline_cache: dict[str, str] = {}
        asset_idx = int(start_index or 0)
        uploaded: List[str] = []
        processed_docs: List[Document] = []

        for doc in documents:
            content = doc.page_content or ""
            origin_for_doc = origin_path
            base_dir = (doc.metadata or {}).get("asset_base_dir")
            if isinstance(base_dir, str) and base_dir.strip():
                origin_for_doc = Path(base_dir.strip())
            new_content, new_img_ids, asset_idx = self._svc._upload_inline_images_to_minio(
                markdown_text=content,
                tenant_id=str(tenant_id),
                dataset_id=dataset_id,
                document_id=str(document_id),
                cache=inline_cache,
                start_index=asset_idx,
                origin_path=origin_for_doc,
            )
            uploaded.extend(list(new_img_ids or []))
            if new_content != content:
                processed_docs.append(
                    Document(
                        page_content=new_content,
                        metadata=dict(doc.metadata or {}),
                        id=doc.id,
                    )
                )
            else:
                processed_docs.append(doc)

        return InlineAssetResult(documents=processed_docs, uploaded_img_ids=uploaded, next_asset_index=asset_idx)


class GovernanceStage:
    def run(
        self,
        *,
        items: List[Document],
        enabled: bool,
        kwargs: Dict[str, Any],
    ) -> GovernanceResult:
        if not enabled:
            return GovernanceResult(items=items, stats=None)
        cleaned, stats = governance_processor.clean_documents(items, **kwargs)
        return GovernanceResult(items=cleaned, stats=stats)


class NormalizeStage:
    """
    Apply conservative normalization before governance/chunking.

    Unlike governance cleaning, this stage is always safe to run:
    - Normalizes line endings and Unicode whitespace artifacts
    - Removes zero-width/control characters and soft hyphens
    - Repairs common PDF ligatures
    """

    def run(self, *, items: List[Document]) -> List[Document]:
        if not items:
            return items
        out: List[Document] = []
        for doc in items:
            raw = doc.page_content or ""
            normalized = normalize_text(raw, normalize_line_endings=True, remove_control_chars=True)
            meta = dict(doc.metadata or {})
            meta["text_normalized"] = True
            meta["text_normalized_changed"] = bool(normalized != raw)
            out.append(Document(page_content=normalized, metadata=meta, id=getattr(doc, "id", None)))
        return out


class ChunkingStage:
    def run(
        self,
        *,
        documents: List[Document],
        chunk_strategy: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> ChunkingResult:
        logger.info("Chunking document into smaller pieces...")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        chunker = chunker_factory.get_chunker(
            chunk_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return ChunkingResult(chunks=chunker.split_documents(documents))


class ChunkAssetStage:
    def __init__(self, service: "DocumentProcessorService"):
        self._svc = service

    def run(
        self,
        *,
        chunks: List[Document],
        tenant_id: UUID,
        dataset_id: str,
        document_id: UUID,
        resolved_backend: str,
        resolved_chunk_strategy: str,
    ) -> ChunkAssetResult:
        img_ids: List[str] = []
        for idx, chunk in enumerate(chunks):
            meta = dict(chunk.metadata or {})
            meta["document_id"] = str(document_id)
            meta["chunk_index"] = idx
            meta["parser_backend"] = resolved_backend
            meta["chunk_strategy"] = resolved_chunk_strategy
            chunk.metadata = meta

            img_id = self._svc._extract_and_upload_image_to_minio(
                meta,
                tenant_id=str(tenant_id),
                dataset_id=dataset_id,
                document_id=str(document_id),
                chunk_index=idx,
            )
            if not img_id:
                img_id = self._svc._extract_img_id_from_content(chunk.page_content)
            if img_id:
                meta["img_id"] = img_id
                normalize_image_metadata(meta)
                chunk.metadata = meta
                img_ids.append(img_id)
        return ChunkAssetResult(chunks=chunks, img_ids=img_ids)


class IndexStage:
    def run(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        file_path: Path,
        chunks: List[Document],
        options,
    ) -> IndexResult:
        logger.info("Persisting chunks and indexes...")
        records: List[IndexRecord] = []
        for chunk in chunks:
            meta = dict(chunk.metadata or {})
            content = normalize_text(chunk.page_content or "", normalize_line_endings=True, remove_control_chars=True)
            records.append(
                IndexRecord(
                    kind=IndexKind.CHUNK,
                    content=content,
                    metadata=meta,
                    document_id=document_id,
                    page_number=meta.get("page") or meta.get("page_number"),
                    start_char=meta.get("start_char"),
                    end_char=meta.get("end_char"),
                )
            )

        persist_result = Indexer(db).upsert(
            tenant_id=tenant_id,
            records=records,
            default_source=str(file_path.name),
            commit=False,
            options=options,
        ).chunk_result
        if persist_result is None:
            raise RuntimeError("Chunk indexing returned no result")
        return IndexResult(
            chunk_ids=persist_result.chunk_ids,
            total_characters=persist_result.total_characters,
            db_chunks=persist_result.db_chunks,
        )


class DocumentProcessorService:
    """Document processing service."""

    def __init__(self):
        pass

    # Preset strategies (parse + chunk directly).
    RAGFLOW_STRATEGIES = {"ragflow_naive", "ragflow_book", "ragflow_laws", "ragflow_email"}

    async def process_document(
        self,
        file_path: Path,
        document_id: UUID,
        tenant_id: UUID,
        parser_backend: Optional[str] = None,
        chunk_strategy: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Full document processing flow.

        Steps:
        1. Parse document
        2. Split text
        3. Generate embeddings
        4. Persist to vector store
        5. Persist to database

        Args:
            file_path: Path to the file
            document_id: Document ID
            db: Database session

        Returns:
            Processing result
        """
        owns_db = False
        if db is None:
            db = SessionLocal()
            owns_db = True

        try:
            last_cancel_check = 0.0
            cached_cancel = False

            async def cancel_check(*, force: bool = False) -> bool:
                nonlocal last_cancel_check, cached_cancel
                now = time.monotonic()
                if not force and now - last_cancel_check < 1.0:
                    return cached_cancel
                last_cancel_check = now
                db_doc = (
                    db.query(DBDocument)
                    .populate_existing()
                    .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
                    .first()
                )
                if not db_doc:
                    cached_cancel = True
                    return True
                status = str(db_doc.status or "").lower()
                if status == "cancelled":
                    cached_cancel = True
                    return True
                meta = db_doc.doc_metadata or {}
                if isinstance(meta, dict) and bool(meta.get("cancel_requested")):
                    cached_cancel = True
                    return True
                cached_cancel = False
                return False

            async def raise_if_cancelled(*, force: bool = False) -> None:
                if await cancel_check(force=force):
                    raise DocumentCancelledError("cancel_requested")

            db_document = (
                db.query(DBDocument)
                .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
                .first()
            )
            if db_document is None:
                logger.warning("Document not found for processing: tenant=%s document=%s", tenant_id, document_id)
                return {"status": "skipped", "reason": "document_not_found"}

            # If user already cancelled before the worker started, stop immediately.
            await raise_if_cancelled(force=True)

            # Step 1: update status to processing.
            await self._update_status(
                db, tenant_id, document_id, "processing", 0, "parsing"
            )

            # Resolve dataset_id early (MinerU ZIP / MinIO paths depend on it).
            dataset_id = str(db_document.dataset_id) if db_document.dataset_id else str(tenant_id)

            # Bind metrics context for this coroutine/task (best-effort; used only when ENABLE_METRICS_LOG=true).
            set_metrics_context(tenant_id=tenant_id, document_id=document_id, dataset_id=dataset_id)

            # Track all img_id values linked to this document (used for cleanup).
            document_img_ids: set[str] = set()
            artifact_dirs: set[str] = set()

            dataset_meta: dict[str, Any] = {}
            if db_document.dataset_id:
                ds = (
                    db.query(Dataset)
                    .filter(Dataset.id == db_document.dataset_id, Dataset.tenant_id == tenant_id)
                    .first()
                )
                if ds is not None and isinstance(getattr(ds, "dataset_metadata", None), dict):
                    dataset_meta = dict(ds.dataset_metadata or {})

            pipeline_effective = resolve_pipeline_effective(
                dataset_metadata=dataset_meta,
                document_metadata=(db_document.doc_metadata or {}),
                request_overrides=None,
            )
            index_options = build_indexing_options(pipeline_effective)
            self._record_pipeline_effective(db, tenant_id, document_id, pipeline_effective)
            governance_kwargs = {
                "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
                "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
                "unwrap_lines": pipeline_effective.governance_unwrap_lines,
                "remove_common_lines": pipeline_effective.governance_remove_common_lines,
                "remove_boilerplate": pipeline_effective.governance_remove_boilerplate,
                "remove_images": pipeline_effective.governance_remove_images,
                "pii_anonymize": pipeline_effective.governance_pii_anonymize,
                "pii_mode": pipeline_effective.governance_pii_mode,
                "pii_mask": pipeline_effective.governance_pii_mask,
                "max_blank_lines": pipeline_effective.governance_max_blank_lines,
                "drop_outline_only": pipeline_effective.governance_drop_outline_only,
                "drop_outline_min_content_chars": pipeline_effective.governance_drop_outline_min_content_chars,
                "drop_outline_max_heading_ratio": pipeline_effective.governance_drop_outline_max_heading_ratio,
                "drop_low_density": pipeline_effective.governance_drop_low_density,
                "drop_low_density_threshold": pipeline_effective.governance_drop_low_density_threshold,
                "unwrap_max_line_length": pipeline_effective.governance_unwrap_max_line_length,
                "noise_min_chars": pipeline_effective.governance_noise_min_chars,
                "noise_ratio_threshold": pipeline_effective.governance_noise_ratio_threshold,
                "common_lines_min_docs": pipeline_effective.governance_common_lines_min_docs,
                "common_lines_min_ratio": pipeline_effective.governance_common_lines_min_ratio,
            }

            parsing_stage = ParsingStage(self)
            inline_asset_stage = InlineAssetStage(self)
            normalize_stage = NormalizeStage()
            governance_stage = GovernanceStage()
            chunking_stage = ChunkingStage()
            chunk_asset_stage = ChunkAssetStage(self)
            index_stage = IndexStage()

            with metrics_span(
                "ingest.parse",
                parser_backend_requested=parser_backend,
                chunk_strategy_requested=chunk_strategy,
            ):
                parsed = await parsing_stage.run(
                    db=db,
                    db_document=db_document,
                    file_path=file_path,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    parser_backend=parser_backend,
                    chunk_strategy=chunk_strategy,
                    html_xpath=(
                        pipeline_effective.governance_html_xpath
                        if file_path.suffix.lower() in {".html", ".htm"}
                        else None
                    ),
                )

            await raise_if_cancelled(force=True)

            resolved_backend = parsed.resolved_backend
            resolved_chunk_strategy = parsed.resolved_chunk_strategy

            # Collect images uploaded by the parser (e.g., MinerU ZIP mode returns images).
            if parsed.documents:
                for doc in parsed.documents:
                    images = (doc.metadata or {}).get("images")
                    if isinstance(images, list):
                        for item in images:
                            img_id = item.get("img_id") if isinstance(item, dict) else None
                            if isinstance(img_id, str) and img_id.strip():
                                document_img_ids.add(img_id)
                    artifact_dir = (doc.metadata or {}).get("artifact_dir")
                    if isinstance(artifact_dir, str) and artifact_dir.strip():
                        artifact_dirs.add(artifact_dir.strip())

            # Inline image assets (non-ragflow path: documents -> documents).
            if parsed.documents:
                with metrics_span("ingest.inline_assets"):
                    inline_result = inline_asset_stage.run(
                        documents=parsed.documents,
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                        document_id=document_id,
                        origin_path=file_path,
                        start_index=0,
                    )
                parsed_documents = inline_result.documents
                for iid in inline_result.uploaded_img_ids:
                    if isinstance(iid, str) and iid.strip():
                        document_img_ids.add(iid)
            else:
                parsed_documents = None

            # Best-effort cleanup for parser artifact directories (e.g., MagicPDF output).
            self._cleanup_parser_artifacts(artifact_dirs, tenant_id=tenant_id)

            await raise_if_cancelled()

            # Governance: normalize/clean documents or ragflow chunks.
            governance_stats: Optional[GovernanceStats] = None
            if parsed.chunks is not None:
                with metrics_span("ingest.normalize"):
                    parsed_chunks = normalize_stage.run(items=parsed.chunks)
                with metrics_span("ingest.governance", enabled=bool(pipeline_effective.governance_enabled)):
                    gov = governance_stage.run(
                        items=parsed_chunks,
                        enabled=bool(pipeline_effective.governance_enabled),
                        kwargs=governance_kwargs,
                    )
                chunks = gov.items
                governance_stats = gov.stats

                if (
                    bool(pipeline_effective.governance_enabled)
                    and governance_stats is not None
                    and not chunks
                    and int(getattr(governance_stats, "dropped", 0) or 0) > 0
                ):
                    self._record_governance_metadata(db, tenant_id, document_id, governance_stats)
                    reasons = getattr(governance_stats, "drop_reasons", {}) or {}
                    reason_str = ", ".join([f"{k}:{v}" for k, v in sorted(reasons.items())]) if isinstance(reasons, dict) else ""
                    msg = (
                        "Document filtered by governance rules"
                        + (f" ({reason_str})" if reason_str else "")
                        + ". You can disable outline/low-density filters or relax thresholds."
                    )
                    logger.warning("%s document_id=%s", msg, document_id)
                    await self._update_status(
                        db,
                        tenant_id,
                        document_id,
                        "failed",
                        0,
                        "failed",
                        chunk_count=0,
                        total_characters=0,
                        error_message=msg,
                    )
                    return {
                        "status": "failed",
                        "reason": "filtered_by_governance",
                        "chunk_count": 0,
                        "total_characters": 0,
                        "parser_backend": resolved_backend,
                        "chunk_strategy": resolved_chunk_strategy,
                    }
            else:
                with metrics_span("ingest.normalize"):
                    parsed_documents = normalize_stage.run(items=parsed_documents or [])
                with metrics_span("ingest.governance", enabled=bool(pipeline_effective.governance_enabled)):
                    gov = governance_stage.run(
                        items=parsed_documents,
                        enabled=bool(pipeline_effective.governance_enabled),
                        kwargs=governance_kwargs,
                    )
                parsed_documents = gov.items
                governance_stats = gov.stats

                if (
                    bool(pipeline_effective.governance_enabled)
                    and governance_stats is not None
                    and not parsed_documents
                    and int(getattr(governance_stats, "dropped", 0) or 0) > 0
                ):
                    self._record_governance_metadata(db, tenant_id, document_id, governance_stats)
                    reasons = getattr(governance_stats, "drop_reasons", {}) or {}
                    reason_str = ", ".join([f"{k}:{v}" for k, v in sorted(reasons.items())]) if isinstance(reasons, dict) else ""
                    msg = (
                        "Document filtered by governance rules"
                        + (f" ({reason_str})" if reason_str else "")
                        + ". You can disable outline/low-density filters or relax thresholds."
                    )
                    logger.warning("%s document_id=%s", msg, document_id)
                    await self._update_status(
                        db,
                        tenant_id,
                        document_id,
                        "failed",
                        0,
                        "failed",
                        chunk_count=0,
                        total_characters=0,
                        error_message=msg,
                    )
                    return {
                        "status": "failed",
                        "reason": "filtered_by_governance",
                        "chunk_count": 0,
                        "total_characters": 0,
                        "parser_backend": resolved_backend,
                        "chunk_strategy": resolved_chunk_strategy,
                    }

                await raise_if_cancelled()

                await self._update_status(db, tenant_id, document_id, "processing", 33, "chunking")
                with metrics_span(
                    "ingest.chunking",
                    chunk_strategy=resolved_chunk_strategy,
                    chunk_size=int(pipeline_effective.chunk_size),
                    chunk_overlap=int(pipeline_effective.chunk_overlap),
                ):
                    chunked = chunking_stage.run(
                        documents=parsed_documents,
                        chunk_strategy=resolved_chunk_strategy,
                        chunk_size=int(pipeline_effective.chunk_size),
                        chunk_overlap=int(pipeline_effective.chunk_overlap),
                    )
                chunks = chunked.chunks

            await raise_if_cancelled()

            # Drop extremely short chunks to reduce retrieval noise (keep image-bearing chunks).
            min_chars = max(0, int(getattr(settings, "CHUNK_MIN_CHARS", 0) or 0))
            if min_chars > 0 and chunks:
                before = len(chunks)
                original_chunks = chunks
                filtered = []
                for c in original_chunks:
                    content = (c.page_content or "").strip()
                    if len(content) >= min_chars:
                        filtered.append(c)
                        continue
                    meta = c.metadata or {}
                    doc_type = str(meta.get("doc_type_kwd") or "").lower()
                    # Keep image/table chunks even if caption is short: they carry important assets.
                    if doc_type in {"image", "table"} or meta.get("image") is not None:
                        filtered.append(c)
                    elif meta.get("img_id") or meta.get("image_id") or meta.get("image_url"):
                        filtered.append(c)
                kept_short_fallback = False
                if not filtered and original_chunks:
                    # Avoid indexing an empty document: keep the longest chunk even if it's short.
                    longest = max(original_chunks, key=lambda d: len((d.page_content or "").strip()))
                    filtered = [longest]
                    kept_short_fallback = True
                chunks = filtered
                dropped = before - len(chunks)
                if kept_short_fallback:
                    kept_len = len((chunks[0].page_content or "").strip()) if chunks else 0
                    logger.info(
                        "All chunks shorter than %s chars; kept 1 (%s chars) and dropped %s for document %s",
                        min_chars,
                        kept_len,
                        dropped,
                        document_id,
                    )
                elif dropped:
                    logger.info("Dropped %s short chunks (<%s chars) for document %s", dropped, min_chars, document_id)

            if governance_stats is not None:
                self._record_governance_metadata(db, tenant_id, document_id, governance_stats)

            await raise_if_cancelled()

            if not chunks:
                msg = (
                    "No chunks produced for document (empty or filtered by CHUNK_MIN_CHARS). "
                    "Consider lowering CHUNK_MIN_CHARS or checking the parser output."
                )
                logger.warning("%s document_id=%s", msg, document_id)
                await self._update_status(
                    db,
                    tenant_id,
                    document_id,
                    "failed",
                    0,
                    "failed",
                    chunk_count=0,
                    total_characters=0,
                    error_message=msg,
                )
                return {
                    "status": "failed",
                    "reason": "no_chunks",
                    "chunk_count": 0,
                    "total_characters": 0,
                    "parser_backend": resolved_backend,
                    "chunk_strategy": resolved_chunk_strategy,
                }

            # Chunk-level assets & metadata (image upload/binding).
            await raise_if_cancelled()
            with metrics_span("ingest.chunk_assets"):
                chunk_asset = chunk_asset_stage.run(
                    chunks=chunks,
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    document_id=document_id,
                    resolved_backend=resolved_backend,
                    resolved_chunk_strategy=resolved_chunk_strategy,
                )
            chunks = chunk_asset.chunks
            for iid in chunk_asset.img_ids:
                if isinstance(iid, str) and iid.strip():
                    document_img_ids.add(iid)

            # If using auto chunking, persist the per-document selection stats for debugging/tuning.
            if resolved_chunk_strategy == "auto" and chunks:
                selected_counts: dict[str, int] = {}
                for c in chunks:
                    meta = c.metadata or {}
                    selected = meta.get("chunk_strategy_selected")
                    if isinstance(selected, str) and selected.strip():
                        selected_counts[selected] = selected_counts.get(selected, 0) + 1
                if selected_counts:
                    self._record_auto_chunking_metadata(
                        db,
                        tenant_id=tenant_id,
                        document_id=document_id,
                        selected_counts=selected_counts,
                    )

            # Persist all image img_id values to document.metadata (for cleanup).
            self._record_document_image_ids(db, tenant_id=tenant_id, document_id=document_id, img_ids=document_img_ids)

            await raise_if_cancelled()

            await self._update_status(db, tenant_id, document_id, "processing", 66, "embedding")

            await raise_if_cancelled()

            with metrics_span(
                "ingest.index",
                chunk_count=len(chunks),
                chunk_vector_enabled=bool(getattr(index_options, "chunk_vector_enabled", True)),
                bm25_index_enabled=bool(getattr(index_options, "bm25_index_enabled", True)),
            ):
                indexed = index_stage.run(
                    db=db,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    file_path=file_path,
                    chunks=chunks,
                    options=index_options,
                )
            chunk_ids = indexed.chunk_ids
            total_chars = indexed.total_characters
            log_metrics(
                {
                    "event": "ingest.index.result",
                    "chunk_count": len(chunks),
                    "total_characters": total_chars,
                }
            )

            await raise_if_cancelled(force=True)

            await self._update_status(
                db,
                tenant_id,
                document_id,
                "completed",
                100,
                "completed",
                chunk_count=len(chunks),
                total_characters=total_chars
            )

            logger.info(
                "Document processed: %s chunks (parser=%s, chunker=%s)",
                len(chunks),
                resolved_backend,
                resolved_chunk_strategy,
            )
            log_metrics(
                {
                    "event": "ingest.completed",
                    "chunk_count": len(chunks),
                    "total_characters": total_chars,
                    "parser_backend": resolved_backend,
                    "chunk_strategy": resolved_chunk_strategy,
                    "img_count": len(document_img_ids),
                }
            )

            # Step 7: run KG extraction (events/entities) when enabled.
            if pipeline_effective.kg_enabled:
                # When queue is enabled, move KG extraction to the worker for better ingest throughput.
                if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
                    try:
                        from app.tasks.queue import enqueue_kg_extraction

                        pipeline_hash = (db_document.doc_metadata or {}).get("pipeline_hash") or "unknown"
                        job_id = f"kg:{tenant_id}:{document_id}:{pipeline_hash}"
                        kg_task_id = await enqueue_kg_extraction(
                            tenant_id=tenant_id,
                            document_id=document_id,
                            requested_by="system",
                            job_id=job_id,
                        )
                        if kg_task_id:
                            meta = dict(db_document.doc_metadata or {})
                            meta["kg_task_id"] = kg_task_id
                            db_document.doc_metadata = meta
                            db.commit()
                            db.refresh(db_document)
                        logger.info("KG extraction enqueued for document %s (task_id=%s)", document_id, kg_task_id)
                        log_metrics(
                            {
                                "event": "ingest.kg.enqueued",
                                "kg_task_id": kg_task_id,
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        # Queue errors should not affect the main document flow.
                        logger.warning("Failed to enqueue KG extraction: %s", str(exc)[:200])
                else:
                    logger.info("Running KG extraction on document chunks...")
                    prompt_template_id = None
                    raw_tid = (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "").strip()
                    if raw_tid:
                        try:
                            prompt_template_id = UUID(raw_tid)
                        except Exception:
                            logger.warning("Invalid KG_EXTRACT_PROMPT_TEMPLATE_ID: %s", raw_tid[:50])
                    try:
                        events = await extract_events(
                            chunk_ids,
                            tenant_id=tenant_id,
                            chunks=indexed.db_chunks,
                            index_options=index_options,
                            prompt_template_id=prompt_template_id,
                            prompt_template_key=(getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip() or None,
                            prompt_ab_experiment_key=(getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or "").strip() or None,
                        )
                        logger.info("KG extracted %s events for document %s", len(events), document_id)
                        log_metrics({"event": "ingest.kg.completed", "event_count": len(events)})
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("KG extraction failed for document %s: %s", document_id, str(exc)[:200])

            return {
                "status": "success",
                "chunk_count": len(chunks),
                "total_characters": total_chars,
                "parser_backend": resolved_backend,
                "chunk_strategy": resolved_chunk_strategy
            }

        except DocumentCancelledError as e:
            logger.info("Document processing cancelled: tenant=%s document=%s (%s)", tenant_id, document_id, str(e)[:120])
            # Roll back any uncommitted DB work (e.g., flushed chunks) to avoid committing partial results.
            try:
                db.rollback()
            except Exception:
                pass
            # Best-effort cleanup for vector/BM25 side effects (indexing is not transactional).
            try:
                Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
            except Exception:
                pass
            await self._update_status(
                db,
                tenant_id,
                document_id,
                "cancelled",
                0,
                "cancelled",
                error_message="cancelled",
            )
            return {"status": "cancelled"}
        except asyncio.CancelledError:
            # arq Job.abort cancels the coroutine; ensure we stop the child parser process and persist status.
            try:
                db.rollback()
            except Exception:
                pass
            try:
                Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
            except Exception:
                pass
            try:
                await asyncio.shield(
                    self._update_status(
                        db,
                        tenant_id,
                        document_id,
                        "cancelled",
                        0,
                        "cancelled",
                        error_message="cancelled",
                    )
                )
            except Exception:
                pass
            raise
        except Exception as e:
            # Error handling.
            logger.exception("Error processing document %s: %s", document_id, e)
            log_metrics({"event": "ingest.failed", "success": False, "error": str(e)[:200]})
            try:
                db.rollback()
            except Exception:
                pass
            try:
                Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)
            except Exception:
                pass
            await self._update_status(
                db,
                tenant_id,
                document_id,
                "failed",
                0,
                "failed",
                error_message=str(e)
            )
            raise
        finally:
            if owns_db:
                db.close()

    async def _update_status(
        self,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        status: str,
        progress: int,
        stage: str,
        **kwargs
    ):
        """Update document processing status."""
        db_doc = (
            db.query(DBDocument)
            .populate_existing()
            .filter(
                DBDocument.id == document_id,
                DBDocument.tenant_id == tenant_id,
            )
            .first()
        )

        if db_doc:
            # Do not overwrite a user-requested cancellation from a long-running worker.
            current_status = str(db_doc.status or "").lower()
            if current_status == "cancelled" and str(status).lower() != "cancelled":
                return
            meta = db_doc.doc_metadata or {}
            if isinstance(meta, dict) and bool(meta.get("cancel_requested")) and str(status).lower() != "cancelled":
                return

            db_doc.status = status
            db_doc.processing_progress = progress
            db_doc.current_stage = stage

            for key, value in kwargs.items():
                setattr(db_doc, key, value)

            db.commit()
            db.refresh(db_doc)

    async def _rebuild_bm25_index_for_tenant(self, db: Session, tenant_id: UUID):
        """Rebuild BM25 index for a specific tenant."""
        try:
            if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
                try:
                    from app.tasks.queue import enqueue_rebuild_indexes

                    job_id = f"rebuild:{tenant_id}"
                    await enqueue_rebuild_indexes(tenant_id=tenant_id, requested_by="system", job_id=job_id)
                    logger.info("Rebuild indexes enqueued for tenant %s", tenant_id)
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to enqueue rebuild indexes (fallback to inline): %s", str(exc)[:200])

            any_chunk = (
                db.query(DocumentChunk.id)
                .join(DBDocument)
                .filter(DBDocument.status == "completed", DocumentChunk.tenant_id == tenant_id)
                .limit(1)
                .first()
            )
            if not any_chunk:
                logger.warning("No chunks found for BM25 index")
                return

            logger.info("Rebuilding BM25 index for tenant %s", tenant_id)
            Indexer(db).rebuild_tenant(tenant_id=tenant_id, kinds=[IndexKind.CHUNK])

        except Exception as e:
            logger.warning("Failed to rebuild BM25 index: %s", e)

    async def _rebuild_bm25_index(self, db: Session):
        """Rebuild BM25 indexes for all tenants."""
        try:
            if bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
                try:
                    from app.tasks.queue import enqueue_rebuild_indexes

                    tenant_rows = db.query(DocumentChunk.tenant_id).distinct().all()
                    tenant_ids = [row[0] for row in tenant_rows if row and row[0]]
                    for tid in tenant_ids:
                        job_id = f"rebuild:{tid}"
                        await enqueue_rebuild_indexes(tenant_id=tid, requested_by="system", job_id=job_id)
                    logger.info("Rebuild indexes enqueued for %s tenants", len(tenant_ids))
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to enqueue rebuild indexes (fallback to inline): %s", str(exc)[:200])

            tenant_ids: List[UUID] = []
            q = (
                db.query(DocumentChunk.tenant_id)
                .distinct()
                .execution_options(stream_results=True)
                .enable_eagerloads(False)
            )
            for row in q.yield_per(2000):
                if row and row[0]:
                    tenant_ids.append(row[0])
            if not tenant_ids:
                logger.warning("No chunks found for BM25 index")
                return
            for tid in tenant_ids:
                Indexer(db).rebuild_tenant(tenant_id=tid, kinds=[IndexKind.CHUNK])
        except Exception as e:
            logger.warning("Failed to rebuild BM25 index: %s", e)

    def _record_processing_metadata(
        self,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        parser_backend: str,
        chunk_strategy: str
    ):
        """Ensure document metadata records the final parser selection."""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        ).first()

        if not db_doc:
            return

        metadata = dict(db_doc.doc_metadata or {})
        metadata["parser_backend"] = parser_backend
        metadata["chunk_strategy"] = chunk_strategy
        metadata.setdefault("parser_backend_requested", parser_backend)
        metadata.setdefault("chunk_strategy_requested", chunk_strategy)

        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)
        # Avoid raising errors to keep the document flow intact.

    def _cleanup_parser_artifacts(self, artifact_dirs: set[str], *, tenant_id: UUID) -> None:
        if not artifact_dirs:
            return
        if bool(getattr(settings, "MAGIC_PDF_KEEP_ARTIFACTS", False)):
            return

        upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
        tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)

        for raw in sorted(artifact_dirs):
            try:
                path = Path(raw).resolve(strict=False)
                if not path.exists():
                    continue
                if not any(p in path.parts for p in {".magicpdf", ".deepseek_ocr", ".etl4llm", ".marker", ".paddlevl", ".olmocr", ".mimirq_parse"}):
                    continue
                # Safety: only delete within this tenant's upload directory.
                path.relative_to(tenant_root)
            except Exception:
                logger.warning("Skipping unsafe parser artifact cleanup: %s", str(raw)[:200])
                continue

            try:
                shutil.rmtree(path, ignore_errors=True)
            except Exception:
                # Best-effort only.
                pass

    def _record_pipeline_effective(
        self,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        effective: PipelineEffective,
    ) -> None:
        """Persist effective pipeline settings on the document metadata."""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        ).first()

        if not db_doc:
            return

        metadata = dict(db_doc.doc_metadata or {})
        metadata["pipeline_effective"] = {
            "governance_enabled": bool(effective.governance_enabled),
            "governance_remove_toc_lines": bool(effective.governance_remove_toc_lines),
            "governance_remove_noise_lines": bool(effective.governance_remove_noise_lines),
            "governance_unwrap_lines": bool(effective.governance_unwrap_lines),
            "governance_remove_common_lines": bool(effective.governance_remove_common_lines),
            "governance_unwrap_max_line_length": int(effective.governance_unwrap_max_line_length),
            "governance_noise_min_chars": int(effective.governance_noise_min_chars),
            "governance_noise_ratio_threshold": float(effective.governance_noise_ratio_threshold),
            "governance_common_lines_min_docs": int(effective.governance_common_lines_min_docs),
            "governance_common_lines_min_ratio": float(effective.governance_common_lines_min_ratio),
            "chunk_size": int(effective.chunk_size),
            "chunk_overlap": int(effective.chunk_overlap),
            "chunk_vector_enabled": bool(effective.chunk_vector_enabled),
            "bm25_index_enabled": bool(effective.bm25_index_enabled),
            "kg_enabled": bool(effective.kg_enabled),
            "event_vector_enabled": bool(effective.event_vector_enabled),
            "entity_vector_enabled": bool(effective.entity_vector_enabled),
        }

        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _record_governance_metadata(
        self,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        stats: GovernanceStats,
    ) -> None:
        """Persist governance stats on the document metadata."""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        ).first()

        if not db_doc:
            return

        metadata = dict(db_doc.doc_metadata or {})
        metadata["governance_enabled"] = True
        metadata["governance_documents"] = int(stats.documents)
        metadata["governance_changed_documents"] = int(stats.changed)
        metadata["governance_rules_applied"] = int(stats.applied_rules)
        metadata["governance_dropped_documents"] = int(getattr(stats, "dropped", 0) or 0)
        reasons = getattr(stats, "drop_reasons", None)
        if isinstance(reasons, dict) and reasons:
            metadata["governance_drop_reasons"] = {str(k): int(v) for k, v in reasons.items()}

        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _record_auto_chunking_metadata(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        selected_counts: dict[str, int],
    ) -> None:
        """Persist auto-chunk selection stats on the document metadata."""
        db_doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not db_doc:
            return
        metadata = dict(db_doc.doc_metadata or {})
        metadata["auto_chunking"] = {
            "selected_counts": {str(k): int(v) for k, v in sorted(selected_counts.items())},
        }
        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _record_document_image_ids(self, db: Session, tenant_id: UUID, document_id: UUID, img_ids: set[str]):
        """
        Store all img_id values for a document in documents.metadata for cleanup.

        Notes:
        - This is a document-level aggregated list (deduped); it does not affect per-chunk img_id.
        - Only written when MinIO is enabled to avoid misleading metadata.
        """
        if not settings.MINIO_ENABLED:
            return
        if not img_ids:
            return

        db_doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not db_doc:
            return

        metadata = dict(db_doc.doc_metadata or {})
        existing = metadata.get("img_ids")
        merged: set[str] = set()
        if isinstance(existing, list):
            for v in existing:
                if isinstance(v, str) and v.strip():
                    merged.add(v)

        merged |= {v for v in img_ids if isinstance(v, str) and v.strip()}
        if not merged:
            return

        metadata["img_ids"] = sorted(merged)
        metadata["image_count"] = len(merged)
        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _extract_img_id_from_content(self, content: str) -> Optional[str]:
        """
        Extract the first image-url/{img_id} from chunk content to backfill chunk metadata.
        """
        if not isinstance(content, str) or not content:
            return None

        # Supported patterns:
        # - ![](/api/v1/documents/image-url/{img_id})
        # - <img src="/api/v1/documents/image-url/{img_id}">
        # - http://host/api/v1/documents/image-url/{img_id}
        pattern = re.compile(r"(?:https?://[^\s)\"']+)?/api/v1/documents/image-url/([^\s)\"']+)")
        m = pattern.search(content)
        if not m:
            return None
        img_id = m.group(1)
        return img_id.strip() or None

    def _upload_inline_images_to_minio(
        self,
        markdown_text: str,
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        cache: dict[str, str],
        start_index: int = 0,
        origin_path: Optional[Path] = None,
    ) -> tuple[str, List[str], int]:
        """
        Upload image references in Markdown/HTML to MinIO and rewrite to /image-url/{img_id}.

        Supported:
        - data URI: data:image/...
        - local/relative paths: ![alt](images/foo.png) or <img src="images/foo.png">
          path resolution is relative to `origin_path.parent` (absolute paths are used as-is).
        - skip http/https URLs or already rewritten /api/v1/documents/image-url/... refs.

        Returns:
        - rewritten markdown_text
        - list of newly uploaded img_id values
        - updated asset index (for stable chunk_key: asset{n})
        """
        if not settings.MINIO_ENABLED:
            return markdown_text, [], start_index
        if not isinstance(markdown_text, str) or not markdown_text:
            return markdown_text, [], start_index
        lowered = markdown_text.lower()
        if "data:image" not in lowered and "![" not in lowered and "<img" not in lowered:
            return markdown_text, [], start_index

        # Only process Markdown images and HTML img tags, matching src content.
        md_pat = re.compile(
            r"!\[[^\]]*\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['\"][^'\"]*['\"])?\s*\)",
            flags=re.IGNORECASE,
        )
        html_pat = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", flags=re.IGNORECASE)

        found: List[str] = []
        seen: set[str] = set()
        for pat in (md_pat, html_pat):
            for m in pat.finditer(markdown_text):
                ref = m.group(1)
                if not isinstance(ref, str) or not ref:
                    continue
                ref = ref.strip()
                if ref in seen:
                    continue
                seen.add(ref)
                found.append(ref)

        if not found:
            return markdown_text, [], start_index

        max_inline_images = max(0, int(getattr(settings, "MAX_INLINE_IMAGES", 0) or 0))
        if max_inline_images and len(found) > max_inline_images:
            found = found[:max_inline_images]

        new_ids: List[str] = []
        idx = int(start_index or 0)
        replacements: dict[str, str] = {}

        base_dir = origin_path.parent if origin_path else None
        if origin_path is not None:
            origin_path = origin_path.resolve(strict=False)
            base_dir = origin_path if origin_path.is_dir() else origin_path.parent
        base_dir_resolved = base_dir.resolve(strict=False) if base_dir else None
        max_image_bytes = int(getattr(settings, "MAX_INLINE_IMAGE_BYTES", 10_000_000) or 10_000_000)
        max_image_bytes = max(1_000_000, max_image_bytes)

        for ref in found:
            # Already remote or already rewritten.
            if ref.lower().startswith(("http://", "https://")):
                continue
            if "/api/v1/documents/image-url/" in ref:
                continue

            is_data_uri = ref.startswith("data:image")

            try:
                if is_data_uri:
                    header, b64_part = ref.split(",", 1)
                    if "base64" not in header:
                        continue
                    b64_part = re.sub(r"\s+", "", b64_part)
                    if len(b64_part) > int(max_image_bytes * 4 / 3) + 32:
                        continue
                    binary = base64.b64decode(b64_part)
                else:
                    # Local/relative path.
                    path_obj = Path(ref)
                    if not path_obj.is_absolute():
                        if not base_dir_resolved:
                            continue
                        path_obj = (base_dir_resolved / path_obj).resolve(strict=False)
                    else:
                        if not base_dir_resolved:
                            continue
                        path_obj = path_obj.resolve(strict=False)
                    if base_dir_resolved:
                        try:
                            path_obj.relative_to(base_dir_resolved)
                        except Exception:
                            continue
                    if not path_obj.exists() or not path_obj.is_file():
                        continue
                    try:
                        if path_obj.stat().st_size > max_image_bytes:
                            continue
                    except Exception:
                        continue
                    binary = path_obj.read_bytes()
                if len(binary) > max_image_bytes:
                    continue

                # Convert to JPEG.
                img = None
                converted = None
                try:
                    img = PILImage.open(BytesIO(binary))
                    if img.mode in ("RGBA", "P"):
                        converted = img.convert("RGB")
                        out_img = converted
                    else:
                        out_img = img
                    out = BytesIO()
                    out_img.save(out, format="JPEG", quality=85, optimize=True)
                    image_bytes = out.getvalue()
                finally:
                    if converted is not None:
                        try:
                            converted.close()
                        except Exception:
                            pass
                    if img is not None:
                        try:
                            img.close()
                        except Exception:
                            pass

                digest = hashlib.sha256(image_bytes).hexdigest()
                img_id = cache.get(digest)
                if not img_id:
                    chunk_key = f"asset{idx}"
                    idx += 1
                    img_id = minio_service.upload_image(
                        image_data=image_bytes,
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                        document_id=document_id,
                        chunk_key=chunk_key,
                        extension="jpg",
                    )
                    cache[digest] = img_id
                    new_ids.append(img_id)

                url = f"/api/v1/documents/image-url/{img_id}"
                replacements[ref] = url

            except Exception as e:
                logger.warning("Inline/local image upload failed (skipped): %s", e)
                continue

        if replacements:
            # Single-pass replacement to avoid N full-text replaces (O(N*M)).
            def _md_repl(m: re.Match) -> str:
                raw = m.group(1) or ""
                key = raw.strip()
                new = replacements.get(key)
                if not new:
                    return m.group(0)
                return m.group(0).replace(raw, new, 1)

            def _html_repl(m: re.Match) -> str:
                raw = m.group(1) or ""
                key = raw.strip()
                new = replacements.get(key)
                if not new:
                    return m.group(0)
                return m.group(0).replace(raw, new, 1)

            markdown_text = md_pat.sub(_md_repl, markdown_text)
            markdown_text = html_pat.sub(_html_repl, markdown_text)

        return markdown_text, new_ids, idx

    def _ragflow_chunk_file(self, file_path: Path, strategy: str):
        """
        Use ragflow presets (naive/book/laws/email) to parse and chunk directly.
        Returns a list of LangChain Documents.
        """
        from langchain_core.documents import Document

        from app.rag.chunking.ragflow import chunk_file

        chunks_dict = chunk_file(file_path, strategy=strategy)  # type: ignore[arg-type]

        documents = []
        for item in chunks_dict:
            text = item.get("content_with_weight") or item.get("text") or ""
            if not text:
                continue
            meta = {k: v for k, v in item.items() if k not in {"content_with_weight", "text", "content_ltks", "content_sm_ltks"}}
            documents.append(Document(page_content=text, metadata=meta))

        return documents

    def _extract_and_upload_image_to_minio(
        self,
        metadata: Dict[str, Any],
        tenant_id: str,
        dataset_id: str,
        document_id: str,
        chunk_index: int,
    ) -> Optional[str]:
        """
        Detect image data in chunk metadata, upload to MinIO, and return img_id.
        After upload, original image data is removed from metadata to save memory.

        img_id format: "{tenant_id}:{dataset_id}:{document_id}:{chunk_index}"

        Recognized fields: image (PIL.Image/bytes) / image_base64 / img_base64 / img / image_data
        """
        # If img_id already exists, return it.
        if isinstance(metadata.get("img_id"), str) and metadata.get("img_id").strip():
            return metadata.get("img_id")

        # If MinIO is disabled, ensure non-serializable fields are removed.
        if not settings.MINIO_ENABLED:
            if "image" in metadata:
                metadata.pop("image", None)
            return None

        # Find image data.
        possible_keys = ["image_base64", "image", "img_base64", "img", "image_data"]
        found_key = None
        raw_image = None
        b64_data = None

        # ragflow may place PIL.Image/bytes in metadata["image"].
        # Only upload for real image chunks (doc_type_kwd == "image").
        val = metadata.get("image")
        if val is not None:
            doc_type = str(metadata.get("doc_type_kwd") or "").lower()
            if doc_type == "image":
                raw_image = val
                found_key = "image"
            else:
                # Non-image chunk: drop image field to avoid JSON serialization failure.
                metadata.pop("image", None)

        if raw_image is None:
            for key in possible_keys:
                val = metadata.get(key)
                if isinstance(val, str) and val.strip():
                    b64_data = val
                    found_key = key
                    break
        
        if raw_image is None and not b64_data:
            return None

        # Handle data URI format.
        if isinstance(b64_data, str) and b64_data.startswith("data:"):
            parts = b64_data.split(",", 1)
            if len(parts) == 2:
                b64_data = parts[1]

        # Convert to JPEG bytes (save storage, simplify reading).
        try:
            if raw_image is not None:
                if isinstance(raw_image, bytes):
                    img = PILImage.open(BytesIO(raw_image))
                else:
                    img = raw_image
            else:
                binary = base64.b64decode(b64_data)
                img = PILImage.open(BytesIO(binary))

            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            out = BytesIO()
            img.save(out, format="JPEG", quality=85, optimize=True)
            image_bytes = out.getvalue()
        except Exception as e:
            logger.warning("Image conversion failed (skip upload): %s", e)
            # Always drop the image field to avoid persistence failures.
            if found_key == "image":
                metadata.pop("image", None)
            return None
        finally:
            if raw_image is not None and not isinstance(raw_image, bytes) and hasattr(raw_image, "close"):
                try:
                    raw_image.close()
                except Exception:
                    pass

        # Upload to MinIO.
        try:
            img_id = minio_service.upload_image(
                image_data=image_bytes,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
                chunk_key=str(chunk_index),
                extension="jpg",
            )
            
            # After upload, delete in-memory image data to save resources.
            if found_key:
                del metadata[found_key]
            
            # Clean up other possible image fields.
            for key in possible_keys:
                if key in metadata and key != found_key:
                    del metadata[key]

            logger.info("Image uploaded and bound: img_id=%s", img_id)
            return img_id
            
        except Exception as e:
            logger.error("Image upload failed: %s", e)
            return None

    def _extract_and_save_image(self, metadata: Dict[str, Any], tenant_id: UUID) -> Optional[str]:
        """
        Fallback: detect image data in chunk metadata and save to local disk.
        Used when MinIO is disabled.
        """
        if isinstance(metadata.get("img_id"), str) and metadata.get("img_id").strip():
            return metadata.get("img_id")

        possible_keys = ["image_base64", "image", "img_base64", "img"]
        b64_data = None
        for key in possible_keys:
            val = metadata.get(key)
            if isinstance(val, str) and val.strip():
                b64_data = val
                break
        if not b64_data:
            return None

        if b64_data.startswith("data:"):
            parts = b64_data.split(",", 1)
            if len(parts) == 2:
                b64_data = parts[1]

        try:
            binary = base64.b64decode(b64_data)
        except Exception:
            return None

        image_id = hashlib.sha256(binary).hexdigest()[:32]
        images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        file_path = images_dir / f"{image_id}.png"
        if not file_path.exists():
            with file_path.open("wb") as f:
                f.write(binary)

        return image_id


# Global instance.
document_processor = DocumentProcessorService()
