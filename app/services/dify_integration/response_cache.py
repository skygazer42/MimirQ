"""Dify response cache, singleflight and lease ownership."""

import asyncio
import contextlib
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.retrieval.planner import DatasetScopePlan
from app.services import corpus_cache_tokens
from app.services.chat_response_cache import (
    InflightResponseLeaderCancelledError,
    extend_best_effort_redis_lease,
    get_best_effort_json_cache_value,
    release_best_effort_redis_lease,
    set_best_effort_json_cache_value,
    try_acquire_best_effort_redis_lease,
)
from app.services.chat_response_cache import acquire_inflight_chat_response as acquire_inflight_response
from app.services.chat_response_cache import reject_inflight_chat_response as reject_inflight_response
from app.services.chat_response_cache import resolve_inflight_chat_response as resolve_inflight_response
from app.services.dify_integration import common
from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError
from app.types.dify_integration import DifyActor as _DifyActor
from app.types.dify_integration import DifyExternalKnowledgeRecord, DifyExternalKnowledgeRequest, DifyRetrievalSetting


@dataclass(frozen=True)
class ResponseCachePolicy:
    ttl_sec: int
    max_entries: int
    response_cache_enabled: bool
    singleflight_enabled: bool


@dataclass(frozen=True)
class PreparedCacheKey:
    key: str | None
    timings_ms: dict[str, float]


@dataclass(frozen=True)
class DifyCacheResult:
    records: list[dict[str, Any]]
    source: Literal["computed", "cache_hit", "singleflight_hit", "distributed_cache_hit"]
    timings_ms: dict[str, float]


def resolve_policy() -> ResponseCachePolicy:
    ttl_sec = max(0, settings.DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC)
    max_entries = max(0, settings.DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES)
    enabled = settings.DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED and ttl_sec > 0 and max_entries > 0
    return ResponseCachePolicy(
        ttl_sec=ttl_sec,
        max_entries=max_entries,
        response_cache_enabled=enabled,
        singleflight_enabled=settings.DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED,
    )


def prepare_key(
    *,
    db: Session,
    actor: _DifyActor,
    body: DifyExternalKnowledgeRequest,
    scope_plan: DatasetScopePlan,
    top_k: int,
    candidate_top_k: int,
    score_threshold: float,
    policy_plugin_refs: tuple[str, ...],
    policy: ResponseCachePolicy,
) -> PreparedCacheKey:
    if not (policy.response_cache_enabled or policy.singleflight_enabled):
        return PreparedCacheKey(key=None, timings_ms={})
    started = time.perf_counter()
    try:
        corpus_token = _resolve_dify_response_cache_corpus_token(
            db=db, tenant_id=actor.tenant_id, dataset_ids=list(scope_plan.dataset_ids)
        )
    finally:
        with contextlib.suppress(Exception):
            db.rollback()
    timings = {"response_cache_corpus_token_ms": round((time.perf_counter() - started) * 1000, 2)}
    key = None
    if corpus_token:
        key = _build_dify_response_cache_key(
            actor=actor,
            knowledge_id=body.knowledge_id,
            query=body.query,
            retrieval_setting=body.retrieval_setting,
            metadata_condition=body.metadata_condition,
            scope_plan=scope_plan,
            top_k=top_k,
            candidate_top_k=candidate_top_k,
            score_threshold=score_threshold,
            policy_plugin_refs=policy_plugin_refs,
            corpus_token=corpus_token,
        )
    return PreparedCacheKey(key=key, timings_ms=timings)


def _resolve_dify_response_cache_corpus_token(*, db: Session, tenant_id: UUID, dataset_ids: list[UUID]) -> str | None:
    scoped_dataset_ids = common._dedupe_dataset_ids(dataset_ids)
    if not scoped_dataset_ids:
        return None
    try:
        return corpus_cache_tokens.resolve_corpus_cache_token(db, tenant_id=tenant_id, dataset_ids=scoped_dataset_ids)
    except Exception:
        logger.warning("Dify response cache corpus token unavailable", exc_info=True)
        return None


