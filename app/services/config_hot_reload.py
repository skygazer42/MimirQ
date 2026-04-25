from __future__ import annotations

from dataclasses import dataclass

from app.rag.core.hashing import stable_hash
from app.services.ops_config_snapshot_service import build_ops_config_snapshot


@dataclass(frozen=True)
class ConfigHotReloadState:
    schema: str
    ops_fingerprint: str
    retrieval_fingerprint: str
    combined_fingerprint: str


def build_config_hot_reload_state() -> ConfigHotReloadState:
    snap = build_ops_config_snapshot()
    cfg = dict(getattr(snap, "config", {}) or {})
    retrieval_fp = str(cfg.get("retrieval_fingerprint") or "").strip()
    ops_fp = str(getattr(snap, "fingerprint", "") or "").strip()
    combined = stable_hash(f"{ops_fp}|{retrieval_fp}", length=24)
    return ConfigHotReloadState(
        schema="mimirq.config_hot_reload.v1",
        ops_fingerprint=ops_fp,
        retrieval_fingerprint=retrieval_fp,
        combined_fingerprint=combined,
    )


def should_hot_reload_config(
    *,
    previous_combined_fingerprint: str | None,
    current_state: ConfigHotReloadState | None = None,
) -> bool:
    current = current_state or build_config_hot_reload_state()
    previous = str(previous_combined_fingerprint or "").strip()
    if not previous:
        return True
    return previous != str(current.combined_fingerprint or "").strip()


__all__ = ["ConfigHotReloadState", "build_config_hot_reload_state", "should_hot_reload_config"]
