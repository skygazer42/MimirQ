# Security/Compliance Hardening (Prod-Strict Baseline) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a production-safe security/compliance baseline that (1) prevents leaking internal tenant/user context headers to third-party services, (2) strengthens production defaults (hosts/CORS/docs/headers/body limits), and (3) improves auditability for sensitive settings updates.

**Architecture:** Add an "external" outbound HTTP client profile (no internal context headers) and migrate all third-party call sites to use it. Add production-gated validation/defaults for host/CORS/docs/security headers, plus new middleware for response header stripping and request body size limits. Add `.env` write hardening and audit logging to Settings API.

**Tech Stack:** FastAPI/Starlette, httpx, Pydantic Settings (v2), pytest, ruff, GitHub Actions.

---

## Preflight (Do Once)

**Step 1: Confirm baseline is clean**

Run:

```bash
git status -sb
bd status
python -m pytest -q
python -m ruff check app tests scripts main.py
```

Expected:

- `git status` clean (or only planned changes).
- Tests pass.

**Step 2: Claim work**

Run:

```bash
bd update MimirQ-xj7.1 --status in_progress
```

---

### Task 1 (MimirQ-xj7.1): External HTTP Client Mode (No Internal Context Headers)

**Files:**

- Modify: `app/core/http_client.py`
- Modify: `app/core/config.py` (optional knobs)
- Test: `tests/test_http_client_context_headers.py` (new)

**Step 1: Write failing tests**

Create `tests/test_http_client_context_headers.py` with tests for header injection behavior:

```python
import httpx

from app.core.http_client import HTTPClientPool
from app.core.logging_config import bind_request_context, reset_request_context


def test_external_client_does_not_inject_tenant_or_user_headers():
    pool = HTTPClientPool()
    tokens = bind_request_context(request_id="rid", tenant_id="tid", user_id="uid")
    try:
        req = httpx.Request("GET", "https://example.com/")
        pool._inject_external_context_headers(req)  # added in implementation
        assert "X-Tenant-ID" not in req.headers
        assert "X-User-ID" not in req.headers
    finally:
        reset_request_context(tokens)
```

**Step 2: Run tests to see failure**

Run:

```bash
python -m pytest -q tests/test_http_client_context_headers.py
```

Expected: FAIL (missing method / behavior not implemented).

**Step 3: Implement minimal code**

In `app/core/http_client.py`:

- Split context header injection into:
  - internal injection (request_id + tenant + user)
  - external injection (request_id only, or optionally none)
- Add cached external sync/async clients:
  - `get_external_sync_client()`
  - `get_external_async_client()`
- Keep `get_sync_client()` / `get_async_client()` behavior as internal by default.

**Step 4: Run tests to verify pass**

Run:

```bash
python -m pytest -q tests/test_http_client_context_headers.py
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/core/http_client.py app/core/config.py tests/test_http_client_context_headers.py
git commit -m "feat(security): add external http client profile (no tenant/user headers)"
bd close MimirQ-xj7.1
```

---

### Task 2 (MimirQ-xj7.2): RAG LLM Calls Use External HTTP Client

**Files:**

- Modify: `app/rag/engine.py`
- Test: `tests/test_rag_engine_uses_external_http_clients.py` (new)

**Step 1: Write failing test**

Create `tests/test_rag_engine_uses_external_http_clients.py`:

```python
from types import SimpleNamespace


def test_rag_engine_uses_external_http_client(monkeypatch):
    calls = {"sync": 0, "async": 0}

    class FakePool:
        def get_external_sync_client(self):
            calls["sync"] += 1
            return object()
        def get_external_async_client(self):
            calls["async"] += 1
            return object()

    monkeypatch.setattr("app.rag.engine.get_http_client_pool", lambda: FakePool())
    monkeypatch.setattr("app.rag.engine.settings", SimpleNamespace(LLM_MOCK_ENABLED=True, LLM_MOCK_RESPONSE="ok", ENABLE_DYNAMIC_MODEL_ROUTING=False, LLM_MODEL="m", LLM_MODEL_FAST=None, LLM_MODEL_HEAVY=None))

    from app.rag.engine import RAGEngine
    RAGEngine()
    assert calls["sync"] == 1
    assert calls["async"] == 1
```

**Step 2: Run and see it fail**

Run:

```bash
python -m pytest -q tests/test_rag_engine_uses_external_http_clients.py
```

Expected: FAIL until `RAGEngine` uses the external clients.

**Step 3: Implement**

In `app/rag/engine.py`, replace:

- `pool.get_sync_client()` -> `pool.get_external_sync_client()`
- `pool.get_async_client()` -> `pool.get_external_async_client()`

**Step 4: Run tests**

Run:

