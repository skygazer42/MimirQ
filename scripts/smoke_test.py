#!/usr/bin/env python3
"""
Purpose-built smoke test (CI / post-deploy):
1) Wait for /api/v1/health/ready
2) Create (or reuse) a dataset
3) Upload a tiny text document
4) Poll until ingestion completes
5) Ask a RAG question and validate structured output

Use --core-only to validate retrieval without an LLM and remove the temporary dataset on success.

Default behavior is PII-safe: it uploads synthetic content and avoids printing secrets.
"""


import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def env_or(dotenv: dict[str, str], key: str, default: str) -> str:
    return os.getenv(key, dotenv.get(key, default)) or default


def _normalize_base_urls(raw_base_url: str) -> tuple[str, str]:
    """
    Accept either:
    - http://host:8000
    - http://host:8000/api/v1

    Returns: (root_base_url, api_v1_base_url)
    """
    base = str(raw_base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("base_url is required")
    if base.endswith("/api/v1"):
        root = base[: -len("/api/v1")].rstrip("/")
    else:
        root = base
    api_v1 = f"{root}/api/v1"
    return root, api_v1


def _join(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def build_headers(*, tenant_id: str, user_id: str | None, token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif user_id:
        headers["X-User-ID"] = user_id
    return headers


_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9]{8,}"), "sk-***"),
    (re.compile(r"(?i)bearer\\s+[A-Za-z0-9\\-_.]{8,}"), "Bearer ***"),
]


def redact_secrets(text: str) -> str:
    out = str(text or "")
    out = " ".join(out.split())
    for pat, repl in _REDACT_PATTERNS:
        out = pat.sub(repl, out)
    return out


def _parse_json(resp: httpx.Response) -> Any:
    try:
        return resp.json() if resp.content else None
    except Exception:
        return None


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    raw = (resp.headers.get("retry-after") or resp.headers.get("Retry-After") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            return None
    payload = _parse_json(resp)
    if isinstance(payload, dict):
        for key in ("retry_after", "retry_after_sec", "retry_after_seconds"):
            if key in payload:
                try:
                    return float(payload.get(key))
                except Exception:
                    return None
    return None


@dataclass
class CallError(Exception):
    method: str
    url: str
    status_code: int | None
    detail: str

    def __str__(self) -> str:
        status = self.status_code if self.status_code is not None else "no-status"
        return f"{self.method} {self.url} failed ({status}): {self.detail}"


def request_with_retries(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    expected: set[int],
    headers: dict[str, str] | None = None,
    max_attempts: int = 3,
    **kwargs: Any,
) -> httpx.Response:
    last_resp: httpx.Response | None = None
    for attempt in range(max(1, int(max_attempts or 1))):
        try:
            resp = client.request(method, url, headers=headers, **kwargs)
        except Exception as exc:
            raise CallError(method=method.upper(), url=url, status_code=None, detail=redact_secrets(str(exc))) from exc
        last_resp = resp
        if resp.status_code in expected:
            return resp
        if resp.status_code != 429 or attempt >= max_attempts - 1:
            break
        time.sleep(_retry_after_seconds(resp) or 0.25)

    body_excerpt = redact_secrets((last_resp.text or "")[:800]) if last_resp is not None else ""
    raise CallError(
        method=method.upper(),
        url=url,
        status_code=(last_resp.status_code if last_resp is not None else None),
        detail=(body_excerpt or "unexpected status"),
    )


def wait_ready(
    client: httpx.Client,
    *,
    api_base: str,
    timeout_sec: float,
    poll_interval_sec: float,
) -> dict[str, Any]:
    url = _join(api_base, "health/ready")
    deadline = time.monotonic() + max(0.0, float(timeout_sec or 0.0))
    last_note = ""
    while True:
        resp = client.get(url)
        payload = _parse_json(resp)
        ok = bool(isinstance(payload, dict) and payload.get("ok") is True)
        if resp.status_code == 200 and ok:
            return payload if isinstance(payload, dict) else {"ok": True}

        # Only print when status changes / every few seconds to avoid CI spam.
        note = f"status={resp.status_code}"
        if isinstance(payload, dict):
            note = f"{note} ok={payload.get('ok')} deps={{{', '.join(k for k in payload.keys() if k != 'ok')}}}"
        note = redact_secrets(note)
        now = time.monotonic()
        if note != last_note:
            print(f"[smoke] wait-ready: {note}", file=sys.stderr)
            last_note = note

        if now >= deadline:
            raise CallError(method="GET", url=url, status_code=resp.status_code, detail="timeout waiting for readiness")
        time.sleep(max(0.1, float(poll_interval_sec or 0.0)))


def _detect_auth_mode(client: httpx.Client, *, api_base: str, override: str | None) -> str:
    if override:
        return str(override).strip().lower()
    try:
        resp = client.get(_join(api_base, "meta"))
        payload = _parse_json(resp)
        if isinstance(payload, dict):
            features = payload.get("features")
            if isinstance(features, dict):
                mode = str(features.get("auth_mode") or "").strip().lower()
                if mode:
                    return mode
    except Exception:
        pass
    return "jwt"


def _login_for_token(
    client: httpx.Client,
    *,
    api_base: str,
    identifier: str,
    password: str,
) -> str:
    resp = request_with_retries(
        client,
        "POST",
        _join(api_base, "auth/login"),
        expected={200},
        json={"identifier": identifier, "password": password},
    )
    payload = _parse_json(resp)
    token = ""
    if isinstance(payload, dict):
        token = str(((payload.get("token") or {}) if isinstance(payload.get("token"), dict) else {}).get("access_token") or "")
    if not token:
        raise CallError(method="POST", url=_join(api_base, "auth/login"), status_code=resp.status_code, detail="no access_token in response")
    return token


def _register_for_token(
    client: httpx.Client,
    *,
    api_base: str,
    email: str,
    username: str,
    password: str,
) -> str:
    resp = request_with_retries(
        client,
        "POST",
        _join(api_base, "auth/register"),
        expected={201},
        json={"email": email, "username": username, "password": password},
    )
    payload = _parse_json(resp)
    token = ""
    if isinstance(payload, dict):
        token = str(((payload.get("token") or {}) if isinstance(payload.get("token"), dict) else {}).get("access_token") or "")
    if not token:
        raise CallError(method="POST", url=_join(api_base, "auth/register"), status_code=resp.status_code, detail="no access_token in response")
    return token


def _upload_form_data(*, dataset_id: str, parser_backend: str, core_only: bool) -> dict[str, str]:
    data = {"dataset_id": dataset_id, "parser_backend": parser_backend}
    if core_only:
        data.update(
            {
                "chunk_vector_enabled": "false",
                "event_vector_enabled": "false",
                "entity_vector_enabled": "false",
                "kg_enabled": "false",
            }
        )
    return data


def _core_retrieve_payload(*, query: str, dataset_id: str) -> dict[str, Any]:
    return {
        "query": query,
        "dataset_id": dataset_id,
        "rag_config": {
            "use_graph": False,
            "top_k": 10,
            "score_threshold": 0.0,
            "retrieval_mode": "keyword",
            "enable_reranker": False,
            "enable_multi_query": False,
        },
    }


def _probe_web_auth_page(client: httpx.Client, *, web_base: str) -> dict[str, Any]:
    web_root, _web_api = _normalize_base_urls(web_base)
    url = _join(web_root, "auth")
    resp = request_with_retries(client, "GET", url, expected={200})
    html = resp.text or ""
    required_labels = ("登录", "账号", "密码")
    missing = [label for label in required_labels if label not in html]
    if missing:
        raise CallError(
            method="GET",
            url=url,
            status_code=resp.status_code,
            detail=f"auth page missing labels: {', '.join(missing)}",
        )
    return {"status_code": resp.status_code, "labels": list(required_labels)}


def _get_system_status_best_effort(
    client: httpx.Client,
    *,
    api_base: str,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    try:
        resp = request_with_retries(
            client,
            "GET",
            _join(api_base, "settings/status"),
            expected={200},
            headers=headers,
        )
    except Exception:
        return None
    payload = _parse_json(resp)
    return payload if isinstance(payload, dict) else None


def _summarize_retrieval_evidence(
    payload: Any,
    *,
    document_id: str,
    marker: str,
) -> dict[str, Any]:
    citations = payload.get("citations") if isinstance(payload, dict) else None
    rows = citations if isinstance(citations, list) else []
    matched = any(
        isinstance(item, dict)
        and str(item.get("document_id") or "") == document_id
        and marker in str(item.get("chunk_content") or "")
        for item in rows
    )
    return {
        "has_evidence": bool(isinstance(payload, dict) and payload.get("has_evidence") is True),
        "citation_count": len(rows),
        "matched": matched,
    }


def _cleanup_created_dataset(
    client: httpx.Client,
    *,
    api_base: str,
    headers: dict[str, str],
    dataset_id: str,
    document_id: str | None = None,
) -> dict[str, Any]:
    if document_id:
        request_with_retries(
            client,
            "DELETE",
            _join(api_base, f"documents/{document_id}"),
            expected={204, 404},
            headers=headers,
        )

    purge_url = _join(api_base, f"datasets/{dataset_id}/purge?dry_run=false&max_delete=1000")
    delete_url = _join(api_base, f"datasets/{dataset_id}")
    total_purged = 0
    last_error: CallError | None = None

    for attempt in range(5):
        purge_resp = request_with_retries(
            client,
            "POST",
            purge_url,
            expected={200},
            headers=headers,
            json={},
        )
        purge_payload = _parse_json(purge_resp)
        if isinstance(purge_payload, dict):
            total_purged += int(purge_payload.get("deleted") or 0)

        try:
            request_with_retries(
                client,
                "DELETE",
                delete_url,
                expected={204},
                headers=headers,
            )
            return {
                "purged_documents": total_purged,
                "dataset_deleted": True,
            }
        except CallError as exc:
            last_error = exc
            if exc.status_code != 409 or attempt >= 4:
                raise
            time.sleep(0.5)

    if last_error is not None:
        raise last_error
    raise RuntimeError("dataset cleanup failed without a specific error")


def _wait_for_document_completion(
    client: httpx.Client,
    *,
    api_base: str,
    headers: dict[str, str],
    document_id: str,
    timeout_sec: float,
    poll_interval_sec: float,
    verbose: bool,
) -> dict[str, Any]:
    status_url = _join(api_base, f"documents/{document_id}/status")
    deadline = time.monotonic() + max(0.0, float(timeout_sec or 0.0))
    last_print = 0.0
    last_stage = None
    while True:
        st_resp = request_with_retries(client, "GET", status_url, expected={200}, headers=headers)
        st_json = _parse_json(st_resp)
        st = str(st_json.get("status") if isinstance(st_json, dict) else "") or ""
        stage = st_json.get("current_stage") if isinstance(st_json, dict) else None
        prog = st_json.get("processing_progress") if isinstance(st_json, dict) else None
        now = time.monotonic()

        if st == "completed":
            return {"status": st, "stage": stage, "progress": prog}
        if st == "failed":
            raise CallError(method="GET", url=status_url, status_code=st_resp.status_code, detail="ingestion failed")
        if now >= deadline:
            raise CallError(method="GET", url=status_url, status_code=st_resp.status_code, detail="timeout waiting for ingestion")

        should_print = verbose or (now - last_print) >= 10.0 or stage != last_stage
        if should_print:
            last_print = now
            last_stage = stage
            prog_s = "" if prog is None else f"{prog}"
            stage_s = "" if stage is None else f"{stage}"
            print(f"[smoke] ingest: status={st} progress={prog_s} stage={stage_s}")

        time.sleep(max(0.1, float(poll_interval_sec or 0.0)))


def _retrieve_core_evidence(
    client: httpx.Client,
    *,
    api_base: str,
    headers: dict[str, str],
    dataset_id: str,
    document_id: str,
    marker: str,
) -> dict[str, Any]:
    retrieve_resp = request_with_retries(
        client,
        "POST",
        _join(api_base, "rag/retrieve"),
        expected={200},
        headers=headers,
        json=_core_retrieve_payload(query=marker, dataset_id=dataset_id),
    )
    retrieve_json = _parse_json(retrieve_resp)
    retrieval_summary = _summarize_retrieval_evidence(
        retrieve_json,
        document_id=document_id,
        marker=marker,
    )
    if not retrieval_summary["has_evidence"] or not retrieval_summary["matched"]:
        raise CallError(
            method="POST",
            url=_join(api_base, "rag/retrieve"),
            status_code=retrieve_resp.status_code,
            detail="retrieval did not return the uploaded synthetic fact",
        )
    return retrieval_summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Smoke test: ready -> ingest -> structured RAG query.")
    p.add_argument("--base-url", default=None, help="API host (http://host:8000) OR API base (http://host:8000/api/v1).")
    p.add_argument("--tenant-id", default=None, help="X-Tenant-ID header (recommended in prod).")
    p.add_argument("--auth-mode", default=None, help="Override server-reported auth mode (jwt|header).")
    p.add_argument("--user-id", default=None, help="X-User-ID header (AUTH_MODE=header).")
    p.add_argument("--token", default=None, help="Bearer token (AUTH_MODE=jwt).")
    p.add_argument("--identifier", default=None, help="Login identifier (email/username) when token is not provided.")
    p.add_argument("--password", default=None, help="Login password when token is not provided.")
    p.add_argument(
        "--bootstrap-register",
        action="store_true",
        help="Create a temporary local account via /auth/register when no JWT token or login credentials are provided.",
    )

    p.add_argument("--dataset-id", default=None, help="Reuse an existing dataset id (skips dataset creation).")
    p.add_argument("--secondary-base-url", default=None, help="Optional second API host/base used for shared-state checks.")
    p.add_argument("--web-base-url", default=None, help="Optional frontend host/base used to verify the login page and API proxy entry.")
    p.add_argument("--parser-backend", default="auto", help="Parser backend for upload (default: %(default)s)")
    p.add_argument("--structured-preset", default="summary", help="Structured preset (faq|summary|action_items).")
    p.add_argument("--allow-unstructured", action="store_true", help="Do not fail if structured output cannot be validated.")
    p.add_argument(
        "--core-only",
        action="store_true",
        help="Validate retrieval without an LLM; delete a dataset created by this run after success.",
    )

    p.add_argument("--ready-timeout-sec", type=float, default=60.0)
    p.add_argument("--ingest-timeout-sec", type=float, default=600.0)
    p.add_argument("--poll-interval-sec", type=float, default=2.0)
    p.add_argument("--timeout-sec", type=float, default=60.0, help="HTTP timeout seconds (default: %(default)s)")
    p.add_argument("--out", default="", help="Write a JSON summary report to a file path.")
    p.add_argument("--verbose", action="store_true")

    args = p.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    dotenv = load_dotenv(repo_root / ".env")

    raw_base_url = args.base_url or env_or(dotenv, "NEXT_PUBLIC_API_URL", "http://localhost:8000")
    _root_base, api_base = _normalize_base_urls(raw_base_url)
    secondary_api_base = ""
    if args.secondary_base_url:
        _secondary_root, secondary_api_base = _normalize_base_urls(args.secondary_base_url)

    tenant_id = (args.tenant_id or env_or(dotenv, "NEXT_PUBLIC_TENANT_ID", "00000000-0000-0000-0000-000000000000")).strip()
    if args.verbose:
        print(f"[smoke] api_base={api_base}")
        print(f"[smoke] tenant_id={tenant_id}")

    timeout = httpx.Timeout(float(args.timeout_sec))
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=10)
    report: dict[str, Any] = {"api_base": api_base, "tenant_id": tenant_id}

    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout, limits=limits, follow_redirects=False, trust_env=False) as client:
            ready_payload = wait_ready(
                client,
                api_base=api_base,
                timeout_sec=float(args.ready_timeout_sec),
                poll_interval_sec=float(args.poll_interval_sec),
            )
            report["ready"] = ready_payload
            print("[smoke] ready: ok")
            if args.web_base_url:
                report["web_auth"] = _probe_web_auth_page(client, web_base=str(args.web_base_url))
                print("[smoke] web: auth page ok")
            if secondary_api_base:
                report["secondary_ready"] = wait_ready(
                    client,
                    api_base=secondary_api_base,
                    timeout_sec=float(args.ready_timeout_sec),
                    poll_interval_sec=float(args.poll_interval_sec),
                )
                print("[smoke] secondary ready: ok")

            auth_mode = _detect_auth_mode(client, api_base=api_base, override=args.auth_mode)
            if auth_mode not in {"jwt", "header"}:
                raise ValueError(f"unsupported auth_mode: {auth_mode}")
            report["auth_mode"] = auth_mode
            print(f"[smoke] auth_mode={auth_mode}")

            token = (args.token or env_or(dotenv, "MIMIRQ_SMOKE_TOKEN", "") or env_or(dotenv, "MIMIRQ_DEMO_TOKEN", "") or "").strip()
            user_id = (args.user_id or env_or(dotenv, "NEXT_PUBLIC_USER_ID", "demo")).strip()
            bootstrap_register = bool(
                args.bootstrap_register
                or str(env_or(dotenv, "MIMIRQ_SMOKE_BOOTSTRAP_REGISTER", "")).strip().lower() in {"1", "true", "yes", "on"}
            )

            if auth_mode == "jwt":
                if not token:
                    identifier = (args.identifier or env_or(dotenv, "MIMIRQ_SMOKE_IDENTIFIER", "") or env_or(dotenv, "MIMIRQ_DEMO_IDENTIFIER", "")).strip()
                    password = (args.password or env_or(dotenv, "MIMIRQ_SMOKE_PASSWORD", "") or env_or(dotenv, "MIMIRQ_DEMO_PASSWORD", "")).strip()
                    if identifier and password:
                        print("[smoke] login: using identifier/password")
                        token = _login_for_token(client, api_base=api_base, identifier=identifier, password=password)
                    elif bootstrap_register:
                        account_seed = uuid.uuid4().hex[:12]
                        print("[smoke] login: bootstrapping local account via register")
                        token = _register_for_token(
                            client,
                            api_base=api_base,
                            email=f"smoke-{account_seed}@example.com",
                            username=f"smoke-{account_seed}",
                            password=f"smoke-{uuid.uuid4().hex}",
                        )
                    else:
                        raise ValueError(
                            "AUTH_MODE=jwt but no token provided. Set --token / MIMIRQ_SMOKE_TOKEN, "
                            "or provide --identifier + --password to login, or pass --bootstrap-register for local CI/dev stacks."
                        )
                user_id = ""

            headers = build_headers(tenant_id=tenant_id, user_id=(user_id or None), token=(token or None))
            report["headers"] = {
                "tenant": bool(headers.get("X-Tenant-ID")),
                "user": bool(headers.get("X-User-ID")),
                "bearer": bool(headers.get("Authorization")),
            }

            dataset_id = (args.dataset_id or "").strip() or None
            created_dataset = dataset_id is None
            if dataset_id:
                print(f"[smoke] dataset: reuse {dataset_id}")
            else:
                ds_payload = {"name": f"smoke-{uuid.uuid4().hex[:8]}", "description": "smoke test dataset"}
                ds_resp = request_with_retries(
                    client,
                    "POST",
                    _join(api_base, "datasets/"),
                    expected={201},
                    headers=headers,
                    json=ds_payload,
                )
                ds_json = _parse_json(ds_resp)
                dataset_id = str(ds_json.get("id") if isinstance(ds_json, dict) else "") or None
                if not dataset_id:
                    raise CallError(
                        method="POST",
                        url=_join(api_base, "datasets/"),
                        status_code=ds_resp.status_code,
                        detail="dataset create returned no id",
                    )
                print(f"[smoke] dataset: created {dataset_id}")
            report["dataset_id"] = dataset_id

            smoke_fact = f"smoke-{uuid.uuid4().hex[:12]}"
            doc_text = (
                "MimirQ smoke test document (synthetic; no PII).\n\n"
                f"SMOKE_FACT: launch_code={smoke_fact}\n"
                "SMOKE_NOTE: This is a test artifact.\n"
            )
            files = {"file": ("smoke.txt", doc_text.encode("utf-8"), "text/plain")}
            data = _upload_form_data(
                dataset_id=str(dataset_id),
                parser_backend=str(args.parser_backend or "auto"),
                core_only=bool(args.core_only),
            )
            up_resp = request_with_retries(
                client,
                "POST",
                _join(api_base, "documents/upload"),
                expected={201},
                headers=headers,
                files=files,
                data=data,
            )
            up_json = _parse_json(up_resp)
            doc_id = str(up_json.get("id") if isinstance(up_json, dict) else "") or None
            if not doc_id:
                raise CallError(
                    method="POST",
                    url=_join(api_base, "documents/upload"),
                    status_code=up_resp.status_code,
                    detail="upload returned no document id",
                )
            report["document_id"] = doc_id
            print(f"[smoke] upload: document_id={doc_id}")

            report["ingest_status"] = _wait_for_document_completion(
                client,
                api_base=api_base,
                headers=headers,
                document_id=doc_id,
                timeout_sec=float(args.ingest_timeout_sec),
                poll_interval_sec=float(args.poll_interval_sec),
                verbose=bool(args.verbose),
            )
            print("[smoke] ingest: completed")
            if secondary_api_base:
                report["secondary_ingest_status"] = _wait_for_document_completion(
                    client,
                    api_base=secondary_api_base,
                    headers=headers,
                    document_id=doc_id,
                    timeout_sec=float(args.ingest_timeout_sec),
                    poll_interval_sec=float(args.poll_interval_sec),
                    verbose=bool(args.verbose),
                )
                print("[smoke] secondary ingest view: completed")

            if args.core_only:
                marker = f"launch_code={smoke_fact}"
                if secondary_api_base:
                    def _retrieve_summary(base: str) -> dict[str, Any]:
                        with httpx.Client(timeout=timeout, limits=limits, follow_redirects=False, trust_env=False) as nested:
                            return _retrieve_core_evidence(
                                nested,
                                api_base=base,
                                headers=headers,
                                dataset_id=str(dataset_id),
                                document_id=doc_id,
                                marker=marker,
                            )

                    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                        primary_future = executor.submit(_retrieve_summary, api_base)
                        secondary_future = executor.submit(_retrieve_summary, secondary_api_base)
                        report["retrieval"] = {
                            "primary": primary_future.result(),
                            "secondary": secondary_future.result(),
                            "concurrent": True,
                        }
                    print("[smoke] retrieval: primary+secondary evidence ok")
                else:
                    report["retrieval"] = _retrieve_core_evidence(
                        client,
                        api_base=api_base,
                        headers=headers,
                        dataset_id=str(dataset_id),
                        document_id=doc_id,
                        marker=marker,
                    )
                    print("[smoke] retrieval: evidence ok")

                if created_dataset:
                    report["cleanup"] = _cleanup_created_dataset(
                        client,
                        api_base=api_base,
                        headers=headers,
                        dataset_id=str(dataset_id),
                        document_id=doc_id,
                    )
                    print("[smoke] cleanup: dataset deleted")
                else:
                    report["cleanup"] = {"skipped": True, "reason": "dataset_reused"}

                report["ok"] = True
                report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
                print(f"[smoke] OK in {report['elapsed_ms']}ms")
                return 0

            require_structured = not bool(args.allow_unstructured)
            chat_payload: dict[str, Any] = {
                "message": (
                    "What is the value of launch_code in SMOKE_FACT? "
                    "Return only the structured JSON object as instructed."
                ),
                # Use the dataset scope for the freshly uploaded smoke corpus.
                # In real environments this is more stable than document-id scoped
                # retrieval immediately after ingestion, while still keeping the
                # query bounded to the synthetic smoke dataset created by this script.
                "dataset_id": str(dataset_id),
                "structured_output": True,
                "structured_preset": str(args.structured_preset or "summary"),
                "stream": False,
                # Keep the smoke path deterministic and bounded in real environments:
                # - avoid the graph pipeline and multi-query fan-out
                # - use a mid-scale top_k that matches the repo guardrail
                "rag_config": {
                    "use_graph": False,
                    "top_k": 10,
                    "enable_multi_query": False,
                },
            }
            chat_resp = request_with_retries(
                client,
                "POST",
                _join(api_base, "chat"),
                expected={200},
                headers=headers,
                json=chat_payload,
            )
            chat_json = _parse_json(chat_resp)
            if not isinstance(chat_json, dict):
                raise CallError(
                    method="POST",
                    url=_join(api_base, "chat"),
                    status_code=chat_resp.status_code,
                    detail="chat response is not JSON object",
                )

            structured_flag = bool(chat_json.get("structured") is True)
            structured_data = chat_json.get("structured_data")
            content = str(chat_json.get("content") or "")
            answer = ""
            summary = ""
            if isinstance(structured_data, dict):
                answer = str(structured_data.get("answer") or "")
                summary = str(structured_data.get("summary") or "")

            report["chat"] = {
                "structured": structured_flag,
                "structured_type": type(structured_data).__name__ if structured_data is not None else None,
                "structured_preset": str(args.structured_preset or "summary"),
                "content_chars": len(content),
            }

            if require_structured and (not structured_flag or not isinstance(structured_data, dict)):
                status = _get_system_status_best_effort(client, api_base=api_base, headers=headers)
                if status:
                    report["system_status"] = status
                raise CallError(
                    method="POST",
                    url=_join(api_base, "chat"),
                    status_code=chat_resp.status_code,
                    detail=(
                        "structured output validation failed. "
                        "Ensure LLM is configured and that structured presets are enabled."
                    ),
                )

            haystack = "\n".join([answer, summary, content])
            if smoke_fact not in haystack:
                excerpt = redact_secrets(haystack[:400])
                raise CallError(
                    method="POST",
                    url=_join(api_base, "chat"),
                    status_code=chat_resp.status_code,
                    detail=f"answer does not contain expected launch_code. excerpt={excerpt!r}",
                )

            print("[smoke] chat: structured ok" if structured_flag else "[smoke] chat: ok (unstructured allowed)")
            report["ok"] = True
            report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)

    except CallError as exc:
        report["ok"] = False
        report["error"] = str(exc)
        report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        print(f"[smoke] ERROR: {exc}", file=sys.stderr)
        if args.out:
            Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[smoke] wrote report: {args.out}", file=sys.stderr)
        return 1
    except Exception as exc:
        report["ok"] = False
        report["error"] = redact_secrets(str(exc) or exc.__class__.__name__)
        report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        print(f"[smoke] ERROR: {report['error']}", file=sys.stderr)
        if args.out:
            Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[smoke] wrote report: {args.out}", file=sys.stderr)
        return 2
    finally:
        if args.out and report:
            # Best-effort: on success write report too.
            try:
                Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    if args.out:
        print(f"[smoke] wrote report: {args.out}")
    print(f"[smoke] OK in {int((time.perf_counter() - started) * 1000)}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
