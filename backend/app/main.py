"""
FastAPI 主应用入口
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.exceptions import register_exception_handlers
from app.core.runtime_migrations import apply_runtime_migrations
from app.api.v1 import router as api_v1_router
from app.rag.retriever import hybrid_retriever
from app.models.document import DocumentChunk, Document as DBDocument
from app.storage.vector.milvus import milvus_store
from app.storage.object.minio import minio_service
# Ensure KG models are registered for metadata creation
import app.rag.kg.models  # noqa: F401
# Ensure evaluation models are registered for metadata creation
import app.models.evaluation  # noqa: F401
# Ensure feedback models are registered for metadata creation
import app.models.feedback  # noqa: F401

logger = logging.getLogger("mimirq")


# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭时的操作"""
    # 启动时：创建数据库表
    logger.info("Starting MimirQ backend...")

    if bool(getattr(settings, "LANGSMITH_TRACING_ENABLED", False)):
        try:
            from app.rag.tracing import setup_tracing

            setup_tracing()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to setup LangSmith tracing: %s", str(exc)[:200])
    # Best-effort runtime migrations run before/after `create_all()`:
    # - before: upgrade existing deployments early (best-effort)
    # - after: ensure fresh tables get latest columns/indexes
    apply_runtime_migrations(engine)

    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    apply_runtime_migrations(engine)
    logger.info("Database initialized")

    # 初始化 BM25 索引
    logger.info("Initializing BM25 index...")
    db = SessionLocal()
    try:
        # Single query to get all chunks with completed documents (avoids N+1)
        all_chunks = (
            db.query(DocumentChunk)
            .join(DBDocument)
            .filter(DBDocument.status == "completed")
            .all()
        )

        if all_chunks:
            # Group chunks by tenant_id in Python
            from collections import defaultdict
            chunks_by_tenant: dict = defaultdict(list)
            for chunk in all_chunks:
                chunks_by_tenant[chunk.tenant_id].append(chunk)

            for tid, chunks in chunks_by_tenant.items():
                hybrid_retriever.build_bm25_index(chunks, tenant_id=tid)

            logger.info(
                "BM25 index loaded with %s chunks across %s tenants",
                len(all_chunks),
                len(chunks_by_tenant),
            )
        else:
            logger.warning("No documents found, BM25 index will be built on first upload")
    finally:
        db.close()

    yield

    # 关闭时的清理操作
    logger.info("Shutting down MimirQ backend...")


# 创建 FastAPI 应用
app = FastAPI(
    title="MimirQ - Knowledge Base RAG System",
    description="知识库管理与 RAG 对话系统",
    version="1.0.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting 中间件
if settings.RATE_LIMIT_ENABLED:
    from app.api.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(
        RateLimitMiddleware,
        requests_per_second=settings.RATE_LIMIT_REQUESTS_PER_SECOND,
        burst_size=settings.RATE_LIMIT_BURST_SIZE,
    )

# 注册路由
app.include_router(api_v1_router, prefix="/api/v1")

# 注册异常处理器
register_exception_handlers(app)


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "Welcome to MimirQ API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    from sqlalchemy import text

    db_status = {"status": "disconnected"}
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_status["status"] = "connected"
    except Exception as exc:
        db_status["error"] = str(exc)[:200]
    finally:
        db.close()

    milvus_status = {"status": "disconnected", "count": None}
    try:
        milvus_status["count"] = milvus_store.get_collection_count()
        milvus_status["status"] = "connected"
    except Exception as exc:
        milvus_status["error"] = str(exc)[:200]

    minio_status = {"status": "disabled"}
    if settings.MINIO_ENABLED:
        try:
            minio_service._get_client()
            minio_status["status"] = "connected"
            minio_status["bucket"] = settings.MINIO_BUCKET_NAME
        except Exception as exc:
            minio_status["status"] = "disconnected"
            minio_status["error"] = str(exc)[:200]

    return {
        "status": "healthy",
        "database": db_status,
        "milvus": milvus_status,
        "minio": minio_status,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )
