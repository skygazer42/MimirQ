"""
Generic per-process warmup for the active embedding and reranker runtimes.

This is intentionally bounded and read-only:
- No dataset/business probes
- No DB writes
- Minimal single-text/provider probes only
"""

import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("services.rag_runtime_warmup")

_RAG_RUNTIME_WARMUP_PROBE_TEXT = "MimirQ runtime warmup probe"
_rag_runtime_warmup_state_lock = threading.Lock()
_rag_runtime_warmup_tasks: set[asyncio.Task[Any]] = set()
_rag_runtime_warmup_state: dict[str, Any] = {
    "enabled": False,
    "required_for_ready": False,
    "ready": True,
    "status": "idle",
    "attempted": 0,
    "completed": 0,
    "failed": 0,
    "elapsed_ms": None,
    "updated_at": None,
    "embedding": None,
    "reranker": None,
}


def _new_probe_state(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "idle",
        "ready": False,
        "provider": None,
        "model": None,
        "elapsed_ms": None,
        "error": None,
        "reason": None,
    }


def _set_rag_runtime_warmup_status(**updates: Any) -> None:
    with _rag_runtime_warmup_state_lock:
        _rag_runtime_warmup_state.update(updates)
        _rag_runtime_warmup_state["updated_at"] = datetime.now(timezone.utc).isoformat()


def _set_rag_runtime_warmup_schedule_failed(*, required_for_ready: bool, error: str) -> None:
    failed_probe = {
        **_new_probe_state("embedding"),
        "status": "failed",
        "reason": "schedule_failed",
        "error": error,
    }
    _set_rag_runtime_warmup_status(
        enabled=True,
        required_for_ready=required_for_ready,
        ready=False,
        status="failed",
        attempted=0,
        completed=0,
        failed=2,
        elapsed_ms=0.0,
        embedding=failed_probe,
        reranker={**failed_probe, "name": "reranker"},
    )


def get_rag_runtime_warmup_status() -> dict[str, Any]:
    with _rag_runtime_warmup_state_lock:
        snapshot = dict(_rag_runtime_warmup_state)
    embedding = snapshot.get("embedding")
    reranker = snapshot.get("reranker")
    if isinstance(embedding, dict):
        snapshot["embedding"] = dict(embedding)
    if isinstance(reranker, dict):
        snapshot["reranker"] = dict(reranker)
    return snapshot


def rag_runtime_warmup_ready() -> bool:
    if not bool(getattr(settings, "RAG_RUNTIME_WARMUP_ENABLED", False)):
        return True
    return bool(get_rag_runtime_warmup_status().get("ready"))


def _resolve_timeout_sec() -> float:
    try:
        timeout_sec = float(getattr(settings, "RAG_RUNTIME_WARMUP_TIMEOUT_SEC", 15.0) or 15.0)
    except (TypeError, ValueError):
        timeout_sec = 15.0
    return max(0.5, min(timeout_sec, 120.0))


def _sanitize_error_message(exc: BaseException) -> str:
    message = str(exc or "").strip() or exc.__class__.__name__
    for secret in {
        str(getattr(settings, "EMBEDDING_API_KEY", "") or ""),
        str(getattr(settings, "RERANKER_API_KEY", "") or ""),
        str(getattr(settings, "LLM_API_KEY", "") or ""),
    }:
        if secret:
            message = message.replace(secret, "[redacted]")
    return message[:200]


def _probe_embedding_runtime_sync() -> dict[str, Any]:
    from app.storage.vector.factory import get_embedding_client, get_vector_store

    provider_name = str(getattr(settings, "EMBEDDING_PROVIDER", "") or "").strip().lower() or "openai_compatible"
    model_name = str(getattr(settings, "EMBEDDING_MODEL", "") or "").strip() or None
    vector_backend = str(getattr(settings, "VECTOR_BACKEND", "") or "milvus").strip().lower() or "milvus"
    probe = _new_probe_state("embedding")
    probe.update({"provider": provider_name, "model": model_name, "vector_backend": vector_backend})
    started = time.perf_counter()
    active_store = get_vector_store()
    provider = active_store.get_embedding_client()
    resolved_provider = get_embedding_client()
    if provider is not resolved_provider:
        raise RuntimeError("embedding_client_not_reused_by_active_store")

    vector: list[float] | None = None
    embed_query = getattr(provider, "embed_query", None)
    embed_documents = getattr(provider, "embed_documents", None)
    if callable(embed_query):
        vector = embed_query(_RAG_RUNTIME_WARMUP_PROBE_TEXT)
    elif callable(embed_documents):
        vectors = embed_documents([_RAG_RUNTIME_WARMUP_PROBE_TEXT])
        vector = vectors[0] if vectors else None
    else:
        raise RuntimeError("embedding_provider_missing_embed_query")

    if not isinstance(vector, list) or not vector:
        raise RuntimeError("embedding_probe_returned_empty_vector")
    if active_store.get_embedding_client() is not provider:
        raise RuntimeError("embedding_client_not_reused_after_probe")

    probe.update(
        {
            "status": "completed",
            "ready": True,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "dimension": len(vector),
        }
    )
    return probe


