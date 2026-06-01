from __future__ import annotations

import logging
from typing import Any


def adapt_ragas_scores(scores: dict[str, Any]) -> dict[str, Any]:
    payload = {}
    for key, value in (scores or {}).items():
        try:
            payload[str(key)] = float(value)
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    return {"provider": "ragas", "scores": payload}
