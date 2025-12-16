"""
FastAPI 主应用入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.api.v1 import router as api_v1_router
# Ensure SAG models are registered for metadata creation
import app.models.sag_entities  # noqa: F401
# Ensure evaluation models are registered for metadata creation
import app.models.evaluation  # noqa: F401


# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭时的操作"""
    # 启动时：创建数据库表
    print("[*] Starting MimirQ backend...")
    print("[*] Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("[OK] Database initialized")

    # 初始化 BM25 索引
    print("[*] Initializing BM25 index...")
    try:
        from app.services.hybrid_retriever import hybrid_retriever
        from app.models.document import DocumentChunk, Document as DBDocument

        db = SessionLocal()
        try:
            tenant_ids = db.query(DocumentChunk.tenant_id).join(DBDocument).filter(
                DBDocument.status == 'completed'
            ).distinct().all()

            if tenant_ids:
                total = 0
                for (tid,) in tenant_ids:
                    chunks = db.query(DocumentChunk).join(DBDocument).filter(
                        DBDocument.status == 'completed',
                        DocumentChunk.tenant_id == tid
                    ).all()
                    if chunks:
                        hybrid_retriever.build_bm25_index(chunks, tenant_id=tid)
                        total += len(chunks)
                if total:
                    print(f"[OK] BM25 index loaded with {total} chunks across {len(tenant_ids)} tenants")
                else:
                    print("[WARN]  No documents found, BM25 index will be built on first upload")
            else:
                print("[WARN]  No documents found, BM25 index will be built on first upload")
        finally:
            db.close()
    except Exception as e:
        print(f"[WARN]  Failed to load BM25 index: {str(e)}")

    yield

    # 关闭时的清理操作
    print("[*] Shutting down MimirQ backend...")


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

# 注册路由
app.include_router(api_v1_router, prefix="/api/v1")


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
    milvus_status = {"status": "disconnected", "count": None}
    try:
        from app.services.milvus_store import milvus_store

        milvus_status["count"] = milvus_store.get_collection_count()
        milvus_status["status"] = "connected"
    except Exception as exc:
        milvus_status["error"] = str(exc)

    return {
        "status": "healthy",
        "database": "connected",
        "milvus": milvus_status,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )
