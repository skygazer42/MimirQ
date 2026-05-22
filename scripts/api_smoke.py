import argparse
import json
import mimetypes
import os
import re
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

API_SETTINGS = '/api/v1/settings'
API_SETTINGS_LLM_TEST = '/api/v1/settings/llm/test'
API_DATASETS = '/api/v1/datasets/'
API_DATASET_BY_ID = '/api/v1/datasets/{dataset_id}'
API_DATASET_INGESTION_POLICY = '/api/v1/datasets/{dataset_id}/ingestion-policy'
API_DOCUMENT_BY_ID = '/api/v1/documents/{document_id}'
API_DOCUMENTS_MANUAL = '/api/v1/documents/manual'
API_DOCUMENTS_PREVIEW = '/api/v1/documents/preview'
API_DOCUMENT_CHUNK_BY_ID = '/api/v1/documents/{document_id}/chunks/{chunk_id}'
API_BATCH_UPLOAD_APPLY_URLS = '/api/v1/documents/batch-upload/apply-urls'
API_BATCH_UPLOAD_STATUS = '/api/v1/documents/batch-upload/status/{batch_id}'
API_PIPELINE_INGESTION_PREVIEW = '/api/v1/pipeline/ingestion-preview'
API_PIPELINE_GOVERNANCE_PROFILES = '/api/v1/pipeline/governance-profiles'
API_PIPELINE_GOVERNANCE_PROFILE_BY_REF = '/api/v1/pipeline/governance-profiles/{profile_ref}'
API_PIPELINE_UPLOAD_ZIP_WITH_IMAGES = '/api/v1/pipeline/upload-zip-with-images'
API_PARSING_DOCUMENTS = '/api/v1/parsing/documents'
API_PARSING_DOCUMENT_CONTENT_BY_ID = '/api/v1/parsing/documents/{document_id}/content'
API_CHAT_CONVERSATIONS = '/api/v1/chat/conversations'
API_CHAT_STREAM = '/api/v1/chat/stream'
API_CHAT_MESSAGES_BY_CONVERSATION = '/api/v1/chat/conversations/{conversation_id}/messages'
API_CHAT_CHECKPOINTS_BY_CONVERSATION = '/api/v1/chat/conversations/{conversation_id}/checkpoints'
API_PROMPT_TEMPLATES = '/api/v1/prompt-templates'
API_PROMPT_TEMPLATE_BY_ID = '/api/v1/prompt-templates/{template_id}'
API_RAG_RETRIEVE_PREVIEW = '/api/v1/rag/retrieve-preview'
API_RAG_PROMPT_PREVIEW = '/api/v1/rag/prompt-preview'
API_EVAL_RAGAS_RUNS = '/api/v1/evaluations/ragas/runs'
API_EVAL_REGRESSION_CASES = '/api/v1/evaluations/ragas/regression/cases'
API_EVAL_REGRESSION_RUNS = '/api/v1/evaluations/ragas/regression/runs'
API_EVAL_TEST_GEN_FROM_DOCUMENTS = '/api/v1/evaluations/ragas/test-gen/from-documents'
API_EVAL_TEST_GEN_FROM_CONVERSATIONS = '/api/v1/evaluations/ragas/test-gen/from-conversations'
API_FEEDBACK_MESSAGES = '/api/v1/feedback/messages'
API_KG_SEARCH = '/api/v1/kg/search'
MEDIA_TYPE_TEXT_PLAIN = 'text/plain'


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


def build_headers(tenant_id: str, user_id: str | None, token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif user_id:
        headers["X-User-ID"] = user_id
    return headers


def is_expected(status: int, expected: Iterable[int]) -> bool:
    return status in set(expected)


@dataclass
class CallResult:
    method: str
    path: str
    status: int | None
    ok: bool
    note: str


class SmokeRunner:
    def __init__(self, client: httpx.Client, base_url: str, headers: dict[str, str]):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.covered: set[tuple[str, str]] = set()
        self.results: list[CallResult] = []

    def mark(self, method: str, path_template: str) -> None:
        self.covered.add((method.upper(), path_template))

    def call(
        self,
        method: str,
        path_template: str,
        path: str,
        expected: Iterable[int],
        **kwargs: Any,
    ) -> httpx.Response | None:
        self.mark(method, path_template)
        url = f"{self.base_url}{path}"
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}) or {})
        resp = None
        for attempt in range(3):
            try:
                resp = self.client.request(method, url, headers=headers, **kwargs)
            except Exception as exc:
                self.results.append(
                    CallResult(method.upper(), path_template, None, False, f"request failed: {exc}")
                )
                return None
            if resp.status_code != 429 or attempt == 2:
                break
            retry_after = None
            try:
                retry_after = float((resp.json() or {}).get("retry_after"))
            except Exception:
                retry_after = None
            time.sleep(retry_after or 0.25)
        if resp is None:
            self.results.append(
                CallResult(method.upper(), path_template, None, False, "request failed: no response")
            )
            return None
        ok = is_expected(resp.status_code, expected)
        note = "" if ok else f"unexpected status {resp.status_code}: {resp.text[:400]}"
        self.results.append(CallResult(method.upper(), path_template, resp.status_code, ok, note))
        return resp

    def probe(
        self,
        method: str,
        path_template: str,
        path: str,
        expected: Iterable[int],
        **kwargs: Any,
    ) -> bool:
        """
        Lightweight request that avoids downloading full response bodies.

        Useful for large exports or endpoints that might stream for a while: we only
        validate the status code and (on failure) capture a tiny snippet.
        """
        self.mark(method, path_template)
        url = f"{self.base_url}{path}"
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}) or {})

        for attempt in range(3):
            try:
                with self.client.stream(method, url, headers=headers, **kwargs) as resp:
                    if resp.status_code == 429 and attempt < 2:
                        retry_after = None
                        try:
                            retry_after = float((resp.json() or {}).get("retry_after"))
                        except Exception:
                            retry_after = None
                        time.sleep(retry_after or 0.25)
                        continue

                    ok = is_expected(resp.status_code, expected)
                    if ok:
                        self.results.append(CallResult(method.upper(), path_template, resp.status_code, True, ""))
                        return True

                    snippet = ""
                    try:
                        for chunk in resp.iter_bytes():
                            if not chunk:
                                continue
                            snippet = chunk[:400].decode("utf-8", errors="replace")
                            break
                    except Exception:
                        snippet = ""

                    note = f"unexpected status {resp.status_code}: {snippet}"
                    self.results.append(CallResult(method.upper(), path_template, resp.status_code, False, note))
                    return False
            except Exception as exc:
                self.results.append(CallResult(method.upper(), path_template, None, False, f"request failed: {exc}"))
                return False

        self.results.append(CallResult(method.upper(), path_template, None, False, "request failed after retries"))
        return False

    def stream(
        self,
        method: str,
        path_template: str,
        path: str,
        expected: Iterable[int],
        **kwargs: Any,
    ) -> tuple[bool, str]:
        self.mark(method, path_template)
        url = f"{self.base_url}{path}"
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}) or {})
        for attempt in range(3):
            try:
                with self.client.stream(method, url, headers=headers, **kwargs) as resp:
                    if resp.status_code == 429 and attempt < 2:
                        retry_after = None
                        try:
                            retry_after = float((resp.json() or {}).get("retry_after"))
                        except Exception:
                            retry_after = None
                        time.sleep(retry_after or 0.25)
                        continue
                    ok = is_expected(resp.status_code, expected)
                    if not ok:
                        note = f"unexpected status {resp.status_code}: {resp.text[:400]}"
                        self.results.append(CallResult(method.upper(), path_template, resp.status_code, False, note))
                        return False, note
                    first_line = None
                    for line in resp.iter_lines():
                        if line:
                            first_line = line
                            break
                    if not first_line:
                        note = "stream returned no data"
                        self.results.append(CallResult(method.upper(), path_template, resp.status_code, False, note))
                        return False, note
                    self.results.append(CallResult(method.upper(), path_template, resp.status_code, True, ""))
                    return True, ""
            except Exception as exc:
                note = f"stream failed: {exc}"
                self.results.append(CallResult(method.upper(), path_template, None, False, note))
                return False, note
        note = "stream failed after retries"
        self.results.append(CallResult(method.upper(), path_template, None, False, note))
        return False, note


