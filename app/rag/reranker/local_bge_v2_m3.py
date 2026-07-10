
from app.rag.core.logging import get_logger
from app.rag.reranker.cross_encoder import CrossEncoderReranker

logger = get_logger(__name__)


def _resolve_device() -> str:
    try:
        import torch  # type: ignore

        if bool(getattr(torch.backends, "mps", None)) and bool(torch.backends.mps.is_available()):  # type: ignore[attr-defined]
            return "mps"
        if bool(torch.cuda.is_available()):
            return "cuda"
    except Exception as exc:
        logger.debug("Ignoring local BGE device detection failure: %s", exc)
    return "cpu"


class LocalBGEV2M3Reranker(CrossEncoderReranker):
    def __init__(self, model_name: str | None = None, *, device: str | None = None, model=None) -> None:  # noqa: ANN001
        resolved_device = (str(device).strip() if device is not None else "") or _resolve_device()
        super().__init__(
            model_name=model_name or "BAAI/bge-reranker-v2-m3",
            device=resolved_device,
            model=model,
        )


__all__ = ["LocalBGEV2M3Reranker"]
