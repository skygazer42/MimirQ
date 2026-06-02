"""
Reranker base classes.

Unified reranker architecture:
- BaseReranker: top-level abstract base class defining the rerank() interface
- APIReranker: HTTP API reranker (e.g., OpenAI, DashScope)
- DocumentReranker: document-level reranker (e.g., Weight, ParentChild, LLM)
"""

import asyncio
import hashlib
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

import aiohttp
import httpx
import numpy as np

from app.core.config import settings
from app.core.http_env import httpx_trust_env
from app.rag.core.logging import get_logger
from app.rag.reranker.types import RerankCandidate, RerankResult
from app.services.metrics_logger import log_metrics

logger = get_logger("rag.reranker")

# HTTP status codes: retryable errors
RETRYABLE_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})


class _ScoreCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._max_entries: int = 0
        self._ttl_sec: float = 0.0

    def configure(self, *, max_entries: int, ttl_sec: float) -> None:
        max_entries = max(0, int(max_entries or 0))
        ttl_sec = float(ttl_sec or 0.0)
        with self._lock:
            self._max_entries = max_entries
            self._ttl_sec = ttl_sec
            if self._max_entries <= 0:
                self._data.clear()
                return
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)

    def _is_expired(self, ts: float, now: float) -> bool:
        ttl = float(self._ttl_sec or 0.0)
        if ttl <= 0:
            return False
        return (now - ts) > ttl

    def get(self, key: str) -> float | None:
        if not key:
            return None
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            score, ts = item
            if self._is_expired(ts, now):
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key, last=True)
            return float(score)

    def set(self, key: str, score: float) -> None:
        if not key:
            return
        if self._max_entries <= 0:
            return
        now = time.time()
        with self._lock:
            self._data[key] = (float(score), now)
            self._data.move_to_end(key, last=True)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)


def sigmoid(x: float) -> float:
    """Sigmoid normalization function."""
    return 1 / (1 + np.exp(-x))


class BaseReranker(ABC):
    """
    Top-level abstract base class for rerankers.

    Defines the common rerank() interface. Subclasses can implement sync
    or async variants.
    """

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        """
        Synchronous rerank interface.

        Args:
            query: query text
            candidates: candidate list
            **kwargs: other parameters (e.g., top_n, score_threshold)

        Returns:
            RerankResult: rerank result
        """
        raise NotImplementedError

    async def arerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        """
        Asynchronous rerank interface (optional).

        Default: run synchronous rerank() in a separate thread. Subclasses can
        override to provide a true async implementation.
        """
        return await asyncio.to_thread(lambda: self.rerank(query, candidates, **kwargs))