```bash
python -m pytest -q tests/test_rag_engine_uses_external_http_clients.py
```

Expected: PASS.

**Step 5: Commit**

```bash
git add app/rag/engine.py tests/test_rag_engine_uses_external_http_clients.py
git commit -m "fix(security): prevent leaking tenant/user headers to LLM providers"
bd close MimirQ-xj7.2
```

---

### Task 3 (MimirQ-xj7.3): Embedding Outbound Calls Header Guardrails

**Files:**

- Modify: `app/rag/embedding/providers/openai.py` (optional refactor to use external pool)
- Test: `tests/test_embedding_outbound_does_not_use_internal_headers.py` (new)

**Step 1: Write failing test (behavioral)**

Write a test that ensures any shared HTTP client used by embedding providers is the external profile.

If embeddings remain on `requests`/ad-hoc `httpx.AsyncClient`, document as non-applicable and add a regression test asserting no dependency on request context vars.

**Step 2: Implement**

Preferred: refactor to use `HTTPClientPool.get_external_*` for consistency and to guarantee no internal header injection.

**Step 3: Verify**

Run:

```bash
python -m pytest -q tests/test_embedding_outbound_does_not_use_internal_headers.py
```

**Step 4: Commit**

```bash
git add app/rag/embedding/providers/openai.py tests/test_embedding_outbound_does_not_use_internal_headers.py
git commit -m "feat(security): enforce external http client for embedding providers"
bd close MimirQ-xj7.3
```

---

### Task 4 (MimirQ-xj7.4): URL Ingest Uses External HTTP Client

**Files:**

- Modify: `app/api/utils/url_ingest.py`
- Test: `tests/test_url_ingest_does_not_leak_internal_headers.py` (new)

**Steps (TDD):**

1. Add a test that patches `get_http_client_pool()` and asserts the external client is used.
2. Run test: expect fail.
3. Implement: use `pool.get_external_async_client()` (or `pool.get_external_client()` wrapper).
4. Run test: expect pass.
5. Commit + `bd close MimirQ-xj7.4`.

---

### Task 5 (MimirQ-xj7.5): Web Crawler Uses External HTTP Client

**Files:**

- Modify: `app/services/web_crawler.py`
- Test: `tests/test_web_crawler_does_not_leak_internal_headers.py` (new)

**Steps (TDD):**

1. Add test asserting external client usage.
2. Implement migration to external client.
3. Verify tests.
4. Commit + close.

---

### Task 6 (MimirQ-xj7.6): Connectors Outbound HTTP Uses External HTTP Client

**Files:**

- Modify: `app/api/v1/connectors.py` (and any connector helper modules)
- Test: `tests/test_connectors_outbound_http_uses_external_client.py` (new)

**Steps (TDD):**

1. Add targeted test for Confluence connector HTTP path.
2. Implement: external client for third-party calls.
3. Verify.
4. Commit + close.

---

### Task 7 (MimirQ-xj7.7): Regression Test Suite For Outbound Header Leakage

**Files:**

- Create: `tests/helpers/outbound_http_assertions.py` (new)
- Modify: tests from Tasks 1-6 to reuse helper

**Steps:**

1. Create helper `assert_no_internal_context_headers(headers, tenant_header_name="X-Tenant-ID")`.
2. Update tests to use helper.
3. Run `python -m pytest -q`.
4. Commit + close.

---

### Task 8 (MimirQ-xj7.8): TrustedHost Protection In Production

**Files:**

- Modify: `app/core/config.py` (ALLOWED_HOSTS + validation)
- Modify: `app/main.py` (add TrustedHostMiddleware in prod)
- Test: `tests/test_allowed_hosts_validation.py` (new)

**Steps (TDD):**

1. Add test: in production env, empty `ALLOWED_HOSTS` triggers validation error.
2. Implement settings + validation and middleware wiring.
3. Verify tests.
4. Commit + close.

---

### Task 9 (MimirQ-xj7.9): Production CORS Validation (Fail Closed)

**Files:**

- Modify: `app/core/config.py`
- Test: `tests/test_cors_prod_validation.py` (new)

**Steps:**

1. Add tests that `ENV=production` + localhost origins fail.
2. Implement validation in Settings validator.
3. Run tests.
4. Commit + close.

---

### Task 10 (MimirQ-xj7.10): Configurable CORS allow_credentials

**Files:**

- Modify: `app/core/config.py` (CORS_ALLOW_CREDENTIALS)
- Modify: `app/main.py` (wire allow_credentials)
- Test: `tests/test_cors_allow_credentials_setting.py` (new)

**Steps:**

1. Add failing test (prod default false unless set).
2. Implement dynamic default (prod-safe) + wiring.
3. Verify.
4. Commit + close.

