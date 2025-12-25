"""
Knowledge Graph Engine.

Provides extraction and search capabilities for knowledge graphs.
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.config import settings
from app.kg.extraction.config import ExtractBaseConfig
from app.kg.extraction.extractor import EventExtractor
from app.kg.loading.config import ConversationLoadConfig, DocumentLoadConfig
from app.kg.search.config import SearchBaseConfig
from app.kg.search.searcher import SAGSearcher
from app.kg.utils import get_logger

logger = get_logger("kg.engine")


# ========= Enums =========

class TaskStatus(str):
    PENDING = "pending"
    LOADING = "loading"
    EXTRACTING = "extracting"
    SEARCHING = "searching"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStage(str):
    INIT = "init"
    LOAD = "load"
    EXTRACT = "extract"
    SEARCH = "search"
    OUTPUT = "output"


class LogLevel(str):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class OutputMode(str):
    ID_ONLY = "id_only"
    FULL = "full"


# ========= Config Models =========

class ModelConfig(BaseModel):
    """LLM config (optional override)."""
    api_key: Optional[str] = Field(default=None, description="API key")
    model: str = Field(default=settings.LLM_MODEL, description="Model name")
    base_url: Optional[str] = Field(default=settings.LLM_API_BASE, description="API base URL")
    timeout: int = Field(default=settings.LLM_TIMEOUT, description="Timeout seconds")
    max_retries: int = Field(default=settings.LLM_MAX_RETRIES, description="Max retries")
    temperature: float = Field(default=settings.LLM_TEMPERATURE, description="Sampling temperature")
    with_retry: bool = Field(default=True, description="Enable retry")


class OutputConfig(BaseModel):
    """Output format config."""
    mode: OutputMode = Field(default=OutputMode.FULL, description="Return IDs only or full content")
    format: str = Field(default="json", description="json/markdown")
    include_logs: bool = Field(default=True, description="Include logs")
    print_logs: bool = Field(default=True, description="Print logs to stdout")
    export_path: Optional[Path] = Field(default=None, description="Optional export path")
    pretty: bool = Field(default=True, description="Pretty JSON")


class TaskConfig(BaseModel):
    """Unified task config for engine."""
    task_name: str = Field(default="SAG task", description="Task name")
    task_description: Optional[str] = Field(default=None, description="Task description")
    source_config_id: Optional[str] = Field(default=None, description="Source config id")
    source_name: Optional[str] = Field(default=None, description="Source name")
    background: Optional[str] = Field(default=None, description="Global background info")
    load: Optional[Union[ConversationLoadConfig, DocumentLoadConfig]] = Field(
        default=None, description="Load stage config"
    )
    extract: Optional[ExtractBaseConfig] = Field(default=None, description="Extract stage config")
    search: Optional[SearchBaseConfig] = Field(default=None, description="Search stage config")
    output: OutputConfig = Field(default_factory=OutputConfig, description="Output config")
    fail_fast: bool = Field(default=False, description="Stop on first failure")


# ========= Result Models =========

class TaskLog(BaseModel):
    timestamp: datetime
    stage: TaskStage
    level: LogLevel
    message: str
    extra: Optional[Dict[str, Any]] = None
    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, **data):
        if "timestamp" not in data:
            data["timestamp"] = datetime.utcnow()
        super().__init__(**data)

    def __str__(self) -> str:
        time_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return f"[{time_str}] [{self.stage}] {self.level.upper()}: {self.message}"


class StageResult(BaseModel):
    stage: TaskStage
    status: str  # success/failed/skipped
    data_ids: List[str] = Field(default_factory=list)
    data_full: List[Dict[str, Any]] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    duration: Optional[float] = None


class TaskResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    task_id: str
    task_name: str
    status: TaskStatus
    source_config_id: Optional[str] = None
    article_id: Optional[str] = None
    load_result: Optional[StageResult] = None
    extract_result: Optional[StageResult] = None
    search_result: Optional[StageResult] = None
    stats: Dict[str, Any] = Field(default_factory=dict)
    logs: List[TaskLog] = Field(default_factory=list)
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[float] = None

    def to_dict(self, output_config: OutputConfig) -> dict:
        data = {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "status": self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "source_config_id": self.source_config_id,
            "article_id": self.article_id,
            "stats": self.stats,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": self.duration,
        }

        results_key = "data_ids" if output_config.mode == OutputMode.ID_ONLY else "data_full"

        if self.load_result:
            data["load"] = {
                "status": self.load_result.status,
                "results": getattr(self.load_result, results_key),
                "stats": self.load_result.stats,
            }
        if self.extract_result:
            data["extract"] = {
                "status": self.extract_result.status,
                "results": getattr(self.extract_result, results_key),
                "stats": self.extract_result.stats,
            }
        if self.search_result:
            data["search"] = {
                "status": self.search_result.status,
                "results": getattr(self.search_result, results_key),
                "stats": self.search_result.stats,
            }

        if output_config.include_logs:
            data["logs"] = [
                {
                    "timestamp": log.timestamp.isoformat(),
                    "stage": log.stage,
                    "level": log.level,
                    "message": log.message,
                    "extra": log.extra,
                }
                for log in self.logs
            ]

        if self.error:
            data["error"] = self.error
        return data

    def to_json(self, output_config: OutputConfig) -> str:
        import json
        data = self.to_dict(output_config)
        if output_config.pretty:
            return json.dumps(data, ensure_ascii=False, indent=2)
        return json.dumps(data, ensure_ascii=False)

    def is_success(self) -> bool:
        return self.status == TaskStatus.COMPLETED


# ========= Engine Core =========

class SAGEngine:
    """
    Knowledge Graph Engine.

    Orchestrates extraction and search for knowledge graphs.
    """

    def __init__(self, model_config: Optional[dict] = None):
        self.extractor = EventExtractor(model_config=model_config)
        self.searcher = SAGSearcher()

    async def extract(self, chunk_ids, tenant_id: Optional[UUID] = None):
        """Extract entities and events from document chunks."""
        config = ExtractBaseConfig(
            chunk_ids=list(chunk_ids),
            tenant_id=tenant_id or settings.DEFAULT_TENANT_ID
        )
        return await self.extractor.extract(config)

    async def search(self, query: str, tenant_id: Optional[UUID] = None) -> Dict:
        """Search knowledge graph."""
        from app.kg.search.config import SearchConfig
        config = SearchConfig(
            query=query,
            tenant_id=tenant_id or settings.DEFAULT_TENANT_ID
        )
        return await self.searcher.search(config)


# ========= Exports =========

__all__ = [
    # Enums
    "TaskStatus",
    "TaskStage",
    "LogLevel",
    "OutputMode",
    # Config
    "ModelConfig",
    "OutputConfig",
    "TaskConfig",
    # Results
    "TaskLog",
    "StageResult",
    "TaskResult",
    # Engine
    "SAGEngine",
]
