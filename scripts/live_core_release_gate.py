#!/usr/bin/env python3
"""
Live core release gate:
1) ready -> primary tenant upload -> evidence retrieval
2) duplicate upload idempotency (same bytes + pipeline => same document id)
3) retrieval-only serial vs concurrent live comparison
4) cross-tenant retrieval isolation
"""

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def _run_retrieve_only_load_pair(
    *,
    config: LiveCoreReleaseGateConfig,
    dataset_id: str,
    query: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    async def _run_once(concurrency: int, *, retrieve_requests: int | None = None) -> dict[str, Any]:
        cfg = E2ELoadTestConfig(
            base_url=config.api_base,
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

    asyncio.run(_run_once(1, retrieve_requests=1))
    baseline = asyncio.run(_run_once(1))
    candidate = asyncio.run(_run_once(max(2, int(config.candidate_concurrency or 0))))
    return baseline, candidate


def run_live_core_release_gate(
    config: LiveCoreReleaseGateConfig,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "mimirq.live_core_release_gate.v1",
        "api_base": config.api_base,
        "auth_mode": "header",
        "tenant_ids": {
            "primary": config.primary_tenant_id,
            "secondary": config.secondary_tenant_id,
        },
        "failures": [],
    }

    close_client = False
    created_datasets: list[tuple[str, dict[str, str]]] = []
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

        duplicate_document_id = _upload_text_document(
            client,
            api_base=config.api_base,
            headers=primary_headers,
            dataset_id=primary_dataset_id,
            parser_backend=config.parser_backend,
            text=(
                "MimirQ live core release gate synthetic document.\n\n"
                f"LIVE_GATE_FACT: {primary_marker}\n"
                "LIVE_GATE_NOTE: retrieval-only probe.\n"
            ),
        )
        duplicate_passed = duplicate_document_id == primary_document_id
        report["primary"] = {
            "dataset_id": primary_dataset_id,
            "document_id": primary_document_id,
            "marker": primary_marker,
        }
        report["duplicate_upload"] = {
            "first_document_id": primary_document_id,
            "second_document_id": duplicate_document_id,
            "passed": duplicate_passed,
        }
        if not duplicate_passed:
            _failures_extend(report, "duplicate upload returned a different document id")

        baseline, candidate = _run_retrieve_only_load_pair(
            config=config,
            dataset_id=primary_dataset_id,
            query=primary_marker,
        )
        concurrency_gate = evaluate_concurrency_gate(
            baseline,
            candidate,
            min_retrieve_throughput_ratio=float(config.min_retrieve_throughput_ratio),
            min_chat_throughput_ratio=0.0,
        )
        report["concurrency"] = {
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

        report["passed"] = not bool(report["failures"])
        if bool(report["passed"]) and bool(config.cleanup_on_success):
            cleanup: dict[str, Any] = {}
            for dataset_id, headers in reversed(created_datasets):
                cleanup[dataset_id] = _cleanup_created_dataset(
                    client,
                    api_base=config.api_base,
                    headers=headers,
                    dataset_id=dataset_id,
                )
            report["cleanup"] = cleanup
        return report
    finally:
        if close_client and client is not None:
            client.close()


def _resolve_runtime_config(args: argparse.Namespace) -> LiveCoreReleaseGateConfig:
    raw_base_url = args.base_url or "http://localhost:8000"
    _root_base, api_base = _normalize_base_urls(str(raw_base_url))
    timeout = float(args.timeout_sec or 60.0)
    ready_timeout = float(args.ready_timeout_sec or 60.0)
    poll_interval = float(args.poll_interval_sec or 2.0)
    tenant_id = str(args.tenant_id or uuid.uuid4()).strip()
    secondary_tenant_id = str(args.secondary_tenant_id or uuid.uuid4()).strip()
    user_id = str(args.user_id or "live-core-gate").strip()

    return LiveCoreReleaseGateConfig(
        api_base=api_base,
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
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Header-auth live HTTP gate for core retrieval concurrency, upload idempotency, and tenant isolation."
    )
    parser.add_argument("--base-url", default="", help="API host (http://host:8000) or API base (/api/v1).")
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