async def _dify_response_cache_redis_payload(key: str) -> list[dict[str, Any]] | None:
    payload = await get_best_effort_json_cache_value(key)
    if payload is None:
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != _DIFY_RESPONSE_CACHE_REDIS_SCHEMA
        or not isinstance(payload.get("records"), list)
    ):
        logger.warning("Ignoring invalid Dify response cache payload key=%s", key)
        return None
    try:
        return [
            DifyExternalKnowledgeRecord.model_validate(record).model_dump(mode="json") for record in payload["records"]
        ]
    except ValidationError:
        logger.warning("Ignoring invalid Dify response cache records key=%s", key)
        return None


async def get_or_compute_response(
    *,
    key: str | None,
    compute: Callable[[], Awaitable[list[dict[str, Any]]]],
    policy: ResponseCachePolicy,
) -> DifyCacheResult:
    local_leader = False
    lease = None
    lease_task = None
    error: Exception | None = None
    timings: dict[str, float] = {}
    try:
        if key is not None:
            cached = await _cached_dify_records_for_key(
                key,
                response_cache_enabled=policy.response_cache_enabled,
                ttl_sec=policy.ttl_sec,
                max_entries=policy.max_entries,
            )
            if cached is not None:
                return DifyCacheResult(records=cached, source="cache_hit", timings_ms=timings)
        if key is not None and policy.singleflight_enabled:
            wait_started = time.perf_counter()
            local_leader, shared_payload = await _acquire_or_wait_for_inflight_response(key)
            if not local_leader:
                timings["singleflight_wait_ms"] = round((time.perf_counter() - wait_started) * 1000, 2)
                payload = cast(dict[str, Any], shared_payload)
                return DifyCacheResult(
                    records=[dict(record) for record in payload["records"]],
                    source="singleflight_hit",
                    timings_ms=timings,
                )
            if policy.response_cache_enabled:
                cached = await _cached_dify_records_for_key(
                    key, response_cache_enabled=True, ttl_sec=policy.ttl_sec, max_entries=policy.max_entries
                )
                if cached is not None:
                    resolve_inflight_response(key, {"records": cached})
                    return DifyCacheResult(records=cached, source="cache_hit", timings_ms=timings)
            wait_started = time.perf_counter()
            distributed_leader, records, lease = await _acquire_or_wait_for_distributed_dify_response(
                key, response_cache_enabled=policy.response_cache_enabled, response_cache_ttl_sec=policy.ttl_sec
            )
            timings["distributed_singleflight_wait_ms"] = round((time.perf_counter() - wait_started) * 1000, 2)
            if not distributed_leader:
                records = [dict(record) for record in cast(list[dict[str, Any]], records)]
                if policy.response_cache_enabled:
                    _dify_response_cache.set(key, records, ttl_sec=policy.ttl_sec, max_entries=policy.max_entries)
                resolve_inflight_response(key, {"records": records})
                return DifyCacheResult(records=records, source="distributed_cache_hit", timings_ms=timings)
            if lease is not None:
                lease_task = asyncio.create_task(
                    _maintain_best_effort_dify_lease(lease, ttl_sec=_dify_singleflight_lease_ttl_sec(policy.ttl_sec))
                )
        records = await compute()
        if local_leader:
            resolve_inflight_response(key, {"records": records})
        if key is not None and policy.response_cache_enabled:
            _dify_response_cache.set(key, records, ttl_sec=policy.ttl_sec, max_entries=policy.max_entries)
            await _set_dify_response_cache_redis_payload(key, records, ttl_sec=policy.ttl_sec)
        if key is not None and lease is not None and not policy.response_cache_enabled:
            await _set_dify_response_cache_redis_payload(
                _dify_singleflight_result_key(key), records, ttl_sec=_DIFY_RESPONSE_SINGLEFLIGHT_RESULT_TTL_SEC
            )
        return DifyCacheResult(records=records, source="computed", timings_ms=timings)
    except asyncio.CancelledError:
        error = InflightResponseLeaderCancelledError("singleflight leader request cancelled")
        raise
    except Exception as exc:
        error = exc
        raise
    finally:
        try:
            await _cleanup_distributed_dify_response_lease(lease_task, lease)
        finally:
            if local_leader and error is not None:
                reject_inflight_response(key, error)


logger = get_logger(__name__)


@dataclass(frozen=True)
class _DifyResponseCacheEntry:
    created_at_monotonic: float
    records: tuple[dict[str, Any], ...]


