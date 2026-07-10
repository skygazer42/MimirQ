"""
CLIP embeddings for multimodal retrieval (text <-> image).

This is used for optional image embedding indexing and retrieval:
- Index: encode image chunks (PIL.Image) into a vector.
- Query: encode user text queries into the same vector space.

Design goals:
- Lazy imports: keep default startup fast and avoid importing torch unless enabled.
- Best-effort: callers should treat failures as "no embeddings" (never block ingest/retrieval).
"""


import threading
from collections.abc import Iterable
from typing import Any

import numpy as np

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("rag.embedding.clip")


class _ClipEmbedder:
    def __init__(self, *, model_name: str, device: str, batch_size: int) -> None:
        self._model_name = str(model_name or "").strip() or "clip-ViT-B-32"
        self._device = str(device or "cpu").strip().lower() or "cpu"
        self._batch_size = max(1, int(batch_size or 0))

        self._lock = threading.Lock()
        self._model: Any | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore

                # SentenceTransformer handles device selection ("cpu"/"cuda").
                self._model = SentenceTransformer(self._model_name, device=self._device)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Failed to load CLIP model: {type(exc).__name__}: {exc}") from exc

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        raw = [str(t or "") for t in (texts or [])]
        if not raw:
            return np.zeros((0, 1), dtype=np.float32)
        self._ensure_loaded()
        if self._model is None:
            raise RuntimeError("CLIP model is not initialized")
        vecs = self._model.encode(  # type: ignore[no-any-return]
            raw,
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    def encode_images(self, images: list[Any]) -> np.ndarray:
        if not images:
            return np.zeros((0, 1), dtype=np.float32)
        self._ensure_loaded()
        if self._model is None:
            raise RuntimeError("CLIP model is not initialized")
        vecs = self._model.encode(  # type: ignore[no-any-return]
            images,
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)


_EMBEDDER_CACHE: dict[tuple[str, str, int], _ClipEmbedder] = {}
_EMBEDDER_LOCK = threading.Lock()


def get_clip_embedder() -> _ClipEmbedder:
    model_name = str(getattr(settings, "IMAGE_EMBEDDING_MODEL_NAME", "") or "clip-ViT-B-32").strip() or "clip-ViT-B-32"
    device = str(getattr(settings, "IMAGE_EMBEDDING_DEVICE", "cpu") or "cpu").strip().lower() or "cpu"
    batch_size = int(getattr(settings, "IMAGE_EMBEDDING_BATCH_SIZE", 8) or 8)

    key = (model_name, device, batch_size)
    with _EMBEDDER_LOCK:
        cached = _EMBEDDER_CACHE.get(key)
        if cached is not None:
            return cached
        inst = _ClipEmbedder(model_name=model_name, device=device, batch_size=batch_size)
        _EMBEDDER_CACHE[key] = inst
        return inst


def encode_clip_text(query: str) -> list[float] | None:
    """
    Encode a single query string into a CLIP embedding vector.

    Returns:
      List[float] or None (best-effort).
    """
    raw = str(query or "").strip()
    if not raw:
        return None
    try:
        emb = get_clip_embedder().encode_texts([raw])
        if emb.ndim != 2 or emb.shape[0] <= 0:
            return None
        vec = np.asarray(emb[0], dtype=np.float32)
        if vec.size <= 0:
            return None
        return [float(x) for x in vec.tolist()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("CLIP text embedding failed (ignored): %s", str(exc)[:200])
        return None


def encode_clip_image(image: Any) -> list[float] | None:
    """
    Encode a single PIL.Image image into a CLIP embedding vector.

    Returns:
      List[float] or None (best-effort).
    """
    if image is None:
        return None
    try:
        emb = get_clip_embedder().encode_images([image])
        if emb.ndim != 2 or emb.shape[0] <= 0:
            return None
        vec = np.asarray(emb[0], dtype=np.float32)
        if vec.size <= 0:
            return None
        return [float(x) for x in vec.tolist()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("CLIP image embedding failed (ignored): %s", str(exc)[:200])
        return None


def coerce_embedding_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    out: list[float] = []
    for x in value:
        try:
            out.append(float(x))
        except Exception:
            return None
    return out


def batch_mean_dim(vectors: Iterable[list[float] | None]) -> int:
    dims: list[int] = []
    for v in vectors:
        if not v:
            continue
        dims.append(int(len(v)))
    if not dims:
        return 0
    # Use max (safer for Milvus schema); dimensions should be consistent in practice.
    return max(dims)
