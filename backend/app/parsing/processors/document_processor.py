"""
文档处理服务 - 核心处理流程
"""
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

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document as DBDocument, DocumentChunk
from app.parsing.factory import parser_factory
from app.rag.chunking.factory import chunker_factory
from app.storage.object.minio import minio_service
from app.services.indexer import IndexKind, IndexRecord, Indexer
from app.services.pipeline_config import (
    PipelineEffective,
    build_indexing_options,
    parse_pipeline_from_metadata,
    resolve_pipeline_options,
)
from app.governance.processor import governance_processor, GovernanceStats
from app.rag.kg.pipeline import extract_events


class DocumentProcessorService:
    """文档处理服务"""

    def __init__(self):
        pass

    # ragflow 预设策略（直接解析+切块）
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
            # Step 1: 更新状态为 processing
            await self._update_status(
                db, document_id, "processing", 0, "parsing"
            )

            # 提前获取 dataset_id（MinerU 本地 ZIP / MinIO 路径依赖）
            db_document = db.query(DBDocument).filter(DBDocument.id == document_id).first()
            dataset_id = str(db_document.dataset_id) if db_document and db_document.dataset_id else str(tenant_id)

            # 记录本次处理过程中关联到该文档的所有 img_id（用于删除清理等）
            document_img_ids: set[str] = set()

            pipeline_options = parse_pipeline_from_metadata(db_document.doc_metadata if db_document else {})
            pipeline_effective = resolve_pipeline_options(pipeline_options)
            index_options = build_indexing_options(pipeline_effective)
            self._record_pipeline_effective(db, document_id, pipeline_effective)
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

            use_ragflow = (chunk_strategy or "").lower() in {"ragflow_naive", "ragflow_book", "ragflow_laws", "ragflow_email"}
            governance_stats: Optional[GovernanceStats] = None

            if use_ragflow:
                resolved_backend = (parser_backend or "ragflow").lower()
                resolved_chunk_strategy = (chunk_strategy or "ragflow_naive").lower()

                self._record_processing_metadata(
                    db,
                    document_id,
                    parser_backend=resolved_backend,
                    chunk_strategy=resolved_chunk_strategy,
                )

                # ragflow 直接解析+切块（同步），放到线程池避免阻塞事件循环
                chunks = await asyncio.to_thread(
                    self._ragflow_chunk_file,
                    file_path,
                    resolved_chunk_strategy
                )
                if pipeline_effective.governance_enabled:
                    chunks, governance_stats = governance_processor.clean_documents(
                        chunks,
                        **governance_kwargs,
                    )

            else:
                # Step 2: 解析文档
                print(f"Parsing document: {file_path}")
                documents, resolved_backend = parser_factory.parse(
                    file_path,
                    parser_backend=parser_backend,
                    dataset_id=dataset_id,
                    document_id=str(document_id),
                )

                # 收集解析器已上传的图片（例如 MinerU 本地 ZIP 模式会返回 images 列表）
                for doc in documents:
                    images = (doc.metadata or {}).get("images")
                    if isinstance(images, list):
                        for item in images:
                            img_id = item.get("img_id") if isinstance(item, dict) else None
                            if isinstance(img_id, str) and img_id.strip():
                                document_img_ids.add(img_id)

                # 对解析结果中的内嵌 data URI 图片进行 MinIO 上传并替换引用
                #（避免把 base64 直接存入向量库/数据库）
                if settings.MINIO_ENABLED:
                    inline_cache: dict[str, str] = {}
                    asset_idx = 0
                    processed_docs: List[Document] = []
                    for doc in documents:
                        content = doc.page_content or ""
                        new_content, new_img_ids, asset_idx = self._upload_inline_images_to_minio(
                            markdown_text=content,
                            tenant_id=str(tenant_id),
                            dataset_id=dataset_id,
                            document_id=str(document_id),
                            cache=inline_cache,
                            start_index=asset_idx,
                            origin_path=file_path,
                        )
                        for iid in new_img_ids:
                            document_img_ids.add(iid)
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
                    documents = processed_docs

                if pipeline_effective.governance_enabled:
                    documents, governance_stats = governance_processor.clean_documents(
                        documents,
                        **governance_kwargs,
                    )

                resolved_chunk_strategy = chunker_factory.resolve_strategy(chunk_strategy)
                self._record_processing_metadata(
                    db,
                    document_id,
                    parser_backend=resolved_backend,
                    chunk_strategy=resolved_chunk_strategy
                )

                await self._update_status(
                    db, document_id, "processing", 33, "chunking"
                )

                # Step 3: 文本切片
                print(f"Chunking document into smaller pieces...")
                if pipeline_effective.chunk_overlap >= pipeline_effective.chunk_size:
                    raise ValueError("chunk_overlap must be less than chunk_size")
                chunker = chunker_factory.get_chunker(
                    resolved_chunk_strategy,
                    chunk_size=pipeline_effective.chunk_size,
                    chunk_overlap=pipeline_effective.chunk_overlap,
                )
                chunks = chunker.split_documents(documents)

            if governance_stats is not None:
                self._record_governance_metadata(db, document_id, governance_stats)

            # 为每个 chunk 添加元数据并处理图片上传到 MinIO
            for idx, chunk in enumerate(chunks):
                chunk.metadata['document_id'] = str(document_id)
                chunk.metadata['chunk_index'] = idx
                chunk.metadata['parser_backend'] = resolved_backend
                chunk.metadata['chunk_strategy'] = resolved_chunk_strategy
                
                # 提取并上传图片到 MinIO（如果启用）
                img_id = self._extract_and_upload_image_to_minio(
                    chunk.metadata,
                    tenant_id=str(tenant_id),
                    dataset_id=dataset_id,
                    document_id=str(document_id),
                    chunk_index=idx,
                )
                if not img_id:
                    img_id = self._extract_img_id_from_content(chunk.page_content)

                if img_id:
                    chunk.metadata['img_id'] = img_id
                    document_img_ids.add(img_id)

            # 将所有图片 img_id 记录到 document.metadata（用于删除清理等）
            self._record_document_image_ids(db, document_id=document_id, img_ids=document_img_ids)

            await self._update_status(
                db, document_id, "processing", 66, "embedding"
            )

            # Step 4/5: 向量化 + 写入 PostgreSQL + 增量更新 BM25（统一实现，避免多处重复）
            print(f"Saving chunks to PostgreSQL...")
            records: List[IndexRecord] = []
            for chunk in chunks:
                meta = dict(chunk.metadata or {})
                records.append(
                    IndexRecord(
                        kind=IndexKind.CHUNK,
                        content=chunk.page_content,
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
                options=index_options,
            ).chunk_result
            if persist_result is None:
                raise RuntimeError("Chunk indexing returned no result")
            chunk_ids = persist_result.chunk_ids

            # Step 6: 更新文档状态为完成
            total_chars = persist_result.total_characters
            await self._update_status(
                db,
                document_id,
                "completed",
                100,
                "completed",
                chunk_count=len(chunks),
                total_characters=total_chars
            )

            print(
                f"[OK] Document processed successfully: {len(chunks)} chunks "
                f"(parser={resolved_backend}, chunker={resolved_chunk_strategy})"
            )

            # Step 7: 如启用则运行 SAG 抽取（事件/实体）
            if pipeline_effective.sag_enabled:
                print("[*] Running SAG extraction on document chunks...")
                events = await extract_events(
                    chunk_ids,
                    tenant_id=tenant_id,
                    chunks=persist_result.db_chunks,
                    index_options=index_options,
                )
                print(f"[OK] SAG extracted {len(events)} events for document {document_id}")

            return {
                "status": "success",
                "chunk_count": len(chunks),
                "total_characters": total_chars,
                "parser_backend": resolved_backend,
                "chunk_strategy": resolved_chunk_strategy
            }

        except Exception as e:
            # 错误处理
            print(f"[ERR] Error processing document: {str(e)}")
            await self._update_status(
                db,
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
        document_id: UUID,
        status: str,
        progress: int,
        stage: str,
        **kwargs
    ):
        """更新文档处理状态"""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id
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
            all_chunks = db.query(DocumentChunk).join(DBDocument).filter(
                DBDocument.status == 'completed',
                DocumentChunk.tenant_id == tenant_id
            ).all()

            if all_chunks:
                print(f"🔎 Rebuilding BM25 index with {len(all_chunks)} chunks for tenant {tenant_id}...")
                Indexer(db).rebuild_tenant(tenant_id=tenant_id, kinds=[IndexKind.CHUNK])
            else:
                print("[WARN]  No chunks found for BM25 index")

        except Exception as e:
            print(f"[WARN]  Failed to rebuild BM25 index: {str(e)}")

    async def _rebuild_bm25_index(self, db: Session):
        """Rebuild BM25 indexes for all tenants."""
        try:
            tenant_rows = db.query(DocumentChunk.tenant_id).distinct().all()
            tenant_ids = [row[0] for row in tenant_rows if row and row[0]]
            if not tenant_ids:
                print("[WARN]  No chunks found for BM25 index")
                return
            for tid in tenant_ids:
                Indexer(db).rebuild_tenant(tenant_id=tid, kinds=[IndexKind.CHUNK])
        except Exception as e:
            print(f"[WARN]  Failed to rebuild BM25 index: {str(e)}")

    def _record_processing_metadata(
        self,
        db: Session,
        document_id: UUID,
        parser_backend: str,
        chunk_strategy: str
    ):
        """确保文档元数据里记录了最终选用的解析器。"""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id
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

    def _record_pipeline_effective(
        self,
        db: Session,
        document_id: UUID,
        effective: PipelineEffective,
    ) -> None:
        """Persist effective pipeline settings on the document metadata."""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id
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
            "sag_enabled": bool(effective.sag_enabled),
            "event_vector_enabled": bool(effective.event_vector_enabled),
            "entity_vector_enabled": bool(effective.entity_vector_enabled),
        }

        db_doc.doc_metadata = metadata
        db.commit()
        db.refresh(db_doc)

    def _record_governance_metadata(
        self,
        db: Session,
        document_id: UUID,
        stats: GovernanceStats,
    ) -> None:
        """Persist governance stats on the document metadata."""
        db_doc = db.query(DBDocument).filter(
            DBDocument.id == document_id
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

    def _record_document_image_ids(self, db: Session, document_id: UUID, img_ids: set[str]):
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

        db_doc = db.query(DBDocument).filter(DBDocument.id == document_id).first()
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
        if not isinstance(markdown_text, str) or "data:image" not in markdown_text:
            return markdown_text, [], start_index

        # 仅处理 markdown 图片与 html img，匹配 src 内容
        md_pat = re.compile(r"!\[[^\]]*\]\(([^)]+)\)", flags=re.IGNORECASE)
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

        new_ids: List[str] = []
        idx = int(start_index or 0)

        base_dir = origin_path.parent if origin_path else None

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
                    binary = base64.b64decode(b64_part)
                else:
                    # 本地/相对路径
                    path_obj = Path(ref)
                    if not path_obj.is_absolute():
                        if base_dir:
                            path_obj = (base_dir / path_obj).resolve()
                        else:
                            path_obj = path_obj.resolve()
                    if not path_obj.exists() or not path_obj.is_file():
                        continue
                    binary = path_obj.read_bytes()

                # 统一转 JPEG
                img = PILImage.open(BytesIO(binary))
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                out = BytesIO()
                img.save(out, format="JPEG", quality=85, optimize=True)
                image_bytes = out.getvalue()

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
                markdown_text = markdown_text.replace(ref, url)

            except Exception as e:
                print(f"[WARN] 内嵌/本地图片上传失败（跳过）: {e}")
                continue

        return markdown_text, new_ids, idx

    def _ragflow_chunk_file(self, file_path: Path, strategy: str):
        """
        调用 ragflow 预设（naive/book/laws/email）直接完成解析+切块，
        返回 LangChain Document 列表。
        """
        from langchain_core.documents import Document

        from app.rag.chunking.ragflow_legacy import chunk_file

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
            print(f"[WARN] 图片转换失败（跳过上传）: {e}")
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
            
            print(f"[MinIO] 图片已上传并绑定: img_id={img_id}")
            return img_id
            
        except Exception as e:
            print(f"[ERROR] MinIO 图片上传失败: {e}")
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
