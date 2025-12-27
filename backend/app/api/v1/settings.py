"""
Settings API - 系统配置管理
支持读取和更新 .env 配置
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from pathlib import Path

from app.core.config import settings

router = APIRouter()

# .env 文件路径
ENV_FILE = Path(__file__).parent.parent.parent.parent / ".env"


class FeatureFlags(BaseModel):
    """功能开关"""
    kg_enabled: bool = False
    deepdoc_enabled: bool = False
    markitdown_enabled: bool = False
    llama_index_enabled: bool = False
    mineru_enabled: bool = False


class LLMConfig(BaseModel):
    """LLM 配置"""
    api_key: str = ""
    api_base: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    timeout: int = 60
    max_retries: int = 3


class EmbeddingConfig(BaseModel):
    """Embedding 配置"""
    provider: str = "openai_compatible"
    model: str = "text-embedding-3-small"
    api_key: str = ""
    api_base: str = ""


class MilvusConfig(BaseModel):
    """Milvus 配置"""
    host: str = "localhost"
    port: int = 19530
    user: str = ""
    password: str = ""
    collection_name: str = "documents"


class RAGConfig(BaseModel):
    """RAG 参数配置"""
    chunk_size: int = 1000
    chunk_overlap: int = 200
    retrieval_top_k: int = 5
    similarity_threshold: float = 0.7
    default_parser_backend: str = "auto"
    default_chunk_strategy: str = "langchain_recursive"


class MinerUConfig(BaseModel):
    """MinerU 配置"""
    api_token: str = ""
    api_base: str = "https://mineru.net/api/v4"
    model_version: str = "vlm"


class SystemSettings(BaseModel):
    """完整系统配置"""
    feature_flags: FeatureFlags
    llm: LLMConfig
    embedding: EmbeddingConfig
    milvus: MilvusConfig
    rag: RAGConfig
    mineru: MinerUConfig


class UpdateSettingsRequest(BaseModel):
    """更新配置请求"""
    feature_flags: Optional[FeatureFlags] = None
    llm: Optional[LLMConfig] = None
    embedding: Optional[EmbeddingConfig] = None
    milvus: Optional[MilvusConfig] = None
    rag: Optional[RAGConfig] = None
    mineru: Optional[MinerUConfig] = None


def read_env_file() -> Dict[str, str]:
    """读取 .env 文件"""
    env_vars = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    env_vars[key.strip()] = value.strip()
    return env_vars


def write_env_file(env_vars: Dict[str, str]):
    """写入 .env 文件，保留注释和格式"""
    lines = []
    existing_keys = set()

    # 读取现有文件保留注释
    if ENV_FILE.exists():
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('#') or not stripped:
                    lines.append(line.rstrip('\n'))
                elif '=' in stripped:
                    key = stripped.split('=')[0].strip()
                    existing_keys.add(key)
                    if key in env_vars:
                        lines.append(f"{key}={env_vars[key]}")
                    else:
                        lines.append(line.rstrip('\n'))

    # 添加新的键值对
    for key, value in env_vars.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")

    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def mask_secret(value: str) -> str:
    """隐藏敏感信息"""
    if not value or len(value) < 8:
        return "***" if value else ""
    return value[:4] + "***" + value[-4:]


@router.get("", response_model=SystemSettings)
async def get_settings():
    """获取当前系统配置"""
    return SystemSettings(
        feature_flags=FeatureFlags(
            kg_enabled=settings.KG_ENABLED,
            deepdoc_enabled=settings.DEEPDOC_ENABLED,
            markitdown_enabled=settings.MARKITDOWN_ENABLED,
            llama_index_enabled=settings.LLAMA_INDEX_ENABLED,
            mineru_enabled=settings.MINERU_ENABLED,
        ),
        llm=LLMConfig(
            api_key=mask_secret(settings.LLM_API_KEY),
            api_base=settings.LLM_API_BASE,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
        ),
        embedding=EmbeddingConfig(
            provider=settings.EMBEDDING_PROVIDER,
            model=settings.EMBEDDING_MODEL,
            api_key=mask_secret(settings.EMBEDDING_API_KEY),
            api_base=settings.EMBEDDING_API_BASE,
        ),
        milvus=MilvusConfig(
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            user=settings.MILVUS_USER,
            password=mask_secret(settings.MILVUS_PASSWORD),
            collection_name=settings.MILVUS_COLLECTION_NAME,
        ),
        rag=RAGConfig(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            retrieval_top_k=settings.RETRIEVAL_TOP_K,
            similarity_threshold=settings.SIMILARITY_THRESHOLD,
            default_parser_backend=settings.DEFAULT_PARSER_BACKEND,
            default_chunk_strategy=settings.DEFAULT_CHUNK_STRATEGY,
        ),
        mineru=MinerUConfig(
            api_token=mask_secret(settings.MINERU_API_TOKEN),
            api_base=settings.MINERU_API_BASE,
            model_version=settings.MINERU_MODEL_VERSION,
        ),
    )


@router.put("")
async def update_settings(request: UpdateSettingsRequest):
    """更新系统配置（写入 .env 文件）"""
    try:
        env_vars = read_env_file()
        updated_keys = []

        # 更新功能开关
        if request.feature_flags:
            ff = request.feature_flags
            env_vars["KG_ENABLED"] = str(ff.kg_enabled).lower()
            env_vars["DEEPDOC_ENABLED"] = str(ff.deepdoc_enabled).lower()
            env_vars["MARKITDOWN_ENABLED"] = str(ff.markitdown_enabled).lower()
            env_vars["LLAMA_INDEX_ENABLED"] = str(ff.llama_index_enabled).lower()
            env_vars["MINERU_ENABLED"] = str(ff.mineru_enabled).lower()
            updated_keys.extend(["KG_ENABLED", "DEEPDOC_ENABLED", "MARKITDOWN_ENABLED", "LLAMA_INDEX_ENABLED", "MINERU_ENABLED"])

        # 更新 LLM 配置
        if request.llm:
            llm = request.llm
            # 只有非掩码值才更新
            if llm.api_key and "***" not in llm.api_key:
                env_vars["LLM_API_KEY"] = llm.api_key
                updated_keys.append("LLM_API_KEY")
            env_vars["LLM_API_BASE"] = llm.api_base
            env_vars["LLM_MODEL"] = llm.model
            env_vars["LLM_TEMPERATURE"] = str(llm.temperature)
            env_vars["LLM_TIMEOUT"] = str(llm.timeout)
            env_vars["LLM_MAX_RETRIES"] = str(llm.max_retries)
            updated_keys.extend(["LLM_API_BASE", "LLM_MODEL", "LLM_TEMPERATURE", "LLM_TIMEOUT", "LLM_MAX_RETRIES"])

        # 更新 Embedding 配置
        if request.embedding:
            emb = request.embedding
            env_vars["EMBEDDING_PROVIDER"] = emb.provider
            env_vars["EMBEDDING_MODEL"] = emb.model
            if emb.api_key and "***" not in emb.api_key:
                env_vars["EMBEDDING_API_KEY"] = emb.api_key
                updated_keys.append("EMBEDDING_API_KEY")
            env_vars["EMBEDDING_API_BASE"] = emb.api_base
            updated_keys.extend(["EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_API_BASE"])

        # 更新 Milvus 配置
        if request.milvus:
            mv = request.milvus
            env_vars["MILVUS_HOST"] = mv.host
            env_vars["MILVUS_PORT"] = str(mv.port)
            env_vars["MILVUS_USER"] = mv.user
            if mv.password and "***" not in mv.password:
                env_vars["MILVUS_PASSWORD"] = mv.password
                updated_keys.append("MILVUS_PASSWORD")
            env_vars["MILVUS_COLLECTION_NAME"] = mv.collection_name
            updated_keys.extend(["MILVUS_HOST", "MILVUS_PORT", "MILVUS_USER", "MILVUS_COLLECTION_NAME"])

        # 更新 RAG 配置
        if request.rag:
            rag = request.rag
            env_vars["CHUNK_SIZE"] = str(rag.chunk_size)
            env_vars["CHUNK_OVERLAP"] = str(rag.chunk_overlap)
            env_vars["RETRIEVAL_TOP_K"] = str(rag.retrieval_top_k)
            env_vars["SIMILARITY_THRESHOLD"] = str(rag.similarity_threshold)
            env_vars["DEFAULT_PARSER_BACKEND"] = rag.default_parser_backend
            env_vars["DEFAULT_CHUNK_STRATEGY"] = rag.default_chunk_strategy
            updated_keys.extend(["CHUNK_SIZE", "CHUNK_OVERLAP", "RETRIEVAL_TOP_K", "SIMILARITY_THRESHOLD", "DEFAULT_PARSER_BACKEND", "DEFAULT_CHUNK_STRATEGY"])

        # 更新 MinerU 配置
        if request.mineru:
            mn = request.mineru
            if mn.api_token and "***" not in mn.api_token:
                env_vars["MINERU_API_TOKEN"] = mn.api_token
                updated_keys.append("MINERU_API_TOKEN")
            env_vars["MINERU_API_BASE"] = mn.api_base
            env_vars["MINERU_MODEL_VERSION"] = mn.model_version
            updated_keys.extend(["MINERU_API_BASE", "MINERU_MODEL_VERSION"])

        write_env_file(env_vars)

        return {
            "success": True,
            "message": "配置已保存，部分设置需要重启后端服务才能生效",
            "updated_keys": updated_keys
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")


@router.get("/status")
async def get_system_status():
    """获取系统状态"""
    from sqlalchemy import text
    from app.core.database import SessionLocal
    from pymilvus import connections

    status = {
        "database": {"connected": False, "message": ""},
        "milvus": {"connected": False, "message": ""},
        "llm": {"configured": bool(settings.LLM_API_KEY), "model": settings.LLM_MODEL},
        "embedding": {"configured": bool(settings.EMBEDDING_API_KEY or settings.LLM_API_KEY), "model": settings.EMBEDDING_MODEL},
    }

    # 检查数据库连接
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        status["database"]["connected"] = True
        status["database"]["message"] = "已连接"
    except Exception as e:
        status["database"]["message"] = str(e)[:100]

    # 检查 Milvus 连接
    try:
        connections.connect(
            alias="status_check",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            user=settings.MILVUS_USER or None,
            password=settings.MILVUS_PASSWORD or None,
        )
        connections.disconnect("status_check")
        status["milvus"]["connected"] = True
        status["milvus"]["message"] = "已连接"
    except Exception as e:
        status["milvus"]["message"] = str(e)[:100]

    return status