class _DifyResponseCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, _DifyResponseCacheEntry]" = OrderedDict()

    def _purge_expired_locked(self, *, now: float, ttl_sec: int) -> None:
        if ttl_sec <= 0 or not self._entries:
            return
        expired = [
            key for key, entry in self._entries.items() if now - float(entry.created_at_monotonic) > float(ttl_sec)
        ]
        for key in expired:
            self._entries.pop(key, None)

    def get(self, key: str, *, ttl_sec: int) -> list[dict[str, Any]] | None:
        if not key or ttl_sec <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now=now, ttl_sec=ttl_sec)
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key, last=True)
            return [dict(record) for record in entry.records]

    def set(self, key: str, records: list[dict[str, Any]], *, ttl_sec: int, max_entries: int) -> None:
        if not key or ttl_sec <= 0 or max_entries <= 0:
            return
        snapshot = tuple(dict(record) for record in records)
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now=now, ttl_sec=ttl_sec)
            self._entries[key] = _DifyResponseCacheEntry(created_at_monotonic=now, records=snapshot)
            self._entries.move_to_end(key, last=True)
            while len(self._entries) > max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._entries)


_dify_response_cache = _DifyResponseCache()


_DIFY_RESPONSE_CACHE_REDIS_SCHEMA = "mimirq.dify_external_response_cache.redis.v1"


_DIFY_RESPONSE_SINGLEFLIGHT_LEASE_SUFFIX = ":lease"


_DIFY_RESPONSE_SINGLEFLIGHT_RESULT_SUFFIX = ":transient_result"


_DIFY_RESPONSE_SINGLEFLIGHT_RESULT_TTL_SEC = 10


_DIFY_RESPONSE_SINGLEFLIGHT_LEASE_POLL_INITIAL_SEC = 0.05


_DIFY_RESPONSE_SINGLEFLIGHT_LEASE_POLL_MAX_SEC = 0.25


_DIFY_WARMUP_LEASE_KEY = "dify:warmup:lease"


def _dify_singleflight_wait_timeout_sec() -> float:
    return max(
        1e-3,
        float(settings.DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC or 0.0),
    )


def _clear_dify_response_cache() -> None:
    _dify_response_cache.clear()


