from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.rag.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ParseCacheEntry:
    created_at_epoch: float
    file_sha256: str
    parser_backend: str
    resolved_backend: str
    resolved_chunk_strategy: str
    documents: list[dict[str, Any]] | None
    chunks: list[dict[str, Any]] | None


def build_parse_cache_key(*, file_sha256: str, parser_backend: str, config_hash: str) -> str:
    payload = "|".join(
        [
            str(file_sha256 or "").strip().lower(),
            str(parser_backend or "").strip().lower(),
            str(config_hash or "").strip(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8", "ignore")).hexdigest()


class LocalParseCacheStore:
    def __init__(self, *, root: Path) -> None:
        self._root = Path(root)

    def _path_for(self, key: str) -> Path:
        safe = str(key or "").strip().lower()
        return self._root / safe[:2] / f"{safe}.json"

    def get(
        self,
        key: str,
        *,
        ttl_sec: int,
        now_epoch: float | None = None,
    ) -> tuple[ParseCacheEntry | None, int | None]:
        path = self._path_for(key)
        if not path.exists() or not path.is_file():
            return None, None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entry = ParseCacheEntry(**payload)
        except Exception:
            return None, None

        now = float(time.time() if now_epoch is None else now_epoch)
        age_sec = max(0.0, now - float(entry.created_at_epoch or 0.0))
        if int(ttl_sec or 0) > 0 and age_sec > int(ttl_sec):
            try:
                path.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("Ignoring stale parse cache unlink failure: %s", exc)
            return None, None

        return entry, int(age_sec * 1000.0)

    def set(self, key: str, entry: ParseCacheEntry) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(asdict(entry), ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp_path, path)


__all__ = ["LocalParseCacheStore", "ParseCacheEntry", "build_parse_cache_key"]
