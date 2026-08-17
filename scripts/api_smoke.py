import argparse
import json
import mimetypes
import os
import re
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

API_SETTINGS = "/api/v1/settings"
API_SETTINGS_LLM_TEST = "/api/v1/settings/llm/test"
API_DATASETS = "/api/v1/datasets/"
API_DATASET_BY_ID = "/api/v1/datasets/{dataset_id}"
API_DATASET_INGESTION_POLICY = "/api/v1/datasets/{dataset_id}/ingestion-policy"
API_DOCUMENT_BY_ID = "/api/v1/documents/{document_id}"
API_DOCUMENTS_MANUAL = "/api/v1/documents/manual"
API_DOCUMENTS_PREVIEW = "/api/v1/documents/preview"
API_DOCUMENT_CHUNK_BY_ID = "/api/v1/documents/{document_id}/chunks/{chunk_id}"
API_BATCH_UPLOAD_APPLY_URLS = "/api/v1/documents/batch-upload/apply-urls"
API_BATCH_UPLOAD_STATUS = "/api/v1/documents/batch-upload/status/{batch_id}"
API_PIPELINE_INGESTION_PREVIEW = "/api/v1/pipeline/ingestion-preview"
API_PIPELINE_GOVERNANCE_PROFILES = "/api/v1/pipeline/governance-profiles"
API_PIPELINE_GOVERNANCE_PROFILE_BY_REF = "/api/v1/pipeline/governance-profiles/{profile_ref}"
API_PIPELINE_UPLOAD_ZIP_WITH_IMAGES = "/api/v1/pipeline/upload-zip-with-images"
API_PARSING_DOCUMENTS = "/api/v1/parsing/documents"
API_PARSING_DOCUMENT_CONTENT_BY_ID = "/api/v1/parsing/documents/{document_id}/content"
API_CHAT_CONVERSATIONS = "/api/v1/chat/conversations"
API_CHAT_STREAM = "/api/v1/chat/stream"
API_CHAT_MESSAGES_BY_CONVERSATION = "/api/v1/chat/conversations/{conversation_id}/messages"
API_CHAT_CHECKPOINTS_BY_CONVERSATION = "/api/v1/chat/conversations/{conversation_id}/checkpoints"
API_PROMPT_TEMPLATES = "/api/v1/prompt-templates"
API_PROMPT_TEMPLATE_BY_ID = "/api/v1/prompt-templates/{template_id}"
API_RAG_RETRIEVE_PREVIEW = "/api/v1/rag/retrieve-preview"
API_RAG_PROMPT_PREVIEW = "/api/v1/rag/prompt-preview"
API_EVAL_RAGAS_RUNS = "/api/v1/evaluations/ragas/runs"
API_EVAL_REGRESSION_CASES = "/api/v1/evaluations/ragas/regression/cases"
API_EVAL_REGRESSION_RUNS = "/api/v1/evaluations/ragas/regression/runs"
API_EVAL_TEST_GEN_FROM_DOCUMENTS = "/api/v1/evaluations/ragas/test-gen/from-documents"
API_EVAL_TEST_GEN_FROM_CONVERSATIONS = "/api/v1/evaluations/ragas/test-gen/from-conversations"
API_FEEDBACK_MESSAGES = "/api/v1/feedback/messages"
API_KG_SEARCH = "/api/v1/kg/search"
MEDIA_TYPE_TEXT_PLAIN = "text/plain"


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


def settings_write_expected_statuses(*, tenant_id: str, system_tenant_id: str) -> list[int]:
    return [200] if str(tenant_id).strip() == str(system_tenant_id).strip() else [403]


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
                self.results.append(CallResult(method.upper(), path_template, None, False, f"request failed: {exc}"))
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
            self.results.append(CallResult(method.upper(), path_template, None, False, "request failed: no response"))
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
        200,
        201,
        202,
        204,
        # Common "reachable but not allowed" outcomes
        400,
        401,
        403,
        404,
        405,
        409,
        410,
        415,
        422,
        # Rate limiting / optional subsystems
        429,
        503,
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


@dataclass
class SmokeContext:
    args: argparse.Namespace
    repo_root: Path
    dotenv: dict[str, str]
    runner: SmokeRunner
    openapi_paths: set[tuple[str, str]]
    tenant_id: str
    system_tenant_id: str
    auth_mode: str
    reuse_jwt_account: bool
    user_email: str
    login_identifier: str
    user_name: str
    user_password: str
    llm_api_key: str
    llm_api_base: str
    llm_model: str
    live_parser_backends: list[str]
    live_parser_fixture: Path | None
    smoke_rag_config: dict[str, Any]
    ds_id: str | None = None
    doc_id: str | None = None
    manual_doc_id: str | None = None
    first_chunk_id: str | None = None
    batch_doc_ids: list[str] = field(default_factory=list)
    conversation_id: str | None = None
    tmpl_id: str | None = None


def mark_routes(runner: SmokeRunner, *routes: tuple[str, str]) -> None:
    for method, path_template in routes:
        runner.mark(method, path_template)