async def _probe_embedding_runtime(timeout_sec: float) -> dict[str, Any]:
    provider_name = str(getattr(settings, "EMBEDDING_PROVIDER", "") or "").strip().lower() or None
    model_name = str(getattr(settings, "EMBEDDING_MODEL", "") or "").strip() or None
    vector_backend = str(getattr(settings, "VECTOR_BACKEND", "") or "milvus").strip().lower() or None
    try:
        return await asyncio.wait_for(asyncio.to_thread(_probe_embedding_runtime_sync), timeout=timeout_sec)
    except asyncio.TimeoutError:
        probe = _new_probe_state("embedding")
        probe.update(
            {
                "provider": provider_name,
                "model": model_name,
                "vector_backend": vector_backend,
                "status": "failed",
                "ready": False,
                "reason": "timeout",
                "error": f"warmup timed out after {timeout_sec:.2f}s",
            }
        )
        return probe
    except Exception as exc:  # noqa: BLE001
        probe = _new_probe_state("embedding")
        probe.update(
            {
                "provider": provider_name,
                "model": model_name,
                "vector_backend": vector_backend,
                "status": "failed",
                "ready": False,
                "reason": exc.__class__.__name__,
                "error": _sanitize_error_message(exc),
            }
        )
        return probe


def _probe_reranker_runtime_sync(timeout_sec: float) -> dict[str, Any]:
    from app.rag.reranker.factory import describe_reranker_provider, get_reranker
    from app.rag.reranker.types import RerankCandidate

    configured_provider = str(getattr(settings, "RERANKER_PROVIDER", "") or "").strip().lower() or "none"
    probe = _new_probe_state("reranker")
    probe.update(
        {
            "provider": configured_provider,
            "model": str(getattr(settings, "RERANKER_MODEL", "") or "").strip() or None,
        }
    )
    if configured_provider in {"none", "off", "false", "0"}:
        probe.update({"status": "skipped", "ready": True, "reason": "provider_disabled", "elapsed_ms": 0.0})
        return probe
    if configured_provider in {"weighted", "kg_pagerank", "kg_rrf"}:
        probe.update(
            {
                "status": "skipped",
                "ready": True,
                "reason": "provider_has_no_safe_generic_probe",
                "elapsed_ms": 0.0,
            }
        )
        return probe

    started = time.perf_counter()
    init_kwargs: dict[str, Any] = {}
    if configured_provider in {"openai", "dashscope", "aliyun"}:
        init_kwargs["timeout"] = min(timeout_sec, float(getattr(settings, "RERANKER_API_TIMEOUT_SEC", 30.0) or 30.0))

    reranker = get_reranker(configured_provider, model_name=probe["model"], **init_kwargs)
    result = reranker.rerank(
        _RAG_RUNTIME_WARMUP_PROBE_TEXT,
        [RerankCandidate(id="warmup-1", text="Warmup candidate passage.")],
        top_n=1,
        max_chars=128,
    )
    ordered_ids = list(getattr(result, "ordered_ids", []) or [])
    if configured_provider not in {"parent_child", "pc"} and not ordered_ids:
        raise RuntimeError("reranker_probe_returned_no_results")

    desc = describe_reranker_provider(configured_provider)
    probe.update(
        {
            "provider": str(desc.get("provider") or configured_provider),
            "tier": desc.get("tier"),
            "mode": desc.get("mode"),
            "status": "completed",
            "ready": True,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    )
    if getattr(result, "model_used", None):
        probe["model"] = str(result.model_used)
    return probe


async def _probe_reranker_runtime(timeout_sec: float) -> dict[str, Any]:
    provider_name = str(getattr(settings, "RERANKER_PROVIDER", "") or "").strip().lower() or None
    model_name = str(getattr(settings, "RERANKER_MODEL", "") or "").strip() or None
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_probe_reranker_runtime_sync, timeout_sec),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        probe = _new_probe_state("reranker")
        probe.update(
            {
                "provider": provider_name,
                "model": model_name,
                "status": "failed",
                "ready": False,
                "reason": "timeout",
                "error": f"warmup timed out after {timeout_sec:.2f}s",
            }
        )
        return probe
    except Exception as exc:  # noqa: BLE001
        probe = _new_probe_state("reranker")
        probe.update(
            {
                "provider": provider_name,
                "model": model_name,
                "status": "failed",
                "ready": False,
                "reason": exc.__class__.__name__,
                "error": _sanitize_error_message(exc),
            }
        )
        return probe