class APIReranker(BaseReranker):
    """
    Abstract HTTP API reranker base class.

    Used for remote reranker APIs (e.g., OpenAI, DashScope, SiliconFlow).
    Subclasses must implement:
    - _build_payload(): build request payload
    - _extract_results(): parse response results
    """

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout: float = 30.0,
        **kwargs,
    ):
        self.url = base_url
        self.model = model_name
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.session: aiohttp.ClientSession | None = None
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.parameters: dict[str, Any] = dict(kwargs.get("parameters", {}))

        # Engineering state (rate-limit / circuit-breaker / cache)
        self._score_cache = _ScoreCache()
        self._rate_lock = threading.Lock()
        self._rate_next_at = 0.0
        self._cb_lock = threading.Lock()
        self._cb_failures = 0
        self._cb_open_until = 0.0

    def _cache_key(self, query: str, document: str, *, max_length: int) -> str:
        q = (query or "").strip()
        d = (document or "").strip()
        if not q or not d:
            return ""
        payload = f"{q}\n\n{d}\n\nmax_length={int(max_length)}".encode("utf-8", errors="ignore")
        return hashlib.sha256(payload).hexdigest()

    def _rate_limit_sync(self) -> None:
        qps = float(settings.RERANKER_API_RATE_LIMIT_QPS or 0.0)
        if qps <= 0:
            return
        min_interval = 1.0 / qps if qps > 0 else 0.0
        if min_interval <= 0:
            return

        wait = 0.0
        now = time.monotonic()
        with self._rate_lock:
            if self._rate_next_at <= 0 or now >= self._rate_next_at:
                self._rate_next_at = now + min_interval
                return
            wait = self._rate_next_at - now
            self._rate_next_at = self._rate_next_at + min_interval
        if wait > 0:
            time.sleep(wait)

    async def _rate_limit_async(self) -> None:
        qps = float(settings.RERANKER_API_RATE_LIMIT_QPS or 0.0)
        if qps <= 0:
            return
        min_interval = 1.0 / qps if qps > 0 else 0.0
        if min_interval <= 0:
            return

        wait = 0.0
        now = time.monotonic()
        with self._rate_lock:
            if self._rate_next_at <= 0 or now >= self._rate_next_at:
                self._rate_next_at = now + min_interval
                return
            wait = self._rate_next_at - now
            self._rate_next_at = self._rate_next_at + min_interval
        if wait > 0:
            await asyncio.sleep(wait)

    def _circuit_open(self) -> bool:
        now = time.monotonic()
        with self._cb_lock:
            return bool(self._cb_open_until and now < self._cb_open_until)

    def _record_success(self) -> None:
        with self._cb_lock:
            self._cb_failures = 0
            self._cb_open_until = 0.0

    def _record_failure(self) -> None:
        threshold = max(1, int(settings.RERANKER_API_CIRCUIT_BREAKER_FAILURE_THRESHOLD or 5))
        reset_sec = max(1, int(settings.RERANKER_API_CIRCUIT_BREAKER_RESET_SEC or 60))
        now = time.monotonic()
        with self._cb_lock:
            self._cb_failures += 1
            if self._cb_failures >= threshold:
                self._cb_open_until = now + float(reset_sec)

    def _ensure_session(self) -> None:
        """Ensure the aiohttp session is available."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers=self.headers,
                timeout=self.timeout,
            )

    @abstractmethod
    def _build_payload(
        self,
        query: str,
        documents: list[str],
        max_length: int,
    ) -> dict[str, Any]:
        """Build the request payload (implemented by subclasses)."""
        raise NotImplementedError

    @abstractmethod
    def _extract_results(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse response results (implemented by subclasses)."""
        raise NotImplementedError

    async def acompute_score(
        self,
        query: str,
        documents: list[str],
        batch_size: int = 32,
        max_length: int = 512,
        normalize: bool = True,
    ) -> list[float]:
        """
        Compute rerank scores asynchronously.

        Args:
            query: query text
            documents: document list
            batch_size: batch size
            max_length: max length
            normalize: whether to normalize scores

        Returns:
            scores aligned with the documents list
        """
        if not documents:
            return []

        if self._circuit_open():
            raise RuntimeError("reranker circuit is open")

        self._ensure_session()

        all_scores: list[float] = []
        batch_size = max(1, int(batch_size))
        max_retries = max(0, int(settings.RERANKER_API_MAX_RETRIES or 0))
        backoff = max(0.0, float(settings.RERANKER_API_RETRY_BACKOFF_SEC or 0.0))
        max_concurrency = max(1, int(settings.RERANKER_API_MAX_CONCURRENCY or 1))

        batches: list[tuple[int, list[str]]] = []
        for start in range(0, len(documents), batch_size):
            idx = start // batch_size
            batches.append((idx, documents[start : start + batch_size]))

        sem = asyncio.Semaphore(max_concurrency)

        async def run_one(batch_idx: int, batch_docs: list[str]) -> tuple[int, list[float]]:
            async with sem:
                last_exc: Exception | None = None
                for attempt in range(max_retries + 1):
                    try:
                        scores = await self._batch_rerank(query, batch_docs, max_length=max_length)
                        return batch_idx, scores
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        status = getattr(exc, "status", None)
                        retryable = status in RETRYABLE_HTTP_CODES or isinstance(exc, (aiohttp.ClientError, asyncio.TimeoutError))
                        if attempt < max_retries and retryable:
                            await asyncio.sleep(backoff * (2**attempt))
                            continue
                        raise
                raise last_exc or RuntimeError("reranker request failed")

        try:
            results = await asyncio.gather(*(run_one(i, b) for i, b in batches))
            for _, scores in sorted(results, key=lambda x: x[0]):
                all_scores.extend(scores)
            self._record_success()
        except Exception:  # noqa: BLE001
            self._record_failure()
            raise

        if normalize:
            all_scores = [float(sigmoid(score)) for score in all_scores]

        return all_scores

    async def _batch_rerank(
        self,
        query: str,
        documents: list[str],
        max_length: int,
    ) -> list[float]:
        """Rerank a single batch."""
        if not documents:
            return []

        payload = self._build_payload(query, documents, max_length)

        self._ensure_session()
        if self.session is None:
            raise RuntimeError("Reranker HTTP session is not initialized")

        await self._rate_limit_async()
        async with self.session.post(self.url, json=payload) as response:
            response.raise_for_status()
            result: dict[str, Any] = await response.json()

        scores = [0.0] * len(documents)
        for entry in self._extract_results(result) or []:
            if not isinstance(entry, dict):
                continue
            try:
                idx = int(entry.get("index", -1))
            except Exception:
                logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            if idx < 0 or idx >= len(documents):
                continue
            try:
                scores[idx] = float(entry.get("relevance_score", 0.0) or 0.0)
            except Exception:
                scores[idx] = 0.0
        return scores

    def compute_score(
        self,
        query: str,
        documents: list[str],
        batch_size: int = 32,
        max_length: int = 512,
        normalize: bool = True,
    ) -> list[float]:
        """
        Compute rerank scores synchronously (thread-safe, event-loop friendly).

        Notes:
        - The server main path is async, but retrieval uses sync calls (`retriever.invoke()`).
        - Avoid conflicts between `asyncio.run()` / `aiohttp.ClientSession` and a running loop.
        - Use httpx for sync HTTP calls to stay safe under async execution.
        """
        if not documents:
            return []

        if self._circuit_open():
            raise RuntimeError("reranker circuit is open")

        all_scores: list[float] = []
        batch_size = max(1, int(batch_size))
        timeout_sec = float(settings.RERANKER_API_TIMEOUT_SEC or getattr(self.timeout, "total", None) or 30.0)
        max_retries = max(0, int(settings.RERANKER_API_MAX_RETRIES or 0))
        backoff = max(0.0, float(settings.RERANKER_API_RETRY_BACKOFF_SEC or 0.0))
        max_concurrency = max(1, int(settings.RERANKER_API_MAX_CONCURRENCY or 1))
        trust_env = httpx_trust_env(logger=logger)

        batches: list[tuple[int, list[str]]] = []
        for start in range(0, len(documents), batch_size):
            idx = start // batch_size
            batches.append((idx, documents[start : start + batch_size]))

        def should_retry(exc: Exception) -> bool:
            if isinstance(exc, httpx.HTTPStatusError):
                status = exc.response.status_code
                return status in RETRYABLE_HTTP_CODES
            return isinstance(exc, httpx.RequestError)

        def post_one(batch_docs: list[str], *, client: httpx.Client | None = None) -> list[float]:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    self._rate_limit_sync()
                    payload = self._build_payload(query, batch_docs, max_length)
                    if client is None:
                        with httpx.Client(headers=self.headers, timeout=timeout_sec, trust_env=trust_env) as local_client:
                            resp = local_client.post(self.url, json=payload)
                            resp.raise_for_status()
                            result: dict[str, Any] = resp.json()
                    else:
                        resp = client.post(self.url, json=payload)
                        resp.raise_for_status()
                        result = resp.json()

                    scores = [0.0] * len(batch_docs)
                    for entry in self._extract_results(result) or []:
                        if not isinstance(entry, dict):
                            continue
                        try:
                            index = int(entry.get("index", -1))
                        except Exception:
                            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                            continue
                        if index < 0 or index >= len(batch_docs):
                            continue
                        try:
                            scores[index] = float(entry.get("relevance_score", 0.0) or 0.0)
                        except Exception:
                            scores[index] = 0.0
                    return scores
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt < max_retries and should_retry(exc):
                        time.sleep(backoff * (2**attempt))
                        continue
                    raise
            raise last_exc or RuntimeError("reranker request failed")

        try:
            if max_concurrency <= 1 or len(batches) <= 1:
                with httpx.Client(headers=self.headers, timeout=timeout_sec, trust_env=trust_env) as client:
                    for _, batch_docs in batches:
                        all_scores.extend(post_one(batch_docs, client=client))
            else:
                import concurrent.futures

                results_by_idx: dict[int, list[float]] = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as pool:
                    future_map = {pool.submit(post_one, batch): idx for idx, batch in batches}
                    for fut in concurrent.futures.as_completed(future_map):
                        idx = future_map[fut]
                        results_by_idx[idx] = fut.result()
                for idx in sorted(results_by_idx.keys()):
                    all_scores.extend(results_by_idx[idx])
            self._record_success()
        except Exception:  # noqa: BLE001
            self._record_failure()
            raise

        if normalize:
            all_scores = [float(sigmoid(score)) for score in all_scores]

        return all_scores

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        """
        Synchronous rerank implementation (BaseReranker).

        Converts candidates to documents and calls the API to compute scores.
        """
        if not candidates:
            return RerankResult(ordered_ids=[], score_map={})

        provider = self.__class__.__name__.replace("Reranker", "").lower()
        if self._circuit_open():
            stats = {
                "skipped": True,
                "skip_reason": "circuit_open",
                "provider": provider,
                "model": self.model,
            }
            if settings.ENABLE_METRICS_LOG:
                try:
                    qh = hashlib.sha256((query or "").encode("utf-8", errors="ignore")).hexdigest()[:12]
                except Exception:
                    qh = None
                log_metrics(
                    {
                        "event": "reranker_api",
                        "provider": provider,
                        "model": self.model,
                        "url": self.url,
                        "query_hash": qh,
                        "query_chars": len(query or ""),
                        "docs": len(candidates),
                        "skipped": True,
                        "skip_reason": "circuit_open",
                    }
                )
            return RerankResult(
                ordered_ids=[],
                score_map={},
                elapsed_sec=0.0,
                model_used=self.model,
                provider=provider,
                stats=stats,
            )

        start = time.time()
        top_n = kwargs.get("top_n")
        batch_size = int(kwargs.get("batch_size") or settings.RERANKER_API_BATCH_SIZE or 32)
        batch_size = max(1, batch_size)
        max_length = int(kwargs.get("max_length") or 512)
        normalize = bool(kwargs.get("normalize", True))
        max_chars = int(kwargs.get("max_chars") or settings.RERANKER_MAX_CHARS or 0)

        cache_enabled = bool(settings.RERANKER_API_CACHE_ENABLED) and int(settings.RERANKER_API_CACHE_MAX_ENTRIES or 0) > 0
        if cache_enabled:
            self._score_cache.configure(
                max_entries=int(settings.RERANKER_API_CACHE_MAX_ENTRIES or 0),
                ttl_sec=float(settings.RERANKER_API_CACHE_TTL_SEC or 0),
            )
        else:
            self._score_cache.configure(max_entries=0, ttl_sec=0.0)

        candidate_ids: list[str] = []
        documents: list[str] = []
        for c in candidates:
            candidate_ids.append(str(c.id))
            text = (c.text or "").strip()
            if max_chars > 0 and len(text) > max_chars:
                text = text[:max_chars] + "..."
            documents.append(text)

        scores: list[float | None] = [None] * len(documents)
        cache_hits = 0
        cache_misses = 0
        missing_docs: list[str] = []
        missing_indices: list[int] = []

        if cache_enabled:
            for i, doc in enumerate(documents):
                key = self._cache_key(query, doc, max_length=max_length)
                cached = self._score_cache.get(key)
                if cached is None:
                    cache_misses += 1
                    missing_docs.append(doc)
                    missing_indices.append(i)
                else:
                    cache_hits += 1
                    scores[i] = float(cached)
        else:
            missing_docs = list(documents)
            missing_indices = list(range(len(documents)))

        if missing_docs:
            try:
                network_scores = self.compute_score(
                    query=query,
                    documents=missing_docs,
                    batch_size=batch_size,
                    max_length=max_length,
                    normalize=normalize,
                )
            except Exception as exc:  # noqa: BLE001
                elapsed = time.time() - start
                logger.warning("API reranker failed (%s): %s", provider, str(exc)[:200])
                if settings.ENABLE_METRICS_LOG:
                    try:
                        qh = hashlib.sha256((query or "").encode("utf-8", errors="ignore")).hexdigest()[:12]
                    except Exception:
                        qh = None
                    log_metrics(
                        {
                            "event": "reranker_api",
                            "provider": provider,
                            "model": self.model,
                            "url": self.url,
                            "query_hash": qh,
                            "query_chars": len(query or ""),
                            "docs": len(candidates),
                            "missing_docs": len(missing_docs),
                            "elapsed_sec": round(float(elapsed), 3),
                            "batch_size": batch_size,
                            "max_concurrency": int(settings.RERANKER_API_MAX_CONCURRENCY or 1),
                            "rate_limit_qps": float(settings.RERANKER_API_RATE_LIMIT_QPS or 0.0),
                            "max_retries": int(settings.RERANKER_API_MAX_RETRIES or 0),
                            "cache_enabled": bool(cache_enabled),
                            "cache_hits": int(cache_hits),
                            "cache_misses": int(cache_misses),
                            "error": str(exc)[:200],
                        }
                    )
                raise
            if len(network_scores) != len(missing_docs):
                logger.warning(
                    "API reranker score count mismatch: expected %d, got %d (provider=%s, model=%s)",
                    len(missing_docs), len(network_scores), provider, self.model
                )
                if len(network_scores) < len(missing_docs):
                    network_scores = list(network_scores) + [0.0] * (len(missing_docs) - len(network_scores))
                else:
                    network_scores = list(network_scores)[: len(missing_docs)]

            for idx, score in zip(missing_indices, network_scores, strict=False):
                scores[idx] = float(score)
                if cache_enabled:
                    key = self._cache_key(query, documents[idx], max_length=max_length)
                    self._score_cache.set(key, float(score))

        final_scores = [float(s if s is not None else 0.0) for s in scores]
        score_map = {cid: score for cid, score in zip(candidate_ids, final_scores, strict=False) if cid}

        ordered = sorted(
            zip(candidate_ids, final_scores, strict=False),
            key=lambda x: x[1],
            reverse=True,
        )
        ordered_ids = [cid for cid, _ in ordered if cid]

        if top_n:
            ordered_ids = ordered_ids[: int(top_n)]
            score_map = {cid: score_map[cid] for cid in ordered_ids if cid in score_map}

        elapsed = time.time() - start
        stats = {
            "provider": provider,
            "model": self.model,
            "url": self.url,
            "query_chars": len(query or ""),
            "docs": len(candidates),
            "batch_size": batch_size,
            "max_concurrency": int(settings.RERANKER_API_MAX_CONCURRENCY or 1),
            "rate_limit_qps": float(settings.RERANKER_API_RATE_LIMIT_QPS or 0.0),
            "max_retries": int(settings.RERANKER_API_MAX_RETRIES or 0),
            "cache_enabled": bool(cache_enabled),
            "cache_hits": int(cache_hits),
            "cache_misses": int(cache_misses),
        }

        if settings.ENABLE_METRICS_LOG:
            try:
                qh = hashlib.sha256((query or "").encode("utf-8", errors="ignore")).hexdigest()[:12]
            except Exception:
                qh = None
            log_metrics(
                {
                    "event": "reranker_api",
                    "provider": provider,
                    "model": self.model,
                    "url": self.url,
                    "query_hash": qh,
                    "query_chars": len(query or ""),
                    "docs": len(candidates),
                    "elapsed_sec": round(float(elapsed), 3),
                    "batch_size": batch_size,
                    "max_concurrency": int(settings.RERANKER_API_MAX_CONCURRENCY or 1),
                    "rate_limit_qps": float(settings.RERANKER_API_RATE_LIMIT_QPS or 0.0),
                    "max_retries": int(settings.RERANKER_API_MAX_RETRIES or 0),
                    "cache_enabled": bool(cache_enabled),
                    "cache_hits": int(cache_hits),
                    "cache_misses": int(cache_misses),
                }
            )

        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            elapsed_sec=float(elapsed),
            model_used=self.model,
            provider=provider,
            stats=stats,
        )

    async def arerank_legacy(
        self,
        query: str,
        candidates: Sequence[dict[str, Any]],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Asynchronously rerank candidates (legacy interface for backward compatibility).

        Args:
            query: query text
            candidates: candidate documents (id, text, metadata)
            top_n: return top N results

        Returns:
            reranked candidates sorted by score
        """
        if not candidates:
            return []

        documents = [c.get("text", "") for c in candidates]
        scores = await self.acompute_score(query, documents)

        results = []
        for candidate, score in zip(candidates, scores, strict=False):
            result = dict(candidate)
            result["rerank_score"] = score
            results.append(result)

        results.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

        if top_n:
            results = results[:top_n]

        return results

    async def aclose(self) -> None:
        """Close the session."""
        if self.session and not self.session.closed:
            await self.session.close()

    def __del__(self) -> None:
        if self.session and not self.session.closed:
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                asyncio.run(self.aclose())
                return

            if loop.is_closed():
                asyncio.run(self.aclose())
            elif not loop.is_running():
                loop.run_until_complete(self.aclose())


class DocumentReranker(BaseReranker):
    """
    Abstract document-level reranker base class.

    Reranks document lists (weight fusion, parent/child, LLM rerank, etc.).
    Subclasses must implement run().
    """

    @abstractmethod
    def run(
        self,
        query: str,
        documents: list[Any],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
    ) -> list[Any]:
        """
        Run the reranker and return documents sorted by relevance.

        Args:
            query: query text
            documents: document list (usually Document objects)
            score_threshold: score threshold
            top_n: return top N results
            user: user identifier (optional)

        Returns:
            reranked document list
        """
        raise NotImplementedError

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **kwargs: Any,
    ) -> RerankResult:
        """
        Synchronous rerank implementation (BaseReranker).

        Converts RerankCandidate to Document and calls run().
        """
        from app.models.chunk import Document as ChunkDocument
        
        if not candidates:
            return RerankResult(ordered_ids=[], score_map={})
        
        # Convert to Document objects.
        docs: list[ChunkDocument] = []
        for c in candidates:
            meta = dict(c.metadata or {})
            meta.setdefault("candidate_id", c.id)
            docs.append(
                ChunkDocument(
                    page_content=c.text,
                    metadata=meta,
                    provider="reranker"
                )
            )
        
        # Call run().
        top_n = kwargs.get("top_n")
        score_threshold = kwargs.get("score_threshold")
        reranked = self.run(query, docs, score_threshold=score_threshold, top_n=top_n)
        
        # Extract results.
        ordered_ids: list[str] = []
        score_map: dict[str, float] = {}
        for doc in reranked:
            meta = doc.metadata or {}
            cid = meta.get("candidate_id")
            if cid is None:
                continue
            cid = str(cid)
            ordered_ids.append(cid)
            score_map[cid] = float(meta.get("score", 0.0) or 0.0)
        
        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            provider=self.__class__.__name__.replace("Reranker", "").lower(),
        )
