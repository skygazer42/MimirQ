"""
FastAPI 主应用入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.config import settings
from app.database import engine, Base, get_db
from app.api.v1 import router as api_v1_router


# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭时的操作"""
    # 启动时：创建数据库表
    print("🚀 Starting MimirQ backend...")
    print("📦 Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized")

    # 初始化 BM25 索引
    print("🔍 Initializing BM25 index...")
    try:
        from app.services.hybrid_retriever import hybrid_retriever
        from app.models.document import DocumentChunk, Document as DBDocument

        db = next(get_db())
        all_chunks = db.query(DocumentChunk).join(DBDocument).filter(
            DBDocument.status == 'completed'
        ).all()

        if all_chunks:
            hybrid_retriever.build_bm25_index(all_chunks)
            print(f"✅ BM25 index loaded with {len(all_chunks)} chunks")
        else:
            print("⚠️  No documents found, BM25 index will be built on first upload")
    except Exception as e:
        print(f"⚠️  Failed to load BM25 index: {str(e)}")

    yield

    # 关闭时的清理操作
    print("👋 Shutting down MimirQ backend...")


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
    from app.services.milvus_store import milvus_store

    return {
        "status": "healthy",
        "database": "connected",
        "milvus": {
            "status": "connected",
            "count": milvus_store.get_collection_count()
        }
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )
