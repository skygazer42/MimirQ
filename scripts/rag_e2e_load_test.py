#!/usr/bin/env python3

import argparse
import asyncio
import json
import math
import os
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


def percentile_ms(values_ms: list[int], p: int) -> int:
    """
    Nearest-rank percentile.

    - p is clamped to [0, 100]
    - empty input returns 0
    """
    if not values_ms:
        return 0
    pp = int(p)
    pp = max(0, min(100, pp))
    vals = sorted(int(v or 0) for v in values_ms)
    if pp <= 0:
        return int(vals[0] or 0)
    if pp >= 100:
        return int(vals[-1] or 0)
    n = len(vals)
    rank = int(math.ceil((pp / 100.0) * n))
    idx = max(0, min(n - 1, rank - 1))
    return int(vals[idx] or 0)


def summarize_latencies_ms(values_ms: list[int]) -> dict[str, Any]:
    vals = [int(v or 0) for v in (values_ms or [])]
    if not vals:
        return {
            "count": 0,
            "min_ms": 0,
            "max_ms": 0,
            "mean_ms": 0.0,
            "p50_ms": 0,
            "p90_ms": 0,
            "p95_ms": 0,
            "p99_ms": 0,
        }

    sorted_vals = sorted(vals)
    total = float(sum(sorted_vals))
    count = int(len(sorted_vals))
    mean_ms = total / float(count)

    return {
        "count": count,
        "min_ms": int(sorted_vals[0]),
        "max_ms": int(sorted_vals[-1]),
        "mean_ms": float(mean_ms),
        "p50_ms": percentile_ms(sorted_vals, 50),
        "p90_ms": percentile_ms(sorted_vals, 90),
        "p95_ms": percentile_ms(sorted_vals, 95),
        "p99_ms": percentile_ms(sorted_vals, 99),
    }


def throughput_per_sec(*, count: int, elapsed_ms: int) -> float:
    if int(elapsed_ms or 0) <= 0:
        return 0.0
    return float(int(count or 0)) / (float(elapsed_ms) / 1000.0)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _p95_ms(section: dict[str, Any], key: str) -> int:
    raw = section.get(key)
    if not isinstance(raw, dict):
        return 0
    return _as_int(raw.get("p95_ms"))


def evaluate_load_gate(
    result: dict[str, Any],
    *,
    max_ingest_p95_ms: int = 0,
    max_retrieve_p95_ms: int = 0,
    max_chat_p95_ms: int = 0,
) -> dict[str, Any]:
    """Turn the load-test report into a deterministic pass/fail gate."""
    ingest = result.get("ingest") if isinstance(result.get("ingest"), dict) else {}
    retrieve = result.get("retrieve") if isinstance(result.get("retrieve"), dict) else {}
    chat = result.get("chat") if isinstance(result.get("chat"), dict) else {}
    failures: list[str] = []

    expected_ingest = _as_int(ingest.get("requested"))
    completed_ingest = _as_int(ingest.get("completed"))
    ingest_errors = _as_int(ingest.get("errors"))
    if expected_ingest > 0 and completed_ingest < expected_ingest:
        failures.append(f"ingest_completed {completed_ingest} < requested {expected_ingest}")
    if ingest_errors > 0:
        failures.append(f"ingest_errors {ingest_errors} > 0")

    expected_retrieve = _as_int(retrieve.get("requested"))
    ok_retrieve = _as_int(retrieve.get("ok"))
    retrieve_errors = _as_int(retrieve.get("errors"))
    if expected_retrieve > 0 and ok_retrieve < expected_retrieve:
        failures.append(f"retrieve_ok {ok_retrieve} < requested {expected_retrieve}")
    if retrieve_errors > 0:
        failures.append(f"retrieve_errors {retrieve_errors} > 0")

    expected_chat = _as_int(chat.get("requested"))
    ok_chat = _as_int(chat.get("ok"))
    chat_errors = _as_int(chat.get("errors"))
    if expected_chat > 0 and ok_chat < expected_chat:
        failures.append(f"chat_ok {ok_chat} < requested {expected_chat}")
    if chat_errors > 0:
        failures.append(f"chat_errors {chat_errors} > 0")

    ingest_p95 = _p95_ms(ingest, "e2e_latency_ms")
    retrieve_p95 = _p95_ms(retrieve, "latency_ms")
    chat_p95 = _p95_ms(chat, "latency_ms")
    if max_ingest_p95_ms > 0 and ingest_p95 > max_ingest_p95_ms:
        failures.append(f"ingest_p95_ms {ingest_p95} > max {max_ingest_p95_ms}")
    if max_retrieve_p95_ms > 0 and retrieve_p95 > max_retrieve_p95_ms:
        failures.append(f"retrieve_p95_ms {retrieve_p95} > max {max_retrieve_p95_ms}")
    if max_chat_p95_ms > 0 and chat_p95 > max_chat_p95_ms:
        failures.append(f"chat_p95_ms {chat_p95} > max {max_chat_p95_ms}")

    return {
        "passed": not failures,
        "failures": failures,
        "thresholds": {
            "max_ingest_p95_ms": max_ingest_p95_ms,
            "max_retrieve_p95_ms": max_retrieve_p95_ms,
            "max_chat_p95_ms": max_chat_p95_ms,
        },
        "observed": {
            "ingest_p95_ms": ingest_p95,
            "retrieve_p95_ms": retrieve_p95,
            "chat_p95_ms": chat_p95,
        },
    }


