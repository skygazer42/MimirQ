"""Engine config models."""

from pathlib import Path
from pydantic import BaseModel, Field

from app.core.config import settings
from app.rag.kg.engine.enums import OutputMode
from app.rag.kg.extraction.config import ExtractBaseConfig
from app.rag.kg.loading.config import ConversationLoadConfig, DocumentLoadConfig
from app.rag.kg.search.config import SearchBaseConfig


class ModelConfig(BaseModel):
    """LLM config (optional override)."""

    api_key: str | None = Field(default=None, description="API key")
    model: str = Field(default=settings.LLM_MODEL, description="Model name")
    base_url: str | None = Field(default=settings.LLM_API_BASE, description="API base URL")
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
    export_path: Path | None = Field(default=None, description="Optional export path")
    pretty: bool = Field(default=True, description="Pretty JSON")


class TaskConfig(BaseModel):
    """Unified task config for engine."""

    task_name: str = Field(default="KG task", description="Task name")
    task_description: str | None = Field(default=None, description="Task description")

    source_config_id: str | None = Field(default=None, description="Source config id")
    source_name: str | None = Field(default=None, description="Source name")
    background: str | None = Field(default=None, description="Global background info")

    load: ConversationLoadConfig | DocumentLoadConfig | None = Field(
        default=None, description="Load stage config"
    )
    extract: ExtractBaseConfig | None = Field(default=None, description="Extract stage config")
    search: SearchBaseConfig | None = Field(default=None, description="Search stage config")

    output: OutputConfig = Field(default_factory=OutputConfig, description="Output config")

    fail_fast: bool = Field(default=False, description="Stop on first failure")
