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
from app.models.document import Document as DBDocument, DocumentChunk, DocumentParsedContent
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
from app.rag.preprocessing.rules import build_governance_rules
from app.rag.preprocessing.normalization import normalize_text
from app.rag.preprocessing.simhash import simhash64, simhash64_hex
from app.rag.preprocessing.near_dedup import add_simhashes, find_near_duplicate, with_near_dedup_index
from app.rag.kg.pipeline import extract_events
from app.parsing.routing import route_pdf_backend
from app.parsing.quality.text_quality import score_parsed_text_quality
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
class ChunkDedupResult:
    chunks: List[Document]
    duplicates_dropped: int


@dataclass(frozen=True)
class ChunkAssetResult:
    chunks: List[Document]
    img_ids: List[str]


@dataclass(frozen=True)
class IndexResult:
    chunk_ids: List[UUID]
    total_characters: int
    db_chunks: List[DocumentChunk]


def _chunk_has_asset(meta: dict[str, Any]) -> bool:
    doc_type = str(meta.get("doc_type_kwd") or "").lower()
    if doc_type in {"image", "table"}:
        return True
    if meta.get("image") is not None:
        return True
    if isinstance(meta.get("image_path"), str) and meta.get("image_path").strip():
        return True
    return bool(meta.get("img_id") or meta.get("image_id") or meta.get("image_url"))