def build_smoke_rag_config() -> dict[str, Any]:
    # Keep smoke requests offline-friendly and fast: avoid default chat retrieval
    # profile (hybrid_ce) which can trigger local cross-encoder model downloads.
    return {
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


def build_smoke_context(
    *,
    args: argparse.Namespace,
    repo_root: Path,
    dotenv: dict[str, str],
    client: httpx.Client,
    live_parser_backends: list[str],
    live_parser_fixture: Path | None,
) -> SmokeContext:
    base_url = args.base_url or env_or(dotenv, "NEXT_PUBLIC_API_URL", "http://localhost:8000")
    tenant_id = args.tenant_id or env_or(dotenv, "NEXT_PUBLIC_TENANT_ID", "00000000-0000-0000-0000-000000000000")
    system_tenant_id = env_or(dotenv, "DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000000")
    auth_mode = (args.auth_mode or env_or(dotenv, "AUTH_MODE", "header")).lower()
    reuse_jwt_account = bool(args.jwt_identifier)
    user_email = f"smoke_{uuid.uuid4().hex[:8]}@example.com"
    login_identifier = args.jwt_identifier or user_email
    user_name = f"smoke_{uuid.uuid4().hex[:8]}"
    user_password = args.jwt_password or "smoke-pass-123"
    openapi_paths = load_openapi_paths(client, base_url, args.openapi)
    headers = build_headers(tenant_id, None, None)
    llm_api_key = env_or(dotenv, "LLM_API_KEY", "")
    llm_api_base = env_or(dotenv, "LLM_API_BASE", "https://api.openai.com/v1")
    llm_model = env_or(dotenv, "LLM_MODEL", "gpt-4o-mini")
    return SmokeContext(
        args=args,
        repo_root=repo_root,
        dotenv=dotenv,
        runner=SmokeRunner(client, base_url, headers),
        openapi_paths=openapi_paths,
        tenant_id=tenant_id,
        system_tenant_id=system_tenant_id,
        auth_mode=auth_mode,
        reuse_jwt_account=reuse_jwt_account,
        user_email=user_email,
        login_identifier=login_identifier,
        user_name=user_name,
        user_password=user_password,
        llm_api_key=llm_api_key,
        llm_api_base=llm_api_base,
        llm_model=llm_model,
        live_parser_backends=live_parser_backends,
        live_parser_fixture=live_parser_fixture,
        smoke_rag_config=build_smoke_rag_config(),
    )


def run_health_smokes(ctx: SmokeContext) -> None:
    ctx.runner.call("GET", "/", "/", expected=[200])
    ctx.runner.call("GET", "/health", "/health", expected=[200])
    ctx.runner.call("GET", "/api/v1/health", "/api/v1/health", expected=[200])
    ctx.runner.call("GET", "/api/v1/health/ready", "/api/v1/health/ready", expected=[200])
    ctx.runner.call("GET", "/api/v1/meta", "/api/v1/meta", expected=[200])


def configure_auth(ctx: SmokeContext) -> None:
    if ctx.auth_mode == "jwt":
        register_payload = {"email": ctx.user_email, "username": ctx.user_name, "password": ctx.user_password}
        reg_resp = ctx.runner.call(
            "POST",
            "/api/v1/auth/register",
            "/api/v1/auth/register",
            expected=[201, 400, 409] if ctx.reuse_jwt_account else [201, 400],
            json=register_payload,
        )
        reg_data = parse_json(reg_resp)
        token = (reg_data.get("token") or {}).get("access_token")
        login_payload = {"identifier": ctx.login_identifier, "password": ctx.user_password}
        login_resp = ctx.runner.call(
            "POST",
            "/api/v1/auth/login",
            "/api/v1/auth/login",
            expected=[200],
            json=login_payload,
        )
        login_data = parse_json(login_resp)
        token = token or (login_data.get("token") or {}).get("access_token")
        ctx.runner.headers = build_headers(ctx.tenant_id, None, token)
        ctx.runner.call("GET", "/api/v1/auth/me", "/api/v1/auth/me", expected=[200])
        return

    mark_routes(
        ctx.runner,
        ("POST", "/api/v1/auth/register"),
        ("POST", "/api/v1/auth/login"),
        ("GET", "/api/v1/auth/me"),
    )
    ctx.runner.headers = build_headers(
        ctx.tenant_id,
        env_or(ctx.dotenv, "NEXT_PUBLIC_USER_ID", "demo"),
        None,
    )
    # Header auth does not create a local user record. In clean CI databases,
    # listing datasets bootstraps the owner membership before settings writes.
    ctx.runner.call("GET", API_DATASETS, API_DATASETS, expected=[200])


def run_settings_smokes(ctx: SmokeContext) -> None:
    ctx.runner.call("GET", API_SETTINGS, API_SETTINGS, expected=[200])
    ctx.runner.call("GET", "/api/v1/settings/status", "/api/v1/settings/status", expected=[200])
    ctx.runner.call(
        "PUT",
        API_SETTINGS,
        API_SETTINGS,
        expected=settings_write_expected_statuses(
            tenant_id=ctx.tenant_id,
            system_tenant_id=ctx.system_tenant_id,
        ),
        json={},
    )
    if ctx.args.skip_llm_test:
        ctx.runner.mark("POST", API_SETTINGS_LLM_TEST)
        return

    ctx.runner.call(
        "POST",
        API_SETTINGS_LLM_TEST,
        API_SETTINGS_LLM_TEST,
        expected=[200, 400],
        json={
            "api_key": ctx.llm_api_key,
            "api_base": ctx.llm_api_base,
            "model": ctx.llm_model,
            "temperature": 0.0,
            "timeout": 10,
            "max_retries": 1,
        },
    )


def run_dataset_smokes(ctx: SmokeContext) -> None:
    dataset_payload = {"name": f"Smoke Dataset {uuid.uuid4().hex[:6]}", "description": "smoke"}
    ds_resp = ctx.runner.call("POST", API_DATASETS, API_DATASETS, expected=[201], json=dataset_payload)
    ctx.ds_id = parse_json(ds_resp).get("id")
    ctx.runner.call("GET", API_DATASETS, API_DATASETS, expected=[200])
    if not ctx.ds_id:
        return

    ctx.runner.call("GET", API_DATASET_BY_ID, f"/api/v1/datasets/{ctx.ds_id}", expected=[200])
    ctx.runner.call(
        "PATCH",
        API_DATASET_BY_ID,
        f"/api/v1/datasets/{ctx.ds_id}",
        expected=[200],
        json={"description": "smoke-updated"},
    )


def run_dataset_ingestion_policy_smokes(ctx: SmokeContext) -> None:
    if not ctx.ds_id:
        mark_routes(
            ctx.runner,
            ("GET", API_DATASET_INGESTION_POLICY),
            ("PUT", API_DATASET_INGESTION_POLICY),
            ("POST", "/api/v1/datasets/{dataset_id}/ingestion-policy/import"),
            ("GET", "/api/v1/datasets/{dataset_id}/ingestion-policy/export"),
        )
        return

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
    ctx.runner.call(
        "PUT",
        API_DATASET_INGESTION_POLICY,
        f"/api/v1/datasets/{ctx.ds_id}/ingestion-policy",
        expected=[200],
        json=policy_payload,
    )
    ctx.runner.call(
        "GET",
        API_DATASET_INGESTION_POLICY,
        f"/api/v1/datasets/{ctx.ds_id}/ingestion-policy",
        expected=[200],
    )
    ctx.runner.call(
        "GET",
        "/api/v1/datasets/{dataset_id}/ingestion-policy/export",
        f"/api/v1/datasets/{ctx.ds_id}/ingestion-policy/export",
        expected=[200],
    )
    policy_bytes = json.dumps(policy_payload, ensure_ascii=False).encode("utf-8")
    ctx.runner.call(
        "POST",
        "/api/v1/datasets/{dataset_id}/ingestion-policy/import",
        f"/api/v1/datasets/{ctx.ds_id}/ingestion-policy/import",
        expected=[200, 409],
        files={"file": ("policy.json", policy_bytes, "application/json")},
        data={"replace": "true"},
    )


def run_document_upload_smokes(ctx: SmokeContext) -> None:
    sample_text = "Smoke test document.\nSecond line."
    files = {"file": ("smoke.txt", sample_text.encode("utf-8"), MEDIA_TYPE_TEXT_PLAIN)}
    data = {"chunk_vector_enabled": "false"}
    if ctx.ds_id:
        data["dataset_id"] = ctx.ds_id
    doc_resp = ctx.runner.call(
        "POST",
        "/api/v1/documents/upload",
        "/api/v1/documents/upload",
        expected=[201],
        files=files,
        data=data,
    )
    ctx.doc_id = parse_json(doc_resp).get("id")
    ctx.first_chunk_id = None
    ctx.batch_doc_ids = []

    files_batch = [
        ("files", ("batch1.txt", b"batch-one", MEDIA_TYPE_TEXT_PLAIN)),
        ("files", ("batch2.txt", b"batch-two", MEDIA_TYPE_TEXT_PLAIN)),
    ]
    data_batch = {"chunk_vector_enabled": "false"}
    if ctx.ds_id:
        data_batch["dataset_id"] = ctx.ds_id
    batch_resp = ctx.runner.call(
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
            ctx.batch_doc_ids.append(str(did))

    ctx.runner.call("GET", "/api/v1/documents/", "/api/v1/documents/?limit=5", expected=[200])
    ctx.runner.call("GET", "/api/v1/documents/stats", "/api/v1/documents/stats", expected=[200])
    if not ctx.doc_id:
        mark_routes(
            ctx.runner,
            ("PATCH", "/api/v1/documents/{document_id}/metadata"),
            ("GET", "/api/v1/documents/{document_id}/download"),
        )
        return

    ctx.runner.call("GET", API_DOCUMENT_BY_ID, f"/api/v1/documents/{ctx.doc_id}", expected=[200])
    ctx.runner.call(
        "GET",
        "/api/v1/documents/{document_id}/status",
        f"/api/v1/documents/{ctx.doc_id}/status",
        expected=[200],
    )
    ctx.runner.call(
        "PATCH",
        "/api/v1/documents/{document_id}/metadata",
        f"/api/v1/documents/{ctx.doc_id}/metadata",
        expected=[200, 403, 404],
        json={"patch": {"source": "smoke"}, "replace": False},
    )
    ctx.runner.call(
        "GET",
        "/api/v1/documents/{document_id}/download",
        f"/api/v1/documents/{ctx.doc_id}/download?inline=true",
        expected=[200, 403, 404],
    )


def run_document_preview_smokes(ctx: SmokeContext) -> None:
    ctx.runner.call(
        "POST",
        API_DOCUMENTS_PREVIEW,
        API_DOCUMENTS_PREVIEW,
        expected=[200],
        timeout=120.0,
        files={"file": ("preview.txt", b"preview", MEDIA_TYPE_TEXT_PLAIN)},
    )
    if ctx.live_parser_backends and ctx.live_parser_fixture is not None:
        run_live_parser_preview_smokes(
            runner=ctx.runner,
            fixture_path=ctx.live_parser_fixture,
            parser_backends=ctx.live_parser_backends,
            timeout=ctx.args.live_parser_timeout,
        )
    ctx.runner.call(
        "POST",
        "/api/v1/documents/chunk-preview",
        "/api/v1/documents/chunk-preview",
        expected=[200],
        files={"file": ("chunk.txt", b"chunk preview text", MEDIA_TYPE_TEXT_PLAIN)},
        data={"chunk_size": 200, "chunk_overlap": 20},
    )


def build_batch_patch_ids(ctx: SmokeContext) -> list[str]:
    batch_patch_ids: list[str] = []
    if ctx.doc_id:
        batch_patch_ids.append(str(ctx.doc_id))
    if ctx.manual_doc_id:
        batch_patch_ids.append(str(ctx.manual_doc_id))
    if not batch_patch_ids:
        batch_patch_ids.append(str(uuid.uuid4()))
    return batch_patch_ids


def run_manual_and_batch_document_smokes(ctx: SmokeContext) -> None:
    if ctx.ds_id:
        manual_payload = {
            "dataset_id": ctx.ds_id,
            "filename": "manual.txt",
            "file_type": "txt",
            "file_size": 12,
            "chunks": [{"content": "manual chunk"}],
        }
        manual_resp = ctx.runner.call(
            "POST",
            API_DOCUMENTS_MANUAL,
            API_DOCUMENTS_MANUAL,
            expected=[201],
            json=manual_payload,
        )
        ctx.manual_doc_id = parse_json(manual_resp).get("id")
    else:
        ctx.runner.mark("POST", API_DOCUMENTS_MANUAL)
        ctx.manual_doc_id = None

    ctx.runner.call(
        "POST",
        "/api/v1/documents/batch/metadata",
        "/api/v1/documents/batch/metadata",
        expected=[200],
        json={
            "document_ids": build_batch_patch_ids(ctx),
            "patch": {"batch": True, "source": "smoke"},
            "replace": False,
        },
    )
    ctx.runner.call(
        "POST",
        "/api/v1/documents/batch-delete",
        "/api/v1/documents/batch-delete",
        expected=[200],
        json={"document_ids": [str(uuid.uuid4())]},
    )
    cancel_target = str(ctx.manual_doc_id or uuid.uuid4())
    ctx.runner.call(
        "POST",
        "/api/v1/documents/{document_id}/cancel",
        f"/api/v1/documents/{cancel_target}/cancel",
        expected=[200, 404, 409],
    )
    retry_target = str(ctx.manual_doc_id or uuid.uuid4())
    ctx.runner.call(
        "POST",
        "/api/v1/documents/{document_id}/retry",
        f"/api/v1/documents/{retry_target}/retry",
        expected=[200, 404, 409],
    )


def run_batch_upload_apply_smokes(ctx: SmokeContext) -> None:
    if ctx.args.skip_mineru:
        mark_routes(
            ctx.runner,
            ("POST", API_BATCH_UPLOAD_APPLY_URLS),
            ("GET", API_BATCH_UPLOAD_STATUS),
        )
        return

    apply_resp = ctx.runner.call(
        "POST",
        API_BATCH_UPLOAD_APPLY_URLS,
        API_BATCH_UPLOAD_APPLY_URLS,
        expected=[200, 400, 500, 503],
        json={"files": [{"name": "a.pdf", "data_id": "smoke-a"}]},
    )
    batch_id = parse_json(apply_resp).get("batch_id")
    if batch_id:
        ctx.runner.call(
            "GET",
            API_BATCH_UPLOAD_STATUS,
            API_BATCH_UPLOAD_STATUS.format(batch_id=batch_id),
            expected=[200, 400, 404, 500, 503],
        )
        return

    ctx.runner.call(
        "GET",
        API_BATCH_UPLOAD_STATUS,
        "/api/v1/documents/batch-upload/status/invalid",
        expected=[200, 400, 404, 500, 503],
    )


def run_image_smokes(ctx: SmokeContext) -> None:
    ctx.runner.call(
        "GET",
        "/api/v1/documents/image-url/{img_id}",
        "/api/v1/documents/image-url/invalid",
        expected=[404, 503],
    )
    ctx.runner.call(
        "GET",
        "/api/v1/documents/image/{image_id}",
        "/api/v1/documents/image/invalid",
        expected=[404],
    )


def run_pipeline_preview_smokes(ctx: SmokeContext) -> None:
    ctx.runner.call("GET", "/api/v1/pipeline/capabilities", "/api/v1/pipeline/capabilities", expected=[200])
    ctx.runner.call(
        "POST",
        "/api/v1/pipeline/parse-preview",
        "/api/v1/pipeline/parse-preview",
        expected=[200],
        files={"file": ("pipe.txt", b"pipeline preview", MEDIA_TYPE_TEXT_PLAIN)},
    )
    ctx.runner.call(
        "POST",
        "/api/v1/pipeline/chunk-preview",
        "/api/v1/pipeline/chunk-preview",
        expected=[200],
        json={"markdown": "# Title\n\nContent"},
    )
    ctx.runner.call(
        "POST",
        "/api/v1/pipeline/clean-preview",
        "/api/v1/pipeline/clean-preview",
        expected=[200],
        json={"markdown": "A  \n\nB", "use_default_rules": True},
    )
    ctx.runner.call("GET", "/api/v1/pipeline/clean-rules", "/api/v1/pipeline/clean-rules", expected=[200])
    ctx.runner.call(
        "POST",
        "/api/v1/pipeline/governance-analyze",
        "/api/v1/pipeline/governance-analyze",
        expected=[200],
        json={"markdown": "<p>hello</p>\n\nA  \n\nB"},
    )
    if ctx.ds_id:
        ctx.runner.call(
            "POST",
            API_PIPELINE_INGESTION_PREVIEW,
            API_PIPELINE_INGESTION_PREVIEW,
            expected=[200, 400, 500],
            files={"file": ("ingest.txt", b"ingestion preview", MEDIA_TYPE_TEXT_PLAIN)},
            data={"dataset_id": ctx.ds_id},
        )
        return

    ctx.runner.mark("POST", API_PIPELINE_INGESTION_PREVIEW)


def run_governance_profile_smokes(ctx: SmokeContext) -> None:
    ctx.runner.call(
        "GET",
        API_PIPELINE_GOVERNANCE_PROFILES,
        "/api/v1/pipeline/governance-profiles?limit=5",
        expected=[200],
    )
    gov_key = f"smoke_profile_{uuid.uuid4().hex[:6]}"
    gov_resp = ctx.runner.call(
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
    ctx.runner.call(
        "GET",
        API_PIPELINE_GOVERNANCE_PROFILE_BY_REF,
        f"/api/v1/pipeline/governance-profiles/{gov_id}",
        expected=[200],
    )
    ctx.runner.call(
        "PATCH",
        API_PIPELINE_GOVERNANCE_PROFILE_BY_REF,
        f"/api/v1/pipeline/governance-profiles/{gov_id}",
        expected=[200],
        json={"description": "smoke-updated"},
    )
    ctx.runner.call(
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
    ctx.runner.call(
        "POST",
        "/api/v1/pipeline/governance-profiles/import",
        "/api/v1/pipeline/governance-profiles/import",
        expected=[200, 409],
        files={"file": ("profile.json", import_bytes, "application/json")},
        data={"overwrite": "true"},
    )
    ctx.runner.call(
        "GET",
        API_PIPELINE_GOVERNANCE_PROFILE_BY_REF,
        f"/api/v1/pipeline/governance-profiles/{import_key}",
        expected=[200, 404],
    )
    ctx.runner.call(
        "DELETE",
        API_PIPELINE_GOVERNANCE_PROFILE_BY_REF,
        f"/api/v1/pipeline/governance-profiles/{import_key}",
        expected=[204, 404],
    )
    ctx.runner.call(
        "DELETE",
        API_PIPELINE_GOVERNANCE_PROFILE_BY_REF,
        f"/api/v1/pipeline/governance-profiles/{gov_id}",
        expected=[204, 404],
    )
    ctx.runner.call(
        "POST",
        "/api/v1/pipeline/extract-keywords",
        "/api/v1/pipeline/extract-keywords",
        expected=[200],
        json={"text": "keyword extraction smoke", "provider": "jieba", "top_k": 3},
    )
    ctx.runner.call(
        "POST",
        "/api/v1/pipeline/llm-clean-preview",
        "/api/v1/pipeline/llm-clean-preview",
        expected=[200, 502, 503],
        json={"markdown": "LLM clean preview", "max_chars": 2000},
    )


def run_pipeline_zip_upload_smokes(ctx: SmokeContext) -> None:
    if not ctx.ds_id:
        ctx.runner.mark("POST", API_PIPELINE_UPLOAD_ZIP_WITH_IMAGES)
        return

    zip_path = create_zip_with_image(ctx.repo_root / "uploads" / "smoke_zip")
    with zip_path.open("rb") as fh:
        ctx.runner.call(
            "POST",
            API_PIPELINE_UPLOAD_ZIP_WITH_IMAGES,
            API_PIPELINE_UPLOAD_ZIP_WITH_IMAGES,
            expected=[200, 503],
            files={"file": (zip_path.name, fh, "application/zip")},
            data={"dataset_id": ctx.ds_id},
        )


def run_parsing_workspace_smokes(ctx: SmokeContext) -> None:
    ctx.runner.call(
        "GET",
        API_PARSING_DOCUMENTS,
        "/api/v1/parsing/documents?limit=5",
        expected=[200],
    )
    parsing_upload = ctx.runner.call(
        "POST",
        API_PARSING_DOCUMENTS,
        API_PARSING_DOCUMENTS,
        expected=[201],
        files={"file": ("parsing.txt", b"parsing workspace", MEDIA_TYPE_TEXT_PLAIN)},
        data={"parser_backend": "auto"},
    )
    parsing_doc_id = parse_json(parsing_upload).get("id")
    if not parsing_doc_id:
        mark_routes(
            ctx.runner,
            ("POST", "/api/v1/parsing/documents/{document_id}/parse"),
            ("GET", API_PARSING_DOCUMENT_CONTENT_BY_ID),
            ("PATCH", API_PARSING_DOCUMENT_CONTENT_BY_ID),
            ("DELETE", "/api/v1/parsing/documents/{document_id}"),
        )
        return

    ctx.runner.call(
        "POST",
        "/api/v1/parsing/documents/{document_id}/parse",
        f"/api/v1/parsing/documents/{parsing_doc_id}/parse",
        expected=[200, 400, 500],
    )
    ctx.runner.call(
        "GET",
        API_PARSING_DOCUMENT_CONTENT_BY_ID,
        f"/api/v1/parsing/documents/{parsing_doc_id}/content",
        expected=[200],
    )
    ctx.runner.call(
        "PATCH",
        API_PARSING_DOCUMENT_CONTENT_BY_ID,
        f"/api/v1/parsing/documents/{parsing_doc_id}/content",
        expected=[200],
        json={"markdown_content": "# Edited\n\nok", "original_markdown_content": "# Edited\n\nok"},
    )
    ctx.runner.call(
        "DELETE",
        "/api/v1/parsing/documents/{document_id}",
        f"/api/v1/parsing/documents/{parsing_doc_id}",
        expected=[204],
    )


def poll_document_status(ctx: SmokeContext) -> None:
    if not ctx.doc_id:
        return

    status_url = f"/api/v1/documents/{ctx.doc_id}/status"
    for _ in range(30):
        resp = ctx.runner.call(
            "GET",
            "/api/v1/documents/{document_id}/status",
            status_url,
            expected=[200],
        )
        status = parse_json(resp).get("status")
        if status in {"completed", "failed"}:
            break
        time.sleep(1)


def run_document_pipeline_and_chunk_smokes(ctx: SmokeContext) -> None:
    if not ctx.doc_id:
        mark_routes(
            ctx.runner,
            ("PATCH", "/api/v1/documents/{document_id}/pipeline"),
            ("GET", "/api/v1/documents/{document_id}/chunks"),
            ("GET", "/api/v1/documents/{document_id}/chunks/matches"),
            ("GET", API_DOCUMENT_CHUNK_BY_ID),
        )
        return

    ctx.runner.call(
        "PATCH",
        "/api/v1/documents/{document_id}/pipeline",
        f"/api/v1/documents/{ctx.doc_id}/pipeline",
        expected=[200, 404, 409],
        json={"patch": {"governance_enabled": True}, "replace": False},
    )
    chunks_resp = ctx.runner.call(
        "GET",
        "/api/v1/documents/{document_id}/chunks",
        f"/api/v1/documents/{ctx.doc_id}/chunks?limit=5",
        expected=[200],
    )
    items = parse_json(chunks_resp).get("items") or []
    ctx.first_chunk_id = items[0].get("id") if items else None
    ctx.runner.call(
        "GET",
        "/api/v1/documents/{document_id}/chunks/matches",
        f"/api/v1/documents/{ctx.doc_id}/chunks/matches?q=Smoke&limit=20",
        expected=[200],
    )
    if ctx.first_chunk_id:
        ctx.runner.call(
            "GET",
            API_DOCUMENT_CHUNK_BY_ID,
            f"/api/v1/documents/{ctx.doc_id}/chunks/{ctx.first_chunk_id}",
            expected=[200, 404],
        )
        return

    ctx.runner.call(
        "GET",
        API_DOCUMENT_CHUNK_BY_ID,
        f"/api/v1/documents/{ctx.doc_id}/chunks/{uuid.uuid4()}",
        expected=[404],
    )


def run_ragviz_smokes(ctx: SmokeContext) -> None:
    col_resp = ctx.runner.call(
        "GET",
        "/api/v1/ragviz/similarity/collections",
        "/api/v1/ragviz/similarity/collections",
        expected=[200],
    )
    collections = parse_json(col_resp).get("collections") or []
    x_collection = collections[0].get("id") if collections else "invalid"
    y_collection = collections[0].get("id") if collections else "invalid"
    ctx.runner.call(
        "POST",
        "/api/v1/ragviz/similarity/calculate",
        "/api/v1/ragviz/similarity/calculate",
        expected=[200],
        json={"x_collection": x_collection, "y_collection": y_collection, "max_items": 10},
    )


def create_conversation(ctx: SmokeContext) -> None:
    ctx.conversation_id = None
    if not ctx.doc_id:
        ctx.runner.mark("POST", API_CHAT_CONVERSATIONS)
        return

    conv_resp = ctx.runner.call(
        "POST",
        API_CHAT_CONVERSATIONS,
        API_CHAT_CONVERSATIONS,
        expected=[201],
        json={"title": "Smoke conversation", "document_ids": [ctx.doc_id]},
    )
    ctx.conversation_id = parse_json(conv_resp).get("id")


def run_non_stream_chat_smoke(ctx: SmokeContext) -> None:
    chat_path = "/api/v1/chat/" if ("POST", "/api/v1/chat/") in ctx.openapi_paths else "/api/v1/chat"
    if not ctx.doc_id:
        ctx.runner.mark("POST", chat_path)
        return
    if ctx.args.skip_llm_test:
        return

    ctx.runner.call(
        "POST",
        chat_path,
        chat_path,
        expected=[200, 500, 502, 503],
        timeout=90.0,
        json={
            "message": "smoke non-stream",
            "document_ids": [ctx.doc_id],
            "stream": False,
            "rag_config": dict(ctx.smoke_rag_config),
        },
    )


def run_stream_chat_smoke(ctx: SmokeContext) -> None:
    if not ctx.doc_id:
        mark_routes(
            ctx.runner,
            ("POST", API_CHAT_STREAM),
            ("GET", API_CHAT_CONVERSATIONS),
        )
        return
    if ctx.args.skip_llm_test:
        return

    ok, _ = ctx.runner.stream(
        "POST",
        API_CHAT_STREAM,
        API_CHAT_STREAM,
        expected=[200],
        timeout=90.0,
        json={
            "message": "smoke test",
            "document_ids": [ctx.doc_id],
            "rag_config": dict(ctx.smoke_rag_config),
        },
    )
    if not ok or ctx.conversation_id:
        return

    conv_list = ctx.runner.call(
        "GET",
        API_CHAT_CONVERSATIONS,
        "/api/v1/chat/conversations?limit=5",
        expected=[200],
    )
    items = parse_json(conv_list).get("items") or []
    if items:
        ctx.conversation_id = items[0].get("id")


def run_conversation_endpoint_smokes(ctx: SmokeContext) -> None:
    if not ctx.conversation_id:
        mark_routes(
            ctx.runner,
            ("GET", API_CHAT_MESSAGES_BY_CONVERSATION),
            ("GET", API_CHAT_CHECKPOINTS_BY_CONVERSATION),
            ("GET", "/api/v1/chat/conversations/{conversation_id}/checkpoints/{checkpoint_id}"),
            ("DELETE", API_CHAT_CHECKPOINTS_BY_CONVERSATION),
        )
        return

    ctx.runner.call(
        "GET",
        API_CHAT_MESSAGES_BY_CONVERSATION,
        API_CHAT_MESSAGES_BY_CONVERSATION.format(conversation_id=ctx.conversation_id),
        expected=[200],
    )
    ctx.runner.call(
        "GET",
        API_CHAT_CONVERSATIONS,
        "/api/v1/chat/conversations?limit=5",
        expected=[200],
    )
    ctx.runner.call(
        "GET",
        API_CHAT_CHECKPOINTS_BY_CONVERSATION,
        f"/api/v1/chat/conversations/{ctx.conversation_id}/checkpoints?limit=5",
        expected=[200],
    )
    ctx.runner.call(
        "GET",
        "/api/v1/chat/conversations/{conversation_id}/checkpoints/{checkpoint_id}",
        f"/api/v1/chat/conversations/{ctx.conversation_id}/checkpoints/invalid",
        expected=[404],
    )
    ctx.runner.call(
        "DELETE",
        API_CHAT_CHECKPOINTS_BY_CONVERSATION,
        API_CHAT_CHECKPOINTS_BY_CONVERSATION.format(conversation_id=ctx.conversation_id),
        expected=[204],
    )


def run_chat_smokes(ctx: SmokeContext) -> None:
    create_conversation(ctx)
    run_non_stream_chat_smoke(ctx)
    run_stream_chat_smoke(ctx)
    run_conversation_endpoint_smokes(ctx)


def run_prompt_template_smokes(ctx: SmokeContext) -> None:
    tmpl_payload = {
        "name": f"Smoke Template {uuid.uuid4().hex[:6]}",
        "content": "Answer the question: {question}",
        "variables": ["question"],
        "is_active": True,
    }
    tmpl_resp = ctx.runner.call(
        "POST",
        API_PROMPT_TEMPLATES,
        API_PROMPT_TEMPLATES,
        expected=[201],
        json=tmpl_payload,
    )
    ctx.tmpl_id = parse_json(tmpl_resp).get("id")
    ctx.runner.call("GET", API_PROMPT_TEMPLATES, "/api/v1/prompt-templates?limit=5", expected=[200])
    if not ctx.tmpl_id:
        return

    ctx.runner.call(
        "GET",
        API_PROMPT_TEMPLATE_BY_ID,
        f"/api/v1/prompt-templates/{ctx.tmpl_id}",
        expected=[200],
    )
    ctx.runner.call(
        "POST",
        "/api/v1/prompt-templates/{template_id}/duplicate",
        f"/api/v1/prompt-templates/{ctx.tmpl_id}/duplicate",
        expected=[201],
    )
    ctx.runner.call(
        "POST",
        "/api/v1/prompt-templates/{template_id}/versions",
        f"/api/v1/prompt-templates/{ctx.tmpl_id}/versions",
        expected=[201],
        json={"content": "New version {question}", "is_active": True},
    )
    ctx.runner.call(
        "PUT",
        API_PROMPT_TEMPLATE_BY_ID,
        f"/api/v1/prompt-templates/{ctx.tmpl_id}",
        expected=[200],
        json={"description": "smoke-updated"},
    )


def run_rag_smokes(ctx: SmokeContext) -> None:
    if not ctx.doc_id:
        mark_routes(
            ctx.runner,
            ("POST", API_RAG_RETRIEVE_PREVIEW),
            ("POST", API_RAG_PROMPT_PREVIEW),
        )
        return

    rag_payload = {"query": "smoke retrieval", "document_ids": [ctx.doc_id], "rag_config": dict(ctx.smoke_rag_config)}
    ctx.runner.call(
        "POST",
        API_RAG_RETRIEVE_PREVIEW,
        API_RAG_RETRIEVE_PREVIEW,
        expected=[200],
        json=rag_payload,
    )
    ctx.runner.call(
        "POST",
        API_RAG_PROMPT_PREVIEW,
        API_RAG_PROMPT_PREVIEW,
        expected=[200],
        json=rag_payload,
    )


def run_ragas_smokes(ctx: SmokeContext) -> None:
    if not ctx.conversation_id:
        mark_routes(
            ctx.runner,
            ("POST", API_EVAL_RAGAS_RUNS),
            ("GET", API_EVAL_RAGAS_RUNS),
            ("GET", "/api/v1/evaluations/ragas/runs/{run_id}"),
        )
        return

    eval_payload = {"conversation_id": ctx.conversation_id, "metrics": ["faithfulness"]}
    run_resp = ctx.runner.call(
        "POST",
        API_EVAL_RAGAS_RUNS,
        API_EVAL_RAGAS_RUNS,
        expected=[201],
        json=eval_payload,
    )
    run_id = parse_json(run_resp).get("id")
    ctx.runner.call(
        "GET",
        API_EVAL_RAGAS_RUNS,
        "/api/v1/evaluations/ragas/runs?limit=5",
        expected=[200],
    )
    if run_id:
        ctx.runner.call(
            "GET",
            "/api/v1/evaluations/ragas/runs/{run_id}",
            f"/api/v1/evaluations/ragas/runs/{run_id}",
            expected=[200],
        )


def run_regression_eval_smokes(ctx: SmokeContext) -> None:
    if not ctx.ds_id:
        mark_routes(
            ctx.runner,
            ("POST", API_EVAL_REGRESSION_CASES),
            ("GET", API_EVAL_REGRESSION_CASES),
            ("POST", API_EVAL_REGRESSION_RUNS),
            ("GET", API_EVAL_REGRESSION_RUNS),
            ("GET", "/api/v1/evaluations/ragas/regression/runs/{run_id}"),
            ("POST", API_EVAL_TEST_GEN_FROM_DOCUMENTS),
        )
        return

    case_id = None
    if ctx.doc_id and ctx.first_chunk_id:
        case_payload = {
            "dataset_id": ctx.ds_id,
            "document_ids": [ctx.doc_id],
            "question": "smoke question",
            "expected_answer": "smoke answer",
            "reference_sources": [{"document_id": ctx.doc_id, "chunk_id": ctx.first_chunk_id}],
        }
        case_resp = ctx.runner.call(
            "POST",
            API_EVAL_REGRESSION_CASES,
            API_EVAL_REGRESSION_CASES,
            expected=[201],
            json=case_payload,
        )
        case_id = parse_json(case_resp).get("id")
    else:
        ctx.runner.mark("POST", API_EVAL_REGRESSION_CASES)

    ctx.runner.call(
        "GET",
        API_EVAL_REGRESSION_CASES,
        "/api/v1/evaluations/ragas/regression/cases?limit=5",
        expected=[200],
    )
    reg_run_resp = ctx.runner.call(
        "POST",
        API_EVAL_REGRESSION_RUNS,
        API_EVAL_REGRESSION_RUNS,
        expected=[201, 400, 422],
        json={"case_ids": [case_id] if case_id else [], "metrics": ["faithfulness"]},
    )
    reg_run_id = parse_json(reg_run_resp).get("id")
    ctx.runner.call(
        "GET",
        API_EVAL_REGRESSION_RUNS,
        "/api/v1/evaluations/ragas/regression/runs?limit=5",
        expected=[200],
    )
    if reg_run_id:
        ctx.runner.call(
            "GET",
            "/api/v1/evaluations/ragas/regression/runs/{run_id}",
            f"/api/v1/evaluations/ragas/regression/runs/{reg_run_id}",
            expected=[200],
        )
    if case_id:
        ctx.runner.call(
            "DELETE",
            "/api/v1/evaluations/ragas/regression/cases/{case_id}",
            f"/api/v1/evaluations/ragas/regression/cases/{case_id}",
            expected=[204],
        )
    else:
        ctx.runner.mark("DELETE", "/api/v1/evaluations/ragas/regression/cases/{case_id}")

    test_gen_docs = {
        "document_ids": [ctx.doc_id] if ctx.doc_id else [],
        "num_questions": 1,
        "auto_save_as_cases": False,
    }
    ctx.runner.call(
        "POST",
        API_EVAL_TEST_GEN_FROM_DOCUMENTS,
        API_EVAL_TEST_GEN_FROM_DOCUMENTS,
        expected=[200, 400, 422, 500],
        json=test_gen_docs,
    )


def run_conversation_test_generation_smoke(ctx: SmokeContext) -> None:
    if not ctx.conversation_id:
        ctx.runner.mark("POST", API_EVAL_TEST_GEN_FROM_CONVERSATIONS)
        return

    test_gen_conv = {
        "conversation_ids": [ctx.conversation_id],
        "num_questions": 1,
        "auto_save_as_cases": False,
    }
    ctx.runner.call(
        "POST",
        API_EVAL_TEST_GEN_FROM_CONVERSATIONS,
        API_EVAL_TEST_GEN_FROM_CONVERSATIONS,
        expected=[200, 400, 500],
        json=test_gen_conv,
    )


def run_eval_smokes(ctx: SmokeContext) -> None:
    run_ragas_smokes(ctx)
    run_regression_eval_smokes(ctx)
    run_conversation_test_generation_smoke(ctx)


def run_feedback_smokes(ctx: SmokeContext) -> None:
    assistant_message_id = None
    if ctx.conversation_id:
        msg_resp = ctx.runner.call(
            "GET",
            API_CHAT_MESSAGES_BY_CONVERSATION,
            API_CHAT_MESSAGES_BY_CONVERSATION.format(conversation_id=ctx.conversation_id),
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
        ctx.runner.call(
            "POST",
            API_FEEDBACK_MESSAGES,
            API_FEEDBACK_MESSAGES,
            expected=[201],
            json=feedback_payload,
        )
        ctx.runner.call(
            "GET",
            API_FEEDBACK_MESSAGES,
            "/api/v1/feedback/messages?limit=5",
            expected=[200],
        )
    else:
        mark_routes(
            ctx.runner,
            ("POST", API_FEEDBACK_MESSAGES),
            ("GET", API_FEEDBACK_MESSAGES),
        )

    ctx.runner.call(
        "GET",
        "/api/v1/feedback/messages/enriched",
        "/api/v1/feedback/messages/enriched?limit=5",
        expected=[200],
    )


def run_observability_smokes(ctx: SmokeContext) -> None:
    call_embedding_drift_snapshot(ctx.runner, timeout=ctx.args.timeout)


def run_kg_smokes(ctx: SmokeContext) -> None:
    ctx.runner.call(
        "GET",
        "/api/v1/kg/graph",
        "/api/v1/kg/graph",
        expected=[200, 400, 503],
    )
    kg_node_id = ctx.doc_id or ctx.tenant_id or str(uuid.uuid4())
    ctx.runner.call(
        "GET",
        "/api/v1/kg/graph/expand",
        f"/api/v1/kg/graph/expand?node_id={kg_node_id}",
        expected=[200, 400, 404, 503],
    )
    ctx.runner.call(
        "GET",
        "/api/v1/kg/graph/search",
        "/api/v1/kg/graph/search?q=smoke",
        expected=[200, 400, 503],
    )
    ctx.runner.call(
        "GET",
        "/api/v1/kg/stats",
        "/api/v1/kg/stats",
        expected=[200, 503],
    )
    ctx.runner.call(
        "GET",
        "/api/v1/kg/graph/export",
        "/api/v1/kg/graph/export?download=false",
        expected=[200, 503],
    )
    probe_uuid = uuid.uuid4()
    ctx.runner.call(
        "GET",
        "/api/v1/kg/events/{event_id}",
        f"/api/v1/kg/events/{probe_uuid}",
        expected=[200, 404, 503],
    )
    ctx.runner.call(
        "GET",
        "/api/v1/kg/entities/{entity_id}",
        f"/api/v1/kg/entities/{probe_uuid}",
        expected=[200, 404, 503],
    )
    if ctx.doc_id:
        ctx.runner.call(
            "POST",
            "/api/v1/kg/documents/{document_id}/extract",
            f"/api/v1/kg/documents/{ctx.doc_id}/extract",
            expected=[200, 400, 502, 503],
        )
        ctx.runner.call(
            "POST",
            API_KG_SEARCH,
            API_KG_SEARCH,
            expected=[200, 400, 503],
            json={"query": "smoke"},
        )
    else:
        mark_routes(
            ctx.runner,
            ("POST", "/api/v1/kg/documents/{document_id}/extract"),
            ("POST", API_KG_SEARCH),
        )

    kg_delete_target = str(ctx.doc_id or uuid.uuid4())
    ctx.runner.call(
        "DELETE",
        "/api/v1/kg/documents/{document_id}",
        f"/api/v1/kg/documents/{kg_delete_target}",
        expected=[200, 403, 404, 503],
    )


def iter_batch_cleanup_ids(ctx: SmokeContext) -> list[str]:
    out: list[str] = []
    for bid in sorted({str(x) for x in (ctx.batch_doc_ids or []) if str(x).strip()}):
        if bid == str(ctx.doc_id) or bid == str(ctx.manual_doc_id):
            continue
        out.append(bid)
    return out


def run_cleanup_smokes(ctx: SmokeContext) -> None:
    if ctx.conversation_id:
        ctx.runner.call(
            "DELETE",
            "/api/v1/chat/conversations/{conversation_id}",
            f"/api/v1/chat/conversations/{ctx.conversation_id}",
            expected=[204],
        )
    else:
        ctx.runner.mark("DELETE", "/api/v1/chat/conversations/{conversation_id}")

    if ctx.tmpl_id:
        ctx.runner.call(
            "DELETE",
            API_PROMPT_TEMPLATE_BY_ID,
            f"/api/v1/prompt-templates/{ctx.tmpl_id}",
            expected=[204],
        )
    else:
        ctx.runner.mark("DELETE", API_PROMPT_TEMPLATE_BY_ID)

    if ctx.doc_id:
        ctx.runner.call(
            "DELETE",
            API_DOCUMENT_BY_ID,
            f"/api/v1/documents/{ctx.doc_id}",
            expected=[204],
        )
    else:
        ctx.runner.mark("DELETE", API_DOCUMENT_BY_ID)

    if ctx.manual_doc_id:
        ctx.runner.call(
            "DELETE",
            API_DOCUMENT_BY_ID,
            f"/api/v1/documents/{ctx.manual_doc_id}",
            expected=[204],
        )

    for bid in iter_batch_cleanup_ids(ctx):
        ctx.runner.call(
            "DELETE",
            API_DOCUMENT_BY_ID,
            f"/api/v1/documents/{bid}",
            expected=[204, 404],
        )

    if ctx.ds_id:
        ctx.runner.call(
            "DELETE",
            API_DATASET_BY_ID,
            f"/api/v1/datasets/{ctx.ds_id}",
            expected=[204],
        )
        return

    ctx.runner.mark("DELETE", API_DATASET_BY_ID)


def run_smoke_scenario(ctx: SmokeContext) -> None:
    run_health_smokes(ctx)
    configure_auth(ctx)
    run_settings_smokes(ctx)
    run_dataset_smokes(ctx)
    run_dataset_ingestion_policy_smokes(ctx)
    run_document_upload_smokes(ctx)
    run_document_preview_smokes(ctx)
    run_manual_and_batch_document_smokes(ctx)
    run_batch_upload_apply_smokes(ctx)
    run_image_smokes(ctx)
    run_pipeline_preview_smokes(ctx)
    run_governance_profile_smokes(ctx)
    run_pipeline_zip_upload_smokes(ctx)
    run_parsing_workspace_smokes(ctx)
    poll_document_status(ctx)
    run_document_pipeline_and_chunk_smokes(ctx)
    run_ragviz_smokes(ctx)
    run_chat_smokes(ctx)
    run_prompt_template_smokes(ctx)
    run_rag_smokes(ctx)
    run_eval_smokes(ctx)
    run_feedback_smokes(ctx)
    run_observability_smokes(ctx)
    run_kg_smokes(ctx)
    run_cleanup_smokes(ctx)
    probe_uncovered_openapi_endpoints(ctx.runner, ctx.openapi_paths)


def report_smoke_results(ctx: SmokeContext) -> int:
    missing = sorted(ctx.openapi_paths - ctx.runner.covered)
    failures = [result for result in ctx.runner.results if not result.ok]

    print(f"Calls: {len(ctx.runner.results)} | Failures: {len(failures)} | Missing: {len(missing)}")
    if failures:
        print("\nFailures:")
        for result in failures:
            print(f"- {result.method} {result.path}: {result.note}")
    if missing:
        print("\nMissing endpoints:")
        for method, path in missing:
            print(f"- {method} {path}")

    return 1 if failures or missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test MimirQ API endpoints.")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--auth-mode", default=None)
    parser.add_argument(
        "--jwt-identifier",
        "--jwt-email",
        dest="jwt_identifier",
        default=os.getenv("MIMIRQ_SMOKE_IDENTIFIER") or os.getenv("MIMIRQ_SMOKE_JWT_EMAIL") or "",
    )
    parser.add_argument(
        "--jwt-password",
        default=os.getenv("MIMIRQ_SMOKE_PASSWORD") or os.getenv("MIMIRQ_SMOKE_JWT_PASSWORD") or "",
    )
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
    if bool(args.jwt_identifier) != bool(args.jwt_password):
        parser.error("--jwt-identifier and --jwt-password must be provided together")

    repo_root = Path(__file__).resolve().parents[1]
    dotenv = load_dotenv(repo_root / ".env")
    live_parser_backends = parse_csv_items(args.live_parser_backends)
    live_parser_fixture = resolve_repo_path(repo_root, args.live_parser_fixture)
    if live_parser_backends and live_parser_fixture is None:
        parser.error("--live-parser-fixture is required when --live-parser-backends is set")
    if live_parser_backends and live_parser_fixture is not None and not live_parser_fixture.exists():
        parser.error(f"--live-parser-fixture not found: {live_parser_fixture}")

    with httpx.Client(timeout=args.timeout, follow_redirects=False, trust_env=False) as client:
        ctx = build_smoke_context(
            args=args,
            repo_root=repo_root,
            dotenv=dotenv,
            client=client,
            live_parser_backends=live_parser_backends,
            live_parser_fixture=live_parser_fixture,
        )
        run_smoke_scenario(ctx)
        return report_smoke_results(ctx)


if __name__ == "__main__":
    raise SystemExit(main())
