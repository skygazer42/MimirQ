"""
文档处理服务 - 核心处理流程
"""
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from uuid import UUID
import asyncio

from app.config import settings
from app.models.document import Document as DBDocument, DocumentChunk
from app.services.parsers import parser_factory
from app.services.chunkers import chunker_factory
from app.services.milvus_store import milvus_store
from app.services.hybrid_retriever import hybrid_retriever


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
        db: Session,
        parser_backend: Optional[str] = None,
        chunk_strategy: Optional[str] = None
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

            # 为每个 chunk 添加元数据
            for idx, chunk in enumerate(chunks):
                chunk.metadata['document_id'] = str(document_id)
                chunk.metadata['chunk_index'] = idx
                chunk.metadata['parser_backend'] = resolved_backend
                chunk.metadata['chunk_strategy'] = resolved_chunk_strategy

            await self._update_status(
                db, document_id, "processing", 66, "embedding"
            )

            # Step 4: 生成 Embeddings 并存入 Milvus
            print(f"Generating embeddings and storing in Milvus...")

            # 转换为 Milvus 需要的格式
            milvus_docs = []
            for chunk in chunks:
                milvus_docs.append({
                    'content': chunk.page_content,
                    'metadata': chunk.metadata
                })

            vector_ids = milvus_store.add_documents(
                milvus_docs, document_id
            )

            # Step 5: 保存切片到数据库
            print(f"Saving chunks to PostgreSQL...")
            await self._save_chunks_to_db(
                db, document_id, chunks, vector_ids
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
                f"✅ Document processed successfully: {len(chunks)} chunks "
                f"(parser={resolved_backend}, chunker={resolved_chunk_strategy})"
            )

            # Step 7: 重新构建 BM25 索引（包含所有文档）
            await self._rebuild_bm25_index(db)

            return {
                "status": "success",
                "chunk_count": len(chunks),
                "total_characters": total_chars,
                "parser_backend": resolved_backend,
                "chunk_strategy": resolved_chunk_strategy
            }

        except Exception as e:
            # 错误处理
            print(f"❌ Error processing document: {str(e)}")
            await self._update_status(
                db,
                document_id,
                "failed",
                0,
                "failed",
                error_message=str(e)
            )
            raise

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
        vector_ids: List[str]
    ):
        """保存切片到数据库"""
        if len(vector_ids) != len(chunks):
            raise ValueError(
                f"Vector ID count ({len(vector_ids)}) does not match chunk count ({len(chunks)})"
            )
        db_chunks = [
            DocumentChunk(
                document_id=document_id,
                chunk_index=idx,
                content=chunk.page_content,
                page_number=chunk.metadata.get('page'),
                start_char=chunk.metadata.get('start_char'),
                end_char=chunk.metadata.get('end_char'),
                doc_metadata=chunk.metadata,
                vector_id=vector_id
            )
            for idx, (chunk, vector_id) in enumerate(zip(chunks, vector_ids))
        ]

        # 批量插入减少 commit 次数和 ORM 开销
        db.bulk_save_objects(db_chunks)
        db.commit()

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
                print("⚠️  No chunks found for BM25 index")

        except Exception as e:
            print(f"⚠️  Failed to rebuild BM25 index: {str(e)}")

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
        import sys
        from langchain_core.documents import Document

        # 确保 third_party 在路径中（start 脚本已加，这里再兜底）
        tp = str(Path(__file__).resolve().parents[2] / "third_party")
        if tp not in sys.path:
            sys.path.insert(0, tp)

        # 选择 ragflow chunk 函数
        strat = strategy.lower()
        if strat == "ragflow_naive":
            from ragflow.app.naive import chunk as rf_chunk
        elif strat == "ragflow_book":
            from ragflow.app.book import chunk as rf_chunk
        elif strat == "ragflow_laws":
            from ragflow.app.laws import chunk as rf_chunk
        elif strat == "ragflow_email":
            from ragflow.app.email import chunk as rf_chunk
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


# 全局实例
document_processor = DocumentProcessorService()