async def _acquire_or_wait_for_inflight_response(
    key: str,
) -> tuple[bool, dict[str, Any] | None]:
    loop = asyncio.get_running_loop()
    wait_timeout_sec = _dify_singleflight_wait_timeout_sec()
    deadline = loop.time() + wait_timeout_sec
    while True:
        leader, future = await acquire_inflight_response(key)
        if leader:
            return True, None
        try:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise RetrievalAdmissionTimeoutError(wait_timeout_sec)
            done, _pending = await asyncio.wait(
                {future},
                timeout=max(1e-3, remaining),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise RetrievalAdmissionTimeoutError(wait_timeout_sec)
            return False, future.result()
        except InflightResponseLeaderCancelledError:
            continue


@dataclass(frozen=True)
class _DifyDistributedLease:
    lease_key: str
    owner: str


async def _set_dify_response_cache_redis_payload(
    key: str,
    records: list[dict[str, Any]],
    *,
    ttl_sec: int,
) -> bool:
    max_value_bytes = max(0, settings.CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES)
    return await set_best_effort_json_cache_value(
        key,
        {
            "schema": _DIFY_RESPONSE_CACHE_REDIS_SCHEMA,
            "records": [dict(record) for record in records],
        },
        ttl_sec=ttl_sec,
        max_value_bytes=max_value_bytes,
    )


def _dify_singleflight_result_key(key: str) -> str:
    return f"{key}{_DIFY_RESPONSE_SINGLEFLIGHT_RESULT_SUFFIX}"


async def _dify_distributed_singleflight_payload(
    key: str,
    *,
    response_cache_enabled: bool,
) -> list[dict[str, Any]] | None:
    if response_cache_enabled:
        cached = await _dify_response_cache_redis_payload(key)
        if cached is not None:
            return cached
    return await _dify_response_cache_redis_payload(_dify_singleflight_result_key(key))


def _dify_singleflight_lease_ttl_sec(response_cache_ttl_sec: int) -> int:
    warmup_timeout_sec = 60
    with contextlib.suppress(Exception):
        warmup_timeout_sec = max(
            60,
            min(300, int(float(settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC or 60.0))),
        )
    response_ttl_sec = max(60, int(response_cache_ttl_sec or 0))
    return max(60, min(300, max(response_ttl_sec, warmup_timeout_sec)))


async def _acquire_or_wait_for_distributed_dify_response(
    key: str,
    *,
    response_cache_enabled: bool,
    response_cache_ttl_sec: int,
) -> tuple[bool, list[dict[str, Any]] | None, _DifyDistributedLease | None]:
    if not key:
        return True, None, None

    lease_key = f"{key}{_DIFY_RESPONSE_SINGLEFLIGHT_LEASE_SUFFIX}"
    owner = uuid.uuid4().hex
    lease_ttl_sec = _dify_singleflight_lease_ttl_sec(response_cache_ttl_sec)
    poll_delay = _DIFY_RESPONSE_SINGLEFLIGHT_LEASE_POLL_INITIAL_SEC
    wait_timeout_sec = _dify_singleflight_wait_timeout_sec()
    deadline = time.monotonic() + wait_timeout_sec

    while True:
        cached = await _dify_distributed_singleflight_payload(
            key,
            response_cache_enabled=response_cache_enabled,
        )
        if cached is not None:
            return False, cached, None

        acquired = await try_acquire_best_effort_redis_lease(
            lease_key,
            value=owner,
            ttl_sec=lease_ttl_sec,
        )
        if acquired is None:
            return True, None, None
        if acquired:
            return True, None, _DifyDistributedLease(lease_key=lease_key, owner=owner)

        if time.monotonic() >= deadline:
            logger.warning(
                "Dify distributed singleflight timed out waiting for lease payload: %s (timeout=%.2fs)",
                key,
                wait_timeout_sec,
            )
            raise RetrievalAdmissionTimeoutError(wait_timeout_sec)

        await asyncio.sleep(poll_delay)
        poll_delay = min(_DIFY_RESPONSE_SINGLEFLIGHT_LEASE_POLL_MAX_SEC, poll_delay * 1.5)


async def _release_distributed_dify_response_lease(lease: _DifyDistributedLease | None) -> None:
    if lease is None:
        return
    await release_best_effort_redis_lease(lease.lease_key, value=lease.owner)


async def _cleanup_distributed_dify_response_lease(
    lease_task: asyncio.Task[Any] | None,
    lease: _DifyDistributedLease | None,
) -> None:
    if lease_task is not None:
        lease_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await lease_task
    await _release_distributed_dify_response_lease(lease)


async def _maintain_best_effort_dify_lease(
    lease: _DifyDistributedLease | None,
    *,
    ttl_sec: int,
) -> None:
    if lease is None or ttl_sec <= 0:
        return
    renew_interval_sec = max(5.0, min(float(ttl_sec) / 3.0, 30.0))
    while True:
        await asyncio.sleep(renew_interval_sec)
        renewed = await extend_best_effort_redis_lease(
            lease.lease_key,
            value=lease.owner,
            ttl_sec=ttl_sec,
        )
        if renewed is False:
            return


def _dify_warmup_lease_ttl_sec(*, knowledge_count: int, timeout_sec: float) -> int:
    per_item_timeout_sec = max(1, int(timeout_sec or 0))
    estimated_total_sec = max(60, per_item_timeout_sec * max(1, int(knowledge_count)) + 30)
    return min(1800, estimated_total_sec)


async def _acquire_dify_warmup_lease(
    *,
    knowledge_count: int,
    timeout_sec: float,
) -> tuple[_DifyDistributedLease | None, int] | tuple[None, None]:
    lease_ttl_sec = _dify_warmup_lease_ttl_sec(
        knowledge_count=knowledge_count,
        timeout_sec=timeout_sec,
    )
    owner = uuid.uuid4().hex
    acquired = await try_acquire_best_effort_redis_lease(
        _DIFY_WARMUP_LEASE_KEY,
        value=owner,
        ttl_sec=lease_ttl_sec,
    )
    if acquired is None:
        return None, None
    if not acquired:
        return None, lease_ttl_sec
    return _DifyDistributedLease(lease_key=_DIFY_WARMUP_LEASE_KEY, owner=owner), lease_ttl_sec


def _dify_response_cache_settings_signature() -> dict[str, Any]:
    return {
        "internal_top_k_min": (settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN or 20),
        "internal_top_k_multiplier": (settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER or 4),
        "internal_top_k_max": (settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX or 50),
        "primary_scope_enabled": settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED,
        "primary_min_records": (settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS or 1),
        "primary_min_top_score": float(settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE or 0.0),
        "compact_enabled": settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED,
        "compact_min_top_score": float(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE or 0.0),
        "compact_relative_score_floor": float(settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR or 0.0),
        "compact_min_records": (settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS or 1),
        "fast_candidate_top_k_max": (settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX or 3),
        "fast_response_top_k_max": (settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX or 2),
        "fast_content_max_chars": (settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS or 1400),
        "fast_total_content_max_chars": (settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS or 2200),
        "enable_reranker": settings.ENABLE_RERANKER,
        "dify_reranker_enabled": settings.DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED,
        "reranker_provider": settings.RERANKER_PROVIDER,
        "reranker_model": str(settings.RERANKER_MODEL or ""),
        "reranker_top_n": (settings.RERANKER_TOP_N or 20),
        "metadata_anchor_enabled": settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED,
        "metadata_anchor_preflight_enabled": settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED,
        "metadata_anchor_max_scan": (settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_SCAN or 80),
        "metadata_anchor_total_budget_ms": settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS,
        "metadata_anchor_text_scan_enabled": settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_TEXT_SCAN_ENABLED,
        "metadata_anchor_extend_sibling_policy_scope_enabled": settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED,
        "metadata_anchor_extended_scope_max_datasets": settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTENDED_SCOPE_MAX_DATASETS,
        "mixed_intent_supplement_enabled": settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED,
        "mixed_intent_max_subqueries": (settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES or 4),
        "mixed_intent_subquery_top_k": settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUBQUERY_TOP_K,
        "kg_on_demand_enabled": settings.DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED,
        "kg_query_expansion_default": settings.DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED,
        "kg_chunk_injection_default": settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED,
        "kg_chunk_injection_max_chunks_default": (settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS or 3),
        "kg_chunk_boost_default": settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED,
        "kg_chunk_boost_weight_default": float(settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT or 0.0),
        "kg_chunk_boost_max_promoted_default": (settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED or 2),
    }


def _build_dify_response_cache_key(
    *,
    actor: _DifyActor,
    knowledge_id: str,
    query: str,
    retrieval_setting: DifyRetrievalSetting,
    metadata_condition: dict[str, Any] | None,
    scope_plan: DatasetScopePlan,
    top_k: int,
    candidate_top_k: int,
    score_threshold: float,
    policy_plugin_refs: tuple[str, ...],
    corpus_token: str,
) -> str:
    signature = {
        "schema": "mimirq.dify_external_response_cache.v1",
        "tenant_id": str(actor.tenant_id),
        "account_id": str(actor.account_id or ""),
        "knowledge_id": str(knowledge_id or "").strip(),
        "query": str(query or "").strip(),
        "retrieval_setting": retrieval_setting.model_dump(mode="json"),
        "metadata_condition": metadata_condition or None,
        "dataset_ids": [str(item) for item in scope_plan.dataset_ids],
        "primary_dataset_ids": [str(item) for item in scope_plan.primary_dataset_ids],
        "expansion_dataset_ids": [str(item) for item in scope_plan.expansion_dataset_ids],
        "strict_scope": bool(scope_plan.strict_scope),
        "matched_terms": list(scope_plan.matched_terms),
        "top_k": int(top_k),
        "candidate_top_k": int(candidate_top_k),
        "score_threshold": float(score_threshold),
        "policy_plugin_refs": list(policy_plugin_refs),
        "corpus_token": str(corpus_token or ""),
        "settings": _dify_response_cache_settings_signature(),
    }
    raw = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()
    return f"difyext:{actor.tenant_id}:{digest[:32]}"


async def _cached_dify_records_for_key(
    cache_key: str,
    *,
    response_cache_enabled: bool,
    ttl_sec: int,
    max_entries: int,
) -> list[dict[str, Any]] | None:
    if not response_cache_enabled:
        return None
    cached_records = _dify_response_cache.get(cache_key, ttl_sec=ttl_sec)
    if cached_records is None:
        cached_records = await _dify_response_cache_redis_payload(cache_key)
        if cached_records is not None:
            _dify_response_cache.set(
                cache_key,
                cached_records,
                ttl_sec=ttl_sec,
                max_entries=max_entries,
            )
    return cached_records
