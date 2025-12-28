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


class ObservabilityConfig(BaseModel):
    """观测/调试相关配置"""
    tool_call_log_enabled: bool = False
    tool_call_log_include_preview: bool = False
    tool_call_log_max_preview_chars: int = 500

    agent_log_enabled: bool = False
    agent_log_include_execution_path: bool = False
    agent_log_max_preview_chars: int = 500


class SafetyConfig(BaseModel):
    """安全/隐私相关配置"""
    pii_redaction_enabled: bool = False
    pii_redaction_mask: str = "[REDACTED]"
    pii_stream_holdback_chars: int = 128


class LangGraphConfig(BaseModel):
    """LangGraph 运行方式配置"""
    use_subgraphs: bool = False


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
    observability: ObservabilityConfig
    safety: SafetyConfig
    langgraph: LangGraphConfig


class UpdateSettingsRequest(BaseModel):
    """更新配置请求"""
    feature_flags: Optional[FeatureFlags] = None
    llm: Optional[LLMConfig] = None
    embedding: Optional[EmbeddingConfig] = None
    milvus: Optional[MilvusConfig] = None
    rag: Optional[RAGConfig] = None
    mineru: Optional[MinerUConfig] = None
    observability: Optional[ObservabilityConfig] = None
    safety: Optional[SafetyConfig] = None
    langgraph: Optional[LangGraphConfig] = None


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _parse_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _apply_runtime_settings(env_vars: Dict[str, str], updated_keys: list[str]) -> None:
    """
    Best-effort: apply updated .env values to the in-memory settings object so
    config changes can take effect without a restart.
    """
    # Feature flags
    if "KG_ENABLED" in updated_keys and "KG_ENABLED" in env_vars:
        settings.KG_ENABLED = _parse_bool(env_vars["KG_ENABLED"])
    if "DEEPDOC_ENABLED" in updated_keys and "DEEPDOC_ENABLED" in env_vars:
        settings.DEEPDOC_ENABLED = _parse_bool(env_vars["DEEPDOC_ENABLED"])
    if "MARKITDOWN_ENABLED" in updated_keys and "MARKITDOWN_ENABLED" in env_vars:
        settings.MARKITDOWN_ENABLED = _parse_bool(env_vars["MARKITDOWN_ENABLED"])
    if "LLAMA_INDEX_ENABLED" in updated_keys and "LLAMA_INDEX_ENABLED" in env_vars:
        settings.LLAMA_INDEX_ENABLED = _parse_bool(env_vars["LLAMA_INDEX_ENABLED"])
    if "MINERU_ENABLED" in updated_keys and "MINERU_ENABLED" in env_vars:
        settings.MINERU_ENABLED = _parse_bool(env_vars["MINERU_ENABLED"])

    # LLM
    if "LLM_API_KEY" in updated_keys and "LLM_API_KEY" in env_vars:
        settings.LLM_API_KEY = env_vars["LLM_API_KEY"]
    if "LLM_API_BASE" in updated_keys and "LLM_API_BASE" in env_vars:
        settings.LLM_API_BASE = env_vars["LLM_API_BASE"]
    if "LLM_MODEL" in updated_keys and "LLM_MODEL" in env_vars:
        settings.LLM_MODEL = env_vars["LLM_MODEL"]
    if "LLM_TEMPERATURE" in updated_keys and "LLM_TEMPERATURE" in env_vars:
        settings.LLM_TEMPERATURE = _parse_float(env_vars["LLM_TEMPERATURE"], default=settings.LLM_TEMPERATURE)
    if "LLM_TIMEOUT" in updated_keys and "LLM_TIMEOUT" in env_vars:
        settings.LLM_TIMEOUT = _parse_int(env_vars["LLM_TIMEOUT"], default=settings.LLM_TIMEOUT)
    if "LLM_MAX_RETRIES" in updated_keys and "LLM_MAX_RETRIES" in env_vars:
        settings.LLM_MAX_RETRIES = _parse_int(env_vars["LLM_MAX_RETRIES"], default=settings.LLM_MAX_RETRIES)

    # Embedding
    if "EMBEDDING_PROVIDER" in updated_keys and "EMBEDDING_PROVIDER" in env_vars:
        settings.EMBEDDING_PROVIDER = env_vars["EMBEDDING_PROVIDER"]
    if "EMBEDDING_MODEL" in updated_keys and "EMBEDDING_MODEL" in env_vars:
        settings.EMBEDDING_MODEL = env_vars["EMBEDDING_MODEL"]
    if "EMBEDDING_API_KEY" in updated_keys and "EMBEDDING_API_KEY" in env_vars:
        settings.EMBEDDING_API_KEY = env_vars["EMBEDDING_API_KEY"]
    if "EMBEDDING_API_BASE" in updated_keys and "EMBEDDING_API_BASE" in env_vars:
        settings.EMBEDDING_API_BASE = env_vars["EMBEDDING_API_BASE"]

    # Milvus
    if "MILVUS_HOST" in updated_keys and "MILVUS_HOST" in env_vars:
        settings.MILVUS_HOST = env_vars["MILVUS_HOST"]
    if "MILVUS_PORT" in updated_keys and "MILVUS_PORT" in env_vars:
        settings.MILVUS_PORT = _parse_int(env_vars["MILVUS_PORT"], default=settings.MILVUS_PORT)
    if "MILVUS_USER" in updated_keys and "MILVUS_USER" in env_vars:
        settings.MILVUS_USER = env_vars["MILVUS_USER"]
    if "MILVUS_PASSWORD" in updated_keys and "MILVUS_PASSWORD" in env_vars:
        settings.MILVUS_PASSWORD = env_vars["MILVUS_PASSWORD"]
    if "MILVUS_COLLECTION_NAME" in updated_keys and "MILVUS_COLLECTION_NAME" in env_vars:
        settings.MILVUS_COLLECTION_NAME = env_vars["MILVUS_COLLECTION_NAME"]

    # RAG knobs
    if "CHUNK_SIZE" in updated_keys and "CHUNK_SIZE" in env_vars:
        settings.CHUNK_SIZE = _parse_int(env_vars["CHUNK_SIZE"], default=settings.CHUNK_SIZE)
    if "CHUNK_OVERLAP" in updated_keys and "CHUNK_OVERLAP" in env_vars:
        settings.CHUNK_OVERLAP = _parse_int(env_vars["CHUNK_OVERLAP"], default=settings.CHUNK_OVERLAP)
    if "RETRIEVAL_TOP_K" in updated_keys and "RETRIEVAL_TOP_K" in env_vars:
        settings.RETRIEVAL_TOP_K = _parse_int(env_vars["RETRIEVAL_TOP_K"], default=settings.RETRIEVAL_TOP_K)
    if "SIMILARITY_THRESHOLD" in updated_keys and "SIMILARITY_THRESHOLD" in env_vars:
        settings.SIMILARITY_THRESHOLD = _parse_float(
            env_vars["SIMILARITY_THRESHOLD"],
            default=settings.SIMILARITY_THRESHOLD,
        )
    if "DEFAULT_PARSER_BACKEND" in updated_keys and "DEFAULT_PARSER_BACKEND" in env_vars:
        settings.DEFAULT_PARSER_BACKEND = env_vars["DEFAULT_PARSER_BACKEND"]
    if "DEFAULT_CHUNK_STRATEGY" in updated_keys and "DEFAULT_CHUNK_STRATEGY" in env_vars:
        settings.DEFAULT_CHUNK_STRATEGY = env_vars["DEFAULT_CHUNK_STRATEGY"]

    # MinerU
    if "MINERU_API_TOKEN" in updated_keys and "MINERU_API_TOKEN" in env_vars:
        settings.MINERU_API_TOKEN = env_vars["MINERU_API_TOKEN"]
    if "MINERU_API_BASE" in updated_keys and "MINERU_API_BASE" in env_vars:
        settings.MINERU_API_BASE = env_vars["MINERU_API_BASE"]
    if "MINERU_MODEL_VERSION" in updated_keys and "MINERU_MODEL_VERSION" in env_vars:
        settings.MINERU_MODEL_VERSION = env_vars["MINERU_MODEL_VERSION"]

    # Observability / debug toggles
    if "TOOL_CALL_LOG_ENABLED" in updated_keys and "TOOL_CALL_LOG_ENABLED" in env_vars:
        settings.TOOL_CALL_LOG_ENABLED = _parse_bool(env_vars["TOOL_CALL_LOG_ENABLED"])
    if "TOOL_CALL_LOG_INCLUDE_PREVIEW" in updated_keys and "TOOL_CALL_LOG_INCLUDE_PREVIEW" in env_vars:
        settings.TOOL_CALL_LOG_INCLUDE_PREVIEW = _parse_bool(env_vars["TOOL_CALL_LOG_INCLUDE_PREVIEW"])
    if "TOOL_CALL_LOG_MAX_PREVIEW_CHARS" in updated_keys and "TOOL_CALL_LOG_MAX_PREVIEW_CHARS" in env_vars:
        settings.TOOL_CALL_LOG_MAX_PREVIEW_CHARS = _parse_int(
            env_vars["TOOL_CALL_LOG_MAX_PREVIEW_CHARS"],
            default=settings.TOOL_CALL_LOG_MAX_PREVIEW_CHARS,
        )

    if "AGENT_LOG_ENABLED" in updated_keys and "AGENT_LOG_ENABLED" in env_vars:
        settings.AGENT_LOG_ENABLED = _parse_bool(env_vars["AGENT_LOG_ENABLED"])
    if "AGENT_LOG_INCLUDE_EXECUTION_PATH" in updated_keys and "AGENT_LOG_INCLUDE_EXECUTION_PATH" in env_vars:
        settings.AGENT_LOG_INCLUDE_EXECUTION_PATH = _parse_bool(env_vars["AGENT_LOG_INCLUDE_EXECUTION_PATH"])
    if "AGENT_LOG_MAX_PREVIEW_CHARS" in updated_keys and "AGENT_LOG_MAX_PREVIEW_CHARS" in env_vars:
        settings.AGENT_LOG_MAX_PREVIEW_CHARS = _parse_int(
            env_vars["AGENT_LOG_MAX_PREVIEW_CHARS"],
            default=settings.AGENT_LOG_MAX_PREVIEW_CHARS,
        )

    # Safety / PII
    if "PII_REDACTION_ENABLED" in updated_keys and "PII_REDACTION_ENABLED" in env_vars:
        settings.PII_REDACTION_ENABLED = _parse_bool(env_vars["PII_REDACTION_ENABLED"])
    if "PII_REDACTION_MASK" in updated_keys and "PII_REDACTION_MASK" in env_vars:
        settings.PII_REDACTION_MASK = env_vars["PII_REDACTION_MASK"]
    if "PII_STREAM_HOLDBACK_CHARS" in updated_keys and "PII_STREAM_HOLDBACK_CHARS" in env_vars:
        settings.PII_STREAM_HOLDBACK_CHARS = _parse_int(
            env_vars["PII_STREAM_HOLDBACK_CHARS"],
            default=settings.PII_STREAM_HOLDBACK_CHARS,
        )

    # LangGraph
    if "LANGGRAPH_USE_SUBGRAPHS" in updated_keys and "LANGGRAPH_USE_SUBGRAPHS" in env_vars:
        settings.LANGGRAPH_USE_SUBGRAPHS = _parse_bool(env_vars["LANGGRAPH_USE_SUBGRAPHS"])


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
        observability=ObservabilityConfig(
            tool_call_log_enabled=settings.TOOL_CALL_LOG_ENABLED,
            tool_call_log_include_preview=settings.TOOL_CALL_LOG_INCLUDE_PREVIEW,
            tool_call_log_max_preview_chars=settings.TOOL_CALL_LOG_MAX_PREVIEW_CHARS,
            agent_log_enabled=settings.AGENT_LOG_ENABLED,
            agent_log_include_execution_path=settings.AGENT_LOG_INCLUDE_EXECUTION_PATH,
            agent_log_max_preview_chars=settings.AGENT_LOG_MAX_PREVIEW_CHARS,
        ),
        safety=SafetyConfig(
            pii_redaction_enabled=settings.PII_REDACTION_ENABLED,
            pii_redaction_mask=settings.PII_REDACTION_MASK,
            pii_stream_holdback_chars=settings.PII_STREAM_HOLDBACK_CHARS,
        ),
        langgraph=LangGraphConfig(
            use_subgraphs=settings.LANGGRAPH_USE_SUBGRAPHS,
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

        # 更新观测/调试配置
        if request.observability:
            ob = request.observability
            env_vars["TOOL_CALL_LOG_ENABLED"] = str(ob.tool_call_log_enabled).lower()
            env_vars["TOOL_CALL_LOG_INCLUDE_PREVIEW"] = str(ob.tool_call_log_include_preview).lower()
            env_vars["TOOL_CALL_LOG_MAX_PREVIEW_CHARS"] = str(int(ob.tool_call_log_max_preview_chars or 0))
            env_vars["AGENT_LOG_ENABLED"] = str(ob.agent_log_enabled).lower()
            env_vars["AGENT_LOG_INCLUDE_EXECUTION_PATH"] = str(ob.agent_log_include_execution_path).lower()
            env_vars["AGENT_LOG_MAX_PREVIEW_CHARS"] = str(int(ob.agent_log_max_preview_chars or 0))
            updated_keys.extend(
                [
                    "TOOL_CALL_LOG_ENABLED",
                    "TOOL_CALL_LOG_INCLUDE_PREVIEW",
                    "TOOL_CALL_LOG_MAX_PREVIEW_CHARS",
                    "AGENT_LOG_ENABLED",
                    "AGENT_LOG_INCLUDE_EXECUTION_PATH",
                    "AGENT_LOG_MAX_PREVIEW_CHARS",
                ]
            )

        # 更新安全/隐私配置
        if request.safety:
            sf = request.safety
            env_vars["PII_REDACTION_ENABLED"] = str(sf.pii_redaction_enabled).lower()
            env_vars["PII_REDACTION_MASK"] = sf.pii_redaction_mask
            env_vars["PII_STREAM_HOLDBACK_CHARS"] = str(int(sf.pii_stream_holdback_chars or 0))
            updated_keys.extend(["PII_REDACTION_ENABLED", "PII_REDACTION_MASK", "PII_STREAM_HOLDBACK_CHARS"])

        # 更新 LangGraph 配置
        if request.langgraph:
            lg = request.langgraph
            env_vars["LANGGRAPH_USE_SUBGRAPHS"] = str(lg.use_subgraphs).lower()
            updated_keys.append("LANGGRAPH_USE_SUBGRAPHS")

        write_env_file(env_vars)
        try:
            _apply_runtime_settings(env_vars, updated_keys)
        except Exception:
            # Best-effort only.
            pass
        if request.llm is not None:
            # RAG engine caches LLM clients; reset so new settings take effect.
            try:
                from app.rag.engine import reset_rag_engine

                reset_rag_engine()
            except Exception:
                pass

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


class TestLLMRequest(BaseModel):
    api_key: str
    api_base: str = "https://api.openai.com/v1"
    model: str
    temperature: float = 0.0
    timeout: int = 20
    max_retries: int = 1


@router.post("/llm/test")
async def test_llm_connection(request: TestLLMRequest):
    """测试 LLM 连接（不写入配置）"""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    import httpx

    from app.rag.core.http import httpx_trust_env
    from app.rag.core.logging import get_logger

    logger = get_logger("settings.llm_test")

    if not request.api_key.strip():
        raise HTTPException(status_code=400, detail="api_key is required")
    if not request.model.strip():
        raise HTTPException(status_code=400, detail="model is required")

    trust_env = httpx_trust_env(logger=logger)
    timeout = float(request.timeout) if request.timeout else 20.0

    try:
        async with httpx.AsyncClient(trust_env=trust_env, timeout=timeout) as http_async_client:
            llm = ChatOpenAI(
                model=request.model,
                api_key=request.api_key,
                base_url=request.api_base,
                temperature=float(request.temperature or 0.0),
                streaming=False,
                timeout=timeout,
                max_retries=int(request.max_retries or 1),
                http_async_client=http_async_client,
            )
            resp = await llm.ainvoke([HumanMessage(content="Say 1")])
            content = (getattr(resp, "content", "") or "").strip()
            if not content:
                return {"success": False, "message": "Empty response"}
            return {"success": True, "message": content[:200]}
    except Exception as exc:
        msg = str(exc)
        logger.warning("LLM test failed: %s", msg[:200])
        return {"success": False, "message": msg[:400]}
