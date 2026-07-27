#!/usr/bin/env python3
"""
Live core release gate:
1) ready -> primary tenant upload -> evidence retrieval
2) duplicate upload idempotency (same bytes + pipeline => same document id)
3) retrieval-only serial vs concurrent live comparison
4) cross-tenant retrieval isolation
5) dataset-analysis PNG export shared state across API instances
6) abandoned PNG worker reaches failed/worker_lost
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.evaluation.poc_runner.png_tasks import begin_png_export_task, create_png_export_task
from scripts.rag_e2e_load_test import E2ELoadTestConfig, evaluate_concurrency_gate, run_e2e_load_test
from scripts.smoke_test import (
    _cleanup_created_dataset,
    _core_retrieve_payload,
    _join,
    _normalize_base_urls,
    _parse_json,
    _retrieve_core_evidence,
    _upload_form_data,
    _wait_for_document_completion,
    build_headers,
    request_with_retries,
    wait_ready,
)


@dataclass(frozen=True)
class LiveCoreReleaseGateConfig:
    api_base: str
    secondary_api_base: str | None
    primary_tenant_id: str
    secondary_tenant_id: str
    user_id: str
    parser_backend: str = "auto"
    retrieve_requests: int = 6
    candidate_concurrency: int = 3
    min_retrieve_throughput_ratio: float = 1.0
    ready_timeout_sec: float = 60.0
    ingest_timeout_sec: float = 600.0
    poll_interval_sec: float = 2.0
    timeout_sec: float = 60.0
    cleanup_on_success: bool = True
    png_probe_enabled: bool = True
    png_timeout_sec: float = 120.0
    png_worker_lost_wait_sec: float | None = None


def _failures_extend(report: dict[str, Any], *messages: str) -> None:
    failures = report.setdefault("failures", [])
    if not isinstance(failures, list):
        return
    for message in messages:
        msg = str(message or "").strip()
        if msg:
            failures.append(msg)


def _make_marker(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _create_dataset(client: httpx.Client, *, api_base: str, headers: dict[str, str], label: str) -> str:
    response = request_with_retries(
        client,
        "POST",
        _join(api_base, "datasets/"),
        expected={201},
        headers=headers,
        json={"name": f"live-gate-{label}-{uuid.uuid4().hex[:8]}", "description": "live core release gate"},
    )
    payload = _parse_json(response)
    dataset_id = str(payload.get("id") if isinstance(payload, dict) else "").strip()
    if not dataset_id:
        raise ValueError("dataset create returned no id")
    return dataset_id


def _upload_text_document(
    client: httpx.Client,
    *,
    api_base: str,
    headers: dict[str, str],
    dataset_id: str,
    parser_backend: str,
    text: str,
) -> str:
    response = request_with_retries(
        client,
        "POST",
        _join(api_base, "documents/upload"),
        expected={201},
        headers=headers,
        files={"file": ("live-core-gate.txt", text.encode("utf-8"), "text/plain")},
        data=_upload_form_data(dataset_id=dataset_id, parser_backend=parser_backend, core_only=True),
    )
    payload = _parse_json(response)
    document_id = str(payload.get("id") if isinstance(payload, dict) else "").strip()
    if not document_id:
        raise ValueError("upload returned no document id")
    return document_id


def _upload_and_wait_for_evidence(
    client: httpx.Client,
    *,
    api_base: str,
    headers: dict[str, str],
    dataset_id: str,
    parser_backend: str,
    marker: str,
    ingest_timeout_sec: float,
    poll_interval_sec: float,
) -> str:
    doc_text = (
        "MimirQ live core release gate synthetic document.\n\n"
        f"LIVE_GATE_FACT: {marker}\n"
        "LIVE_GATE_NOTE: retrieval-only probe.\n"
    )
    document_id = _upload_text_document(
        client,
        api_base=api_base,
        headers=headers,
        dataset_id=dataset_id,
        parser_backend=parser_backend,
        text=doc_text,
    )
    _wait_for_document_completion(
        client,
        api_base=api_base,
        headers=headers,
        document_id=document_id,
        timeout_sec=ingest_timeout_sec,
        poll_interval_sec=poll_interval_sec,
        verbose=False,
    )
    _retrieve_core_evidence(
        client,
        api_base=api_base,
        headers=headers,
        dataset_id=dataset_id,
        document_id=document_id,
        marker=marker,
    )
    return document_id


def _is_expected_tenant_denial_status(status_code: int | None) -> bool:
    return int(status_code or 0) in {403, 404}


def _probe_cross_tenant_denial(
    client: httpx.Client,
    *,
    api_base: str,
    headers: dict[str, str],
    dataset_id: str,
    marker: str,
    label: str,
) -> dict[str, Any]:
    response = client.post(
        _join(api_base, "rag/retrieve"),
        headers=headers,
        json=_core_retrieve_payload(query=marker, dataset_id=dataset_id),
    )
    passed = _is_expected_tenant_denial_status(response.status_code)
    return {
        "label": label,
        "status_code": int(response.status_code),
        "passed": passed,
    }


def _probe_png_cross_instance(
    client: httpx.Client,
    *,
    config: LiveCoreReleaseGateConfig,
    headers: dict[str, str],
    dataset_id: str,
) -> dict[str, Any]:
    secondary_base = str(config.secondary_api_base or "").strip() or config.api_base
    create_response = request_with_retries(
        client,
        "POST",
        _join(config.api_base, f"datasets/{dataset_id}/analysis/export.png"),
        expected={202},
        headers=headers,
    )
    create_payload = _parse_json(create_response)
    task_id = str(create_payload.get("task_id") if isinstance(create_payload, dict) else "").strip()
    if not task_id:
        return {"passed": False, "reason": "create returned no task_id"}

    status_payload: dict[str, Any] = {}
    deadline = time.monotonic() + max(0.1, float(config.png_timeout_sec))
    while time.monotonic() < deadline:
        status_response = request_with_retries(
            client,
            "GET",
            _join(secondary_base, f"datasets/{dataset_id}/analysis/export-tasks/{task_id}"),
            expected={200},
            headers=headers,
        )
        parsed = _parse_json(status_response)
        status_payload = dict(parsed) if isinstance(parsed, dict) else {}
        status = str(status_payload.get("status") or "").strip().lower()
        if status == "done":
            break
        if status == "failed":
            return {
                "task_id": task_id,
                "status": status,
                "error_code": status_payload.get("error_code"),
                "passed": False,
            }
        time.sleep(max(0.0, float(config.poll_interval_sec)))
    else:
        return {"task_id": task_id, "status": status_payload.get("status"), "passed": False, "reason": "timeout"}

    result_response = request_with_retries(
        client,
        "GET",
        _join(secondary_base, f"datasets/{dataset_id}/analysis/export-tasks/{task_id}/result.png"),
        expected={200},
        headers=headers,
    )
    payload = bytes(result_response.content or b"")
    content_type = str(result_response.headers.get("content-type") or "").lower()
    passed = content_type.startswith("image/png") and payload.startswith(b"\x89PNG\r\n\x1a\n")
    return {
        "task_id": task_id,
        "status": "done",
        "content_type": content_type,
        "result_size_bytes": len(payload),
        "passed": passed,
    }


def _probe_png_worker_lost(
    client: httpx.Client,
    *,
    config: LiveCoreReleaseGateConfig,
    headers: dict[str, str],
    dataset_id: str,
) -> dict[str, Any]:
    task = create_png_export_task(
        tenant_id=config.primary_tenant_id,
        dataset_id=dataset_id,
        filters={"probe": "worker_lost"},
        requested_by=config.user_id,
        account_id=config.user_id,
    )
    task_id = str(task.get("task_id") or "").strip()
    started_task = begin_png_export_task(
        task_id,
        tenant_id=config.primary_tenant_id,
        dataset_id=dataset_id,
    )

    shared_state_response = request_with_retries(
        client,
        "GET",
        _join(config.api_base, f"datasets/{dataset_id}/analysis/export-tasks/{task_id}"),
        expected={200},
        headers=headers,
    )
    shared_state_payload = _parse_json(shared_state_response)
    shared_state_status = str(
        shared_state_payload.get("status") if isinstance(shared_state_payload, dict) else ""
    ).strip().lower()
    if shared_state_status != "running":
        return {
            "task_id": task_id,
            "shared_state_status": shared_state_status,
            "passed": False,
            "reason": "seeded task is not visible as running through the primary API",
        }
    time.sleep(
        _resolve_png_worker_lost_wait_sec(
            started_task,
            configured_wait_sec=config.png_worker_lost_wait_sec,
        )
    )

    secondary_base = str(config.secondary_api_base or "").strip() or config.api_base
    response = request_with_retries(
        client,
        "GET",
        _join(secondary_base, f"datasets/{dataset_id}/analysis/export-tasks/{task_id}"),
        expected={200},
        headers=headers,
    )
    parsed = _parse_json(response)
    status = str(parsed.get("status") if isinstance(parsed, dict) else "").strip().lower()
    error_code = str(parsed.get("error_code") if isinstance(parsed, dict) else "").strip().lower()
    return {
        "task_id": task_id,
        "shared_state_status": shared_state_status,
        "status": status,
        "error_code": error_code,
        "passed": status == "failed" and error_code == "worker_lost",
    }


def _resolve_png_worker_lost_wait_sec(
    started_task: dict[str, Any],
    *,
    configured_wait_sec: float | None,
) -> float:
    if configured_wait_sec is not None:
        return max(0.0, float(configured_wait_sec))

    raw_expiry = str(started_task.get("lease_expires_at") or "").strip()
    if not raw_expiry:
        raise RuntimeError("Seeded PNG task did not expose lease_expires_at")
    if raw_expiry.endswith("Z"):
        raw_expiry = f"{raw_expiry[:-1]}+00:00"
    try:
        lease_expires_at = datetime.fromisoformat(raw_expiry)
    except ValueError as exc:
        raise RuntimeError("Seeded PNG task returned invalid lease_expires_at") from exc
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)

    remaining_sec = (lease_expires_at - datetime.now(UTC)).total_seconds()
    return max(0.0, remaining_sec) + 0.5


def _shared_async_transport(client: httpx.Client | None) -> Any | None:
    transport = getattr(client, "_transport", None) if client is not None else None
    return transport if isinstance(transport, httpx.MockTransport) else None


def _concurrent_duplicate_upload_ids(
    *,
    config: LiveCoreReleaseGateConfig,
    headers: dict[str, str],
    dataset_id: str,
    text: str,
    client: httpx.Client | None = None,
) -> list[str]:
    async def _run() -> list[str]:
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=4)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout_sec),
            limits=limits,
            follow_redirects=False,
            trust_env=False,
            transport=_shared_async_transport(client),
        ) as async_client:
            targets = [
                config.api_base,
                str(config.secondary_api_base or "").strip() or config.api_base,
            ]

            async def _upload_once(target_base: str) -> str:
                response = await async_client.post(
                    _join(target_base, "documents/upload"),
                    headers=headers,
                    files={"file": ("live-core-gate.txt", text.encode("utf-8"), "text/plain")},
                    data=_upload_form_data(dataset_id=dataset_id, parser_backend=config.parser_backend, core_only=True),
                )
                if not response.is_success:
                    raise RuntimeError(
                        f"duplicate upload failed: base_url={target_base} "
                        f"status={response.status_code} body={response.text[:500]}"
                    )
                payload = _parse_json(response)
                document_id = str(payload.get("id") if isinstance(payload, dict) else "").strip()
                if not document_id:
                    raise ValueError("upload returned no document id")
                return document_id

            return list(await asyncio.gather(*[_upload_once(target) for target in targets]))

    return asyncio.run(_run())


def _same_key_dual_instance_probe(
    *,
    config: LiveCoreReleaseGateConfig,
    headers: dict[str, str],
    dataset_id: str,
    query: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    secondary_base = str(config.secondary_api_base or "").strip()
    if not secondary_base:
        return {"skipped": True, "reason": "secondary_api_base_missing"}

    async def _run() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=4)
        payload = _core_retrieve_payload(query=query, dataset_id=dataset_id)
        start_gate = asyncio.Event()
        ready = 0
        ready_lock = asyncio.Lock()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout_sec),
            limits=limits,
            follow_redirects=False,
            trust_env=False,
            transport=_shared_async_transport(client),
        ) as async_client:
            async def _post_retrieve(
                target_base: str,
                *,
                request_id: str,
                request_payload: dict[str, Any],
            ) -> dict[str, Any]:
                started_at = time.perf_counter()
                response = await async_client.post(
                    _join(target_base, "rag/retrieve"),
                    headers={**headers, "X-Request-ID": request_id},
                    json=request_payload,
                )
                finished_at = time.perf_counter()
                body = _parse_json(response)
                query_debug = body.get("query_debug") if isinstance(body, dict) else None
                channels = query_debug.get("channels") if isinstance(query_debug, dict) else None
                cache = channels.get("cache") if isinstance(channels, dict) else None
                metrics = body.get("metrics") if isinstance(body, dict) else None
                if not isinstance(cache, dict):
                    cache = metrics.get("cache") if isinstance(metrics, dict) else None
                runtime_metrics = {
                    key: metrics[key]
                    for key in (
                        "rag_offload_queue_ms",
                        "rag_offload_exec_ms",
                        "rag_distributed_admission_state",
                    )
                    if isinstance(metrics, dict) and key in metrics
                }
                return {
                    "base_url": target_base,
                    "status_code": int(response.status_code),
                    "cache": cache if isinstance(cache, dict) else {},
                    "runtime_metrics": runtime_metrics,
                    "duration_ms": round(max(0.0, (finished_at - started_at) * 1000.0), 1),
                    "started_at": started_at,
                    "finished_at": finished_at,
                }

            # Readiness proves that the process is alive, not that every process-local
            # DB/vector/provider path has handled a request. Warm each target with a
            # distinct key so cold-start work cannot be mistaken for follower wait.
            targets = (config.api_base, secondary_base)
            prewarm_requests: list[dict[str, Any]] = []
            for index, target_base in enumerate(targets):
                prewarm_requests.append(
                    await _post_retrieve(
                        target_base,
                        request_id=f"same-key-prewarm-{index}",
                        request_payload=_core_retrieve_payload(
                            query=f"{query} prewarm-{index}",
                            dataset_id=dataset_id,
                        ),
                    )
                )

            async def _request(target_base: str, request_id: str) -> dict[str, Any]:
                nonlocal ready
                async with ready_lock:
                    ready += 1
                    if ready == 2:
                        start_gate.set()
                await start_gate.wait()
                return await _post_retrieve(
                    target_base,
                    request_id=request_id,
                    request_payload=payload,
                )

            requests = list(
                await asyncio.gather(
                    _request(config.api_base, "same-key-primary"),
                    _request(secondary_base, "same-key-secondary"),
                )
            )
            return requests, prewarm_requests

    requests, prewarm_requests = asyncio.run(_run())
    ok = all(int(item.get("status_code") or 0) == 200 for item in requests)
    prewarm_ok = all(int(item.get("status_code") or 0) == 200 for item in prewarm_requests)
    leader_seen = any(str((item.get("cache") or {}).get("singleflight_role") or "") == "leader" for item in requests)
    follower_seen = any(bool((item.get("cache") or {}).get("distributed_singleflight_hit")) for item in requests)
    overlap_observed = bool(
        len(requests) == 2
        and max(float(item.get("started_at") or 0.0) for item in requests)
        < min(float(item.get("finished_at") or 0.0) for item in requests)
    )
    return {
        "requests": requests,
        "prewarm_requests": prewarm_requests,
        "prewarm_ok": prewarm_ok,
        "overlap_observed": overlap_observed,
        "passed": bool(prewarm_ok and ok and overlap_observed and leader_seen and follower_seen),
    }


def _run_retrieve_only_load_pair(
    *,
    config: LiveCoreReleaseGateConfig,
    dataset_id: str,
    query: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    async def _run_once(
        concurrency: int,
        *,
        retrieve_requests: int | None = None,
        request_base_urls: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        cfg = E2ELoadTestConfig(
            base_url=config.api_base,
            request_base_urls=request_base_urls,
            tenant_id=config.primary_tenant_id,
            user_id=config.user_id,
            bearer="",
            file_bytes=b"unused",
            filename="unused.txt",
            parser_backend=config.parser_backend,
            dataset_id=dataset_id,
            retrieve_requests=int(config.retrieve_requests if retrieve_requests is None else retrieve_requests),
            retrieve_concurrency=max(1, int(concurrency)),
            query=query,
            retrieval_mode="keyword",
            ingest_count=0,
            chat_requests=0,
            chat_concurrency=1,
            message="unused",
            enable_reranker=False,
        )
        limits = httpx.Limits(max_connections=max(2, concurrency * 2), max_keepalive_connections=max(2, concurrency * 2))
        async with httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_sec), limits=limits, trust_env=False) as client:
            return await run_e2e_load_test(cfg, client=client)

    candidate_base_urls = tuple(
        dict.fromkeys(
            base
            for base in (
                config.api_base,
                str(config.secondary_api_base or "").strip() or None,
            )
            if base
        )
    )
    for base_url in candidate_base_urls or (config.api_base,):
        asyncio.run(_run_once(1, retrieve_requests=1, request_base_urls=(base_url,)))
    baseline = asyncio.run(_run_once(1, request_base_urls=(config.api_base,)))
    candidate = asyncio.run(
        _run_once(
            max(2, int(config.candidate_concurrency or 0)),
            request_base_urls=candidate_base_urls or (config.api_base,),
        )
    )
    return baseline, candidate


def run_live_core_release_gate(
    config: LiveCoreReleaseGateConfig,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "mimirq.live_core_release_gate.v1",
        "api_base": config.api_base,
        "secondary_api_base": config.secondary_api_base,
        "auth_mode": "header",
        "tenant_ids": {
            "primary": config.primary_tenant_id,
            "secondary": config.secondary_tenant_id,
        },
        "failures": [],
    }

    close_client = False
    created_datasets: list[tuple[str, dict[str, str]]] = []
    run_completed = False
    if client is None:
        close_client = True
        client = httpx.Client(
            timeout=httpx.Timeout(config.timeout_sec),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=10),
            follow_redirects=False,
            trust_env=False,
        )

    try:
        report["ready"] = wait_ready(
            client,
            api_base=config.api_base,
            timeout_sec=config.ready_timeout_sec,
            poll_interval_sec=config.poll_interval_sec,
        )
        if str(config.secondary_api_base or "").strip():
            report["secondary_ready"] = wait_ready(
                client,
                api_base=str(config.secondary_api_base or ""),
                timeout_sec=config.ready_timeout_sec,
                poll_interval_sec=config.poll_interval_sec,
            )

        primary_headers = build_headers(
            tenant_id=config.primary_tenant_id,
            user_id=(config.user_id or None),
            token=None,
        )
        secondary_headers = build_headers(
            tenant_id=config.secondary_tenant_id,
            user_id=(config.user_id or None),
            token=None,
        )

        if config.png_probe_enabled:
            png_dataset_id = _create_dataset(
                client,
                api_base=config.api_base,
                headers=primary_headers,
                label="png",
            )
            created_datasets.append((png_dataset_id, primary_headers))
            png_cross_instance = _probe_png_cross_instance(
                client,
                config=config,
                headers=primary_headers,
                dataset_id=png_dataset_id,
            )
            report["png_cross_instance"] = png_cross_instance
            if not bool(png_cross_instance.get("passed")):
                _failures_extend(report, "PNG export did not complete across API instances")

            png_worker_lost = _probe_png_worker_lost(
                client,
                config=config,
                headers=primary_headers,
                dataset_id=png_dataset_id,
            )
            report["png_worker_lost"] = png_worker_lost
            if not bool(png_worker_lost.get("passed")):
                _failures_extend(report, "abandoned PNG task did not reach failed/worker_lost")

        primary_dataset_id = _create_dataset(client, api_base=config.api_base, headers=primary_headers, label="primary")
        created_datasets.append((primary_dataset_id, primary_headers))
        primary_marker = _make_marker("primary")
        primary_document_id = _upload_and_wait_for_evidence(
            client,
            api_base=config.api_base,
            headers=primary_headers,
            dataset_id=primary_dataset_id,
            parser_backend=config.parser_backend,
            marker=primary_marker,
            ingest_timeout_sec=config.ingest_timeout_sec,
            poll_interval_sec=config.poll_interval_sec,
        )

        duplicate_marker = _make_marker("duplicate")
        duplicate_text = (
            "MimirQ live core release gate synthetic document.\n\n"
            f"LIVE_GATE_DUPLICATE: {duplicate_marker}\n"
        )
        duplicate_document_ids = _concurrent_duplicate_upload_ids(
            config=config,
            headers=primary_headers,
            dataset_id=primary_dataset_id,
            text=duplicate_text,
            client=client,
        )
        for duplicate_document_id in sorted(set(duplicate_document_ids)):
            _wait_for_document_completion(
                client,
                api_base=config.api_base,
                headers=primary_headers,
                document_id=duplicate_document_id,
                timeout_sec=config.ingest_timeout_sec,
                poll_interval_sec=config.poll_interval_sec,
                verbose=False,
            )
        duplicate_passed = bool(duplicate_document_ids) and len(set(duplicate_document_ids)) == 1 and duplicate_document_ids[0] != primary_document_id
        report["primary"] = {
            "dataset_id": primary_dataset_id,
            "document_id": primary_document_id,
            "marker": primary_marker,
        }
        report["duplicate_upload"] = {
            "first_document_id": primary_document_id,
            "concurrent_document_ids": duplicate_document_ids,
            "marker": duplicate_marker,
            "passed": duplicate_passed,
        }
        if not duplicate_passed:
            _failures_extend(report, "concurrent duplicate upload returned different document ids")

        singleflight_query = f"{primary_marker} {_make_marker('singleflight')}"
        same_key_probe = _same_key_dual_instance_probe(
            config=config,
            headers=primary_headers,
            dataset_id=primary_dataset_id,
            query=singleflight_query,
            client=client,
        )
        same_key_probe["query"] = singleflight_query
        report["same_key_dual_instance"] = same_key_probe
        if not bool(same_key_probe.get("skipped")) and not bool(same_key_probe.get("passed")):
            _failures_extend(report, "same-key dual-instance probe did not prove distributed singleflight follower reuse")

        throughput_query = f"{primary_marker} varied-throughput"
        baseline, candidate = _run_retrieve_only_load_pair(
            config=config,
            dataset_id=primary_dataset_id,
            query=throughput_query,
        )
        concurrency_gate = evaluate_concurrency_gate(
            baseline,
            candidate,
            min_retrieve_throughput_ratio=float(config.min_retrieve_throughput_ratio),
            min_chat_throughput_ratio=0.0,
        )
        report["concurrency"] = {
            "query": throughput_query,
            "baseline": baseline,
            "candidate": candidate,
            "gate": concurrency_gate,
        }
        if not bool(concurrency_gate.get("passed")):
            _failures_extend(
                report,
                *(f"concurrency: {failure}" for failure in (concurrency_gate.get("failures") or [])),
            )

        secondary_dataset_id = _create_dataset(client, api_base=config.api_base, headers=secondary_headers, label="secondary")
        created_datasets.append((secondary_dataset_id, secondary_headers))
        secondary_marker = _make_marker("secondary")
        secondary_document_id = _upload_and_wait_for_evidence(
            client,
            api_base=config.api_base,
            headers=secondary_headers,
            dataset_id=secondary_dataset_id,
            parser_backend=config.parser_backend,
            marker=secondary_marker,
            ingest_timeout_sec=config.ingest_timeout_sec,
            poll_interval_sec=config.poll_interval_sec,
        )
        cross_checks = [
            _probe_cross_tenant_denial(
                client,
                api_base=config.api_base,
                headers=secondary_headers,
                dataset_id=primary_dataset_id,
                marker=primary_marker,
                label="secondary_to_primary",
            ),
            _probe_cross_tenant_denial(
                client,
                api_base=config.api_base,
                headers=primary_headers,
                dataset_id=secondary_dataset_id,
                marker=secondary_marker,
                label="primary_to_secondary",
            ),
        ]
        tenant_isolation_passed = all(bool(item.get("passed")) for item in cross_checks)
        report["secondary"] = {
            "dataset_id": secondary_dataset_id,
            "document_id": secondary_document_id,
            "marker": secondary_marker,
        }
        report["tenant_isolation"] = {
            "passed": tenant_isolation_passed,
            "checks": cross_checks,
        }
        if not tenant_isolation_passed:
            _failures_extend(
                report,
                *(
                    f"tenant isolation failed for {item.get('label')} (status={item.get('status_code')})"
                    for item in cross_checks
                    if not bool(item.get("passed"))
                ),
            )

        run_completed = True
    finally:
        should_cleanup = bool(created_datasets) and (
            not run_completed or bool(config.cleanup_on_success) or bool(report["failures"])
        )
        if should_cleanup:
            cleanup: dict[str, Any] = {}
            cleanup_failures: list[str] = []
            for dataset_id, headers in reversed(created_datasets):
                try:
                    cleanup[dataset_id] = _cleanup_created_dataset(
                        client,
                        api_base=config.api_base,
                        headers=headers,
                        dataset_id=dataset_id,
                    )
                except Exception as exc:
                    cleanup_failures.append(f"cleanup failed for dataset {dataset_id}: {exc}")
            report["cleanup"] = cleanup
            if cleanup_failures:
                report["cleanup_failures"] = cleanup_failures
                _failures_extend(report, *cleanup_failures)
        if run_completed:
            report["passed"] = not bool(report["failures"])
        if close_client and client is not None:
            client.close()

    return report


def _resolve_runtime_config(args: argparse.Namespace) -> LiveCoreReleaseGateConfig:
    raw_base_url = args.base_url or "http://localhost:8000"
    _root_base, api_base = _normalize_base_urls(str(raw_base_url))
    secondary_api_base = None
    if str(args.secondary_base_url or "").strip():
        _secondary_root, secondary_api_base = _normalize_base_urls(str(args.secondary_base_url))
    timeout = float(args.timeout_sec or 60.0)
    ready_timeout = float(args.ready_timeout_sec or 60.0)
    poll_interval = float(args.poll_interval_sec or 2.0)
    tenant_id = str(args.tenant_id or uuid.uuid4()).strip()
    secondary_tenant_id = str(args.secondary_tenant_id or uuid.uuid4()).strip()
    user_id = str(args.user_id or "live-core-gate").strip()

    return LiveCoreReleaseGateConfig(
        api_base=api_base,
        secondary_api_base=secondary_api_base,
        primary_tenant_id=tenant_id,
        secondary_tenant_id=secondary_tenant_id,
        user_id=user_id,
        parser_backend=str(args.parser_backend or "auto"),
        retrieve_requests=max(2, int(args.retrieve_requests or 0)),
        candidate_concurrency=max(2, int(args.candidate_concurrency or 0)),
        min_retrieve_throughput_ratio=float(args.min_retrieve_throughput_ratio or 0.0),
        ready_timeout_sec=ready_timeout,
        ingest_timeout_sec=float(args.ingest_timeout_sec or 600.0),
        poll_interval_sec=poll_interval,
        timeout_sec=timeout,
        cleanup_on_success=not bool(args.keep_datasets),
        png_probe_enabled=not bool(args.skip_png_probe),
        png_timeout_sec=max(1.0, float(args.png_timeout_sec or 120.0)),
        png_worker_lost_wait_sec=(
            None
            if args.png_worker_lost_wait_sec is None
            else max(0.0, float(args.png_worker_lost_wait_sec))
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Header-auth live HTTP gate for core retrieval concurrency, upload idempotency, "
            "tenant isolation, and shared PNG task state."
        )
    )
    parser.add_argument("--base-url", default="", help="API host (http://host:8000) or API base (/api/v1).")
    parser.add_argument("--secondary-base-url", default="", help="Optional second API host/base for dual-instance checks.")
    parser.add_argument("--tenant-id", default="", help="Primary tenant id/header.")
    parser.add_argument("--secondary-tenant-id", default="", help="Secondary tenant id/header.")
    parser.add_argument("--user-id", default="", help="Header auth user id.")
    parser.add_argument("--parser-backend", default="auto")
    parser.add_argument("--retrieve-requests", type=int, default=6)
    parser.add_argument("--candidate-concurrency", type=int, default=3)
    parser.add_argument("--min-retrieve-throughput-ratio", type=float, default=1.0)
    parser.add_argument("--ready-timeout-sec", type=float, default=60.0)
    parser.add_argument("--ingest-timeout-sec", type=float, default=600.0)
    parser.add_argument("--poll-interval-sec", type=float, default=2.0)
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    parser.add_argument("--png-timeout-sec", type=float, default=120.0)
    parser.add_argument(
        "--png-worker-lost-wait-sec",
        type=float,
        default=None,
        help="Override the worker-lost wait; default follows the seeded task lease.",
    )
    parser.add_argument("--skip-png-probe", action="store_true")
    parser.add_argument("--keep-datasets", action="store_true", help="Keep created datasets after a successful run.")
    parser.add_argument("--out", default="", help="Write JSON report to a file path.")
    args = parser.parse_args(argv)

    try:
        config = _resolve_runtime_config(args)
        report = run_live_core_release_gate(config)
    except KeyboardInterrupt:
        print("[live-core-release-gate] cancelled", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[live-core-release-gate] ERROR: {exc}", file=sys.stderr)
        return 1

    out_path = str(args.out or "").strip()
    if out_path:
        output = Path(out_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[live-core-release-gate] wrote: {output}")

    status = "PASS" if bool(report.get("passed")) else "FAIL"
    print(f"[live-core-release-gate] {status}")
    for failure in report.get("failures") or []:
        print(f"[live-core-release-gate] {failure}", file=sys.stderr)
    return 0 if bool(report.get("passed")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
