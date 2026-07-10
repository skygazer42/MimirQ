
from dataclasses import dataclass
from pathlib import Path

from app.core.optional_deps import require_dependency


@dataclass(frozen=True, slots=True)
class HfSnapshotResult:
    repo_id: str
    path: Path
    revision: str | None = None


def download_hf_snapshot(
    *,
    repo_id: str,
    revision: str | None = None,
    local_dir: str | Path | None = None,
) -> HfSnapshotResult:
    """
    Download an explicitly selected HuggingFace small-model snapshot.

    This is intentionally never called by the default parsing path. Callers must
    opt into downloads so offline deployments keep using bundled ONNX models.
    """
    hub = require_dependency("huggingface_hub", feature="parsing_small_model_hf_cache", pip_name="huggingface-hub")
    kwargs: dict[str, object] = {"repo_id": repo_id}
    if revision:
        kwargs["revision"] = revision
    if local_dir is not None:
        kwargs["local_dir"] = str(local_dir)
    path = hub.snapshot_download(**kwargs)  # type: ignore[attr-defined]
    return HfSnapshotResult(repo_id=repo_id, revision=revision, path=Path(str(path)).resolve())


__all__ = ["HfSnapshotResult", "download_hf_snapshot"]
