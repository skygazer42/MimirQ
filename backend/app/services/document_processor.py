"""
文档处理服务 - 核心处理流程
"""
from pathlib import Path
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from uuid import UUID
import asyncio

from app.config import settings
from app.models.document import Document as DBDocument, DocumentChunk
from app.services.parsers import parser_factory
from app.services.milvus_store import milvus_store


class DocumentProcessorService:
    """文档处理服务"""

    def __init__(self):
        # LangChain 文本切片器
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
            length_function=len,
        )

    async def process_document(
        self,
        file_path: Path,
        document_id: UUID,
        db: Session
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

            # Step 2: 解析文档
            print(f"Parsing document: {file_path}")
            documents = parser_factory.parse(file_path)

            await self._update_status(
                db, document_id, "processing", 33, "chunking"
            )

            # Step 3: 文本切片
            print(f"Chunking document into smaller pieces...")
            chunks = self.text_splitter.split_documents(documents)

            # 为每个 chunk 添加元数据
            for idx, chunk in enumerate(chunks):
                chunk.metadata['document_id'] = str(document_id)
                chunk.metadata['chunk_index'] = idx

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

            print(f"✅ Document processed successfully: {len(chunks)} chunks")

            return {
                "status": "success",
                "chunk_count": len(chunks),
                "total_characters": total_chars
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
        for idx, (chunk, vector_id) in enumerate(zip(chunks, vector_ids)):
            db_chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=idx,
                content=chunk.page_content,
                page_number=chunk.metadata.get('page'),
                metadata=chunk.metadata,
                vector_id=vector_id
            )
            db.add(db_chunk)

        db.commit()


# 全局实例
document_processor = DocumentProcessorService()