def evaluate_concurrency_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    min_retrieve_throughput_ratio: float = 1.0,
    min_chat_throughput_ratio: float = 1.0,
) -> dict[str, Any]:
    """Verify that a concurrent run improves batch throughput over a serial run."""
    failures: list[str] = []
    observed: dict[str, Any] = {}

    for label, report in (("baseline", baseline), ("candidate", candidate)):
        gate = evaluate_load_gate(report)
        failures.extend(f"{label}: {failure}" for failure in gate["failures"])

    thresholds = {
        "retrieve": max(0.0, float(min_retrieve_throughput_ratio)),
        "chat": max(0.0, float(min_chat_throughput_ratio)),
    }
    for phase in ("retrieve", "chat"):
        base = baseline.get(phase) if isinstance(baseline.get(phase), dict) else {}
        current = candidate.get(phase) if isinstance(candidate.get(phase), dict) else {}
        base_requested = _as_int(base.get("requested"))
        current_requested = _as_int(current.get("requested"))
        if base_requested == current_requested == 0:
            continue
        if base_requested != current_requested:
            failures.append(f"{phase} requested {current_requested} != baseline {base_requested}")

        base_concurrency = _as_int(base.get("concurrency"))
        current_concurrency = _as_int(current.get("concurrency"))
        if base_concurrency != 1:
            failures.append(f"{phase} baseline concurrency {base_concurrency} != 1")
        if current_concurrency <= base_concurrency:
            failures.append(f"{phase} candidate concurrency {current_concurrency} <= baseline {base_concurrency}")
        if not bool(current.get("client_overlap_observed")):
            failures.append(f"{phase} candidate did not overlap requests")

        base_throughput = _as_float(base.get("throughput_rps"))
        current_throughput = _as_float(current.get("throughput_rps"))
        throughput_ratio = current_throughput / base_throughput if base_throughput > 0.0 else 0.0
        min_ratio = thresholds[phase]
        if throughput_ratio < min_ratio:
            failures.append(f"{phase} throughput_ratio {round(throughput_ratio, 6)} < min {min_ratio}")

        observed[phase] = {
            "baseline_concurrency": base_concurrency,
            "candidate_concurrency": current_concurrency,
            "baseline_throughput_rps": base_throughput,
            "candidate_throughput_rps": current_throughput,
            "throughput_ratio": round(throughput_ratio, 6),
            "baseline_p95_ms": _p95_ms(base, "latency_ms"),
            "candidate_p95_ms": _p95_ms(current, "latency_ms"),
        }

    return {
        "passed": not failures,
        "failures": failures,
        "thresholds": {
            "min_retrieve_throughput_ratio": thresholds["retrieve"],
            "min_chat_throughput_ratio": thresholds["chat"],
        },
        "observed": observed,
    }


def _join(base_url: str, path: str) -> str:
    b = (base_url or "").rstrip("/")
    p = (path or "").lstrip("/")
    return f"{b}/{p}" if p else b


