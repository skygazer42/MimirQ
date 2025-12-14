"""Engine enums for task/status/logging."""

from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    LOADING = "loading"
    EXTRACTING = "extracting"
    SEARCHING = "searching"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStage(str, Enum):
    INIT = "init"
    LOAD = "load"
    EXTRACT = "extract"
    SEARCH = "search"
    OUTPUT = "output"


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class OutputMode(str, Enum):
    ID_ONLY = "id_only"
    FULL = "full"

