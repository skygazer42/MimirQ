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
    snapshot = build_ops_config_snapshot()
    retrieval_fingerprint = str(snapshot.config["retrieval_fingerprint"]).strip()
    ops_fingerprint = snapshot.fingerprint.strip()
    combined_fingerprint = stable_hash(f"{ops_fingerprint}|{retrieval_fingerprint}", length=24)
    return ConfigHotReloadState(
        schema="mimirq.config_hot_reload.v1",
        ops_fingerprint=ops_fingerprint,
        retrieval_fingerprint=retrieval_fingerprint,
        combined_fingerprint=combined_fingerprint,
    )


def should_hot_reload_config(
    *,
    previous_combined_fingerprint: str | None,
    current_state: ConfigHotReloadState | None = None,
) -> bool:
    current = build_config_hot_reload_state() if current_state is None else current_state
    previous = (previous_combined_fingerprint or "").strip()
    if not previous:
        return True
    return previous != current.combined_fingerprint.strip()


__all__ = ["ConfigHotReloadState", "build_config_hot_reload_state", "should_hot_reload_config"]