def _build_headers(*, tenant_id: str, user_id: str, bearer: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if tenant_id:
        headers["X-Tenant-ID"] = str(tenant_id)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    elif user_id:
        headers["X-User-ID"] = str(user_id)
    return headers


@dataclass(frozen=True)
class E2ELoadTestConfig:
    base_url: str
    tenant_id: str
    user_id: str
    bearer: str

    file_bytes: bytes
    filename: str
    request_base_urls: tuple[str, ...] = ()
    parser_backend: str = "auto"

    dataset_id: str | None = None
    dataset_name: str = ""

    ingest_count: int = 1
    ingest_concurrency: int = 1
    poll_interval_sec: float = 2.0
    ingest_timeout_sec: float = 600.0

    retrieve_requests: int = 0
    retrieve_concurrency: int = 1
    query: str = "hello"
    retrieval_mode: str = "hybrid"

    chat_requests: int = 0
    chat_concurrency: int = 1
    message: str = "hello"
    enable_reranker: bool = True

    doc_sample_size: int = 5


@dataclass
class IngestPhaseResult:
    upload_lat_ms: list[int]
    ingest_e2e_ms: list[int]
    uploaded_doc_ids: list[str]
    completed_doc_ids: list[str]
    errors: int = 0


@dataclass
class RequestPhaseResult:
    latencies_ms: list[int]
    errors: int = 0
    client_peak_in_flight: int = 0


def _request_base_url(base_url: str, request_base_urls: tuple[str, ...], index: int) -> str:
    if not request_base_urls:
        return base_url
    return request_base_urls[index % len(request_base_urls)]


def _normalize_request_base_urls(request_base_urls: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(item or "").rstrip("/") for item in request_base_urls if str(item or "").strip())


def _build_upload_request(
    cfg: E2ELoadTestConfig,
    *,
    index: int,
    dataset_id: str,
) -> tuple[dict[str, tuple[str, bytes, str]], dict[str, str]]:
    files = {
        "file": (
            cfg.filename or f"loadtest-{index}.bin",
            cfg.file_bytes or b"",
            "application/octet-stream",
        )
    }
    data = {"dataset_id": dataset_id}
    if cfg.parser_backend:
        data["parser_backend"] = str(cfg.parser_backend)
    return files, data


async def _create_dataset_if_needed(
    cfg: E2ELoadTestConfig,
    *,
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
) -> str:
    if cfg.dataset_id:
        return cfg.dataset_id

    dataset_name = cfg.dataset_name or f"loadtest-{uuid.uuid4().hex[:8]}"
    response = await client.post(
        _join(base_url, "datasets/"),
        headers=headers,
        json={"name": dataset_name, "description": "e2e load test"},
    )
    response.raise_for_status()
    dataset_id = str((response.json() or {}).get("id") or "")
    if not dataset_id:
        raise ValueError("dataset create returned no id")
    return dataset_id


async def _wait_for_document_completion(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    doc_id: str,
    deadline: float,
    poll_interval_sec: float,
) -> bool:
    while True:
        try:
            response = await client.get(
                _join(base_url, f"documents/{doc_id}/status"),
                headers=headers,
            )
        except Exception:
            return False
        if response.status_code < 200 or response.status_code >= 300:
            return False
        try:
            payload = response.json() or {}
        except Exception:
            payload = {}
        status = str(payload.get("status") or "")
        if status == "completed":
            return True
        if status == "failed" or time.perf_counter() >= deadline:
            return False
        await asyncio.sleep(max(0.0, poll_interval_sec))


async def _run_ingest_phase(
    cfg: E2ELoadTestConfig,
    *,
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    dataset_id: str,
) -> tuple[IngestPhaseResult, int]:
    result = IngestPhaseResult(
        upload_lat_ms=[],
        ingest_e2e_ms=[],
        uploaded_doc_ids=[],
        completed_doc_ids=[],
    )
    ingest_sem = asyncio.Semaphore(max(1, int(cfg.ingest_concurrency or 1)))

    async def _upload_and_wait(index: int) -> None:
        async with ingest_sem:
            started_at = time.perf_counter()
            files, data = _build_upload_request(cfg, index=index, dataset_id=dataset_id)
            try:
                response = await client.post(
                    _join(base_url, "documents/upload"),
                    headers=headers,
                    files=files,
                    data=data,
                )
            except Exception:
                result.errors += 1
                return

            upload_ms = int((time.perf_counter() - started_at) * 1000)
            if response.status_code < 200 or response.status_code >= 300:
                result.errors += 1
                return

            try:
                doc_id = str((response.json() or {}).get("id") or "")
            except Exception:
                doc_id = ""
            if not doc_id:
                result.errors += 1
                return

            result.uploaded_doc_ids.append(doc_id)
            result.upload_lat_ms.append(upload_ms)
            completed = await _wait_for_document_completion(
                client=client,
                base_url=base_url,
                headers=headers,
                doc_id=doc_id,
                deadline=time.perf_counter() + float(cfg.ingest_timeout_sec or 0.0),
                poll_interval_sec=max(0.0, float(cfg.poll_interval_sec or 0.0)),
            )
            if not completed:
                result.errors += 1
                return

            result.completed_doc_ids.append(doc_id)
            result.ingest_e2e_ms.append(int((time.perf_counter() - started_at) * 1000))

    started_at = time.perf_counter()
    await asyncio.gather(*[_upload_and_wait(i) for i in range(int(cfg.ingest_count or 0))])
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    return result, elapsed_ms


async def _run_request_phase(
    *,
    client: httpx.AsyncClient,
    headers: dict[str, str],
    base_url: str,
    request_base_urls: tuple[str, ...],
    count: int,
    concurrency: int,
    path: str,
    request_id_prefix: str,
    payload_builder: Callable[[int], dict[str, Any]],
) -> tuple[RequestPhaseResult, int]:
    result = RequestPhaseResult(latencies_ms=[])
    in_flight = 0
    sem = asyncio.Semaphore(max(1, int(concurrency or 1)))

    async def _run_once(index: int) -> None:
        nonlocal in_flight
        async with sem:
            in_flight += 1
            result.client_peak_in_flight = max(
                result.client_peak_in_flight,
                in_flight,
            )
            started_at = time.perf_counter()
            try:
                request_base_url = _request_base_url(
                    base_url,
                    request_base_urls,
                    index,
                )
                response = await client.post(
                    _join(request_base_url, path),
                    headers={
                        **headers,
                        "X-Request-ID": f"load-{request_id_prefix}-{index}",
                    },
                    json=payload_builder(index),
                )
            except Exception:
                result.errors += 1
                return
            finally:
                in_flight -= 1

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            if response.status_code < 200 or response.status_code >= 300:
                result.errors += 1
                return
            result.latencies_ms.append(elapsed_ms)

    started_at = time.perf_counter()
    await asyncio.gather(*[_run_once(i) for i in range(int(count or 0))])
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    return result, elapsed_ms


async def run_e2e_load_test(cfg: E2ELoadTestConfig, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    headers = _build_headers(tenant_id=cfg.tenant_id, user_id=cfg.user_id, bearer=cfg.bearer)
    if not headers.get("X-User-ID") and not headers.get("Authorization"):
        raise ValueError("missing auth headers (set user_id or bearer)")

    close_client = False
    if client is None:
        close_client = True
        client = httpx.AsyncClient(timeout=httpx.Timeout(60.0), headers=headers, trust_env=False)

    try:
        base_url = str(cfg.base_url or "").rstrip("/")
        request_base_urls = _normalize_request_base_urls(cfg.request_base_urls)
        run_id = uuid.uuid4().hex
        query_nonce = run_id[:6]
        dataset_id = await _create_dataset_if_needed(
            cfg,
            client=client,
            base_url=base_url,
            headers=headers,
        )
        ingest_result, ingest_elapsed_ms = await _run_ingest_phase(
            cfg,
            client=client,
            base_url=base_url,
            headers=headers,
            dataset_id=dataset_id,
        )

        doc_ids_for_queries = list(ingest_result.completed_doc_ids)
        if cfg.doc_sample_size and len(doc_ids_for_queries) > int(cfg.doc_sample_size):
            doc_ids_for_queries = doc_ids_for_queries[: int(cfg.doc_sample_size)]
        retrieve_result, retrieve_elapsed_ms = await _run_request_phase(
            client=client,
            headers=headers,
            base_url=base_url,
            request_base_urls=request_base_urls,
            count=int(cfg.retrieve_requests or 0),
            concurrency=int(cfg.retrieve_concurrency or 1),
            path="rag/retrieve-preview",
            request_id_prefix=f"{run_id}-retrieve",
            payload_builder=lambda i: {
                "query": f"{str(cfg.query or 'hello')} [load:{query_nonce}:r:{i}]",
                "dataset_id": dataset_id,
                "document_ids": doc_ids_for_queries,
                "rag_config": {
                    "top_k": 10,
                    "retrieval_mode": str(cfg.retrieval_mode or "hybrid"),
                    "enable_multi_query": False,
                    "enable_reranker": bool(cfg.enable_reranker),
                    "use_graph": False,
                },
            },
        )
        chat_result, chat_elapsed_ms = await _run_request_phase(
            client=client,
            headers=headers,
            base_url=base_url,
            request_base_urls=request_base_urls,
            count=int(cfg.chat_requests or 0),
            concurrency=int(cfg.chat_concurrency or 1),
            path="chat",
            request_id_prefix=f"{run_id}-chat",
            payload_builder=lambda i: {
                "message": f"{str(cfg.message or 'hello')} [load:{query_nonce}:c:{i}]",
                "dataset_id": dataset_id,
                "document_ids": doc_ids_for_queries,
                "structured_output": True,
                "structured_preset": "summary",
                "rag_config": {
                    "top_k": 10,
                    "enable_multi_query": False,
                    "enable_reranker": bool(cfg.enable_reranker),
                    "use_graph": False,
                },
            },
        )

        return {
            "dataset_id": dataset_id,
            "document_ids": ingest_result.completed_doc_ids,
            "ingest": {
                "requested": int(cfg.ingest_count or 0),
                "uploaded": len(ingest_result.uploaded_doc_ids),
                "completed": len(ingest_result.completed_doc_ids),
                "errors": int(ingest_result.errors),
                "elapsed_ms": int(ingest_elapsed_ms),
                "throughput_docs_per_sec": throughput_per_sec(
                    count=len(ingest_result.completed_doc_ids),
                    elapsed_ms=ingest_elapsed_ms,
                ),
                "upload_latency_ms": summarize_latencies_ms(ingest_result.upload_lat_ms),
                "e2e_latency_ms": summarize_latencies_ms(ingest_result.ingest_e2e_ms),
            },
            "retrieve": {
                "requested": int(cfg.retrieve_requests or 0),
                "concurrency": max(1, int(cfg.retrieve_concurrency or 1)),
                "client_peak_in_flight": retrieve_result.client_peak_in_flight,
                "client_overlap_observed": retrieve_result.client_peak_in_flight > 1,
                "reranker_enabled": bool(cfg.enable_reranker),
                "ok": len(retrieve_result.latencies_ms),
                "errors": int(retrieve_result.errors),
                "elapsed_ms": int(retrieve_elapsed_ms),
                "throughput_rps": throughput_per_sec(
                    count=len(retrieve_result.latencies_ms),
                    elapsed_ms=retrieve_elapsed_ms,
                ),
                "latency_ms": summarize_latencies_ms(retrieve_result.latencies_ms),
            },
            "chat": {
                "requested": int(cfg.chat_requests or 0),
                "concurrency": max(1, int(cfg.chat_concurrency or 1)),
                "client_peak_in_flight": chat_result.client_peak_in_flight,
                "client_overlap_observed": chat_result.client_peak_in_flight > 1,
                "reranker_enabled": bool(cfg.enable_reranker),
                "ok": len(chat_result.latencies_ms),
                "errors": int(chat_result.errors),
                "elapsed_ms": int(chat_elapsed_ms),
                "throughput_rps": throughput_per_sec(
                    count=len(chat_result.latencies_ms),
                    elapsed_ms=chat_elapsed_ms,
                ),
                "latency_ms": summarize_latencies_ms(chat_result.latencies_ms),
            },
        }
    finally:
        if close_client and client is not None:
            await client.aclose()


def _default_base_url() -> str:
    base = (os.getenv("NEXT_PUBLIC_API_URL") or "http://localhost:8000").rstrip("/")
    if base.endswith("/api/v1"):
        return base
    return f"{base}/api/v1"


def _build_parser(default_file: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="E2E RAG load test: ingest -> retrieve -> answer (throughput + P95).")
    parser.add_argument(
        "--base-url",
        default=_default_base_url(),
        help="API base url incl /api/v1 (default: %(default)s)",
    )
    parser.add_argument(
        "--tenant-id",
        default=os.getenv("NEXT_PUBLIC_TENANT_ID") or "",
        help="X-Tenant-ID header (optional)",
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("NEXT_PUBLIC_USER_ID") or "",
        help="X-User-ID header (AUTH_MODE=header)",
    )
    parser.add_argument("--bearer", default="", help="Bearer token (AUTH_MODE=jwt)")
    parser.add_argument("--file", default=str(default_file), help="File path to upload for ingestion")
    parser.add_argument(
        "--filename",
        default="",
        help="Override uploaded filename (default: basename of --file)",
    )
    parser.add_argument(
        "--parser-backend",
        default="auto",
        help="Parser backend (default: %(default)s)",
    )
    parser.add_argument(
        "--dataset-id",
        default="",
        help="Optional dataset id to reuse (skips dataset creation)",
    )
    parser.add_argument(
        "--dataset-name",
        default="",
        help="Dataset name when creating a new one (optional)",
    )
    parser.add_argument(
        "--ingest-count",
        type=int,
        default=1,
        help="How many documents to ingest (default: %(default)s)",
    )
    parser.add_argument(
        "--ingest-concurrency",
        type=int,
        default=1,
        help="Upload+poll concurrency (default: %(default)s)",
    )
    parser.add_argument(
        "--poll-interval-sec",
        type=float,
        default=2.0,
        help="Status polling interval seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--ingest-timeout-sec",
        type=float,
        default=600.0,
        help="Per-document ingest timeout seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--retrieve-requests",
        type=int,
        default=20,
        help="Retrieve-preview requests (default: %(default)s)",
    )
    parser.add_argument(
        "--retrieve-concurrency",
        type=int,
        default=10,
        help="Retrieve-preview concurrency (default: %(default)s)",
    )
    parser.add_argument("--query", default="Smoke", help="Retrieve query (default: %(default)s)")
    parser.add_argument(
        "--chat-requests",
        type=int,
        default=10,
        help="Chat requests (default: %(default)s)",
    )
    parser.add_argument(
        "--chat-concurrency",
        type=int,
        default=5,
        help="Chat concurrency (default: %(default)s)",
    )
    parser.add_argument(
        "--message",
        default="Summarize this document.",
        help="Chat message (default: %(default)s)",
    )
    parser.add_argument(
        "--no-reranker",
        dest="enable_reranker",
        action="store_false",
        help="Disable reranking during retrieve/chat load",
    )
    parser.add_argument(
        "--doc-sample-size",
        type=int,
        default=5,
        help="Max document ids per request (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=60.0,
        help="HTTP timeout seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--max-ingest-p95-ms",
        type=int,
        default=0,
        help="Fail if ingest P95 exceeds this value; 0 disables",
    )
    parser.add_argument(
        "--max-retrieve-p95-ms",
        type=int,
        default=0,
        help="Fail if retrieve P95 exceeds this value; 0 disables",
    )
    parser.add_argument(
        "--max-chat-p95-ms",
        type=int,
        default=0,
        help="Fail if chat P95 exceeds this value; 0 disables",
    )
    parser.add_argument(
        "--baseline-report",
        default="",
        help="Serial load report to compare without running network calls",
    )
    parser.add_argument(
        "--candidate-report",
        default="",
        help="Concurrent load report to compare without running network calls",
    )
    parser.add_argument("--min-retrieve-throughput-ratio", type=float, default=1.0)
    parser.add_argument("--min-chat-throughput-ratio", type=float, default=1.0)
    parser.add_argument("--out", default="", help="Write JSON report to path (or directory)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate args and exit without network calls",
    )
    return parser


def _comparison_report_paths(args: argparse.Namespace) -> tuple[str, str] | None:
    baseline_report = str(args.baseline_report or "").strip()
    candidate_report = str(args.candidate_report or "").strip()
    if not baseline_report and not candidate_report:
        return None
    if bool(baseline_report) != bool(candidate_report):
        raise ValueError("--baseline-report and --candidate-report are required together")
    return baseline_report, candidate_report


def _read_report_payload(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json_output(out_path: Path, payload: dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _handle_comparison_mode(args: argparse.Namespace) -> int | None:
    try:
        report_paths = _comparison_report_paths(args)
    except Exception as exc:
        print(f"[rag-e2e-loadtest] ERROR: {exc}", file=sys.stderr)
        return 2
    if report_paths is None:
        return None

    baseline_report, candidate_report = report_paths
    try:
        baseline = _read_report_payload(baseline_report)
        candidate = _read_report_payload(candidate_report)
        if not isinstance(baseline, dict) or not isinstance(candidate, dict):
            raise ValueError("load report roots must be JSON objects")
    except Exception as exc:
        print(f"[rag-e2e-loadtest] ERROR: {exc}", file=sys.stderr)
        return 2
    comparison = evaluate_concurrency_gate(
        baseline,
        candidate,
        min_retrieve_throughput_ratio=float(args.min_retrieve_throughput_ratio),
        min_chat_throughput_ratio=float(args.min_chat_throughput_ratio),
    )
    comparison["schema"] = "mimirq.rag_concurrency_gate.v1"
    comparison["baseline_report"] = baseline_report
    comparison["candidate_report"] = candidate_report
    if args.out:
        out_path = Path(str(args.out))
        _write_json_output(out_path, comparison)
        print(f"[rag-e2e-loadtest] wrote: {out_path}")
    for failure in comparison["failures"]:
        print(f"[rag-e2e-loadtest] FAIL: {failure}", file=sys.stderr)
    print("[rag-e2e-loadtest] CONCURRENCY PASS" if comparison["passed"] else "[rag-e2e-loadtest] CONCURRENCY FAIL")
    return 0 if comparison["passed"] else 2


def _build_config_from_args(
    args: argparse.Namespace,
    *,
    file_bytes: bytes,
    filename: str,
) -> E2ELoadTestConfig:
    return E2ELoadTestConfig(
        base_url=str(args.base_url or "").rstrip("/"),
        tenant_id=str(args.tenant_id or ""),
        user_id=str(args.user_id or ""),
        bearer=str(args.bearer or ""),
        file_bytes=file_bytes,
        filename=filename,
        parser_backend=str(args.parser_backend or "auto"),
        dataset_id=str(args.dataset_id or "") or None,
        dataset_name=str(args.dataset_name or ""),
        ingest_count=int(args.ingest_count or 0),
        ingest_concurrency=int(args.ingest_concurrency or 1),
        poll_interval_sec=float(args.poll_interval_sec or 0.0),
        ingest_timeout_sec=float(args.ingest_timeout_sec or 0.0),
        retrieve_requests=int(args.retrieve_requests or 0),
        retrieve_concurrency=int(args.retrieve_concurrency or 1),
        query=str(args.query or ""),
        chat_requests=int(args.chat_requests or 0),
        chat_concurrency=int(args.chat_concurrency or 1),
        message=str(args.message or ""),
        enable_reranker=bool(args.enable_reranker),
        doc_sample_size=int(args.doc_sample_size or 0),
    )


def _print_dry_run_summary(
    cfg: E2ELoadTestConfig,
    *,
    file_path: Path,
) -> None:
    print("[rag-e2e-loadtest] DryRun=ON (no network calls will be made)")
    print(f"[rag-e2e-loadtest] base_url={cfg.base_url}")
    print(f"[rag-e2e-loadtest] file={file_path} bytes={len(cfg.file_bytes)}")
    print(f"[rag-e2e-loadtest] ingest_count={cfg.ingest_count} ingest_concurrency={cfg.ingest_concurrency}")
    print(
        f"[rag-e2e-loadtest] retrieve_requests={cfg.retrieve_requests} retrieve_concurrency={cfg.retrieve_concurrency}"
    )
    print(f"[rag-e2e-loadtest] chat_requests={cfg.chat_requests} chat_concurrency={cfg.chat_concurrency}")


async def _run_with_client(
    cfg: E2ELoadTestConfig,
    *,
    timeout_sec: float,
) -> dict[str, Any]:
    max_conc = max(
        int(cfg.ingest_concurrency),
        int(cfg.retrieve_concurrency),
        int(cfg.chat_concurrency),
        1,
    )
    limits = httpx.Limits(
        max_connections=max_conc * 2,
        max_keepalive_connections=max_conc * 2,
    )
    timeout = httpx.Timeout(timeout_sec)
    async with httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        trust_env=False,
    ) as client:
        return await run_e2e_load_test(cfg, client=client)


def _print_result_summary(result: dict[str, Any]) -> None:
    ingest = result.get("ingest") or {}
    retrieve = result.get("retrieve") or {}
    chat = result.get("chat") or {}
    ingest_latency = ingest.get("e2e_latency_ms")
    retrieve_latency = retrieve.get("latency_ms")
    chat_latency = chat.get("latency_ms")
    ingest_p95 = (ingest_latency if isinstance(ingest_latency, dict) else {}).get("p95_ms", 0)
    retrieve_p95 = (retrieve_latency if isinstance(retrieve_latency, dict) else {}).get("p95_ms", 0)
    chat_p95 = (chat_latency if isinstance(chat_latency, dict) else {}).get("p95_ms", 0)

    print(
        f"[rag-e2e-loadtest] ingest: completed={ingest.get('completed')} "
        f"errors={ingest.get('errors')} "
        f"throughput={float(ingest.get('throughput_docs_per_sec') or 0.0):.2f}/s "
        f"p95={ingest_p95}ms"
    )
    print(
        f"[rag-e2e-loadtest] retrieve: ok={retrieve.get('ok')} "
        f"errors={retrieve.get('errors')} "
        f"throughput={float(retrieve.get('throughput_rps') or 0.0):.2f}/s "
        f"p95={retrieve_p95}ms "
        f"client_peak_in_flight={retrieve.get('client_peak_in_flight')}"
    )
    print(
        f"[rag-e2e-loadtest] chat: ok={chat.get('ok')} "
        f"errors={chat.get('errors')} "
        f"throughput={float(chat.get('throughput_rps') or 0.0):.2f}/s "
        f"p95={chat_p95}ms "
        f"client_peak_in_flight={chat.get('client_peak_in_flight')}"
    )


def _write_result_report(out_path: str, result: dict[str, Any]) -> None:
    outp = Path(out_path)
    if outp.exists() and outp.is_dir():
        outp = outp / f"rag-e2e-loadtest-{int(time.time())}.json"
    elif not outp.suffix:
        outp.mkdir(parents=True, exist_ok=True)
        outp = outp / f"rag-e2e-loadtest-{int(time.time())}.json"
    else:
        outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[rag-e2e-loadtest] wrote: {outp}")


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    default_file = repo_root / "README.md"
    args = _build_parser(default_file).parse_args(argv)

    comparison_exit = _handle_comparison_mode(args)
    if comparison_exit is not None:
        return comparison_exit

    file_path = Path(str(args.file))
    if not file_path.exists():
        print(f"[rag-e2e-loadtest] ERROR: file not found: {file_path}", file=sys.stderr)
        return 2

    file_bytes = file_path.read_bytes()
    filename = str(args.filename or file_path.name)

    cfg = _build_config_from_args(args, file_bytes=file_bytes, filename=filename)

    if args.dry_run:
        _print_dry_run_summary(cfg, file_path=file_path)
        return 0

    try:
        result = asyncio.run(_run_with_client(cfg, timeout_sec=float(args.timeout_sec)))
    except KeyboardInterrupt:
        print("[rag-e2e-loadtest] cancelled", file=sys.stderr)
        return 130

    _print_result_summary(result)
    gate = evaluate_load_gate(
        result,
        max_ingest_p95_ms=int(args.max_ingest_p95_ms or 0),
        max_retrieve_p95_ms=int(args.max_retrieve_p95_ms or 0),
        max_chat_p95_ms=int(args.max_chat_p95_ms or 0),
    )
    result["gate"] = gate

    out_path = str(args.out or "").strip()
    if out_path:
        _write_result_report(out_path, result)

    if not bool(gate.get("passed")):
        for failure in gate.get("failures") or []:
            print(f"[rag-e2e-loadtest] FAIL: {failure}", file=sys.stderr)
        return 2
    print("[rag-e2e-loadtest] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
