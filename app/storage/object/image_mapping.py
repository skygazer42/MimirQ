from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_image_mapping(path: str | Path) -> dict[str, str]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        k = str(key or "").strip()
        v = str(value or "").strip()
        if k and v:
            out[k] = v
    return out


def save_image_mapping(path: str | Path, mapping: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        str(key or "").strip(): str(value or "").strip()
        for key, value in (mapping or {}).items()
        if str(key or "").strip() and str(value or "").strip()
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
