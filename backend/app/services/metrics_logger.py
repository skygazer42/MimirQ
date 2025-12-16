"""
轻量级 metrics 日志落地工具，可选开启。
"""
from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any, Dict

from app.core.config import settings

_lock = threading.Lock()


def log_metrics(payload: Dict[str, Any]) -> None:
    """将 metrics 追加到本地 jsonl，默认关闭，配置 ENABLE_METRICS_LOG 打开。"""
    if not settings.ENABLE_METRICS_LOG:
        return
    try:
        path = Path(settings.METRICS_LOG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False)
        with _lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # 避免影响主流程
        return
