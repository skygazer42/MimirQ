"""
Local cross-encoder reranker (sentence-transformers CrossEncoder).

Design constraints:
- Optional dependency: do not import sentence_transformers at module import time.
- CI/offline friendly: allow injecting a fake model for unit tests (no model downloads).
"""


import threading
import time
from collections.abc import Sequence
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult
from app.services.metrics_logger import log_metrics

logger = get_logger("rag.reranker.cross_encoder")


def _as_float(v: Any) -> float:
    try:
        if v is None:
            return 0.0
        return float(v)
    except Exception:
        return 0.0


class CrossEncoderReranker(BaseReranker):
    """
    Cross-encoder reranker backed by sentence-transformers CrossEncoder.

    Notes:
    - Model loading is lazy (performed on first rerank call).
    - For unit tests, pass `model=...` where model has a `.predict(pairs)` method.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        device: str | None = None,
        model: Any | None = None,
        load_timeout_sec: float | None = None,
    ) -> None:
        self.model_name = (model_name or settings.RERANKER_MODEL or "BAAI/bge-reranker-v2-m3").strip()
        self.device = (str(device).strip() if device is not None else None) or None
        self._model = model
        self.load_timeout_sec = (
            float(load_timeout_sec)
            if load_timeout_sec is not None
            else float(getattr(settings, "RERANKER_LOCAL_LOAD_TIMEOUT_SEC", 2.0) or 0.0)
        )
        self._load_lock = threading.Lock()
        self._load_thread: threading.Thread | None = None
        self._load_exception: BaseException | None = None

    def _construct_model(self) -> Any:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise ImportError(
                "sentence-transformers is required for cross-encoder reranking.\n"
                "Please install: pip install sentence-transformers torch"
            ) from exc

        try:
            # Avoid surprises: keep construction simple and let sentence-transformers
            # handle device selection when device is None.
            return CrossEncoder(self.model_name, device=self.device)  # type: ignore[call-arg]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load cross-encoder model (%s): %s", self.model_name, str(exc)[:200])
            raise

    def _start_background_load(self) -> threading.Thread:
        def _target() -> None:
            try:
                model = self._construct_model()
                self._model = model
                self._load_exception = None
            except Exception as exc:  # noqa: BLE001
                self._load_exception = exc

        thread = threading.Thread(
            target=_target,
            name=f"cross-encoder-load:{self.model_name}",
            daemon=True,
        )
        self._load_thread = thread
        thread.start()
        return thread

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        with self._load_lock:
            if self._model is not None:
                return self._model
            thread = self._load_thread
            if thread is None or not thread.is_alive():
                self._load_exception = None
                thread = self._start_background_load()

        timeout_sec = max(0.0, float(self.load_timeout_sec or 0.0))
        if timeout_sec > 0.0:
            thread.join(timeout=timeout_sec)
        else:
            thread.join()

        if self._model is not None:
            return self._model
        if thread.is_alive():
            logger.warning(
                "Cross-encoder model load timed out after %.3fs (%s); falling back to base retrieval order",
                timeout_sec,
                self.model_name,
            )
            raise TimeoutError(f"cross_encoder_load_timeout:{self.model_name}")
        if self._load_exception is not None:
            raise self._load_exception
        raise RuntimeError(f"cross_encoder_load_failed:{self.model_name}")

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        provider = "cross_encoder"
        start = time.time()

        top_n_raw = kwargs.get("top_n")
        try:
            top_n = int(top_n_raw) if top_n_raw is not None else None
        except Exception:
            top_n = None
        if top_n is not None:
            top_n = max(0, top_n)

        batch_size = int(kwargs.get("batch_size") or settings.RERANKER_API_BATCH_SIZE or 32)
        batch_size = max(1, batch_size)
        max_chars = int(kwargs.get("max_chars") or settings.RERANKER_MAX_CHARS or 0)

        q = (query or "").strip()
        if not q or not candidates:
            return RerankResult(
                ordered_ids=[],
                score_map={},
                elapsed_sec=0.0,
                model_used=self.model_name,
                provider=provider,
            )

        ids: list[str] = []
        pairs: list[tuple[str, str]] = []
        for c in candidates:
            cid = str(getattr(c, "id", "") or "").strip()
            text = str(getattr(c, "text", "") or "").strip()
            if not cid or not text:
                continue
            if max_chars > 0 and len(text) > max_chars:
                text = text[:max_chars] + "..."
            ids.append(cid)
            pairs.append((q, text))

        if not pairs:
            return RerankResult(
                ordered_ids=[],
                score_map={},
                elapsed_sec=0.0,
                model_used=self.model_name,
                provider=provider,
            )

        model = self._load_model()

        scores: list[float] = []
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            batch_scores = model.predict(batch)  # type: ignore[attr-defined]
            # sentence-transformers returns list[float] or np.ndarray; normalize to a python list.
            if hasattr(batch_scores, "tolist"):
                try:
                    batch_scores = batch_scores.tolist()
                except Exception as exc:
                    logger.debug("Ignoring cross-encoder score tolist normalization failure: %s", exc)
            if not isinstance(batch_scores, list):
                batch_scores = list(batch_scores)  # type: ignore[arg-type]
            scores.extend([_as_float(s) for s in batch_scores])

        # Defensive: avoid score/id mismatch.
        if len(scores) != len(ids):
            if len(scores) < len(ids):
                scores = scores + [0.0] * (len(ids) - len(scores))
            else:
                scores = scores[: len(ids)]

        score_map = {cid: float(score) for cid, score in zip(ids, scores, strict=False) if cid}
        ordered_idx = sorted(range(len(ids)), key=lambda idx: (-scores[idx], idx))
        ordered_ids = [ids[i] for i in ordered_idx if ids[i]]

        if top_n:
            ordered_ids = ordered_ids[: int(top_n)]
            score_map = {cid: score_map[cid] for cid in ordered_ids if cid in score_map}

        elapsed = time.time() - start
        stats = {
            "provider": provider,
            "model": self.model_name,
            "docs": len(ids),
            "batch_size": int(batch_size),
        }

        if settings.ENABLE_METRICS_LOG:
            log_metrics(
                {
                    "event": "reranker_local",
                    "provider": provider,
                    "model": self.model_name,
                    "query_chars": len(q),
                    "docs": len(ids),
                    "elapsed_sec": round(float(elapsed), 3),
                    "batch_size": int(batch_size),
                }
            )

        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            elapsed_sec=float(elapsed),
            model_used=self.model_name,
            provider=provider,
            stats=stats,
        )
