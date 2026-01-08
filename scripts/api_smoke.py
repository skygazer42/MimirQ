import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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


def create_zip_with_image(tmp_dir: Path) -> Path:
    import io
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test MimirQ API endpoints.")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--auth-mode", default=None)
    parser.add_argument("--openapi", default=None, help="Optional OpenAPI JSON file path.")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--skip-llm-test", action="store_true")
    parser.add_argument("--skip-mineru", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    dotenv = load_dotenv(repo_root / ".env")

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
        runner.call("GET", "/api/v1/settings", "/api/v1/settings", expected=[200])
        runner.call("GET", "/api/v1/settings/status", "/api/v1/settings/status", expected=[200])
        runner.call("PUT", "/api/v1/settings", "/api/v1/settings", expected=[200], json={})
        if not args.skip_llm_test:
            runner.call(
                "POST",
                "/api/v1/settings/llm/test",
                "/api/v1/settings/llm/test",
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
            runner.mark("POST", "/api/v1/settings/llm/test")

        # Dataset endpoints.
        dataset_payload = {"name": f"Smoke Dataset {uuid.uuid4().hex[:6]}", "description": "smoke"}
        ds_resp = runner.call("POST", "/api/v1/datasets/", "/api/v1/datasets/", expected=[201], json=dataset_payload)
        ds_id = parse_json(ds_resp).get("id")
        runner.call("GET", "/api/v1/datasets/", "/api/v1/datasets/", expected=[200])
        if ds_id:
            runner.call("GET", "/api/v1/datasets/{dataset_id}", f"/api/v1/datasets/{ds_id}", expected=[200])
            runner.call(
                "PATCH",
                "/api/v1/datasets/{dataset_id}",
                f"/api/v1/datasets/{ds_id}",
                expected=[200],
                json={"description": "smoke-updated"},
            )

        # Documents endpoints: upload a small text file.
        sample_text = "Smoke test document.\nSecond line."
        files = {"file": ("smoke.txt", sample_text.encode("utf-8"), "text/plain")}
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

        # Batch upload (multi-file).
        files_batch = [
            ("files", ("batch1.txt", b"batch-one", "text/plain")),
            ("files", ("batch2.txt", b"batch-two", "text/plain")),
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
        batch_data = parse_json(batch_resp)
        batch_docs = [item.get("document_id") for item in batch_data.get("successful", []) if item.get("document_id")]

        runner.call("GET", "/api/v1/documents/", "/api/v1/documents/?limit=5", expected=[200])

        if doc_id:
            runner.call("GET", "/api/v1/documents/{document_id}", f"/api/v1/documents/{doc_id}", expected=[200])
            runner.call(
                "GET",
                "/api/v1/documents/{document_id}/status",
                f"/api/v1/documents/{doc_id}/status",
                expected=[200],
            )

        # Preview endpoints.
        runner.call(
            "POST",
            "/api/v1/documents/preview",
            "/api/v1/documents/preview",
            expected=[200],
            files={"file": ("preview.txt", b"preview", "text/plain")},
        )
        runner.call(
            "POST",
            "/api/v1/documents/chunk-preview",
            "/api/v1/documents/chunk-preview",
            expected=[200],
            files={"file": ("chunk.txt", b"chunk preview text", "text/plain")},
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
                "/api/v1/documents/manual",
                "/api/v1/documents/manual",
                expected=[201],
                json=manual_payload,
            )
            manual_doc_id = parse_json(manual_resp).get("id")
        else:
            runner.mark("POST", "/api/v1/documents/manual")
            manual_doc_id = None

        # Batch upload URL apply (MinerU).
        if args.skip_mineru:
            runner.mark("POST", "/api/v1/documents/batch-upload/apply-urls")
            runner.mark("GET", "/api/v1/documents/batch-upload/status/{batch_id}")
        else:
            apply_resp = runner.call(
                "POST",
                "/api/v1/documents/batch-upload/apply-urls",
                "/api/v1/documents/batch-upload/apply-urls",
                expected=[200, 400, 500, 503],
                json={"files": [{"name": "a.pdf", "data_id": "smoke-a"}]},
            )
            apply_data = parse_json(apply_resp)
            batch_id = apply_data.get("batch_id")
            if batch_id:
                runner.call(
                    "GET",
                    "/api/v1/documents/batch-upload/status/{batch_id}",
                    f"/api/v1/documents/batch-upload/status/{batch_id}",
                    expected=[200, 400, 404, 500, 503],
                )
            else:
                runner.call(
                    "GET",
                    "/api/v1/documents/batch-upload/status/{batch_id}",
                    "/api/v1/documents/batch-upload/status/invalid",
                    expected=[200, 400, 404, 500, 503],
                )

        # Image endpoints: expect not found for missing ids.
        runner.call(
            "GET",
            "/api/v1/documents/image-url/{img_id}",
            "/api/v1/documents/image-url/invalid",
            expected=[404],
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
            files={"file": ("pipe.txt", b"pipeline preview", "text/plain")},
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
                    "/api/v1/pipeline/upload-zip-with-images",
                    "/api/v1/pipeline/upload-zip-with-images",
                    expected=[200],
                    files={"file": (zip_path.name, fh, "application/zip")},
                    data={"dataset_id": ds_id},
                )
        else:
            runner.mark("POST", "/api/v1/pipeline/upload-zip-with-images")

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

        # Chat endpoints (stream -> conversation).
        conversation_id = None
        if doc_id:
            conv_resp = runner.call(
                "POST",
                "/api/v1/chat/conversations",
                "/api/v1/chat/conversations",
                expected=[201],
                json={"title": "Smoke conversation", "document_ids": [doc_id]},
            )
            conversation_id = parse_json(conv_resp).get("id")
        else:
            runner.mark("POST", "/api/v1/chat/conversations")
        if doc_id:
            ok, _ = runner.stream(
                "POST",
                "/api/v1/chat/stream",
                "/api/v1/chat/stream",
                expected=[200],
                json={"message": "smoke test", "document_ids": [doc_id]},
            )
            if ok and not conversation_id:
                # Fetch conversations and pick the latest.
                conv_list = runner.call(
                    "GET",
                    "/api/v1/chat/conversations",
                    "/api/v1/chat/conversations?limit=5",
                    expected=[200],
                )
                items = parse_json(conv_list).get("items") or []
                if items:
                    conversation_id = items[0].get("id")
        else:
            runner.mark("POST", "/api/v1/chat/stream")
            runner.mark("GET", "/api/v1/chat/conversations")

        if conversation_id:
            runner.call(
                "GET",
                "/api/v1/chat/conversations/{conversation_id}/messages",
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                expected=[200],
            )
            runner.call(
                "GET",
                "/api/v1/chat/conversations",
                "/api/v1/chat/conversations?limit=5",
                expected=[200],
            )
            runner.call(
                "GET",
                "/api/v1/chat/conversations/{conversation_id}/checkpoints",
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
                "/api/v1/chat/conversations/{conversation_id}/checkpoints",
                f"/api/v1/chat/conversations/{conversation_id}/checkpoints",
                expected=[204],
            )
        else:
            runner.mark("GET", "/api/v1/chat/conversations/{conversation_id}/messages")
            runner.mark("GET", "/api/v1/chat/conversations/{conversation_id}/checkpoints")
            runner.mark("GET", "/api/v1/chat/conversations/{conversation_id}/checkpoints/{checkpoint_id}")
            runner.mark("DELETE", "/api/v1/chat/conversations/{conversation_id}/checkpoints")

        # Prompt templates.
        tmpl_payload = {
            "name": f"Smoke Template {uuid.uuid4().hex[:6]}",
            "content": "Answer the question: {question}",
            "variables": ["question"],
            "is_active": True,
        }
        tmpl_resp = runner.call(
            "POST",
            "/api/v1/prompt-templates",
            "/api/v1/prompt-templates",
            expected=[201],
            json=tmpl_payload,
        )
        tmpl_id = parse_json(tmpl_resp).get("id")
        runner.call("GET", "/api/v1/prompt-templates", "/api/v1/prompt-templates?limit=5", expected=[200])
        if tmpl_id:
            runner.call(
                "GET",
                "/api/v1/prompt-templates/{template_id}",
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
                "/api/v1/prompt-templates/{template_id}",
                f"/api/v1/prompt-templates/{tmpl_id}",
                expected=[200],
                json={"description": "smoke-updated"},
            )

        # RAG endpoints (require documents).
        if doc_id:
            rag_payload = {"query": "smoke retrieval", "document_ids": [doc_id]}
            runner.call(
                "POST",
                "/api/v1/rag/retrieve-preview",
                "/api/v1/rag/retrieve-preview",
                expected=[200],
                json=rag_payload,
            )
            runner.call(
                "POST",
                "/api/v1/rag/prompt-preview",
                "/api/v1/rag/prompt-preview",
                expected=[200],
                json=rag_payload,
            )
        else:
            runner.mark("POST", "/api/v1/rag/retrieve-preview")
            runner.mark("POST", "/api/v1/rag/prompt-preview")

        # Evaluation endpoints (require conversation).
        if conversation_id:
            eval_payload = {"conversation_id": conversation_id, "metrics": ["faithfulness"]}
            run_resp = runner.call(
                "POST",
                "/api/v1/evaluations/ragas/runs",
                "/api/v1/evaluations/ragas/runs",
                expected=[201],
                json=eval_payload,
            )
            run_id = parse_json(run_resp).get("id")
            runner.call(
                "GET",
                "/api/v1/evaluations/ragas/runs",
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
            runner.mark("POST", "/api/v1/evaluations/ragas/runs")
            runner.mark("GET", "/api/v1/evaluations/ragas/runs")
            runner.mark("GET", "/api/v1/evaluations/ragas/runs/{run_id}")

        if ds_id:
            case_payload = {
                "dataset_id": ds_id,
                "question": "smoke question",
                "expected_answer": "smoke answer",
            }
            case_resp = runner.call(
                "POST",
                "/api/v1/evaluations/ragas/regression/cases",
                "/api/v1/evaluations/ragas/regression/cases",
                expected=[201],
                json=case_payload,
            )
            case_id = parse_json(case_resp).get("id")
            runner.call(
                "GET",
                "/api/v1/evaluations/ragas/regression/cases",
                "/api/v1/evaluations/ragas/regression/cases?limit=5",
                expected=[200],
            )
            if case_id:
                runner.call(
                    "DELETE",
                    "/api/v1/evaluations/ragas/regression/cases/{case_id}",
                    f"/api/v1/evaluations/ragas/regression/cases/{case_id}",
                    expected=[204],
                )
            reg_run_resp = runner.call(
                "POST",
                "/api/v1/evaluations/ragas/regression/runs",
                "/api/v1/evaluations/ragas/regression/runs",
                expected=[201],
                json={"case_ids": [case_id] if case_id else [], "metrics": ["faithfulness"]},
            )
            reg_run_id = parse_json(reg_run_resp).get("id")
            runner.call(
                "GET",
                "/api/v1/evaluations/ragas/regression/runs",
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
            test_gen_docs = {
                "document_ids": [doc_id] if doc_id else [],
                "num_questions": 1,
                "auto_save_as_cases": False,
            }
            runner.call(
                "POST",
                "/api/v1/evaluations/ragas/test-gen/from-documents",
                "/api/v1/evaluations/ragas/test-gen/from-documents",
                expected=[200, 400, 500],
                json=test_gen_docs,
            )
        else:
            runner.mark("POST", "/api/v1/evaluations/ragas/regression/cases")
            runner.mark("GET", "/api/v1/evaluations/ragas/regression/cases")
            runner.mark("DELETE", "/api/v1/evaluations/ragas/regression/cases/{case_id}")
            runner.mark("POST", "/api/v1/evaluations/ragas/regression/runs")
            runner.mark("GET", "/api/v1/evaluations/ragas/regression/runs")
            runner.mark("GET", "/api/v1/evaluations/ragas/regression/runs/{run_id}")
            runner.mark("POST", "/api/v1/evaluations/ragas/test-gen/from-documents")

        if conversation_id:
            test_gen_conv = {
                "conversation_ids": [conversation_id],
                "num_questions": 1,
                "auto_save_as_cases": False,
            }
            runner.call(
                "POST",
                "/api/v1/evaluations/ragas/test-gen/from-conversations",
                "/api/v1/evaluations/ragas/test-gen/from-conversations",
                expected=[200, 400, 500],
                json=test_gen_conv,
            )
        else:
            runner.mark("POST", "/api/v1/evaluations/ragas/test-gen/from-conversations")

        # Feedback endpoints.
        assistant_message_id = None
        if conversation_id:
            msg_resp = runner.call(
                "GET",
                "/api/v1/chat/conversations/{conversation_id}/messages",
                f"/api/v1/chat/conversations/{conversation_id}/messages",
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
                "/api/v1/feedback/messages",
                "/api/v1/feedback/messages",
                expected=[201],
                json=feedback_payload,
            )
            runner.call(
                "GET",
                "/api/v1/feedback/messages",
                "/api/v1/feedback/messages?limit=5",
                expected=[200],
            )
        else:
            runner.mark("POST", "/api/v1/feedback/messages")
            runner.mark("GET", "/api/v1/feedback/messages")

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
        if doc_id:
            runner.call(
                "POST",
                "/api/v1/kg/documents/{document_id}/extract",
                f"/api/v1/kg/documents/{doc_id}/extract",
                expected=[200, 400, 502, 503],
            )
            runner.call(
                "POST",
                "/api/v1/kg/search",
                "/api/v1/kg/search",
                expected=[200, 400, 503],
                json={"query": "smoke"},
            )
        else:
            runner.mark("POST", "/api/v1/kg/documents/{document_id}/extract")
            runner.mark("POST", "/api/v1/kg/search")

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
                "/api/v1/prompt-templates/{template_id}",
                f"/api/v1/prompt-templates/{tmpl_id}",
                expected=[204],
            )
        else:
            runner.mark("DELETE", "/api/v1/prompt-templates/{template_id}")

        if doc_id:
            runner.call(
                "DELETE",
                "/api/v1/documents/{document_id}",
                f"/api/v1/documents/{doc_id}",
                expected=[204],
            )
        else:
            runner.mark("DELETE", "/api/v1/documents/{document_id}")

        if manual_doc_id:
            runner.call(
                "DELETE",
                "/api/v1/documents/{document_id}",
                f"/api/v1/documents/{manual_doc_id}",
                expected=[204],
            )

        if ds_id:
            runner.call(
                "DELETE",
                "/api/v1/datasets/{dataset_id}",
                f"/api/v1/datasets/{ds_id}",
                expected=[204],
            )
        else:
            runner.mark("DELETE", "/api/v1/datasets/{dataset_id}")

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