def load_openapi_paths(client: httpx.Client, base_url: str, openapi_path: str | None) -> set[tuple[str, str]]:
    if openapi_path:
        spec = json.loads(Path(openapi_path).read_text(encoding="utf-8"))
    else:
        resp = client.get(f"{base_url.rstrip('/')}/openapi.json")
        resp.raise_for_status()
        spec = resp.json()
    paths = spec.get("paths", {})
    out: set[tuple[str, str]] = set()
    for path, ops in paths.items():
        for method in ops.keys():
            if method.startswith("x-"):
                continue
            out.add((method.upper(), path))
    return out


def parse_json(resp: httpx.Response | None) -> dict[str, Any]:
    if not resp:
        return {}
    try:
        return resp.json() if resp.content else {}
    except Exception:
        return {}


def parse_csv_items(value: str | None) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for raw in (value or "").split(","):
        item = raw.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
    return items


def resolve_repo_path(repo_root: Path, value: str | None) -> Path | None:
    raw = (value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    return repo_root / path


def call_embedding_drift_snapshot(runner: SmokeRunner, *, timeout: float) -> None:
    """Exercise the drift snapshot outside the tiny final OpenAPI sweep timeout."""
    runner.probe(
        "GET",
        "/api/v1/observability/embedding-drift/snapshot",
        "/api/v1/observability/embedding-drift/snapshot",
        expected=[200, 400, 503],
        timeout=max(10.0, float(timeout)),
    )


def run_live_parser_preview_smokes(
    runner: SmokeRunner,
    fixture_path: Path,
    parser_backends: Iterable[str],
    timeout: float,
) -> None:
    backends = parse_csv_items(",".join(str(item) for item in parser_backends))
    if not backends:
        return
    if not fixture_path.exists():
        raise FileNotFoundError(f"live parser fixture not found: {fixture_path}")

    media_type = mimetypes.guess_type(fixture_path.name)[0] or "application/octet-stream"
    for backend in backends:
        with fixture_path.open("rb") as fh:
            resp = runner.call(
                "POST",
                API_DOCUMENTS_PREVIEW,
                API_DOCUMENTS_PREVIEW,
                expected=[200],
                timeout=timeout,
                files={"file": (fixture_path.name, fh, media_type)},
                data={"parser_backend": backend},
            )
        if not runner.results:
            continue
        result = runner.results[-1]
        if resp is None or not result.ok:
            if not result.note:
                result.note = f"live parser preview failed for parser_backend={backend}"
            continue
        payload = parse_json(resp)
        body_backend = str(payload.get("parser_backend") or "").strip()
        segments = payload.get("segments")
        if body_backend != backend:
            result.ok = False
            result.note = (
                f"live parser preview returned parser_backend={body_backend or '<missing>'} "
                f"for requested parser_backend={backend}"
            )
            continue
        if not isinstance(segments, list) or not segments:
            result.ok = False
            result.note = f"live parser preview returned empty segments for parser_backend={backend}"


_PATH_PARAM_RE = re.compile(r"{([^}]+)}")


def materialize_openapi_path(path_template: str) -> str:
    """
    Convert an OpenAPI path template into a concrete path for probing.

    We intentionally use random IDs so most mutation endpoints short-circuit with 404,
    avoiding side effects while still validating the route wiring.
    """

    def repl(match: re.Match[str]) -> str:
        name = (match.group(1) or "").strip().lower()
        if not name:
            return "smoke"
        if name in {"profile_ref", "governance_profile_ref"}:
            return "builtin:kb_default"
        if "pipeline_hash" in name:
            return "smoke"
        if "finding_key" in name:
            return "smoke"
        if "ref" in name and "profile" in name:
            return "builtin:kb_default"
        if "id" in name or name.endswith("_uuid"):
            return str(uuid.uuid4())
        return "smoke"

    return _PATH_PARAM_RE.sub(repl, path_template)


def probe_uncovered_openapi_endpoints(runner: SmokeRunner, openapi_paths: set[tuple[str, str]]) -> None:
    """
    Ensure every OpenAPI operation is at least reachable.

    For endpoints not exercised by the scenario-driven smoke flow above, we do a
    best-effort probe that accepts auth/validation/feature-gate errors (4xx) but
    fails on unexpected 5xx or transport errors.
    """
    remaining = sorted(openapi_paths - runner.covered)
    if not remaining:
        return

    expected = [
        # Success
        200, 201, 202, 204,
        # Common "reachable but not allowed" outcomes
        400, 401, 403, 404, 405, 409, 410, 415, 422,
        # Rate limiting / optional subsystems
        429, 503,
    ]

    for method, path_template in remaining:
        path = materialize_openapi_path(path_template)
        # Keep this very small; uncovered endpoints are mostly feature-gated (404)
        # or validation-gated (422) and should return quickly.
        kwargs: dict[str, Any] = {"timeout": 2.0}
        if method in {"POST", "PUT", "PATCH"}:
            # Prefer validation errors over side effects.
            kwargs["json"] = {}
        runner.probe(method, path_template, path, expected=expected, **kwargs)


def create_zip_with_image(tmp_dir: Path) -> Path:
    import zipfile

    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x01\x01\x01\x00\x18\xdd\x8d\x18"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    md_content = "![demo](images/demo.png)\n\n# Smoke\n\nHello."
    tmp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = tmp_dir / f"smoke-{uuid.uuid4().hex}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.md", md_content)
        zf.writestr("images/demo.png", png_bytes)
    return zip_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test MimirQ API endpoints.")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--auth-mode", default=None)
    parser.add_argument("--openapi", default=None, help="Optional OpenAPI JSON file path.")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--live-parser-backends",
        default="",
        help="Optional comma-separated parser backends for real PDF preview smoke (for example: deepseek_ocr,mineru).",
    )
    parser.add_argument(
        "--live-parser-fixture",
        default="",
        help="Repo-relative or absolute fixture path used by --live-parser-backends.",
    )
    parser.add_argument(
        "--live-parser-timeout",
        type=float,
        default=180.0,
        help="Timeout for each --live-parser-backends preview request in seconds.",
    )
    parser.add_argument("--skip-llm-test", action="store_true")
    parser.add_argument("--skip-mineru", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    dotenv = load_dotenv(repo_root / ".env")
    live_parser_backends = parse_csv_items(args.live_parser_backends)
    live_parser_fixture = resolve_repo_path(repo_root, args.live_parser_fixture)
    if live_parser_backends and live_parser_fixture is None:
        parser.error("--live-parser-fixture is required when --live-parser-backends is set")
    if live_parser_backends and live_parser_fixture is not None and not live_parser_fixture.exists():
        parser.error(f"--live-parser-fixture not found: {live_parser_fixture}")

    base_url = args.base_url or env_or(dotenv, "NEXT_PUBLIC_API_URL", "http://localhost:8000")
    tenant_id = args.tenant_id or env_or(dotenv, "NEXT_PUBLIC_TENANT_ID", "00000000-0000-0000-0000-000000000000")
    auth_mode = (args.auth_mode or env_or(dotenv, "AUTH_MODE", "header")).lower()

    user_email = f"smoke_{uuid.uuid4().hex[:8]}@example.com"
    user_name = f"smoke_{uuid.uuid4().hex[:8]}"
    user_password = "smoke-pass-123"

    llm_api_key = env_or(dotenv, "LLM_API_KEY", "")
    llm_api_base = env_or(dotenv, "LLM_API_BASE", "https://api.openai.com/v1")
    llm_model = env_or(dotenv, "LLM_MODEL", "gpt-4o-mini")

    with httpx.Client(timeout=args.timeout, follow_redirects=False, trust_env=False) as client:
        openapi_paths = load_openapi_paths(client, base_url, args.openapi)
        headers: dict[str, str] = build_headers(tenant_id, None, None)
        runner = SmokeRunner(client, base_url, headers)
        # Keep smoke requests offline-friendly and fast: avoid default chat retrieval
        # profile (hybrid_ce) which can trigger local cross-encoder model downloads.
        smoke_rag_config = {
            "max_tokens": 256,
            "top_k": 3,
            "score_threshold": 0.0,
            "retrieval_mode": "keyword",
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_reranker": False,
            "reranker_provider": "none",
            "enable_weight_rerank": False,
        }

        # Untagged and health endpoints.
        runner.call("GET", "/", "/", expected=[200])
        runner.call("GET", "/health", "/health", expected=[200])
        runner.call("GET", "/api/v1/health", "/api/v1/health", expected=[200])
        runner.call("GET", "/api/v1/health/ready", "/api/v1/health/ready", expected=[200])

        # Meta endpoint.
        runner.call("GET", "/api/v1/meta", "/api/v1/meta", expected=[200])

        # Auth endpoints.
        register_payload = {"email": user_email, "username": user_name, "password": user_password}
        reg_resp = runner.call(
            "POST",
            "/api/v1/auth/register",
            "/api/v1/auth/register",
            expected=[201, 400],
            json=register_payload,
        )
        reg_data = parse_json(reg_resp)
        token = (reg_data.get("token") or {}).get("access_token")
        user_id = (reg_data.get("user") or {}).get("id")

        login_payload = {"identifier": user_email, "password": user_password}
        login_resp = runner.call(
            "POST",
            "/api/v1/auth/login",
            "/api/v1/auth/login",
            expected=[200],
            json=login_payload,
        )
        login_data = parse_json(login_resp)
        token = token or (login_data.get("token") or {}).get("access_token")
        user_id = user_id or (login_data.get("user") or {}).get("id")

        if auth_mode == "jwt" and token:
            runner.headers = build_headers(tenant_id, None, token)
        elif user_id:
            runner.headers = build_headers(tenant_id, user_id, None)
        else:
            fallback_user = env_or(dotenv, "NEXT_PUBLIC_USER_ID", "demo")
            runner.headers = build_headers(tenant_id, fallback_user, None)

        runner.call("GET", "/api/v1/auth/me", "/api/v1/auth/me", expected=[200])

        # Settings endpoints.
        runner.call("GET", API_SETTINGS, API_SETTINGS, expected=[200])
        runner.call("GET", "/api/v1/settings/status", "/api/v1/settings/status", expected=[200])
        runner.call("PUT", API_SETTINGS, API_SETTINGS, expected=[200], json={})
        if not args.skip_llm_test:
            runner.call(
                "POST",
                API_SETTINGS_LLM_TEST,
                API_SETTINGS_LLM_TEST,
                expected=[200, 400],
                json={
                    "api_key": llm_api_key,
                    "api_base": llm_api_base,
                    "model": llm_model,
                    "temperature": 0.0,
                    "timeout": 10,
                    "max_retries": 1,
                },
            )
        else:
            runner.mark("POST", API_SETTINGS_LLM_TEST)

        # Dataset endpoints.
        dataset_payload = {"name": f"Smoke Dataset {uuid.uuid4().hex[:6]}", "description": "smoke"}
        ds_resp = runner.call("POST", API_DATASETS, API_DATASETS, expected=[201], json=dataset_payload)
        ds_id = parse_json(ds_resp).get("id")
        runner.call("GET", API_DATASETS, API_DATASETS, expected=[200])
        if ds_id:
            runner.call("GET", API_DATASET_BY_ID, f"/api/v1/datasets/{ds_id}", expected=[200])
            runner.call(
                "PATCH",
                API_DATASET_BY_ID,
                f"/api/v1/datasets/{ds_id}",
                expected=[200],
                json={"description": "smoke-updated"},
            )

        # Dataset ingestion policy endpoints.
        if ds_id:
            policy_payload = {
                "version": "1",
                "rules": [
                    {
                        "id": "txt-default",
                        "name": "TXT Default",
                        "enabled": True,
                        "match": {"extensions": [".txt"]},
                        "preprocess": {"enabled": False, "steps": []},
                        "parser_backend": "auto",
                        "governance_profile_ref": "builtin:kb_default",
                        "pipeline_patch": {"governance_enabled": True},
                    }
                ],
            }
            runner.call(
                "PUT",
                API_DATASET_INGESTION_POLICY,
                f"/api/v1/datasets/{ds_id}/ingestion-policy",
                expected=[200],
                json=policy_payload,
            )
            runner.call(
                "GET",
                API_DATASET_INGESTION_POLICY,
                f"/api/v1/datasets/{ds_id}/ingestion-policy",
                expected=[200],
            )
            runner.call(
                "GET",
                "/api/v1/datasets/{dataset_id}/ingestion-policy/export",
                f"/api/v1/datasets/{ds_id}/ingestion-policy/export",
                expected=[200],
            )
            policy_bytes = json.dumps(policy_payload, ensure_ascii=False).encode("utf-8")
            runner.call(
                "POST",
                "/api/v1/datasets/{dataset_id}/ingestion-policy/import",
                f"/api/v1/datasets/{ds_id}/ingestion-policy/import",
                expected=[200, 409],
                files={"file": ("policy.json", policy_bytes, "application/json")},
                data={"replace": "true"},
            )
        else:
            runner.mark("GET", API_DATASET_INGESTION_POLICY)
            runner.mark("PUT", API_DATASET_INGESTION_POLICY)
            runner.mark("POST", "/api/v1/datasets/{dataset_id}/ingestion-policy/import")
            runner.mark("GET", "/api/v1/datasets/{dataset_id}/ingestion-policy/export")

        # Documents endpoints: upload a small text file.
        sample_text = "Smoke test document.\nSecond line."
        files = {"file": ("smoke.txt", sample_text.encode("utf-8"), MEDIA_TYPE_TEXT_PLAIN)}
        data = {"dataset_id": ds_id} if ds_id else {}
        doc_resp = runner.call(
            "POST",
            "/api/v1/documents/upload",
            "/api/v1/documents/upload",
            expected=[201],
            files=files,
            data=data,
        )
        doc_id = parse_json(doc_resp).get("id")
        first_chunk_id = None
        batch_doc_ids: list[str] = []

        # Batch upload (multi-file).
        files_batch = [
            ("files", ("batch1.txt", b"batch-one", MEDIA_TYPE_TEXT_PLAIN)),
            ("files", ("batch2.txt", b"batch-two", MEDIA_TYPE_TEXT_PLAIN)),
        ]
        data_batch = {"dataset_id": ds_id} if ds_id else {}
        batch_resp = runner.call(
            "POST",
            "/api/v1/documents/upload-batch",
            "/api/v1/documents/upload-batch",
            expected=[201],
            files=files_batch,
            data=data_batch,
        )
        batch_payload = parse_json(batch_resp)
        for item in batch_payload.get("successful") or []:
            if not isinstance(item, dict):
                continue
            did = item.get("document_id") or item.get("id")
            if did:
                batch_doc_ids.append(str(did))

        runner.call("GET", "/api/v1/documents/", "/api/v1/documents/?limit=5", expected=[200])
        runner.call("GET", "/api/v1/documents/stats", "/api/v1/documents/stats", expected=[200])

        if doc_id:
            runner.call("GET", API_DOCUMENT_BY_ID, f"/api/v1/documents/{doc_id}", expected=[200])
            runner.call(
                "GET",
                "/api/v1/documents/{document_id}/status",
                f"/api/v1/documents/{doc_id}/status",
                expected=[200],
            )
            runner.call(
                "PATCH",
                "/api/v1/documents/{document_id}/metadata",
                f"/api/v1/documents/{doc_id}/metadata",
                expected=[200, 403, 404],
                json={"patch": {"source": "smoke"}, "replace": False},
            )
            runner.call(
                "GET",
                "/api/v1/documents/{document_id}/download",
                f"/api/v1/documents/{doc_id}/download?inline=true",
                expected=[200, 403, 404],
            )
        else:
            runner.mark("PATCH", "/api/v1/documents/{document_id}/metadata")
            runner.mark("GET", "/api/v1/documents/{document_id}/download")

        # Preview endpoints.
        runner.call(
            "POST",
            API_DOCUMENTS_PREVIEW,
            API_DOCUMENTS_PREVIEW,
            expected=[200],
            timeout=120.0,
            files={"file": ("preview.txt", b"preview", MEDIA_TYPE_TEXT_PLAIN)},
        )
        if live_parser_backends and live_parser_fixture is not None:
            run_live_parser_preview_smokes(
                runner=runner,
                fixture_path=live_parser_fixture,
                parser_backends=live_parser_backends,
                timeout=args.live_parser_timeout,
            )
        runner.call(
            "POST",
            "/api/v1/documents/chunk-preview",
            "/api/v1/documents/chunk-preview",
            expected=[200],
            files={"file": ("chunk.txt", b"chunk preview text", MEDIA_TYPE_TEXT_PLAIN)},
            data={"chunk_size": 200, "chunk_overlap": 20},
        )

        # Manual document creation.
        if ds_id:
            manual_payload = {
                "dataset_id": ds_id,
                "filename": "manual.txt",
                "file_type": "txt",
                "file_size": 12,
                "chunks": [{"content": "manual chunk"}],
            }
            manual_resp = runner.call(
                "POST",
                API_DOCUMENTS_MANUAL,
                API_DOCUMENTS_MANUAL,
                expected=[201],
                json=manual_payload,
            )
            manual_doc_id = parse_json(manual_resp).get("id")
        else:
            runner.mark("POST", API_DOCUMENTS_MANUAL)
            manual_doc_id = None

        batch_patch_ids: list[str] = []
        if doc_id:
            batch_patch_ids.append(str(doc_id))
        if manual_doc_id:
            batch_patch_ids.append(str(manual_doc_id))
        if not batch_patch_ids:
            batch_patch_ids.append(str(uuid.uuid4()))

        runner.call(
            "POST",
            "/api/v1/documents/batch/metadata",
            "/api/v1/documents/batch/metadata",
            expected=[200],
            json={
                "document_ids": batch_patch_ids,
                "patch": {"batch": True, "source": "smoke"},
                "replace": False,
            },
        )
        runner.call(
            "POST",
            "/api/v1/documents/batch-delete",
            "/api/v1/documents/batch-delete",
            expected=[200],
            json={"document_ids": [str(uuid.uuid4())]},
        )

        cancel_target = str(manual_doc_id or uuid.uuid4())
        runner.call(
            "POST",
            "/api/v1/documents/{document_id}/cancel",
            f"/api/v1/documents/{cancel_target}/cancel",
            expected=[200, 404, 409],
        )

        retry_target = str(manual_doc_id or uuid.uuid4())
        runner.call(
            "POST",
            "/api/v1/documents/{document_id}/retry",
            f"/api/v1/documents/{retry_target}/retry",
            expected=[200, 404, 409],
        )

        # Batch upload URL apply (MinerU).
        if args.skip_mineru:
            runner.mark("POST", API_BATCH_UPLOAD_APPLY_URLS)
            runner.mark("GET", API_BATCH_UPLOAD_STATUS)
        else:
            apply_resp = runner.call(
                "POST",
                API_BATCH_UPLOAD_APPLY_URLS,
                API_BATCH_UPLOAD_APPLY_URLS,
                expected=[200, 400, 500, 503],
                json={"files": [{"name": "a.pdf", "data_id": "smoke-a"}]},
            )
            apply_data = parse_json(apply_resp)
            batch_id = apply_data.get("batch_id")
            if batch_id:
                runner.call(
                    "GET",
                    API_BATCH_UPLOAD_STATUS,
                    API_BATCH_UPLOAD_STATUS.format(batch_id=batch_id),
                    expected=[200, 400, 404, 500, 503],
                )
            else:
                runner.call(
                    "GET",
                    API_BATCH_UPLOAD_STATUS,
                    "/api/v1/documents/batch-upload/status/invalid",
                    expected=[200, 400, 404, 500, 503],
                )

        # Image endpoints: expect not found for missing ids.
        runner.call(
            "GET",
            "/api/v1/documents/image-url/{img_id}",
            "/api/v1/documents/image-url/invalid",
            expected=[404, 503],
        )
        runner.call(
            "GET",
            "/api/v1/documents/image/{image_id}",
            "/api/v1/documents/image/invalid",
            expected=[404],
        )

        # Pipeline endpoints.
        runner.call("GET", "/api/v1/pipeline/capabilities", "/api/v1/pipeline/capabilities", expected=[200])
        runner.call(
            "POST",
            "/api/v1/pipeline/parse-preview",
            "/api/v1/pipeline/parse-preview",
            expected=[200],
            files={"file": ("pipe.txt", b"pipeline preview", MEDIA_TYPE_TEXT_PLAIN)},
        )
        runner.call(
            "POST",
            "/api/v1/pipeline/chunk-preview",
            "/api/v1/pipeline/chunk-preview",
            expected=[200],
            json={"markdown": "# Title\n\nContent"},
        )
        runner.call(
            "POST",
            "/api/v1/pipeline/clean-preview",
            "/api/v1/pipeline/clean-preview",
            expected=[200],
            json={"markdown": "A  \n\nB", "use_default_rules": True},
        )
        runner.call("GET", "/api/v1/pipeline/clean-rules", "/api/v1/pipeline/clean-rules", expected=[200])
        runner.call(
            "POST",
            "/api/v1/pipeline/governance-analyze",
            "/api/v1/pipeline/governance-analyze",
            expected=[200],
            json={"markdown": "<p>hello</p>\n\nA  \n\nB"},
        )
        if ds_id:
            runner.call(
                "POST",
                API_PIPELINE_INGESTION_PREVIEW,
                API_PIPELINE_INGESTION_PREVIEW,
                expected=[200, 400, 500],
                files={"file": ("ingest.txt", b"ingestion preview", MEDIA_TYPE_TEXT_PLAIN)},
                data={"dataset_id": ds_id},
            )
        else:
            runner.mark("POST", API_PIPELINE_INGESTION_PREVIEW)

        # Governance profile endpoints (custom CRUD + import/export).
        runner.call(
            "GET",
            API_PIPELINE_GOVERNANCE_PROFILES,
            "/api/v1/pipeline/governance-profiles?limit=5",
            expected=[200],
        )
        gov_key = f"smoke_profile_{uuid.uuid4().hex[:6]}"
        gov_resp = runner.call(
            "POST",
            API_PIPELINE_GOVERNANCE_PROFILES,
            API_PIPELINE_GOVERNANCE_PROFILES,
            expected=[201],
            json={
                "name": f"Smoke Governance {uuid.uuid4().hex[:6]}",
                "description": "smoke",
                "key": gov_key,
                "payload": {
                    "version": "1",
                    "input_formats": ["markdown"],
                    "pipeline_patch": {"governance_enabled": True},
                    "regex_rules": [],
                },
            },
        )
        gov_id = parse_json(gov_resp).get("id") or gov_key
        runner.call(
            "GET",
            API_PIPELINE_GOVERNANCE_PROFILE_BY_REF,
            f"/api/v1/pipeline/governance-profiles/{gov_id}",
            expected=[200],
        )
        runner.call(
            "PATCH",
            API_PIPELINE_GOVERNANCE_PROFILE_BY_REF,
            f"/api/v1/pipeline/governance-profiles/{gov_id}",
            expected=[200],
            json={"description": "smoke-updated"},
        )
        runner.call(
            "GET",
            "/api/v1/pipeline/governance-profiles/{profile_ref}/export",
            f"/api/v1/pipeline/governance-profiles/{gov_id}/export",
            expected=[200],
        )

        import_key = f"smoke_import_{uuid.uuid4().hex[:6]}"
        import_bytes = json.dumps(
            {
                "name": f"Smoke Imported {uuid.uuid4().hex[:6]}",
                "description": "smoke",
                "key": import_key,
                "payload": {
                    "version": "1",
                    "input_formats": ["markdown"],
                    "pipeline_patch": {"governance_enabled": True},
                    "regex_rules": [],
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        runner.call(
            "POST",
            "/api/v1/pipeline/governance-profiles/import",
            "/api/v1/pipeline/governance-profiles/import",
            expected=[200, 409],
            files={"file": ("profile.json", import_bytes, "application/json")},
            data={"overwrite": "true"},
        )
        runner.call(
            "GET",
            API_PIPELINE_GOVERNANCE_PROFILE_BY_REF,
            f"/api/v1/pipeline/governance-profiles/{import_key}",
            expected=[200, 404],
        )
        runner.call(
            "DELETE",
            API_PIPELINE_GOVERNANCE_PROFILE_BY_REF,
            f"/api/v1/pipeline/governance-profiles/{import_key}",
            expected=[204, 404],
        )
        runner.call(
            "DELETE",
            API_PIPELINE_GOVERNANCE_PROFILE_BY_REF,
            f"/api/v1/pipeline/governance-profiles/{gov_id}",
            expected=[204, 404],
        )
        runner.call(
            "POST",
            "/api/v1/pipeline/extract-keywords",
            "/api/v1/pipeline/extract-keywords",
            expected=[200],
            json={"text": "keyword extraction smoke", "provider": "jieba", "top_k": 3},
        )
        runner.call(
            "POST",
            "/api/v1/pipeline/llm-clean-preview",
            "/api/v1/pipeline/llm-clean-preview",
            expected=[200, 502, 503],
            json={"markdown": "LLM clean preview", "max_chars": 2000},
        )
        if ds_id:
            zip_path = create_zip_with_image(repo_root / "uploads" / "smoke_zip")
            with zip_path.open("rb") as fh:
                runner.call(
                    "POST",
                    API_PIPELINE_UPLOAD_ZIP_WITH_IMAGES,
                    API_PIPELINE_UPLOAD_ZIP_WITH_IMAGES,
                    expected=[200, 503],
                    files={"file": (zip_path.name, fh, "application/zip")},
                    data={"dataset_id": ds_id},
                )
        else:
            runner.mark("POST", API_PIPELINE_UPLOAD_ZIP_WITH_IMAGES)

        # Parsing workspace endpoints (persistent drafts for /parsing UI).
        runner.call(
            "GET",
            API_PARSING_DOCUMENTS,
            "/api/v1/parsing/documents?limit=5",
            expected=[200],
        )
        parsing_doc_id = None
        parsing_upload = runner.call(
            "POST",
            API_PARSING_DOCUMENTS,
            API_PARSING_DOCUMENTS,
            expected=[201],
            files={"file": ("parsing.txt", b"parsing workspace", MEDIA_TYPE_TEXT_PLAIN)},
            data={"parser_backend": "auto"},
        )
        parsing_doc_id = parse_json(parsing_upload).get("id")
        if parsing_doc_id:
            runner.call(
                "POST",
                "/api/v1/parsing/documents/{document_id}/parse",
                f"/api/v1/parsing/documents/{parsing_doc_id}/parse",
                expected=[200, 400, 500],
            )
            runner.call(
                "GET",
                API_PARSING_DOCUMENT_CONTENT_BY_ID,
                f"/api/v1/parsing/documents/{parsing_doc_id}/content",
                expected=[200],
            )
            runner.call(
                "PATCH",
                API_PARSING_DOCUMENT_CONTENT_BY_ID,
                f"/api/v1/parsing/documents/{parsing_doc_id}/content",
                expected=[200],
                json={"markdown_content": "# Edited\n\nok", "original_markdown_content": "# Edited\n\nok"},
            )
            runner.call(
                "DELETE",
                "/api/v1/parsing/documents/{document_id}",
                f"/api/v1/parsing/documents/{parsing_doc_id}",
                expected=[204],
            )
        else:
            runner.mark("POST", "/api/v1/parsing/documents/{document_id}/parse")
            runner.mark("GET", API_PARSING_DOCUMENT_CONTENT_BY_ID)
            runner.mark("PATCH", API_PARSING_DOCUMENT_CONTENT_BY_ID)
            runner.mark("DELETE", "/api/v1/parsing/documents/{document_id}")

        # Poll document status until ready (best effort).
        if doc_id:
            status_url = f"/api/v1/documents/{doc_id}/status"
            for _ in range(30):
                resp = runner.call(
                    "GET",
                    "/api/v1/documents/{document_id}/status",
                    status_url,
                    expected=[200],
                )
                status = parse_json(resp).get("status")
                if status in {"completed", "failed"}:
                    break
                time.sleep(1)

        # Document pipeline + chunk browsing endpoints.
        if doc_id:
            runner.call(
                "PATCH",
                "/api/v1/documents/{document_id}/pipeline",
                f"/api/v1/documents/{doc_id}/pipeline",
                expected=[200, 404, 409],
                json={"patch": {"governance_enabled": True}, "replace": False},
            )
            chunks_resp = runner.call(
                "GET",
                "/api/v1/documents/{document_id}/chunks",
                f"/api/v1/documents/{doc_id}/chunks?limit=5",
                expected=[200],
            )
            items = parse_json(chunks_resp).get("items") or []
            first_chunk_id = items[0].get("id") if items else None
            runner.call(
                "GET",
                "/api/v1/documents/{document_id}/chunks/matches",
                f"/api/v1/documents/{doc_id}/chunks/matches?q=Smoke&limit=20",
                expected=[200],
            )
            if first_chunk_id:
                runner.call(
                    "GET",
                    API_DOCUMENT_CHUNK_BY_ID,
                    f"/api/v1/documents/{doc_id}/chunks/{first_chunk_id}",
                    expected=[200, 404],
                )
            else:
                runner.call(
                    "GET",
                    API_DOCUMENT_CHUNK_BY_ID,
                    f"/api/v1/documents/{doc_id}/chunks/{uuid.uuid4()}",
                    expected=[404],
                )
        else:
            runner.mark("PATCH", "/api/v1/documents/{document_id}/pipeline")
            runner.mark("GET", "/api/v1/documents/{document_id}/chunks")
            runner.mark("GET", "/api/v1/documents/{document_id}/chunks/matches")
            runner.mark("GET", API_DOCUMENT_CHUNK_BY_ID)

        # RAG visualization endpoints (similarity matrix UI).
        col_resp = runner.call(
            "GET",
            "/api/v1/ragviz/similarity/collections",
            "/api/v1/ragviz/similarity/collections",
            expected=[200],
        )
        collections = parse_json(col_resp).get("collections") or []
        x_collection = collections[0].get("id") if collections else "invalid"
        y_collection = collections[0].get("id") if collections else "invalid"
        runner.call(
            "POST",
            "/api/v1/ragviz/similarity/calculate",
            "/api/v1/ragviz/similarity/calculate",
            expected=[200],
            json={"x_collection": x_collection, "y_collection": y_collection, "max_items": 10},
        )

        # Chat endpoints (stream -> conversation).
        conversation_id = None
        if doc_id:
            conv_resp = runner.call(
                "POST",
                API_CHAT_CONVERSATIONS,
                API_CHAT_CONVERSATIONS,
                expected=[201],
                json={"title": "Smoke conversation", "document_ids": [doc_id]},
            )
            conversation_id = parse_json(conv_resp).get("id")
        else:
            runner.mark("POST", API_CHAT_CONVERSATIONS)

        # Non-streaming chat endpoint (best-effort; may fail without a valid LLM key).
        chat_path = "/api/v1/chat/" if ("POST", "/api/v1/chat/") in openapi_paths else "/api/v1/chat"
        if doc_id:
            # When --skip-llm-test is on, avoid executing any request that would call an LLM.
            # We'll still "cover" the route via the final OpenAPI probe (422/400 expected).
            if not args.skip_llm_test:
                runner.call(
                    "POST",
                    chat_path,
                    chat_path,
                    expected=[200, 500, 502, 503],
                    timeout=90.0,
                    json={
                        "message": "smoke non-stream",
                        "document_ids": [doc_id],
                        "stream": False,
                        "rag_config": dict(smoke_rag_config),
                    },
                )
        else:
            runner.mark("POST", chat_path)
        if doc_id:
            if not args.skip_llm_test:
                ok, _ = runner.stream(
                    "POST",
                    API_CHAT_STREAM,
                    API_CHAT_STREAM,
                    expected=[200],
                    timeout=90.0,
                    json={
                        "message": "smoke test",
                        "document_ids": [doc_id],
                        "rag_config": dict(smoke_rag_config),
                    },
                )
                if ok and not conversation_id:
                    # Fetch conversations and pick the latest.
                    conv_list = runner.call(
                        "GET",
                        API_CHAT_CONVERSATIONS,
                        "/api/v1/chat/conversations?limit=5",
                        expected=[200],
                    )
                    items = parse_json(conv_list).get("items") or []
                    if items:
                        conversation_id = items[0].get("id")
        else:
            runner.mark("POST", API_CHAT_STREAM)
            runner.mark("GET", API_CHAT_CONVERSATIONS)

        if conversation_id:
            runner.call(
                "GET",
                API_CHAT_MESSAGES_BY_CONVERSATION,
                API_CHAT_MESSAGES_BY_CONVERSATION.format(conversation_id=conversation_id),
                expected=[200],
            )
            runner.call(
                "GET",
                API_CHAT_CONVERSATIONS,
                "/api/v1/chat/conversations?limit=5",
                expected=[200],
            )
            runner.call(
                "GET",
                API_CHAT_CHECKPOINTS_BY_CONVERSATION,
                f"/api/v1/chat/conversations/{conversation_id}/checkpoints?limit=5",
                expected=[200],
            )
            runner.call(
                "GET",
                "/api/v1/chat/conversations/{conversation_id}/checkpoints/{checkpoint_id}",
                f"/api/v1/chat/conversations/{conversation_id}/checkpoints/invalid",
                expected=[404],
            )
            runner.call(
                "DELETE",
                API_CHAT_CHECKPOINTS_BY_CONVERSATION,
                API_CHAT_CHECKPOINTS_BY_CONVERSATION.format(conversation_id=conversation_id),
                expected=[204],
            )
        else:
            runner.mark("GET", API_CHAT_MESSAGES_BY_CONVERSATION)
            runner.mark("GET", API_CHAT_CHECKPOINTS_BY_CONVERSATION)
            runner.mark("GET", "/api/v1/chat/conversations/{conversation_id}/checkpoints/{checkpoint_id}")
            runner.mark("DELETE", API_CHAT_CHECKPOINTS_BY_CONVERSATION)

        # Prompt templates.
        tmpl_payload = {
            "name": f"Smoke Template {uuid.uuid4().hex[:6]}",
            "content": "Answer the question: {question}",
            "variables": ["question"],
            "is_active": True,
        }
        tmpl_resp = runner.call(
            "POST",
            API_PROMPT_TEMPLATES,
            API_PROMPT_TEMPLATES,
            expected=[201],
            json=tmpl_payload,
        )
        tmpl_id = parse_json(tmpl_resp).get("id")
        runner.call("GET", API_PROMPT_TEMPLATES, "/api/v1/prompt-templates?limit=5", expected=[200])
        if tmpl_id:
            runner.call(
                "GET",
                API_PROMPT_TEMPLATE_BY_ID,
                f"/api/v1/prompt-templates/{tmpl_id}",
                expected=[200],
            )
            runner.call(
                "POST",
                "/api/v1/prompt-templates/{template_id}/duplicate",
                f"/api/v1/prompt-templates/{tmpl_id}/duplicate",
                expected=[201],
            )
            runner.call(
                "POST",
                "/api/v1/prompt-templates/{template_id}/versions",
                f"/api/v1/prompt-templates/{tmpl_id}/versions",
                expected=[201],
                json={"content": "New version {question}", "is_active": True},
            )
            runner.call(
                "PUT",
                API_PROMPT_TEMPLATE_BY_ID,
                f"/api/v1/prompt-templates/{tmpl_id}",
                expected=[200],
                json={"description": "smoke-updated"},
            )

        # RAG endpoints (require documents).
        if doc_id:
            rag_payload = {"query": "smoke retrieval", "document_ids": [doc_id], "rag_config": dict(smoke_rag_config)}
            runner.call(
                "POST",
                API_RAG_RETRIEVE_PREVIEW,
                API_RAG_RETRIEVE_PREVIEW,
                expected=[200],
                json=rag_payload,
            )
            runner.call(
                "POST",
                API_RAG_PROMPT_PREVIEW,
                API_RAG_PROMPT_PREVIEW,
                expected=[200],
                json=rag_payload,
            )
        else:
            runner.mark("POST", API_RAG_RETRIEVE_PREVIEW)
            runner.mark("POST", API_RAG_PROMPT_PREVIEW)

        # Evaluation endpoints (require conversation).
        if conversation_id:
            eval_payload = {"conversation_id": conversation_id, "metrics": ["faithfulness"]}
            run_resp = runner.call(
                "POST",
                API_EVAL_RAGAS_RUNS,
                API_EVAL_RAGAS_RUNS,
                expected=[201],
                json=eval_payload,
            )
            run_id = parse_json(run_resp).get("id")
            runner.call(
                "GET",
                API_EVAL_RAGAS_RUNS,
                "/api/v1/evaluations/ragas/runs?limit=5",
                expected=[200],
            )
            if run_id:
                runner.call(
                    "GET",
                    "/api/v1/evaluations/ragas/runs/{run_id}",
                    f"/api/v1/evaluations/ragas/runs/{run_id}",
                    expected=[200],
                )
        else:
            runner.mark("POST", API_EVAL_RAGAS_RUNS)
            runner.mark("GET", API_EVAL_RAGAS_RUNS)
            runner.mark("GET", "/api/v1/evaluations/ragas/runs/{run_id}")

        if ds_id:
            case_id = None
            if doc_id and first_chunk_id:
                case_payload = {
                    "dataset_id": ds_id,
                    "document_ids": [doc_id],
                    "question": "smoke question",
                    "expected_answer": "smoke answer",
                    "reference_sources": [{"document_id": doc_id, "chunk_id": first_chunk_id}],
                }
                case_resp = runner.call(
                    "POST",
                    API_EVAL_REGRESSION_CASES,
                    API_EVAL_REGRESSION_CASES,
                    expected=[201],
                    json=case_payload,
                )
                case_id = parse_json(case_resp).get("id")
            else:
                runner.mark("POST", API_EVAL_REGRESSION_CASES)

            runner.call(
                "GET",
                API_EVAL_REGRESSION_CASES,
                "/api/v1/evaluations/ragas/regression/cases?limit=5",
                expected=[200],
            )
            reg_run_resp = runner.call(
                "POST",
                API_EVAL_REGRESSION_RUNS,
                API_EVAL_REGRESSION_RUNS,
                expected=[201, 400, 422],
                json={"case_ids": [case_id] if case_id else [], "metrics": ["faithfulness"]},
            )
            reg_run_id = parse_json(reg_run_resp).get("id")
            runner.call(
                "GET",
                API_EVAL_REGRESSION_RUNS,
                "/api/v1/evaluations/ragas/regression/runs?limit=5",
                expected=[200],
            )
            if reg_run_id:
                runner.call(
                    "GET",
                    "/api/v1/evaluations/ragas/regression/runs/{run_id}",
                    f"/api/v1/evaluations/ragas/regression/runs/{reg_run_id}",
                    expected=[200],
                )
            if case_id:
                runner.call(
                    "DELETE",
                    "/api/v1/evaluations/ragas/regression/cases/{case_id}",
                    f"/api/v1/evaluations/ragas/regression/cases/{case_id}",
                    expected=[204],
                )
            else:
                runner.mark("DELETE", "/api/v1/evaluations/ragas/regression/cases/{case_id}")
            test_gen_docs = {
                "document_ids": [doc_id] if doc_id else [],
                "num_questions": 1,
                "auto_save_as_cases": False,
            }
            runner.call(
                "POST",
                API_EVAL_TEST_GEN_FROM_DOCUMENTS,
                API_EVAL_TEST_GEN_FROM_DOCUMENTS,
                expected=[200, 400, 422, 500],
                json=test_gen_docs,
            )
        else:
            runner.mark("POST", API_EVAL_REGRESSION_CASES)
            runner.mark("GET", API_EVAL_REGRESSION_CASES)
            runner.mark("POST", API_EVAL_REGRESSION_RUNS)
            runner.mark("GET", API_EVAL_REGRESSION_RUNS)
            runner.mark("GET", "/api/v1/evaluations/ragas/regression/runs/{run_id}")
            runner.mark("POST", API_EVAL_TEST_GEN_FROM_DOCUMENTS)

        if conversation_id:
            test_gen_conv = {
                "conversation_ids": [conversation_id],
                "num_questions": 1,
                "auto_save_as_cases": False,
            }
            runner.call(
                "POST",
                API_EVAL_TEST_GEN_FROM_CONVERSATIONS,
                API_EVAL_TEST_GEN_FROM_CONVERSATIONS,
                expected=[200, 400, 500],
                json=test_gen_conv,
            )
        else:
            runner.mark("POST", API_EVAL_TEST_GEN_FROM_CONVERSATIONS)

        # Feedback endpoints.
        assistant_message_id = None
        if conversation_id:
            msg_resp = runner.call(
                "GET",
                API_CHAT_MESSAGES_BY_CONVERSATION,
                API_CHAT_MESSAGES_BY_CONVERSATION.format(conversation_id=conversation_id),
                expected=[200],
            )
            messages = parse_json(msg_resp).get("messages") or []
            for msg in reversed(messages):
                if (msg.get("role") or "").lower() == "assistant":
                    assistant_message_id = msg.get("id")
                    break
        if assistant_message_id:
            feedback_payload = {
                "message_id": assistant_message_id,
                "rating": 4,
                "reason": "smoke",
            }
            runner.call(
                "POST",
                API_FEEDBACK_MESSAGES,
                API_FEEDBACK_MESSAGES,
                expected=[201],
                json=feedback_payload,
            )
            runner.call(
                "GET",
                API_FEEDBACK_MESSAGES,
                "/api/v1/feedback/messages?limit=5",
                expected=[200],
            )
        else:
            runner.mark("POST", API_FEEDBACK_MESSAGES)
            runner.mark("GET", API_FEEDBACK_MESSAGES)

        runner.call(
            "GET",
            "/api/v1/feedback/messages/enriched",
            "/api/v1/feedback/messages/enriched?limit=5",
            expected=[200],
        )

        # Observability endpoints can touch vector stores or embedding providers; keep
        # them explicit so the final catch-all probe does not use a 2s timeout.
        call_embedding_drift_snapshot(runner, timeout=args.timeout)

        # KG endpoints (may be disabled).
        runner.call(
            "GET",
            "/api/v1/kg/graph",
            "/api/v1/kg/graph",
            expected=[200, 400, 503],
        )
        kg_node_id = doc_id or tenant_id or str(uuid.uuid4())
        runner.call(
            "GET",
            "/api/v1/kg/graph/expand",
            f"/api/v1/kg/graph/expand?node_id={kg_node_id}",
            expected=[200, 400, 404, 503],
        )
        runner.call(
            "GET",
            "/api/v1/kg/graph/search",
            "/api/v1/kg/graph/search?q=smoke",
            expected=[200, 400, 503],
        )
        runner.call(
            "GET",
            "/api/v1/kg/stats",
            "/api/v1/kg/stats",
            expected=[200, 503],
        )
        runner.call(
            "GET",
            "/api/v1/kg/graph/export",
            "/api/v1/kg/graph/export?download=false",
            expected=[200, 503],
        )
        probe_uuid = uuid.uuid4()
        runner.call(
            "GET",
            "/api/v1/kg/events/{event_id}",
            f"/api/v1/kg/events/{probe_uuid}",
            expected=[200, 404, 503],
        )
        runner.call(
            "GET",
            "/api/v1/kg/entities/{entity_id}",
            f"/api/v1/kg/entities/{probe_uuid}",
            expected=[200, 404, 503],
        )
        if doc_id:
            runner.call(
                "POST",
                "/api/v1/kg/documents/{document_id}/extract",
                f"/api/v1/kg/documents/{doc_id}/extract",
                expected=[200, 400, 502, 503],
            )
            runner.call(
                "POST",
                API_KG_SEARCH,
                API_KG_SEARCH,
                expected=[200, 400, 503],
                json={"query": "smoke"},
            )
        else:
            runner.mark("POST", "/api/v1/kg/documents/{document_id}/extract")
            runner.mark("POST", API_KG_SEARCH)

        kg_delete_target = str(doc_id or uuid.uuid4())
        runner.call(
            "DELETE",
            "/api/v1/kg/documents/{document_id}",
            f"/api/v1/kg/documents/{kg_delete_target}",
            expected=[200, 403, 404, 503],
        )

        # Cleanup endpoints.
        if conversation_id:
            runner.call(
                "DELETE",
                "/api/v1/chat/conversations/{conversation_id}",
                f"/api/v1/chat/conversations/{conversation_id}",
                expected=[204],
            )
        else:
            runner.mark("DELETE", "/api/v1/chat/conversations/{conversation_id}")

        if tmpl_id:
            runner.call(
                "DELETE",
                API_PROMPT_TEMPLATE_BY_ID,
                f"/api/v1/prompt-templates/{tmpl_id}",
                expected=[204],
            )
        else:
            runner.mark("DELETE", API_PROMPT_TEMPLATE_BY_ID)

        if doc_id:
            runner.call(
                "DELETE",
                API_DOCUMENT_BY_ID,
                f"/api/v1/documents/{doc_id}",
                expected=[204],
            )
        else:
            runner.mark("DELETE", API_DOCUMENT_BY_ID)

        if manual_doc_id:
            runner.call(
                "DELETE",
                API_DOCUMENT_BY_ID,
                f"/api/v1/documents/{manual_doc_id}",
                expected=[204],
            )

        # Batch-uploaded docs: delete them before dataset deletion.
        for bid in sorted({str(x) for x in (batch_doc_ids or []) if str(x).strip()}):
            if bid == str(doc_id) or bid == str(manual_doc_id):
                continue
            runner.call(
                "DELETE",
                API_DOCUMENT_BY_ID,
                f"/api/v1/documents/{bid}",
                expected=[204, 404],
            )

        if ds_id:
            runner.call(
                "DELETE",
                API_DATASET_BY_ID,
                f"/api/v1/datasets/{ds_id}",
                expected=[204],
            )
        else:
            runner.mark("DELETE", API_DATASET_BY_ID)

        # Final sweep: probe any OpenAPI operations not exercised above.
        probe_uncovered_openapi_endpoints(runner, openapi_paths)

        # Coverage report.
        missing = sorted(openapi_paths - runner.covered)
        failures = [r for r in runner.results if not r.ok]

        print(f"Calls: {len(runner.results)} | Failures: {len(failures)} | Missing: {len(missing)}")
        if failures:
            print("\nFailures:")
            for r in failures:
                print(f"- {r.method} {r.path}: {r.note}")
        if missing:
            print("\nMissing endpoints:")
            for method, path in missing:
                print(f"- {method} {path}")

        return 1 if failures or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