async def warmup_rag_runtime() -> dict[str, Any]:
    required_for_ready = bool(getattr(settings, "RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY", False))
    if not bool(getattr(settings, "RAG_RUNTIME_WARMUP_ENABLED", False)):
        embedding = _new_probe_state("embedding")
        reranker = _new_probe_state("reranker")
        embedding.update({"status": "skipped", "ready": True, "reason": "warmup_disabled", "elapsed_ms": 0.0})
        reranker.update({"status": "skipped", "ready": True, "reason": "warmup_disabled", "elapsed_ms": 0.0})
        _set_rag_runtime_warmup_status(
            enabled=False,
            required_for_ready=required_for_ready,
            ready=True,
            status="disabled",
            attempted=0,
            completed=0,
            failed=0,
            elapsed_ms=0.0,
            embedding=embedding,
            reranker=reranker,
        )
        return get_rag_runtime_warmup_status()

    timeout_sec = _resolve_timeout_sec()
    _set_rag_runtime_warmup_status(
        enabled=True,
        required_for_ready=required_for_ready,
        ready=False,
        status="running",
        attempted=2,
        completed=0,
        failed=0,
        elapsed_ms=None,
        embedding={**_new_probe_state("embedding"), "status": "running"},
        reranker={**_new_probe_state("reranker"), "status": "running"},
    )
    started = time.perf_counter()
    embedding, reranker = await asyncio.gather(
        _probe_embedding_runtime(timeout_sec),
        _probe_reranker_runtime(timeout_sec),
    )
    probes = [embedding, reranker]
    failed = sum(1 for probe in probes if not bool(probe.get("ready")))
    completed = sum(1 for probe in probes if str(probe.get("status") or "") in {"completed", "skipped"})
    ready = failed == 0
    status = "completed" if ready else "failed"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    _set_rag_runtime_warmup_status(
        enabled=True,
        required_for_ready=required_for_ready,
        ready=ready,
        status=status,
        attempted=len(probes),
        completed=completed,
        failed=failed,
        elapsed_ms=elapsed_ms,
        embedding=embedding,
        reranker=reranker,
    )
    logger.info(
        "RAG runtime warmup finished status=%s failed=%s elapsed_ms=%s",
        status,
        failed,
        elapsed_ms,
    )
    return get_rag_runtime_warmup_status()


async def _delayed_warmup_rag_runtime() -> dict[str, Any]:
    await asyncio.sleep(0)
    return await warmup_rag_runtime()


def _log_runtime_warmup_task_result(task: Any) -> None:
    if isinstance(task, asyncio.Task):
        _rag_runtime_warmup_tasks.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("RAG runtime warmup task cancelled")
    except Exception:  # noqa: BLE001
        logger.warning("RAG runtime warmup task failed", exc_info=True)


def start_rag_runtime_warmup(*, create_task: Any | None = None) -> Any | None:
    required_for_ready = bool(getattr(settings, "RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY", False))
    if not bool(getattr(settings, "RAG_RUNTIME_WARMUP_ENABLED", False)):
        _set_rag_runtime_warmup_status(
            enabled=False,
            required_for_ready=required_for_ready,
            ready=True,
            status="disabled",
            attempted=0,
            completed=0,
            failed=0,
            elapsed_ms=0.0,
            embedding={**_new_probe_state("embedding"), "status": "skipped", "ready": True, "reason": "warmup_disabled"},
            reranker={**_new_probe_state("reranker"), "status": "skipped", "ready": True, "reason": "warmup_disabled"},
        )
        return None

    _set_rag_runtime_warmup_status(
        enabled=True,
        required_for_ready=required_for_ready,
        ready=False,
        status="scheduled",
        attempted=2,
        completed=0,
        failed=0,
        elapsed_ms=None,
        embedding=_new_probe_state("embedding"),
        reranker=_new_probe_state("reranker"),
    )
    coro = _delayed_warmup_rag_runtime()
    try:
        task = create_task(coro) if create_task is not None else asyncio.create_task(coro)
    except RuntimeError:
        coro.close()
        _set_rag_runtime_warmup_schedule_failed(
            required_for_ready=required_for_ready,
            error="no_running_event_loop",
        )
        logger.warning("RAG runtime warmup was not scheduled: no running event loop")
        return None
    except Exception as exc:  # noqa: BLE001
        coro.close()
        _set_rag_runtime_warmup_schedule_failed(
            required_for_ready=required_for_ready,
            error=_sanitize_error_message(exc),
        )
        logger.warning("RAG runtime warmup was not scheduled", exc_info=True)
        return None

    if isinstance(task, asyncio.Task):
        _rag_runtime_warmup_tasks.add(task)
    add_done_callback = getattr(task, "add_done_callback", None)
    if callable(add_done_callback):
        add_done_callback(_log_runtime_warmup_task_result)
    logger.info("RAG runtime warmup scheduled timeout_sec=%s", _resolve_timeout_sec())
    return task


__all__ = [
    "get_rag_runtime_warmup_status",
    "rag_runtime_warmup_ready",
    "start_rag_runtime_warmup",
    "warmup_rag_runtime",
]
