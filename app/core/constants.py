"""
全局常量定义

集中管理项目中的魔法字符串和硬编码值，提高可维护性。
"""

from typing import FrozenSet


# =============================================================================
# 超时常量 (秒)
# =============================================================================

class Timeouts:
    """HTTP 和操作超时常量"""

    # API 请求超时
    API_DEFAULT = 60          # embedding providers, LLM API calls
    API_SHORT = 30            # 快速 API 请求
    API_UPLOAD = 300          # 文件上传
    API_LONG_RUNNING = 600    # 长时间运行的任务

    # 文档解析超时
    PARSE_DEFAULT = 1800      # 文档解析 (30分钟)
    PARSE_VALIDATION = 5      # 健康检查/验证

    # 流式操作超时
    STREAM_DEFAULT = 5.0      # 流式写入
    STREAM_SHORT = 1.0        # 短流式操作

    # 线程/进程超时
    THREAD_JOIN = 2.0         # 线程 join 超时


# =============================================================================
# 文件类型常量
# =============================================================================

class FileTypes:
    """支持的文件类型"""

    # 文档类型
    PDF = ".pdf"
    TXT = ".txt"
    MD = ".md"
    DOC = ".doc"
    DOCX = ".docx"

    # 表格类型
    XLS = ".xls"
    XLSX = ".xlsx"
    CSV = ".csv"

    # Web 类型
    HTML = ".html"
    JSON = ".json"

    # 支持的扩展名集合
    DOCUMENT_EXTENSIONS: FrozenSet[str] = frozenset({
        ".pdf", ".txt", ".md", ".doc", ".docx"
    })

    SPREADSHEET_EXTENSIONS: FrozenSet[str] = frozenset({
        ".xls", ".xlsx", ".csv"
    })

    WEB_EXTENSIONS: FrozenSet[str] = frozenset({
        ".html", ".json"
    })

    ALL_SUPPORTED: FrozenSet[str] = frozenset({
        ".pdf", ".txt", ".md", ".doc", ".docx",
        ".xls", ".xlsx", ".csv", ".html", ".json"
    })

    # MarkItDown 特殊支持
    MARKITDOWN_EXTENSIONS: FrozenSet[str] = frozenset({
        ".doc", ".docx", ".xls", ".xlsx", ".csv", ".html", ".json"
    })


# =============================================================================
# 文档处理状态
# =============================================================================

class DocumentStatus:
    """文档处理状态常量"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    # 可终止状态
    TERMINAL_STATES: FrozenSet[str] = frozenset({
        "completed", "failed", "cancelled"
    })

    # 活跃状态
    ACTIVE_STATES: FrozenSet[str] = frozenset({
        "pending", "processing"
    })


# =============================================================================
# Milvus 向量数据库配置
# =============================================================================

class MilvusConfig:
    """Milvus 配置常量"""

    # 索引参数
    METRIC_TYPE = "COSINE"
    INDEX_TYPE = "IVF_FLAT"
    NLIST = 1024

    # 搜索参数
    NPROBE = 10

    # 默认 collection 名称
    DEFAULT_COLLECTION = "mimirq_chunks"

    @classmethod
    def get_index_params(cls) -> dict:
        """获取索引参数"""
        return {
            "metric_type": cls.METRIC_TYPE,
            "index_type": cls.INDEX_TYPE,
            "params": {"nlist": cls.NLIST},
        }

    @classmethod
    def get_search_params(cls) -> dict:
        """获取搜索参数"""
        return {
            "metric_type": cls.METRIC_TYPE,
            "params": {"nprobe": cls.NPROBE},
        }


# =============================================================================
# Embedding 提供商
# =============================================================================

class EmbeddingProviders:
    """Embedding 提供商常量"""

    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    LOCAL = "local"
    DASHSCOPE = "dashscope"
    OLLAMA = "ollama"

    ALL: FrozenSet[str] = frozenset({
        "openai", "openai_compatible", "local", "dashscope", "ollama"
    })

    # 提供商映射 (别名 -> 标准名称)
    PROVIDER_MAP = {
        "openai": "openai_compatible",
        "openai_compatible": "openai_compatible",
        "local": "local",
        "dashscope": "dashscope",
        "ollama": "ollama",
    }


# =============================================================================
# PDF 解析后端
# =============================================================================

class PDFBackends:
    """PDF 解析后端常量"""

    AUTO = "auto"
    BASIC = "basic"
    MINERU = "mineru"
    DEEPDOC = "deepdoc"
    MARKITDOWN = "markitdown"
    DOCLING = "docling"
    TCADP = "tcadp"

    ALL: FrozenSet[str] = frozenset({
        "auto", "basic", "mineru", "deepdoc", "markitdown", "docling", "tcadp"
    })


# =============================================================================
# 检索模式
# =============================================================================

class RetrievalModes:
    """检索模式常量"""

    VECTOR = "vector"
    KEYWORD = "keyword"
    HYBRID = "hybrid"
    MMR = "mmr"
    AUTO = "auto"

    ALL: FrozenSet[str] = frozenset({
        "vector", "keyword", "hybrid", "mmr", "auto"
    })


# =============================================================================
# 用户角色
# =============================================================================

class UserRoles:
    """用户角色常量"""

    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    DATASET_OPERATOR = "dataset_operator"
    VIEWER = "viewer"

    # 可编辑角色
    EDIT_ROLES: FrozenSet[str] = frozenset({
        "owner", "admin", "editor", "dataset_operator"
    })

    # 管理员角色
    ADMIN_ROLES: FrozenSet[str] = frozenset({
        "owner", "admin"
    })


# =============================================================================
# 代理环境变量
# =============================================================================

class ProxyEnvKeys:
    """代理相关环境变量"""

    KEYS = (
        "OPENAI_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "ALL_PROXY",
        "https_proxy",
        "http_proxy",
        "all_proxy",
    )


# =============================================================================
# 分块参数限制
# =============================================================================

class ChunkLimits:
    """分块参数限制"""

    SIZE_MIN = 100
    SIZE_MAX = 4000
    SIZE_DEFAULT = 1000

    OVERLAP_MIN = 0
    OVERLAP_MAX = 1000
    OVERLAP_DEFAULT = 200


# =============================================================================
# API 分页限制
# =============================================================================

class PaginationLimits:
    """分页参数限制"""

    DEFAULT_SKIP = 0
    DEFAULT_LIMIT = 50
    MAX_LIMIT = 200


__all__ = [
    "Timeouts",
    "FileTypes",
    "DocumentStatus",
    "MilvusConfig",
    "EmbeddingProviders",
    "PDFBackends",
    "RetrievalModes",
    "UserRoles",
    "ProxyEnvKeys",
    "ChunkLimits",
    "PaginationLimits",
]
