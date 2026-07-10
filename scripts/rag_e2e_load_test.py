#!/usr/bin/env python3

import argparse
import asyncio
import json
import math
import os
import sys
import time
import uuid
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

    chat_requests: int = 0
    chat_concurrency: int = 1
    message: str = "hello"

    doc_sample_size: int = 5


async def run_e2e_load_test(cfg: E2ELoadTestConfig, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    headers = _build_headers(tenant_id=cfg.tenant_id, user_id=cfg.user_id, bearer=cfg.bearer)
    if not headers.get("X-User-ID") and not headers.get("Authorization"):
        raise ValueError("missing auth headers (set user_id or bearer)")

    close_client = False
    if client is None:
        close_client = True
        client = httpx.AsyncClient(timeout=httpx.Timeout(60.0), headers=headers)

    try:
        base_url = str(cfg.base_url or "").rstrip("/")

        dataset_id = cfg.dataset_id
        if not dataset_id:
            ds_name = cfg.dataset_name or f"loadtest-{uuid.uuid4().hex[:8]}"
            r = await client.post(
                _join(base_url, "datasets/"),
                headers=headers,
                json={"name": ds_name, "description": "e2e load test"},
            )
            r.raise_for_status()
            dataset_id = str((r.json() or {}).get("id") or "")
            if not dataset_id:
                raise ValueError("dataset create returned no id")

        upload_lat_ms: list[int] = []
        ingest_e2e_ms: list[int] = []
        uploaded_doc_ids: list[str] = []
        completed_doc_ids: list[str] = []
        ingest_errors = 0

        ingest_sem = asyncio.Semaphore(max(1, int(cfg.ingest_concurrency or 1)))

        async def _upload_and_wait(i: int) -> None:
            nonlocal ingest_errors
            async with ingest_sem:
                t0 = time.perf_counter()
                files = {"file": (cfg.filename or f"loadtest-{i}.bin", cfg.file_bytes or b"", "application/octet-stream")}
                data = {"dataset_id": dataset_id}
                if cfg.parser_backend:
                    data["parser_backend"] = str(cfg.parser_backend)
                try:
                    resp = await client.post(_join(base_url, "documents/upload"), headers=headers, files=files, data=data)
                except Exception:
                    ingest_errors += 1
                    return
                upload_ms = int((time.perf_counter() - t0) * 1000)
                if resp.status_code < 200 or resp.status_code >= 300:
                    ingest_errors += 1
                    return
                try:
                    doc_id = str((resp.json() or {}).get("id") or "")
                except Exception:
                    doc_id = ""
                if not doc_id:
                    ingest_errors += 1
                    return
                uploaded_doc_ids.append(doc_id)
                upload_lat_ms.append(upload_ms)

                deadline = time.perf_counter() + float(cfg.ingest_timeout_sec or 0.0)
                while True:
                    try:
                        st = await client.get(_join(base_url, f"documents/{doc_id}/status"), headers=headers)
                    except Exception:
                        ingest_errors += 1
                        return
                    if st.status_code < 200 or st.status_code >= 300:
                        ingest_errors += 1
                        return
                    try:
                        payload = st.json() or {}
                    except Exception:
                        payload = {}
                    status = str(payload.get("status") or "")
                    if status == "completed":
                        completed_doc_ids.append(doc_id)
                        ingest_e2e_ms.append(int((time.perf_counter() - t0) * 1000))
                        return
                    if status == "failed":
                        ingest_errors += 1
                        return
                    if time.perf_counter() >= deadline:
                        ingest_errors += 1
                        return
                    await asyncio.sleep(max(0.0, float(cfg.poll_interval_sec or 0.0)))

        ingest_start = time.perf_counter()
        await asyncio.gather(*[_upload_and_wait(i) for i in range(int(cfg.ingest_count or 0))])
        ingest_elapsed_ms = int((time.perf_counter() - ingest_start) * 1000)

        doc_ids_for_queries = list(completed_doc_ids)
        if cfg.doc_sample_size and len(doc_ids_for_queries) > int(cfg.doc_sample_size):
            doc_ids_for_queries = doc_ids_for_queries[: int(cfg.doc_sample_size)]

        retrieve_lat_ms: list[int] = []
        retrieve_errors = 0

        retrieve_sem = asyncio.Semaphore(max(1, int(cfg.retrieve_concurrency or 1)))

        async def _retrieve_once() -> None:
            nonlocal retrieve_errors
            async with retrieve_sem:
                t0 = time.perf_counter()
                try:
                    r = await client.post(
                        _join(base_url, "rag/retrieve-preview"),
                        headers=headers,
                        json={
                            "query": str(cfg.query or "hello"),
                            "dataset_id": dataset_id,
                            "document_ids": doc_ids_for_queries,
                            "rag_config": {
                                "top_k": 10,
                                "enable_multi_query": False,
                                "use_graph": False,
                            },
                        },
                    )
                except Exception:
                    retrieve_errors += 1
                    return
                ms = int((time.perf_counter() - t0) * 1000)
                if r.status_code < 200 or r.status_code >= 300:
                    retrieve_errors += 1
                    return
                retrieve_lat_ms.append(ms)

        retrieve_start = time.perf_counter()
        await asyncio.gather(*[_retrieve_once() for _ in range(int(cfg.retrieve_requests or 0))])
        retrieve_elapsed_ms = int((time.perf_counter() - retrieve_start) * 1000)

        chat_lat_ms: list[int] = []
        chat_errors = 0
        chat_sem = asyncio.Semaphore(max(1, int(cfg.chat_concurrency or 1)))

        async def _chat_once() -> None:
            nonlocal chat_errors
            async with chat_sem:
                t0 = time.perf_counter()
                try:
                    r = await client.post(
                        _join(base_url, "chat"),
                        headers=headers,
                        json={
                            "message": str(cfg.message or "hello"),
                            "dataset_id": dataset_id,
                            "document_ids": doc_ids_for_queries,
                            "structured_output": True,
                            "structured_preset": "summary",
                            "rag_config": {
                                "top_k": 10,
                                "enable_multi_query": False,
                                "use_graph": False,
                            },
                        },
                    )
                except Exception:
                    chat_errors += 1
                    return
                ms = int((time.perf_counter() - t0) * 1000)
                if r.status_code < 200 or r.status_code >= 300:
                    chat_errors += 1
                    return
                chat_lat_ms.append(ms)

        chat_start = time.perf_counter()
        await asyncio.gather(*[_chat_once() for _ in range(int(cfg.chat_requests or 0))])
        chat_elapsed_ms = int((time.perf_counter() - chat_start) * 1000)

        return {
            "dataset_id": dataset_id,
            "document_ids": completed_doc_ids,
            "ingest": {
                "requested": int(cfg.ingest_count or 0),
                "uploaded": len(uploaded_doc_ids),
                "completed": len(completed_doc_ids),
                "errors": int(ingest_errors),
                "elapsed_ms": int(ingest_elapsed_ms),
                "throughput_docs_per_sec": throughput_per_sec(count=len(completed_doc_ids), elapsed_ms=ingest_elapsed_ms),
                "upload_latency_ms": summarize_latencies_ms(upload_lat_ms),
                "e2e_latency_ms": summarize_latencies_ms(ingest_e2e_ms),
            },
            "retrieve": {
                "requested": int(cfg.retrieve_requests or 0),
                "ok": len(retrieve_lat_ms),
                "errors": int(retrieve_errors),
                "elapsed_ms": int(retrieve_elapsed_ms),
                "throughput_rps": throughput_per_sec(count=len(retrieve_lat_ms), elapsed_ms=retrieve_elapsed_ms),
                "latency_ms": summarize_latencies_ms(retrieve_lat_ms),
            },
            "chat": {
                "requested": int(cfg.chat_requests or 0),
                "ok": len(chat_lat_ms),
                "errors": int(chat_errors),
                "elapsed_ms": int(chat_elapsed_ms),
                "throughput_rps": throughput_per_sec(count=len(chat_lat_ms), elapsed_ms=chat_elapsed_ms),
                "latency_ms": summarize_latencies_ms(chat_lat_ms),
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


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    default_file = repo_root / "README.md"

    p = argparse.ArgumentParser(description="E2E RAG load test: ingest -> retrieve -> answer (throughput + P95).")
    p.add_argument("--base-url", default=_default_base_url(), help="API base url incl /api/v1 (default: %(default)s)")
    p.add_argument("--tenant-id", default=os.getenv("NEXT_PUBLIC_TENANT_ID") or "", help="X-Tenant-ID header (optional)")
    p.add_argument("--user-id", default=os.getenv("NEXT_PUBLIC_USER_ID") or "", help="X-User-ID header (AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (AUTH_MODE=jwt)")

    p.add_argument("--file", default=str(default_file), help="File path to upload for ingestion")
    p.add_argument("--filename", default="", help="Override uploaded filename (default: basename of --file)")
    p.add_argument("--parser-backend", default="auto", help="Parser backend (default: %(default)s)")
    p.add_argument("--dataset-id", default="", help="Optional dataset id to reuse (skips dataset creation)")
    p.add_argument("--dataset-name", default="", help="Dataset name when creating a new one (optional)")

    p.add_argument("--ingest-count", type=int, default=1, help="How many documents to ingest (default: %(default)s)")
    p.add_argument("--ingest-concurrency", type=int, default=1, help="Upload+poll concurrency (default: %(default)s)")
    p.add_argument("--poll-interval-sec", type=float, default=2.0, help="Status polling interval seconds (default: %(default)s)")
    p.add_argument("--ingest-timeout-sec", type=float, default=600.0, help="Per-document ingest timeout seconds (default: %(default)s)")

    p.add_argument("--retrieve-requests", type=int, default=20, help="Retrieve-preview requests (default: %(default)s)")
    p.add_argument("--retrieve-concurrency", type=int, default=10, help="Retrieve-preview concurrency (default: %(default)s)")
    p.add_argument("--query", default="Smoke", help="Retrieve query (default: %(default)s)")

    p.add_argument("--chat-requests", type=int, default=10, help="Chat requests (default: %(default)s)")
    p.add_argument("--chat-concurrency", type=int, default=5, help="Chat concurrency (default: %(default)s)")
    p.add_argument("--message", default="Summarize this document.", help="Chat message (default: %(default)s)")

    p.add_argument("--doc-sample-size", type=int, default=5, help="Max document ids per request (default: %(default)s)")
    p.add_argument("--timeout-sec", type=float, default=60.0, help="HTTP timeout seconds (default: %(default)s)")
    p.add_argument("--max-ingest-p95-ms", type=int, default=0, help="Fail if ingest P95 exceeds this value; 0 disables")
    p.add_argument("--max-retrieve-p95-ms", type=int, default=0, help="Fail if retrieve P95 exceeds this value; 0 disables")
    p.add_argument("--max-chat-p95-ms", type=int, default=0, help="Fail if chat P95 exceeds this value; 0 disables")
    p.add_argument("--out", default="", help="Write JSON report to path (or directory)")
    p.add_argument("--dry-run", action="store_true", help="Validate args and exit without network calls")

    args = p.parse_args(argv)

    file_path = Path(str(args.file))
    if not file_path.exists():
        print(f"[rag-e2e-loadtest] ERROR: file not found: {file_path}", file=sys.stderr)
        return 2

    file_bytes = file_path.read_bytes()
    filename = str(args.filename or file_path.name)

    cfg = E2ELoadTestConfig(
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
        doc_sample_size=int(args.doc_sample_size or 0),
    )

    if args.dry_run:
        print("[rag-e2e-loadtest] DryRun=ON (no network calls will be made)")
        print(f"[rag-e2e-loadtest] base_url={cfg.base_url}")
        print(f"[rag-e2e-loadtest] file={file_path} bytes={len(file_bytes)}")
        print(f"[rag-e2e-loadtest] ingest_count={cfg.ingest_count} ingest_concurrency={cfg.ingest_concurrency}")
        print(f"[rag-e2e-loadtest] retrieve_requests={cfg.retrieve_requests} retrieve_concurrency={cfg.retrieve_concurrency}")
        print(f"[rag-e2e-loadtest] chat_requests={cfg.chat_requests} chat_concurrency={cfg.chat_concurrency}")
        return 0

    async def _run() -> dict[str, Any]:
        max_conc = max(int(cfg.ingest_concurrency), int(cfg.retrieve_concurrency), int(cfg.chat_concurrency), 1)
        limits = httpx.Limits(max_connections=max_conc * 2, max_keepalive_connections=max_conc * 2)
        timeout = httpx.Timeout(float(args.timeout_sec))
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            return await run_e2e_load_test(cfg, client=client)

    try:
        result = asyncio.run(_run())
    except KeyboardInterrupt:
        print("[rag-e2e-loadtest] cancelled", file=sys.stderr)
        return 130

    ingest = result.get("ingest") or {}
    retrieve = result.get("retrieve") or {}
    chat = result.get("chat") or {}

    ingest_p95 = ((ingest.get("e2e_latency_ms") or {}) if isinstance(ingest.get("e2e_latency_ms"), dict) else {}).get("p95_ms", 0)
    retrieve_p95 = ((retrieve.get("latency_ms") or {}) if isinstance(retrieve.get("latency_ms"), dict) else {}).get("p95_ms", 0)
    chat_p95 = ((chat.get("latency_ms") or {}) if isinstance(chat.get("latency_ms"), dict) else {}).get("p95_ms", 0)

    print(
        f"[rag-e2e-loadtest] ingest: completed={ingest.get('completed')} errors={ingest.get('errors')} "
        f"throughput={float(ingest.get('throughput_docs_per_sec') or 0.0):.2f}/s p95={ingest_p95}ms"
    )
    print(
        f"[rag-e2e-loadtest] retrieve: ok={retrieve.get('ok')} errors={retrieve.get('errors')} "
        f"throughput={float(retrieve.get('throughput_rps') or 0.0):.2f}/s p95={retrieve_p95}ms"
    )
    print(
        f"[rag-e2e-loadtest] chat: ok={chat.get('ok')} errors={chat.get('errors')} "
        f"throughput={float(chat.get('throughput_rps') or 0.0):.2f}/s p95={chat_p95}ms"
    )
    gate = evaluate_load_gate(
        result,
        max_ingest_p95_ms=int(args.max_ingest_p95_ms or 0),
        max_retrieve_p95_ms=int(args.max_retrieve_p95_ms or 0),
        max_chat_p95_ms=int(args.max_chat_p95_ms or 0),
    )
    result["gate"] = gate

    out_path = str(args.out or "").strip()
    if out_path:
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

    if not bool(gate.get("passed")):
        for failure in gate.get("failures") or []:
            print(f"[rag-e2e-loadtest] FAIL: {failure}", file=sys.stderr)
        return 2
    print("[rag-e2e-loadtest] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
