import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.rag.core.logging import get_logger

logger = get_logger(__name__)

_CACHE_SCHEMA = "mimirq.local_parse_cache.v2"


@dataclass(frozen=True)
class ParseCacheEntry:
    created_at_epoch: float
    file_sha256: str
    parser_backend: str | None
    resolved_backend: str
    resolved_chunk_strategy: str
    documents: list[dict[str, Any]] | None
    chunks: list[dict[str, Any]] | None


def build_parse_cache_key(*, file_sha256: str, parser_backend: str | None, config_hash: str) -> str:
    payload = json.dumps(
        {
            "schema": _CACHE_SCHEMA,
            "file_sha256": file_sha256.strip().lower(),
            "parser_backend": None if parser_backend is None else parser_backend.strip().lower(),
            "config_hash": config_hash.strip(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8", "ignore")).hexdigest()


class LocalParseCacheStore:
    def __init__(self, *, root: Path) -> None:
        self._root = Path(root)

    def _path_for(self, key: str) -> Path:
        safe = key.strip().lower()
        return self._root / safe[:2] / f"{safe}.json"

    def get(
        self,
        key: str,
        *,
        ttl_sec: int,
        now_epoch: float | None = None,
    ) -> tuple[ParseCacheEntry | None, int | None]:
        path = self._path_for(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entry = ParseCacheEntry(**payload)
            if not isinstance(entry.resolved_chunk_strategy, str) or not entry.resolved_chunk_strategy.strip():
                return None, None
            now = time.time() if now_epoch is None else now_epoch
            age_sec = max(0.0, now - float(entry.created_at_epoch))
        except (OSError, TypeError, ValueError) as exc:
            logger.debug("Ignoring invalid parse cache entry: %s", type(exc).__name__)
            return None, None
        if ttl_sec > 0 and age_sec > ttl_sec:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug("Ignoring stale parse cache unlink failure: %s", type(exc).__name__)
            return None, None

        return entry, int(age_sec * 1000.0)

    def set(self, key: str, entry: ParseCacheEntry) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(asdict(entry), ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp_path, path)


__all__ = ["LocalParseCacheStore", "ParseCacheEntry", "build_parse_cache_key"]
