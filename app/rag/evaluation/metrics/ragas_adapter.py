from __future__ import annotations

from typing import Any


def adapt_ragas_scores(scores: dict[str, Any]) -> dict[str, Any]:
    payload = {}
    for key, value in (scores or {}).items():
        try:
            payload[str(key)] = float(value)
        except Exception:
            continue
    return {"provider": "ragas", "scores": payload}