def _uniform_sample_indices(indices: List[int], k: int) -> List[int]:
    if k <= 0:
        return []
    if k >= len(indices):
        return list(indices)
    if len(indices) == 1:
        return [indices[0]]
    if k == 1:
        return [indices[len(indices) // 2]]

    n = len(indices)
    picked: List[int] = []
    seen: set[int] = set()
    for i in range(k):
        pos = round(i * (n - 1) / (k - 1))
        pos = max(0, min(n - 1, int(pos)))
        idx = indices[pos]
        if idx in seen:
            continue
        seen.add(idx)
        picked.append(idx)

    if len(picked) < k:
        for idx in indices:
            if idx in seen:
                continue
            seen.add(idx)
            picked.append(idx)
            if len(picked) >= k:
                break

    return picked[:k]


def _truncate_chunks_for_limit(
    chunks: List[Document],
    *,
    max_chunks: int,
    strategy: str,
) -> tuple[List[Document], dict[str, Any]]:
    if max_chunks <= 0 or not chunks or len(chunks) <= max_chunks:
        return chunks, {"strategy": (strategy or "head").strip().lower() or "head", "asset_total": 0, "asset_kept": 0}

    strategy_norm = (strategy or "head").strip().lower() or "head"
    total = len(chunks)

    asset_indices: List[int] = []
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata if isinstance(getattr(chunk, "metadata", None), dict) else {}
        if _chunk_has_asset(meta):
            asset_indices.append(idx)

    if strategy_norm not in {"head", "asset_uniform"}:
        strategy_norm = "head"

    if strategy_norm == "head":
        kept_chunks = chunks[:max_chunks]
        asset_kept = 0
        for c in kept_chunks:
            meta = c.metadata if isinstance(getattr(c, "metadata", None), dict) else {}
            if _chunk_has_asset(meta):
                asset_kept += 1
        return kept_chunks, {
            "strategy": "head",
            "asset_total": int(len(asset_indices)),
            "asset_kept": int(asset_kept),
        }

    # asset_uniform: keep first chunk + assets, then uniformly sample remaining text chunks.
    must_keep: List[int] = [0]
    for idx in asset_indices:
        if idx not in must_keep:
            must_keep.append(idx)

    if len(must_keep) > max_chunks:
        must_keep = must_keep[:max_chunks]

    remaining_slots = max_chunks - len(must_keep)
    keep_set = set(must_keep)
    if remaining_slots > 0:
        candidate_indices = [i for i in range(total) if i not in keep_set]
        sampled = _uniform_sample_indices(candidate_indices, remaining_slots)
        keep_set |= set(sampled)

    kept_chunks = [chunks[i] for i in range(total) if i in keep_set]
    asset_kept = 0
    for idx in asset_indices:
        if idx in keep_set:
            asset_kept += 1

    return kept_chunks, {
        "strategy": "asset_uniform",
        "asset_total": int(len(asset_indices)),
        "asset_kept": int(asset_kept),
    }


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
            cancel_check = self._svc._build_cancel_check(db=db, tenant_id=tenant_id, document_id=document_id)

            async def cancel_check_worker() -> bool:
                return await cancel_check()

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
                    cancel_check=cancel_check_worker,
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
        cancel_check = self._svc._build_cancel_check(db=db, tenant_id=tenant_id, document_id=document_id)

        async def cancel_check_worker() -> bool:
            return await cancel_check()

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
                cancel_check=cancel_check_worker,
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

        # Attach lightweight parsed-text quality metrics for observability/tuning.
        try:
            joined = "\n\n".join([(d.page_content or "") for d in documents])
            quality = score_parsed_text_quality(joined).to_dict()
            meta = dict(db_document.doc_metadata or {})
            meta["parsed_text_quality"] = quality
            db_document.doc_metadata = meta
            db.commit()
            db.refresh(db_document)
        except Exception:
            pass

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


class ChunkDedupStage:
    def run(self, *, chunks: List[Document], enabled: bool) -> ChunkDedupResult:
        """
        Drop exact-duplicate *text* chunks within a single document.

        Notes:
        - Keeps image/table-related chunks even if their text matches (assets matter).
        - Uses a normalized content hash for comparison (line endings/control chars).
        """
        if not enabled or not chunks:
            return ChunkDedupResult(chunks=chunks, duplicates_dropped=0)

        seen: set[str] = set()
        out: List[Document] = []
        dropped = 0

        for c in chunks:
            raw = c.page_content or ""
            normalized = normalize_text(raw, normalize_line_endings=True, remove_control_chars=True)
            digest = hashlib.sha256(normalized.strip().encode("utf-8", "ignore")).hexdigest()

            meta = dict(c.metadata or {})
            meta.setdefault("content_hash", digest)
            meta.setdefault("content_hash_algo", "sha256")
            meta.setdefault("content_len", len(normalized.strip()))

            doc_type = str(meta.get("doc_type_kwd") or "").lower()
            has_asset = (
                doc_type in {"image", "table"}
                or meta.get("image") is not None
                or bool(meta.get("img_id") or meta.get("image_id") or meta.get("image_url"))
            )
            if not has_asset:
                if digest in seen:
                    dropped += 1
                    continue
                seen.add(digest)

            out.append(Document(page_content=c.page_content, metadata=meta, id=getattr(c, "id", None)))

        return ChunkDedupResult(chunks=out, duplicates_dropped=dropped)


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
            meta.setdefault("dataset_id", str(dataset_id))
            meta["document_id"] = str(document_id)
            meta["chunk_index"] = idx
            meta["parser_backend"] = resolved_backend
            meta["chunk_strategy"] = resolved_chunk_strategy
            meta.setdefault("chunk_key", f"{str(document_id)}:{idx}")

            content_norm = normalize_text(chunk.page_content or "", normalize_line_endings=True, remove_control_chars=True)
            meta.setdefault("content_len", len(content_norm.strip()))
            if not isinstance(meta.get("content_hash"), str) or not str(meta.get("content_hash") or "").strip():
                meta["content_hash"] = hashlib.sha256(content_norm.strip().encode("utf-8", "ignore")).hexdigest()
                meta.setdefault("content_hash_algo", "sha256")
            if not isinstance(meta.get("simhash64"), str) or not str(meta.get("simhash64") or "").strip():
                try:
                    meta["simhash64"] = simhash64_hex(simhash64(content_norm))
                    meta.setdefault("simhash_algo", "simhash64_sha1")
                except Exception:
                    # Best-effort only.
                    pass
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
        default_source: str,
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
            default_source=str(default_source or "").strip() or str(file_path.name),
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

    def _build_cancel_check(
        self,
        *,
        db: Session,
        tenant_id: UUID,
        document_id: UUID,
        poll_interval_sec: float = 1.0,
    ):
        """
        Build a cached cancel-check closure.

        This is shared by:
        - ingest pipeline (DocumentProcessorService)
        - parsing subprocess runner (ParsingStage)
        """
        last_check = 0.0
        cached_cancel = False

        async def cancel_check(*, force: bool = False) -> bool:
            nonlocal last_check, cached_cancel
            now = time.monotonic()
            if not force and (now - last_check) < float(poll_interval_sec):
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

        return cancel_check

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
            cancel_check = self._build_cancel_check(db=db, tenant_id=tenant_id, document_id=document_id)

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
            extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
            combined_rules = build_governance_rules(extra_rules) if extra_rules else None
            governance_kwargs = {
                **({"rules": combined_rules} if combined_rules else {}),
                "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
                "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
                "unwrap_lines": pipeline_effective.governance_unwrap_lines,
                "remove_common_lines": pipeline_effective.governance_remove_common_lines,
                "remove_boilerplate": pipeline_effective.governance_remove_boilerplate,
                "remove_images": pipeline_effective.governance_remove_images,
                "extract_frontmatter": pipeline_effective.governance_extract_frontmatter,
                "strip_frontmatter": pipeline_effective.governance_strip_frontmatter,
                "detect_language": pipeline_effective.governance_detect_language,
                "language_min_chars": pipeline_effective.governance_language_min_chars,
                "normalize_urls": pipeline_effective.governance_normalize_urls,
                "normalize_urls_strip_tracking": pipeline_effective.governance_normalize_urls_strip_tracking,
                "drop_duplicate_paragraphs": pipeline_effective.governance_drop_duplicate_paragraphs,
                "drop_duplicate_paragraphs_min_occurrences": pipeline_effective.governance_drop_duplicate_paragraphs_min_occurrences,
                "drop_duplicate_paragraphs_min_chars": pipeline_effective.governance_drop_duplicate_paragraphs_min_chars,
                "drop_duplicate_paragraphs_max_chars": pipeline_effective.governance_drop_duplicate_paragraphs_max_chars,
                "trim_references": pipeline_effective.governance_trim_references,
                "extract_keywords": pipeline_effective.governance_extract_keywords,
                "keywords_provider": pipeline_effective.governance_keywords_provider,
                "keywords_top_k": pipeline_effective.governance_keywords_top_k,
                "keywords_max_chars": pipeline_effective.governance_keywords_max_chars,
                "normalize_tables": pipeline_effective.governance_normalize_tables,
                "strip_code_line_numbers": pipeline_effective.governance_strip_code_line_numbers,
                "pii_anonymize": pipeline_effective.governance_pii_anonymize,
                "pii_mode": pipeline_effective.governance_pii_mode,
                "pii_mask": pipeline_effective.governance_pii_mask,
                "secrets_redact": pipeline_effective.governance_secrets_redact,
                "secrets_mode": pipeline_effective.governance_secrets_mode,
                "secrets_mask": pipeline_effective.governance_secrets_mask,
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
            chunk_dedup_stage = ChunkDedupStage()
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

            # Optional: retry parsing with an alternative backend when output quality is obviously low.
            if (
                bool(getattr(pipeline_effective, "parse_fallback_enabled", False))
                and file_path.suffix.lower() == ".pdf"
                and (str(parser_backend or "").strip().lower() in {"", "auto"})
                and parsed.documents is not None
            ):
                try:
                    min_chars = max(0, int(getattr(pipeline_effective, "parse_fallback_min_content_chars", 0) or 0))
                    max_retries = max(0, int(getattr(pipeline_effective, "parse_fallback_max_retries", 0) or 0))
                    if min_chars > 0 and max_retries > 0:
                        joined = "\n\n".join([(d.page_content or "") for d in (parsed.documents or [])])
                        q0 = score_parsed_text_quality(joined)
                        if int(getattr(q0, "content_chars", 0) or 0) < min_chars:
                            from app.parsing.utils.cli import resolve_cli_command

                            def _magicpdf_available() -> bool:
                                if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
                                    return False
                                cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
                                return bool(resolve_cli_command(cli))

                            candidates: list[str] = []
                            current = str(parsed.resolved_backend or "").strip().lower()

                            if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
                                candidates.append("mineru")
                            if bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False)) and bool(
                                (getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()
                            ):
                                candidates.append("deepseek_ocr")
                            if bool(getattr(settings, "ETL4LLM_ENABLED", False)) and bool(
                                (getattr(settings, "ETL4LLM_API_URL", "") or "").strip()
                            ):
                                candidates.append("etl4llm")
                            if settings.DEEPDOC_ENABLED:
                                candidates.append("deepdoc")
                            if getattr(settings, "DOCLING_ENABLED", False):
                                candidates.append("docling")
                            if _magicpdf_available():
                                candidates.append("magicpdf")
                            if settings.MARKITDOWN_ENABLED:
                                candidates.append("markitdown")
                            candidates.append("basic")

                            # Remove current backend and keep order.
                            filtered: list[str] = []
                            for c in candidates:
                                c_norm = (c or "").strip().lower()
                                if not c_norm or c_norm == current:
                                    continue
                                if c_norm not in filtered:
                                    filtered.append(c_norm)

                            attempts: list[dict[str, object]] = []
                            retries_left = max_retries
                            for candidate in filtered:
                                if retries_left <= 0:
                                    break
                                retries_left -= 1
                                try:
                                    with metrics_span("ingest.parse_fallback", backend=candidate):
                                        alt = await parsing_stage.run(
                                            db=db,
                                            db_document=db_document,
                                            file_path=file_path,
                                            document_id=document_id,
                                            tenant_id=tenant_id,
                                            dataset_id=dataset_id,
                                            parser_backend=candidate,
                                            chunk_strategy=chunk_strategy,
                                            html_xpath=None,
                                        )
                                except Exception as exc:  # noqa: BLE001
                                    attempts.append(
                                        {
                                            "from": current,
                                            "to": candidate,
                                            "quality_before": q0.to_dict(),
                                            "error": str(exc)[:200],
                                            "accepted": False,
                                        }
                                    )
                                    continue
                                if alt.documents is None:
                                    continue
                                joined_alt = "\n\n".join([(d.page_content or "") for d in (alt.documents or [])])
                                q1 = score_parsed_text_quality(joined_alt)
                                attempts.append(
                                    {
                                        "from": current,
                                        "to": candidate,
                                        "quality_before": q0.to_dict(),
                                        "quality_after": q1.to_dict(),
                                        "accepted": bool(int(q1.content_chars) >= min_chars),
                                    }
                                )
                                if int(q1.content_chars) >= min_chars:
                                    parsed = alt
                                    break

                            if attempts:
                                meta = dict(db_document.doc_metadata or {})
                                meta["parse_fallback"] = {
                                    "enabled": True,
                                    "attempts": attempts,
                                    "min_content_chars": int(min_chars),
                                    "max_retries": int(max_retries),
                                }
                                db_document.doc_metadata = meta
                                db.commit()
                                db.refresh(db_document)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Parse fallback failed (ignored): %s", str(exc)[:200])

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
            # Also collect artifact directories from ragflow chunks (subprocess image materialization).
            if parsed.chunks:
                for doc in parsed.chunks:
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
                    quarantined = bool(getattr(pipeline_effective, "governance_quarantine_on_drop", False))
                    reasons = getattr(governance_stats, "drop_reasons", {}) or {}
                    reason_str = ", ".join([f"{k}:{v}" for k, v in sorted(reasons.items())]) if isinstance(reasons, dict) else ""
                    msg = (
                        ("Document quarantined by governance rules" if quarantined else "Document filtered by governance rules")
                        + (f" ({reason_str})" if reason_str else "")
                        + ". You can disable outline/low-density filters or relax thresholds."
                    )
                    logger.warning("%s document_id=%s", msg, document_id)
                    status = "quarantined" if quarantined else "failed"
                    reason = "quarantined_by_governance" if quarantined else "filtered_by_governance"
                    await self._update_status(
                        db,
                        tenant_id,
                        document_id,
                        status,
                        0,
                        status,
                        chunk_count=0,
                        total_characters=0,
                        error_message=msg,
                    )
                    return {
                        "status": status,
                        "reason": reason,
                        "chunk_count": 0,
                        "total_characters": 0,
                        "parser_backend": resolved_backend,
                        "chunk_strategy": resolved_chunk_strategy,
                    }

                if bool(pipeline_effective.governance_enabled) and chunks:
                    try:
                        self._record_governance_enrichment_metadata(
                            db,
                            tenant_id=tenant_id,
                            document_id=document_id,
                            items=chunks,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to record governance enrichment: %s", str(exc)[:200])
                    self._strip_doc_enrichment_fields(chunks)
            else:
                with metrics_span("ingest.normalize"):
                    parsed_documents = normalize_stage.run(items=parsed_documents or [])
                parsed_documents_before_governance = parsed_documents
                with metrics_span("ingest.governance", enabled=bool(pipeline_effective.governance_enabled)):
                    gov = governance_stage.run(
                        items=parsed_documents,
                        enabled=bool(pipeline_effective.governance_enabled),
                        kwargs=governance_kwargs,
                    )
                parsed_documents = gov.items
                governance_stats = gov.stats

                # Optional: persist parsed markdown (raw+clean) for audit/debug.
                if bool(getattr(pipeline_effective, "persist_parsed_content", False)):
                    try:
                        original_md = "\n\n".join([(d.page_content or "") for d in (parsed_documents_before_governance or [])]).strip()
                        cleaned_md = "\n\n".join([(d.page_content or "") for d in (parsed_documents or [])]).strip()
                        persist_meta = self._persist_parsed_content(
                            db,
                            tenant_id=tenant_id,
                            document_id=document_id,
                            original_markdown=original_md,
                            cleaned_markdown=cleaned_md,
                            max_chars=int(getattr(pipeline_effective, "persist_parsed_content_max_chars", 0) or 0),
                        )
                        meta = dict(db_document.doc_metadata or {})
                        meta["parsed_content_persisted"] = persist_meta
                        db_document.doc_metadata = meta
                        db.commit()
                        db.refresh(db_document)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to persist parsed content: %s", str(exc)[:200])

                if (
                    bool(pipeline_effective.governance_enabled)
                    and governance_stats is not None
                    and not parsed_documents
                    and int(getattr(governance_stats, "dropped", 0) or 0) > 0
                ):
                    self._record_governance_metadata(db, tenant_id, document_id, governance_stats)
                    quarantined = bool(getattr(pipeline_effective, "governance_quarantine_on_drop", False))
                    reasons = getattr(governance_stats, "drop_reasons", {}) or {}
                    reason_str = ", ".join([f"{k}:{v}" for k, v in sorted(reasons.items())]) if isinstance(reasons, dict) else ""
                    msg = (
                        ("Document quarantined by governance rules" if quarantined else "Document filtered by governance rules")
                        + (f" ({reason_str})" if reason_str else "")
                        + ". You can disable outline/low-density filters or relax thresholds."
                    )
                    logger.warning("%s document_id=%s", msg, document_id)
                    status = "quarantined" if quarantined else "failed"
                    reason = "quarantined_by_governance" if quarantined else "filtered_by_governance"
                    await self._update_status(
                        db,
                        tenant_id,
                        document_id,
                        status,
                        0,
                        status,
                        chunk_count=0,
                        total_characters=0,
                        error_message=msg,
                    )
                    return {
                        "status": status,
                        "reason": reason,
                        "chunk_count": 0,
                        "total_characters": 0,
                        "parser_backend": resolved_backend,
                        "chunk_strategy": resolved_chunk_strategy,
                    }

                if bool(pipeline_effective.governance_enabled) and parsed_documents:
                    try:
                        self._record_governance_enrichment_metadata(
                            db,
                            tenant_id=tenant_id,
                            document_id=document_id,
                            items=parsed_documents,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to record governance enrichment: %s", str(exc)[:200])
                    # Avoid propagating large per-doc fields to all chunks.
                    self._strip_doc_enrichment_fields(parsed_documents)

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

            # Optional exact-duplicate text chunk drop (within document).
            dedup_enabled = bool(getattr(settings, "CHUNK_DEDUP_ENABLED", False))
            dedup_dropped = 0
            if dedup_enabled and chunks:
                with metrics_span("ingest.chunk_dedup", enabled=True):
                    deduped = chunk_dedup_stage.run(chunks=chunks, enabled=True)
                chunks = deduped.chunks
                dedup_dropped = int(deduped.duplicates_dropped)
                if int(deduped.duplicates_dropped) > 0:
                    logger.info(
                        "Dropped %s duplicate chunks for document %s",
                        int(deduped.duplicates_dropped),
                        document_id,
                    )
                    log_metrics(
                        {
                            "event": "ingest.chunk_dedup",
                            "duplicates_dropped": int(deduped.duplicates_dropped),
                        }
                    )

            # Optional cross-document near-duplicate drop (SimHash bucket index; best-effort).
            near_dedup_dropped = 0
            if bool(getattr(pipeline_effective, "near_dedup_enabled", False)) and chunks:
                try:
                    threshold = max(0, int(getattr(pipeline_effective, "near_dedup_hamming_threshold", 0) or 0))
                    max_bucket_size = max(0, int(getattr(pipeline_effective, "near_dedup_max_bucket_size", 0) or 0))
                    # Safety: keep the index per-tenant per-dataset to avoid unintended cross-pollution.
                    safe_dataset = re.sub(r"[^A-Za-z0-9._-]+", "_", str(dataset_id or tenant_id))
                    index_path = Path(settings.UPLOAD_DIR) / str(tenant_id) / ".mimirq_dedup" / f"{safe_dataset}.json"

                    kept_chunks: list[Document] = []
                    kept_hashes: list[str] = []
                    sample_match: dict[str, Any] | None = None

                    def update_fn(buckets: dict[str, list[str]]):
                        nonlocal near_dedup_dropped, sample_match
                        for c in chunks:
                            meta = c.metadata if isinstance(getattr(c, "metadata", None), dict) else {}
                            if _chunk_has_asset(meta):
                                kept_chunks.append(c)
                                continue

                            content_norm = normalize_text(c.page_content or "", normalize_line_endings=True, remove_control_chars=True)
                            sh_hex = str(meta.get("simhash64") or "").strip().lower()
                            if not sh_hex:
                                sh_hex = simhash64_hex(simhash64(content_norm))
                                meta = dict(meta)
                                meta["simhash64"] = sh_hex
                                meta.setdefault("simhash_algo", "simhash64_sha1")
                                c.metadata = meta

                            match = find_near_duplicate(
                                buckets=buckets,
                                simhash64_hex=sh_hex,
                                hamming_threshold=threshold,
                                max_bucket_size=max_bucket_size,
                            )
                            if match is not None:
                                near_dedup_dropped += 1
                                if sample_match is None:
                                    sample_match = {
                                        "simhash64": sh_hex,
                                        "matched_simhash64": match.simhash64,
                                        "distance": int(match.distance),
                                    }
                                continue

                            kept_chunks.append(c)
                            kept_hashes.append(sh_hex)

                        if kept_hashes:
                            add_simhashes(buckets=buckets, simhashes=kept_hashes, max_bucket_size=max_bucket_size)
                        return buckets

                    with metrics_span("ingest.near_dedup", enabled=True, threshold=threshold):
                        with_near_dedup_index(path=index_path, fn=update_fn)

                    if near_dedup_dropped > 0:
                        original_chunks_for_fallback = list(chunks)
                        chunks = kept_chunks
                        if not chunks:
                            # Avoid indexing an empty document: keep the longest chunk.
                            longest = max(
                                original_chunks_for_fallback,
                                key=lambda d: len((d.page_content or "").strip()),
                                default=None,
                            )
                            if longest is not None:
                                chunks = [longest]
                        logger.info(
                            "Dropped %s near-duplicate chunks for document %s (threshold=%s)",
                            int(near_dedup_dropped),
                            document_id,
                            int(threshold),
                        )
                        log_metrics(
                            {
                                "event": "ingest.near_dedup",
                                "dropped": int(near_dedup_dropped),
                                "threshold": int(threshold),
                            }
                        )
                        meta = dict(db_document.doc_metadata or {})
                        meta["near_dedup"] = {
                            "enabled": True,
                            "dropped": int(near_dedup_dropped),
                            "threshold": int(threshold),
                            "max_bucket_size": int(max_bucket_size),
                            "sample_match": sample_match,
                        }
                        db_document.doc_metadata = meta
                        db.commit()
                        db.refresh(db_document)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Near-dup stage failed (ignored): %s", str(exc)[:200])

            # Guardrail: cap chunk count per document (0 disables).
            max_chunks_per_document = max(0, int(getattr(settings, "MAX_CHUNKS_PER_DOCUMENT", 0) or 0))
            truncation_strategy = str(getattr(settings, "MAX_CHUNKS_PER_DOCUMENT_STRATEGY", "head") or "head")
            truncated_from = 0
            truncated_to = 0
            truncated_dropped = 0
            truncated_asset_total = 0
            truncated_asset_kept = 0
            truncated_strategy_used = ""
            if max_chunks_per_document > 0 and chunks and len(chunks) > max_chunks_per_document:
                truncated_from = len(chunks)
                chunks, truncation_info = _truncate_chunks_for_limit(
                    chunks,
                    max_chunks=max_chunks_per_document,
                    strategy=truncation_strategy,
                )
                truncated_to = len(chunks)
                truncated_dropped = max(0, truncated_from - truncated_to)
                truncated_asset_total = int(truncation_info.get("asset_total") or 0)
                truncated_asset_kept = int(truncation_info.get("asset_kept") or 0)
                truncated_strategy_used = str(truncation_info.get("strategy") or "").strip() or str(truncation_strategy)
                logger.info(
                    "Truncated chunks for document %s: kept=%s dropped=%s assets=%s/%s strategy=%s (MAX_CHUNKS_PER_DOCUMENT=%s)",
                    document_id,
                    truncated_to,
                    truncated_dropped,
                    truncated_asset_kept,
                    truncated_asset_total,
                    truncated_strategy_used,
                    max_chunks_per_document,
                )
                log_metrics(
                    {
                        "event": "ingest.chunk_truncate",
                        "chunk_before": int(truncated_from),
                        "chunk_after": int(truncated_to),
                        "dropped": int(truncated_dropped),
                        "max_chunks_per_document": int(max_chunks_per_document),
                        "strategy": truncated_strategy_used,
                        "asset_kept": int(truncated_asset_kept),
                        "asset_total": int(truncated_asset_total),
                    }
                )

            if dedup_enabled or max_chunks_per_document > 0:
                self._record_chunk_postprocess_metadata(
                    db,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    dedup_enabled=dedup_enabled,
                    dedup_dropped=dedup_dropped,
                    max_chunks_per_document=max_chunks_per_document,
                    max_chunks_strategy=truncated_strategy_used or truncation_strategy,
                    truncated_from=truncated_from,
                    truncated_to=truncated_to,
                    truncated_dropped=truncated_dropped,
                    truncated_asset_total=truncated_asset_total,
                    truncated_asset_kept=truncated_asset_kept,
                )

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
            # Ensure stable traceability metadata exists on each chunk (used by citations/filtering).
            pipeline_hash = str((db_document.doc_metadata or {}).get("pipeline_hash") or "").strip()
            file_type = str(getattr(db_document, "file_type", "") or "").strip().lower() or str(file_path.suffix.lstrip(".")).lower()
            governance_version = (
                str(getattr(governance_stats, "version", "") or "").strip()
                if governance_stats is not None
                else ""
            )
            for c in chunks:
                meta = dict(c.metadata or {})
                if pipeline_hash:
                    meta.setdefault("pipeline_hash", pipeline_hash)
                if file_type:
                    meta.setdefault("file_type", file_type)
                if governance_version:
                    meta.setdefault("governance_version", governance_version)
                c.metadata = meta
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
                    default_source=str(getattr(db_document, "filename", "") or "").strip() or str(file_path.name),
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

    def _persist_parsed_content(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        original_markdown: str,
        cleaned_markdown: str,
        max_chars: int,
    ) -> dict[str, Any]:
        """
        Persist parsed markdown content for audit/debug purposes.

        This stores two versions:
        - original_markdown_content: parsed output after normalize stage (pre-governance)
        - markdown_content: parsed output after governance cleaning
        """
        def _truncate(text: str) -> tuple[str, bool, int, int]:
            raw = text or ""
            raw_len = len(raw)
            if max_chars <= 0 or raw_len <= max_chars:
                return raw, False, raw_len, raw_len
            marker = "\n\n...[TRUNCATED]..."
            keep = max(0, max_chars - len(marker))
            truncated = raw[:keep] + marker
            return truncated, True, raw_len, len(truncated)

        max_chars_eff = max(0, int(max_chars or 0))
        orig_trunc, orig_is_trunc, orig_raw_len, orig_stored_len = _truncate(original_markdown)
        clean_trunc, clean_is_trunc, clean_raw_len, clean_stored_len = _truncate(cleaned_markdown)

        rec = (
            db.query(DocumentParsedContent)
            .filter(DocumentParsedContent.document_id == document_id, DocumentParsedContent.tenant_id == tenant_id)
            .first()
        )
        if rec is None:
            rec = DocumentParsedContent(
                tenant_id=tenant_id,
                document_id=document_id,
                markdown_content=clean_trunc,
                original_markdown_content=orig_trunc,
            )
            db.add(rec)
        else:
            rec.markdown_content = clean_trunc
            rec.original_markdown_content = orig_trunc

        db.commit()
        db.refresh(rec)

        return {
            "enabled": True,
            "max_chars": int(max_chars_eff),
            "original": {"raw_len": int(orig_raw_len), "stored_len": int(orig_stored_len), "truncated": bool(orig_is_trunc)},
            "cleaned": {"raw_len": int(clean_raw_len), "stored_len": int(clean_stored_len), "truncated": bool(clean_is_trunc)},
        }

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
        metadata["governance_version"] = str(getattr(stats, "version", None) or metadata.get("governance_version") or "1")
        metadata["governance_documents"] = int(stats.documents)
        metadata["governance_changed_documents"] = int(stats.changed)
        metadata["governance_rules_applied"] = int(stats.applied_rules)
        metadata["governance_dropped_documents"] = int(getattr(stats, "dropped", 0) or 0)
        reasons = getattr(stats, "drop_reasons", None)
        if isinstance(reasons, dict) and reasons:
            metadata["governance_drop_reasons"] = {str(k): int(v) for k, v in reasons.items()}
        pii_hits = getattr(stats, "pii_hits", None)
        if isinstance(pii_hits, dict) and pii_hits:
            metadata["governance_pii_hits"] = {str(k): int(v) for k, v in pii_hits.items()}
        secrets_hits = getattr(stats, "secrets_hits", None)
        if isinstance(secrets_hits, dict) and secrets_hits:
            metadata["governance_secrets_hits"] = {str(k): int(v) for k, v in secrets_hits.items()}

        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _record_governance_enrichment_metadata(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        items: list[Document] | None,
    ) -> None:
        if not items:
            return

        db_doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not db_doc:
            return

        title: str | None = None
        tags: set[str] = set()
        keywords: set[str] = set()
        keywords_provider: str | None = None
        frontmatter: dict | None = None

        lang_counts: dict[str, int] = {}
        conf_sum = 0.0
        conf_n = 0

        for d in items:
            meta = d.metadata or {}

            if frontmatter is None:
                fm = meta.get("document_frontmatter")
                if isinstance(fm, dict) and fm:
                    frontmatter = fm

            if title is None:
                raw_title = meta.get("document_title")
                if isinstance(raw_title, str) and raw_title.strip():
                    title = raw_title.strip()[:200]

            raw_tags = meta.get("document_tags")
            if isinstance(raw_tags, list):
                for item in raw_tags:
                    if not isinstance(item, str):
                        continue
                    val = item.strip()
                    if val:
                        tags.add(val[:64])

            raw_kws = meta.get("document_keywords")
            if isinstance(raw_kws, list):
                for item in raw_kws:
                    if not isinstance(item, str):
                        continue
                    val = item.strip()
                    if val:
                        keywords.add(val[:64])

            if keywords_provider is None:
                raw_provider = meta.get("document_keywords_provider")
                if isinstance(raw_provider, str) and raw_provider.strip():
                    keywords_provider = raw_provider.strip()[:50]

            raw_lang = meta.get("document_language")
            if isinstance(raw_lang, str) and raw_lang.strip():
                lang = raw_lang.strip()
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
                raw_conf = meta.get("document_language_confidence")
                if isinstance(raw_conf, (int, float)):
                    conf_sum += float(raw_conf)
                    conf_n += 1

        language: str | None = None
        if lang_counts:
            language = sorted(lang_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

        enrichment: dict[str, object] = {}
        if title:
            enrichment["title"] = title
        if tags:
            enrichment["tags"] = sorted(tags)
        if language:
            enrichment["language"] = language
            if conf_n > 0:
                enrichment["language_confidence"] = round(conf_sum / conf_n, 3)
        if keywords:
            enrichment["keywords"] = sorted(keywords)
            enrichment["keywords_provider"] = keywords_provider or "auto"
        if frontmatter:
            enrichment["frontmatter"] = frontmatter

        if not enrichment:
            return

        metadata = dict(db_doc.doc_metadata or {})
        existing = metadata.get("governance_enrichment")
        merged: dict[str, object] = dict(existing) if isinstance(existing, dict) else {}
        merged.update(enrichment)
        metadata["governance_enrichment"] = merged
        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    @staticmethod
    def _strip_doc_enrichment_fields(items: list[Document] | None) -> None:
        if not items:
            return
        to_drop = {
            "document_frontmatter",
            "document_tags",
            "document_keywords",
            "document_keywords_provider",
        }
        for d in items:
            meta = dict(d.metadata or {})
            changed = False
            for k in to_drop:
                if k in meta:
                    meta.pop(k, None)
                    changed = True
            if changed:
                d.metadata = meta

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

    def _record_chunk_postprocess_metadata(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        document_id: UUID,
        dedup_enabled: bool,
        dedup_dropped: int,
        max_chunks_per_document: int,
        max_chunks_strategy: str,
        truncated_from: int,
        truncated_to: int,
        truncated_dropped: int,
        truncated_asset_total: int,
        truncated_asset_kept: int,
    ) -> None:
        """Persist chunk postprocessing stats (dedup/truncation) on the document metadata."""
        db_doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not db_doc:
            return

        metadata = dict(db_doc.doc_metadata or {})
        metadata["chunk_postprocess"] = {
            "dedup_enabled": bool(dedup_enabled),
            "dedup_dropped": int(dedup_dropped),
            "max_chunks_per_document": int(max_chunks_per_document),
            "max_chunks_strategy": str(max_chunks_strategy or "").strip() or "head",
            "truncated": bool(int(truncated_dropped) > 0),
            "truncated_from": int(truncated_from),
            "truncated_to": int(truncated_to),
            "truncated_dropped": int(truncated_dropped),
            "truncated_asset_total": int(truncated_asset_total),
            "truncated_asset_kept": int(truncated_asset_kept),
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

        # Subprocess parser may materialize PIL.Image into an on-disk file path.
        image_path: Path | None = None
        raw_path = metadata.get("image_path")
        if raw_image is None and isinstance(raw_path, str) and raw_path.strip():
            doc_type = str(metadata.get("doc_type_kwd") or "").lower()
            if doc_type != "image":
                metadata.pop("image_path", None)
            else:
                try:
                    upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
                    tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
                    candidate = Path(raw_path.strip()).resolve(strict=False)
                    candidate.relative_to(tenant_root)
                    if candidate.exists() and candidate.is_file():
                        max_bytes = int(getattr(settings, "MINIO_IMAGE_MAX_BYTES", 0) or 0)
                        if max_bytes > 0:
                            try:
                                size = int(candidate.stat().st_size)
                            except Exception:
                                size = 0
                            if size > max_bytes:
                                metadata.pop("image_path", None)
                                try:
                                    candidate.unlink()
                                except Exception:
                                    pass
                            else:
                                image_path = candidate
                                raw_image = candidate.read_bytes()
                                found_key = "image_path"
                        else:
                            image_path = candidate
                            raw_image = candidate.read_bytes()
                            found_key = "image_path"
                    else:
                        metadata.pop("image_path", None)
                except Exception:
                    # Unsafe or unreadable path; drop it to avoid leaking arbitrary filesystem paths.
                    metadata.pop("image_path", None)

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
                chunk_key=str(metadata.get("chunk_key") or chunk_index),
                extension="jpg",
            )
            
            # After upload, delete in-memory image data to save resources.
            if found_key:
                del metadata[found_key]
            
            # Clean up other possible image fields.
            for key in possible_keys:
                if key in metadata and key != found_key:
                    del metadata[key]

            # If the subprocess provided an on-disk image file, remove it after successful upload.
            if image_path is not None:
                try:
                    image_path.unlink()
                except Exception:
                    pass

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