---

### Task 11 (MimirQ-xj7.11): Expand Security Headers Middleware

**Files:**

- Modify: `app/api/middleware/security_headers.py`
- Modify: `app/core/config.py` (new settings for headers)
- Test: `tests/test_security_headers_middleware.py` (extend)

**Steps:**

1. Add tests for new headers (HSTS, Permissions-Policy, COOP/CORP).
2. Implement middleware + config wiring.
3. Run tests.
4. Commit + close.

---

### Task 12 (MimirQ-xj7.12): Strip Server Fingerprint Headers

**Files:**

- Create: `app/api/middleware/response_header_sanitizer.py`
- Modify: `app/main.py` (add middleware)
- Test: `tests/test_response_header_sanitizer.py` (new)

**Steps:**

1. Write failing test asserting `Server` header is removed if present.
2. Implement middleware.
3. Verify.
4. Commit + close.

---

### Task 13 (MimirQ-xj7.13): Disable Docs/OpenAPI In Production By Default

**Files:**

- Modify: `app/core/config.py`
- Modify: `app/main.py` (FastAPI docs_url/redoc_url/openapi_url)
- Test: `tests/test_docs_disabled_in_prod.py` (new)

**Steps:**

1. Write failing test: with ENV=production and default settings, FastAPI app has docs disabled.
2. Implement settings (dynamic defaults) and wiring.
3. Verify.
4. Commit + close.

---

### Task 14 (MimirQ-xj7.14): Request Body Size Limit Middleware

**Files:**

- Create: `app/api/middleware/body_size_limit.py`
- Modify: `app/core/config.py` (REQUEST_MAX_BODY_BYTES)
- Modify: `app/main.py` (add middleware)
- Test: `tests/test_body_size_limit_middleware.py` (new)

**Steps:**

1. Write failing test: Content-Length above limit returns 413.
2. Implement middleware (Content-Length gate, configurable, 0 disables).
3. Verify.
4. Commit + close.

---

### Task 15 (MimirQ-xj7.15): Disable `.env` Write Endpoint In Production By Default

**Files:**

- Modify: `app/core/config.py` (SETTINGS_ENV_WRITE_ENABLED default/validation)
- Modify: `app/api/v1/settings.py` (enforce)
- Test: `tests/test_settings_env_write_prod_guard.py` (new)

**Steps:**

1. Add failing test: ENV=production and default config rejects update_settings.
2. Implement setting + guard.
3. Verify.
4. Commit + close.

---

### Task 16 (MimirQ-xj7.16): Audit Log Settings Changes (No Secret Values)

**Files:**

- Modify: `app/api/v1/settings.py`
- Modify: `app/services/audit_log_service.py` (if helper needed)
- Test: `tests/test_settings_update_writes_audit_log.py` (new)

**Steps:**

1. Add failing test: update_settings writes an AuditLog row with updated keys and no values.
2. Implement: call `audit_log_event(...)` and commit audit log transaction best-effort.
3. Verify.
4. Commit + close.

---

### Task 17 (MimirQ-xj7.17): Auth Dependency Populates request.state user/tenant

**Files:**

- Modify: `app/api/dependencies/auth.py`
- Test: `tests/test_auth_dependency_sets_request_state.py` (new)

**Steps:**

1. Write failing test verifying request.state.user_id after auth dependency.
2. Implement.
3. Verify.
4. Commit + close.

---

### Task 18 (MimirQ-xj7.18): Tenant Resolution Can Prefer Verified JWT Tenant

**Files:**

- Modify: `app/api/dependencies/tenant.py`
- Modify: `app/core/config.py` (new setting)
- Test: `tests/test_tenant_dependency_prefers_verified_jwt_tenant.py` (new)

**Steps:**

1. Add failing test covering new behavior when enabled.
2. Implement (gated by setting, production-focused).
3. Verify.
4. Commit + close.

---

### Task 19 (MimirQ-xj7.19): Security CI Workflow Version Alignment

**Files:**

- Modify: `.github/workflows/security.yml`

**Steps:**

1. Update `pip-audit` version to match repo tooling policy.
2. Verify YAML syntax.
3. Commit + close.

---

### Task 20 (MimirQ-xj7.20): Update Security/Compliance Deployment Docs

**Files:**

- Modify: `SECURITY.md`
- Optionally modify: `README.md` or `docs/` (deployment checklist)

**Steps:**

1. Add production checklist and document new settings.
2. Commit + close.

---

## Quality Gates (Before Merge)

Run:

```bash
python -m ruff check app tests scripts main.py
python -m pytest -q
make verify
```

Expected: all pass.

## Landing The Plane (MANDATORY)

```bash
git pull --rebase
bd sync
git push
git status -sb
```

