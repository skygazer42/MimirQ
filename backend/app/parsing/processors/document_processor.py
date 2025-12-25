"""
文档处理服务 - 核心处理流程
"""
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from uuid import UUID
import asyncio
import base64
import hashlib

from app.core.config import settings
from app.models.document import Document as DBDocument, DocumentChunk
from app.parsing.factory import parser_factory
from app.parsing.chunking.factory import chunker_factory
from app.storage.vector.router import get_vector_store
from app.storage.search.hybrid_retriever import hybrid_retriever
from app.storage.object.minio import minio_service


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
            from app.core.database import SessionLocal

            db = SessionLocal()
            owns_db = True

        try:
            # Step 1: 更新状态为 processing
            await self._update_status(
                db, document_id, "processing", 0, "parsing"
            )

            use_ragflow = (chunk_strategy or "").lower() in {"ragflow_naive", "ragflow_book", "ragflow_laws", "ragflow_email"}

            if use_ragflow:
                resolved_backend = (parser_backend or "ragflow").lower()
                resolved_chunk_strategy = (chunk_strategy or "ragflow_naive").lower()

                # ragflow 直接解析+切块（同步），放到线程池避免阻塞事件循环
                chunks = await asyncio.to_thread(
                    self._ragflow_chunk_file,
                    file_path,
                    resolved_chunk_strategy
                )

            else:
                # Step 2: 解析文档
                print(f"Parsing document: {file_path}")
                documents, resolved_backend = parser_factory.parse(
                    file_path, parser_backend=parser_backend
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
                chunker = chunker_factory.get_chunker(
                    resolved_chunk_strategy,
                    chunk_size=settings.CHUNK_SIZE,
                    chunk_overlap=settings.CHUNK_OVERLAP
                )
                chunks = chunker.split_documents(documents)

            # 查询文档以获取 dataset_id
            db_document = db.query(DBDocument).filter(
                DBDocument.id == document_id
            ).first()
            dataset_id = str(db_document.dataset_id) if db_document and db_document.dataset_id else str(tenant_id)

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
                if img_id:
                    chunk.metadata['img_id'] = img_id

            await self._update_status(
                db, document_id, "processing", 66, "embedding"
            )

            # Step 4: 生成 Embeddings 并存入向量库（可配置后端）
            print(f"Generating embeddings and storing in vector backend...")

            # 转换为 Milvus 需要的格式
            milvus_docs = []
            for chunk in chunks:
                milvus_docs.append({
                    'content': chunk.page_content,
                    'metadata': chunk.metadata
                })

            vector_store = get_vector_store()
            try:
                vector_ids = vector_store.add_documents(
                    milvus_docs, document_id, tenant_id
                )
            except Exception as exc:
                print(f"[WARN]  Failed to store vectors: {exc}")
                print("[WARN]  Proceeding without vector ids; BM25-only retrieval will still work.")
                vector_ids = [None] * len(milvus_docs)

            # Step 5: 保存切片到数据库
            print(f"Saving chunks to PostgreSQL...")
            chunk_ids = await self._save_chunks_to_db(
                db, document_id, chunks, vector_ids, tenant_id
            )

            # Step 6: 更新文档状态为完成
            total_chars = sum(len(c.page_content) for c in chunks)
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
            if settings.SAG_ENABLED:
                try:
                    from app.services.sag_pipeline import extract_events

                    print("[*] Running SAG extraction on document chunks...")
                    events = await extract_events(chunk_ids, tenant_id=tenant_id)
                    print(f"[OK] SAG extracted {len(events)} events for document {document_id}")
                except Exception as exc:
                    print(f"[WARN]  SAG extraction failed: {exc}")

            # Step 8: 增量更新 BM25 索引（按租户，避免每次全量扫描）
            try:
                bm25_docs = []
                for chunk_doc, chunk_id in zip(chunks, chunk_ids):
                    meta = dict(chunk_doc.metadata or {})
                    meta.setdefault("tenant_id", str(tenant_id))
                    meta.setdefault("document_id", str(document_id))
                    meta.setdefault("chunk_index", meta.get("chunk_index"))
                    meta.setdefault("source", meta.get("source", "unknown"))
                    meta.setdefault("page", meta.get("page"))
                    meta.setdefault("image_id", meta.get("image_id"))
                    meta.setdefault("image_url", meta.get("image_url"))
                    bm25_docs.append(Document(page_content=chunk_doc.page_content, id=str(chunk_id), metadata=meta))
                hybrid_retriever.upsert_bm25_documents(bm25_docs, tenant_id=tenant_id)
            except Exception as exc:
                print(f"[WARN]  Failed to update BM25 index incrementally: {exc}")

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

    async def _save_chunks_to_db(
        self,
        db: Session,
        document_id: UUID,
        chunks: List[Document],
        vector_ids: List[Optional[str]],
        tenant_id: UUID
    ) -> List[UUID]:
        """保存切片到数据库并返回所有切片ID（用于后续 SAG 提取）"""
        if not vector_ids:
            vector_ids = [None] * len(chunks)
        if len(vector_ids) != len(chunks):
            raise ValueError(
                f"Vector ID count ({len(vector_ids)}) does not match chunk count ({len(chunks)})"
            )
        db_chunks = []
        for idx, (chunk, vector_id) in enumerate(zip(chunks, vector_ids)):
            db_chunks.append(
                DocumentChunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    chunk_index=idx,
                    content=chunk.page_content,
                    page_number=chunk.metadata.get('page'),
                    start_char=chunk.metadata.get('start_char'),
                    end_char=chunk.metadata.get('end_char'),
                    doc_metadata=chunk.metadata,
                    vector_id=vector_id
                )
            )

        # 批量插入减少 commit 次数和 ORM 开销
        db.bulk_save_objects(db_chunks)
        db.commit()

        # 返回刚写入的切片 ID（再次查询避免 bulk_save_objects 不回填主键）
        ids = [
            row[0]
            for row in db.query(DocumentChunk.id)
            .filter(
                DocumentChunk.document_id == document_id,
                DocumentChunk.tenant_id == tenant_id
            )
            .order_by(DocumentChunk.chunk_index)
            .all()
        ]
        return ids

    async def _rebuild_bm25_index_for_tenant(self, db: Session, tenant_id: UUID):
        """重建指定租户的 BM25 索引"""
        try:
            all_chunks = db.query(DocumentChunk).join(DBDocument).filter(
                DBDocument.status == 'completed',
                DocumentChunk.tenant_id == tenant_id
            ).all()

            if all_chunks:
                print(f"🔎 Rebuilding BM25 index with {len(all_chunks)} chunks for tenant {tenant_id}...")
                hybrid_retriever.build_bm25_index(all_chunks, tenant_id=tenant_id)
            else:
                print("[WARN]  No chunks found for BM25 index")

        except Exception as e:
            print(f"[WARN]  Failed to rebuild BM25 index: {str(e)}")

    async def _rebuild_bm25_index(self, db: Session):
        """重新构建 BM25 索引（包含所有已完成的文档片段）"""
        try:
            # 查询所有已完成文档的片段
            all_chunks = db.query(DocumentChunk).join(DBDocument).filter(
                DBDocument.status == 'completed'
            ).all()

            if all_chunks:
                print(f"🔄 Rebuilding BM25 index with {len(all_chunks)} chunks...")
                hybrid_retriever.build_bm25_index(all_chunks)
            else:
                print("[WARN]  No chunks found for BM25 index")

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

    def _ragflow_chunk_file(self, file_path: Path, strategy: str):
        """
        调用 ragflow 预设（naive/book/laws/email）直接完成解析+切块，
        返回 LangChain Document 列表。
        """
        from langchain_core.documents import Document

        # 选择 ragflow chunk 函数
        strat = strategy.lower()
        if strat == "ragflow_naive":
            from app.rag.ragflow.chunkers.naive import chunk as rf_chunk
        elif strat == "ragflow_book":
            from app.rag.ragflow.chunkers.book import chunk as rf_chunk
        elif strat == "ragflow_laws":
            from app.rag.ragflow.chunkers.laws import chunk as rf_chunk
        elif strat == "ragflow_email":
            from app.rag.ragflow.chunkers.email import chunk as rf_chunk
        else:
            raise ValueError(f"Unsupported ragflow strategy: {strategy}")

        def callback(prog=None, msg=""):
            # 简单日志回调
            if msg:
                print(f"[ragflow] {msg} ({prog})")

        # ragflow chunk 返回 list[dict]（tokenize_chunks 输出格式）
        chunks_dict = rf_chunk(
            str(file_path),
            callback=callback
        )

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
            from io import BytesIO
            from PIL import Image as PILImage

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
