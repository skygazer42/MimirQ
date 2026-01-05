"""
FastAPI 主应用入口
"""
import warnings

# Quiet noisy third-party deprecation warnings during local development.
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API\..*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"The pynvml package is deprecated\..*",
    category=FutureWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"Using default SECRET_KEY\. Change this in production!",
    category=UserWarning,
)

import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.exceptions import register_exception_handlers
from app.core.migrations import apply_runtime_migrations
from app.core.utils import parse_csv
from app.api.v1 import router as api_v1_router
from app.rag.retriever import hybrid_retriever
from app.models.document import DocumentChunk, Document as DBDocument
from app.storage.vector.milvus import milvus_store
from app.storage.object.minio import minio_service
from app.core.http_client import close_http_client_pool
from app.tasks.queue import init_queue, close_queue, is_queue_initialized
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

    # Ensure local directories exist (uploads/logs/vector persistence).
    for dir_path in [
        settings.UPLOAD_DIR,
        settings.FAISS_STORE_PATH if getattr(settings, "VECTOR_BACKEND", "milvus") == "faiss" else None,
        settings.CHROMA_PERSIST_PATH if getattr(settings, "VECTOR_BACKEND", "milvus") == "chroma" else None,
    ]:
        if not dir_path:
            continue
        try:
            Path(str(dir_path)).mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to ensure directory %s: %s", str(dir_path), str(exc)[:200])

    if bool(getattr(settings, "ENABLE_METRICS_LOG", False)):
        try:
            Path(str(getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl"))).parent.mkdir(
                parents=True, exist_ok=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to ensure metrics log dir: %s", str(exc)[:200])

    if bool(getattr(settings, "MINIO_ENABLED", False)):
        try:
            Path(str(getattr(settings, "MINIO_METRICS_LOG_PATH", "./logs/minio_metrics.jsonl"))).parent.mkdir(
                parents=True, exist_ok=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to ensure MinIO metrics log dir: %s", str(exc)[:200])

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

    # 初始化任务队列（可选）
    try:
        await init_queue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to init task queue: %s", str(exc)[:200])

    # 初始化 BM25 索引（可选：大规模部署建议依赖 lazy-build）
    if not bool(getattr(settings, "BM25_INDEX_ENABLED", True)):
        logger.info("BM25 indexing disabled; skipping startup build")
    elif not bool(getattr(settings, "BM25_STARTUP_BUILD_ENABLED", False)):
        logger.info("BM25 startup build disabled (BM25_STARTUP_BUILD_ENABLED=false)")
    else:
        logger.info("Initializing BM25 index (startup build)...")
        db = SessionLocal()
        try:
            from sqlalchemy import func

            max_chunks = int(getattr(settings, "BM25_STARTUP_BUILD_MAX_CHUNKS", 0) or 0)
            total_chunks = (
                db.query(func.count(DocumentChunk.id))
                .join(DBDocument)
                .filter(DBDocument.status == "completed")
                .scalar()
            ) or 0

            if max_chunks > 0 and int(total_chunks) > max_chunks:
                logger.warning(
                    "Skipping BM25 startup build: %s chunks exceeds cap %s; "
                    "enable BM25_LAZY_BUILD_ENABLED for on-demand builds",
                    int(total_chunks),
                    max_chunks,
                )
            else:
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
    
    # 关闭 HTTP 客户端连接池
    await close_http_client_pool()
    logger.info("HTTP client pool closed")

    # 关闭任务队列连接（可选）
    await close_queue()


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
    allow_origins=parse_csv(settings.CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Rate Limiting 中间件
if settings.RATE_LIMIT_ENABLED:
    from app.api.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(
        RateLimitMiddleware,
        requests_per_second=settings.RATE_LIMIT_REQUESTS_PER_SECOND,
        burst_size=settings.RATE_LIMIT_BURST_SIZE,
        chat_requests_per_second=settings.RATE_LIMIT_CHAT_RPS,
        chat_burst_size=settings.RATE_LIMIT_CHAT_BURST,
        chat_prefixes=["/api/v1/chat/stream"],
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

    vector_backend = (getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").lower()
    vector_status: dict = {"backend": vector_backend, "status": "unknown"}

    milvus_status = {"status": "not_configured", "count": None}
    if vector_backend == "milvus":
        milvus_status = {"status": "disconnected", "count": None}
        try:
            milvus_status["count"] = milvus_store.get_collection_count()
            milvus_status["status"] = "connected"
        except Exception as exc:
            milvus_status["error"] = str(exc)[:200]
        vector_status.update(milvus_status)
    elif vector_backend == "faiss":
        path = Path(str(getattr(settings, "FAISS_STORE_PATH", "./vector_faiss")))
        vector_status.update({"status": "ready" if path.exists() else "missing", "path": str(path)})
    elif vector_backend == "chroma":
        path = Path(str(getattr(settings, "CHROMA_PERSIST_PATH", "./vector_chroma")))
        vector_status.update({"status": "ready" if path.exists() else "missing", "path": str(path)})
    elif vector_backend == "memory":
        vector_status.update({"status": "ready"})

    minio_status = {"status": "disabled"}
    if settings.MINIO_ENABLED:
        try:
            minio_service._get_client()
            minio_status["status"] = "connected"
            minio_status["bucket"] = settings.MINIO_BUCKET_NAME
        except Exception as exc:
            minio_status["status"] = "disconnected"
            minio_status["error"] = str(exc)[:200]

    uploads_status = {"status": "unknown", "path": settings.UPLOAD_DIR}
    try:
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        uploads_status["status"] = "ready"
    except Exception as exc:  # noqa: BLE001
        uploads_status["status"] = "unavailable"
        uploads_status["error"] = str(exc)[:200]

    redis_required = bool(getattr(settings, "TASK_QUEUE_ENABLED", False))
    redis_optional_cache = bool(getattr(settings, "EMBEDDING_CACHE_ENABLED", False))
    redis_enabled = redis_required or redis_optional_cache
    redis_status = {
        "status": "disabled",
        "enabled": redis_enabled,
        "required": redis_required,
        "embedding_cache_enabled": redis_optional_cache,
    }
    if redis_enabled:
        try:
            import redis

            r = redis.Redis.from_url(
                settings.REDIS_URL,
                socket_timeout=1,
                socket_connect_timeout=1,
                decode_responses=True,
            )
            r.ping()
            redis_status["status"] = "connected"
        except Exception as exc:  # noqa: BLE001
            redis_status["status"] = "disconnected"
            redis_status["error"] = str(exc)[:200]

    task_queue_status = {
        "enabled": bool(getattr(settings, "TASK_QUEUE_ENABLED", False)),
        "queue": getattr(settings, "TASK_QUEUE_NAME", "mimirq"),
        "status": "disabled",
    }
    if task_queue_status["enabled"]:
        task_queue_status["initialized"] = is_queue_initialized()
        task_queue_status["status"] = "connected" if task_queue_status["initialized"] else "not_initialized"

    return {
        "status": "healthy",
        "database": db_status,
        "vector": vector_status,
        "milvus": milvus_status,
        "redis": redis_status,
        "task_queue": task_queue_status,
        "uploads": uploads_status,
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
