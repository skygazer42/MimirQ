"""Engine result/log models."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.sag.engine.config import OutputConfig
from app.sag.engine.enums import LogLevel, OutputMode, TaskStage, TaskStatus


class TaskLog(BaseModel):
    timestamp: datetime
    stage: TaskStage
    level: LogLevel
    message: str
    extra: Optional[Dict[str, Any]] = None

    def __init__(self, **data):
        if "timestamp" not in data:
            data["timestamp"] = datetime.utcnow()
        super().__init__(**data)

    def __str__(self) -> str:
        time_str = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return f"[{time_str}] [{self.stage.value}] {self.level.value.upper()}: {self.message}"


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
            "status": self.status.value,
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
                    "stage": log.stage.value,
                    "level": log.level.value,
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

