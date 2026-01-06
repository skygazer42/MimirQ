"""
文档处理服务 - 核心处理流程
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
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document as DBDocument, DocumentChunk
from app.parsing.factory import parser_factory
from app.rag.chunking.factory import chunker_factory
from app.storage.object.minio import minio_service
from app.types.indexing import IndexKind, IndexRecord
from app.types.pipeline import PipelineEffective
from app.services.indexer import Indexer
from app.services.pipeline_config import (
    build_indexing_options,
    parse_pipeline_from_metadata,
    resolve_pipeline_options,
)
from app.rag.preprocessing.processor import governance_processor, GovernanceStats
from app.rag.preprocessing.normalization import normalize_text
from app.rag.kg.pipeline import extract_events
from app.parsing.routing import route_pdf_backend
from app.rag.core.logging import get_logger
from app.rag.core.metadata import normalize_image_metadata


logger = get_logger("parsing.document_processor")


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
    ) -> ParseResult:
        use_ragflow = (chunk_strategy or "").lower() in self._svc.RAGFLOW_STRATEGIES
        if use_ragflow:
            resolved_backend = "ragflow"
            resolved_chunk_strategy = (chunk_strategy or "ragflow_naive").lower()
            self._svc._record_processing_metadata(
                db,
                tenant_id,
                document_id,
                parser_backend=resolved_backend,
                chunk_strategy=resolved_chunk_strategy,
            )
            chunks = await asyncio.to_thread(self._svc._ragflow_chunk_file, file_path, resolved_chunk_strategy)
            return ParseResult(
                resolved_backend=resolved_backend,
                resolved_chunk_strategy=resolved_chunk_strategy,
                chunks=chunks,
            )

        logger.info("Parsing document: %s", file_path)
        effective_parser_backend = parser_backend
        file_ext = file_path.suffix.lower()
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

        documents, resolved_backend = parser_factory.parse(
            file_path,
            parser_backend=effective_parser_backend,
            dataset_id=dataset_id,
            document_id=str(document_id),
        )
        resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
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
    """文档处理服务"""

    def __init__(self):
        pass

    #  预设策略（直接解析+切块）
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
        完整的文档处理流程

        流程：
        1. 解析文档
        2. 文本切片
        3. 生成 Embeddings
        4. 存入向量库
        5. 保存到数据库

        Args:
            file_path: 文件路径
            document_id: 文档 ID
            db: 数据库会话

        Returns:
            处理结果
        """
        owns_db = False
        if db is None:
            db = SessionLocal()
            owns_db = True

        try:
            db_document = (
                db.query(DBDocument)
                .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
                .first()
            )
            if db_document is None:
                logger.warning("Document not found for processing: tenant=%s document=%s", tenant_id, document_id)
                return {"status": "skipped", "reason": "document_not_found"}

            # Step 1: 更新状态为 processing
            await self._update_status(
                db, tenant_id, document_id, "processing", 0, "parsing"
            )

            # 提前获取 dataset_id（MinerU 本地 ZIP / MinIO 路径依赖）
            dataset_id = str(db_document.dataset_id) if db_document.dataset_id else str(tenant_id)

            # 记录本次处理过程中关联到该文档的所有 img_id（用于删除清理等）
            document_img_ids: set[str] = set()
            artifact_dirs: set[str] = set()

            pipeline_options = parse_pipeline_from_metadata(db_document.doc_metadata or {})
            pipeline_effective = resolve_pipeline_options(pipeline_options)
            index_options = build_indexing_options(pipeline_effective)
            self._record_pipeline_effective(db, tenant_id, document_id, pipeline_effective)
            governance_kwargs = {
                "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
                "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
                "unwrap_lines": pipeline_effective.governance_unwrap_lines,
                "remove_common_lines": pipeline_effective.governance_remove_common_lines,
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

            parsed = await parsing_stage.run(
                db=db,
                db_document=db_document,
                file_path=file_path,
                document_id=document_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                parser_backend=parser_backend,
                chunk_strategy=chunk_strategy,
            )

            resolved_backend = parsed.resolved_backend
            resolved_chunk_strategy = parsed.resolved_chunk_strategy

            # 收集解析器已上传的图片（例如 MinerU 本地 ZIP 模式会返回 images 列表）
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

            # Inline image assets（仅非 ragflow 分支：documents -> documents）
            if parsed.documents:
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

            # Governance：对 documents 或 ragflow chunks 做统一清洗
            governance_stats: Optional[GovernanceStats] = None
            if parsed.chunks is not None:
                parsed_chunks = normalize_stage.run(items=parsed.chunks)
                gov = governance_stage.run(
                    items=parsed_chunks,
                    enabled=bool(pipeline_effective.governance_enabled),
                    kwargs=governance_kwargs,
                )
                chunks = gov.items
                governance_stats = gov.stats
            else:
                parsed_documents = normalize_stage.run(items=parsed_documents or [])
                gov = governance_stage.run(
                    items=parsed_documents,
                    enabled=bool(pipeline_effective.governance_enabled),
                    kwargs=governance_kwargs,
                )
                parsed_documents = gov.items
                governance_stats = gov.stats

                await self._update_status(db, tenant_id, document_id, "processing", 33, "chunking")
                chunked = chunking_stage.run(
                    documents=parsed_documents,
                    chunk_strategy=resolved_chunk_strategy,
                    chunk_size=int(pipeline_effective.chunk_size),
                    chunk_overlap=int(pipeline_effective.chunk_overlap),
                )
                chunks = chunked.chunks

            # Drop extremely short chunks to reduce retrieval noise (keep image-bearing chunks).
            min_chars = max(0, int(getattr(settings, "CHUNK_MIN_CHARS", 0) or 0))
            if min_chars > 0 and chunks:
                before = len(chunks)
                filtered = []
                for c in chunks:
                    content = (c.page_content or "").strip()
                    if len(content) >= min_chars:
                        filtered.append(c)
                        continue
                    meta = c.metadata or {}
                    if meta.get("img_id") or meta.get("image_id") or meta.get("image_url"):
                        filtered.append(c)
                chunks = filtered
                dropped = before - len(chunks)
                if dropped:
                    logger.info("Dropped %s short chunks (<%s chars) for document %s", dropped, min_chars, document_id)

            if governance_stats is not None:
                self._record_governance_metadata(db, tenant_id, document_id, governance_stats)

            # Chunk-level assets & metadata（图片上传/绑定）
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

            # 将所有图片 img_id 记录到 document.metadata（用于删除清理等）
            self._record_document_image_ids(db, tenant_id=tenant_id, document_id=document_id, img_ids=document_img_ids)

            await self._update_status(db, tenant_id, document_id, "processing", 66, "embedding")

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

            # Step 7: 如启用则运行 KG 抽取（事件/实体）
            if pipeline_effective.kg_enabled:
                # 队列开启时：把 KG 抽取迁到 worker，提升 ingest 吞吐与稳定性
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
                    except Exception as exc:  # noqa: BLE001
                        # 队列异常不应影响文档主流程
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

            return {
                "status": "success",
                "chunk_count": len(chunks),
                "total_characters": total_chars,
                "parser_backend": resolved_backend,
                "chunk_strategy": resolved_chunk_strategy
            }

        except Exception as e:
            # 错误处理
            logger.exception("Error processing document %s: %s", document_id, e)
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
        """更新文档处理状态"""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        ).first()

        if db_doc:
            db_doc.status = status
            db_doc.processing_progress = progress
            db_doc.current_stage = stage

            for key, value in kwargs.items():
                setattr(db_doc, key, value)

            db.commit()
            db.refresh(db_doc)

    async def _rebuild_bm25_index_for_tenant(self, db: Session, tenant_id: UUID):
        """重建指定租户的 BM25 索引"""
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

            all_chunks = db.query(DocumentChunk).join(DBDocument).filter(
                DBDocument.status == 'completed',
                DocumentChunk.tenant_id == tenant_id
            ).all()

            if all_chunks:
                logger.info("Rebuilding BM25 index with %s chunks for tenant %s", len(all_chunks), tenant_id)
                Indexer(db).rebuild_tenant(tenant_id=tenant_id, kinds=[IndexKind.CHUNK])
            else:
                logger.warning("No chunks found for BM25 index")

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

            tenant_rows = db.query(DocumentChunk.tenant_id).distinct().all()
            tenant_ids = [row[0] for row in tenant_rows if row and row[0]]
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
        """确保文档元数据里记录了最终选用的解析器。"""
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
        # 不抛出异常，避免影响文档处理流程

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
                if ".magicpdf" not in path.parts:
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

        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _record_document_image_ids(self, db: Session, tenant_id: UUID, document_id: UUID, img_ids: set[str]):
        """
        将文档关联的所有 img_id 记录到 documents.metadata 中，便于后续删除清理。

        说明：
        - 这里存的是“文档级”聚合列表（去重），不影响每个 chunk 的 img_id。
        - 仅当 MinIO 启用时才写入，避免误导。
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
        从 chunk 文本内容中提取第一个 image-url/{img_id}，用于将“已替换成 URL 的图片”
        反向绑定到 chunk metadata（例如 ZIP 模式/MarkItDown data URI 替换后的文本）。
        """
        if not isinstance(content, str) or not content:
            return None

        # 支持：
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
        将 Markdown/HTML 中的图片引用上传到 MinIO，并替换为 /image-url/{img_id}。

        支持：
        - data URI：data:image/...
        - 本地/相对路径：![alt](images/foo.png) 或 <img src="images/foo.png">
          路径解析：相对 `origin_path.parent`；若为绝对路径直接使用。
        - 已是 http/https 或已指向 /api/v1/documents/image-url/... 的跳过。

        返回：
        - 处理后的 markdown_text
        - 本次新增上传的 img_id 列表
        - 更新后的 asset 序号（用于生成稳定 chunk_key：asset{n}）
        """
        if not settings.MINIO_ENABLED:
            return markdown_text, [], start_index
        if not isinstance(markdown_text, str) or not markdown_text:
            return markdown_text, [], start_index
        lowered = markdown_text.lower()
        if "data:image" not in lowered and "![" not in lowered and "<img" not in lowered:
            return markdown_text, [], start_index

        # 仅处理 markdown 图片与 html img，匹配 src 内容
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
            # 已是远程或已替换过
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
                    # 本地/相对路径
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

                # 统一转 JPEG
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
            # 单次扫描替换：仅替换图片语法中的 src/ref，避免对全文做 N 次 replace（O(N*M)）
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
        调用 ragflow 预设（naive/book/laws/email）直接完成解析+切块，
        返回 LangChain Document 列表。
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
        检测 chunk metadata 中的图片数据，上传到 MinIO，返回 img_id。
        图片上传后，原始图片数据会从 metadata 中删除以节省内存。
        
        img_id 格式："{tenant_id}:{dataset_id}:{document_id}:{chunk_index}"
        
        识别的字段：image (PIL.Image/bytes) / image_base64 / img_base64 / img / image_data
        """
        # 如果已有 img_id，直接返回
        if isinstance(metadata.get("img_id"), str) and metadata.get("img_id").strip():
            return metadata.get("img_id")

        # MinIO 未启用时，确保清理不可序列化字段
        if not settings.MINIO_ENABLED:
            if "image" in metadata:
                metadata.pop("image", None)
            return None

        # 查找图片数据
        possible_keys = ["image_base64", "image", "img_base64", "img", "image_data"]
        found_key = None
        raw_image = None
        b64_data = None

        # ragflow 输出可能直接在 metadata["image"] 放 PIL.Image/bytes，
        # 只为真正的图片块（doc_type_kwd == "image"）上传，避免为每个文本块存截图。
        val = metadata.get("image")
        if val is not None:
            doc_type = str(metadata.get("doc_type_kwd") or "").lower()
            if doc_type == "image":
                raw_image = val
                found_key = "image"
            else:
                # 非图片块：清理掉 image 字段，避免 JSON 序列化失败
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

        # 处理 data URI 格式
        if isinstance(b64_data, str) and b64_data.startswith("data:"):
            parts = b64_data.split(",", 1)
            if len(parts) == 2:
                b64_data = parts[1]

        # 统一转换为 JPEG bytes（节省存储，简化读取）
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
            # 无论成功与否，都要清理 image 字段，避免入库失败
            if found_key == "image":
                metadata.pop("image", None)
            return None
        finally:
            if raw_image is not None and not isinstance(raw_image, bytes) and hasattr(raw_image, "close"):
                try:
                    raw_image.close()
                except Exception:
                    pass

        # 上传到 MinIO
        try:
            img_id = minio_service.upload_image(
                image_data=image_bytes,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
                chunk_key=str(chunk_index),
                extension="jpg",
            )
            
            # 上传成功后，删除内存中的原始图片数据（节省资源）
            if found_key:
                del metadata[found_key]
            
            # 清理其他可能的图片字段
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
        备用方法：检测 chunk metadata 中的图片并保存到本地磁盘。
        当 MinIO 未启用时使用。
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


# 全局实例
document_processor = DocumentProcessorService()
