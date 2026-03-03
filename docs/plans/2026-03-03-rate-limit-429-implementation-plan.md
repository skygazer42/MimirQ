# Standardized 429 Rate Limit Payload Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Standardize all HTTP 429 responses to include `retry_after_sec`, `limit`, and `scope`, and ensure the `Retry-After` header is preserved and consistent with the body.

**Architecture:** Keep the existing unified `ErrorResponse` wrapper (`app/core/exceptions.py`) as the canonical error envelope. For 429s, raise `HTTPException` with a structured `detail` dict (`message` + rate-limit metadata), and preserve `exc.headers` in the global HTTPException handler so `Retry-After` reaches clients.

**Tech Stack:** FastAPI, Starlette middleware (`BaseHTTPMiddleware`), pytest, axios (web client).

---

### Task 1: Preserve HTTPException headers in the global handler

**Files:**
- Modify: `app/core/exceptions.py`
- Test: `tests/test_rate_limit_429_standard_shape.py`

**Step 1: Write the failing test**

Create a small FastAPI app that registers `register_exception_handlers(app)` and raises `HTTPException(status_code=429, headers={"Retry-After": "3"}, detail={...})`. Assert:
- response status is 429
- `Retry-After` header is present and equals `"3"`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_rate_limit_429_standard_shape.py::test_http_exception_handler_preserves_retry_after_header -v`
Expected: FAIL (header missing).

**Step 3: Implement minimal change**

Update `http_exception_handler(...)` to pass `headers=exc.headers` into `JSONResponse(...)`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_rate_limit_429_standard_shape.py::test_http_exception_handler_preserves_retry_after_header -v`
Expected: PASS.

---

### Task 2: Standardize middleware rate limit 429 body

**Files:**
- Modify: `app/api/middleware/rate_limit.py`
- Test: `tests/test_rate_limit_429_standard_shape.py`

**Step 1: Write the failing test**

Build a FastAPI app with:
- `RateLimitMiddleware(requests_per_second=1, burst_size=1)`
- `register_exception_handlers(app)`
- a simple `GET /ping` endpoint

Make 2 requests back-to-back and assert the second response:
- status 429
- JSON body is an `ErrorResponse` shape with `detail.retry_after_sec`, `detail.limit`, `detail.scope`
- `Retry-After` header equals `detail.retry_after_sec` (stringified)

**Step 2: Implement minimal change**

Change `RateLimitMiddleware.dispatch(...)` to **raise** `HTTPException(429, detail={...}, headers={...})` instead of returning a raw `JSONResponse`.

---

### Task 3: Standardize tenant QPS quota 429 body

**Files:**
- Modify: `app/services/tenant_quota_service.py`
- Test: `tests/test_rate_limit_429_standard_shape.py`

**Step 1: Write the failing test**

Create a FastAPI route that calls `enforce_tenant_qps_quota(tenant_id=<fixed_uuid>, key="retrieval")`.
Configure a tiny token bucket (e.g. `TENANT_QPS_QUOTA_ENABLED=true`, `rps=1`, `burst=1`, `mode=block`), then call twice and assert:
- response 429
- `detail.scope == "tenant_qps:retrieval"`
- `Retry-After` header matches `detail.retry_after_sec`

**Step 2: Implement minimal change**

Raise `HTTPException(429, detail={message, retry_after_sec, limit, scope}, headers={"Retry-After": ...})`.

---

### Task 4: Standardize other 429 quota errors (chat tokens / upload quotas)

**Files:**
- Modify: `app/api/v1/chat.py`
- Modify: `app/services/tenant_quota_service.py`
- Optional Test: extend `tests/test_rate_limit_429_standard_shape.py`

**Steps:**
- Replace string-only 429 details with a structured `detail` dict containing:
  - `retry_after_sec`: `None` (no Retry-After header)
  - `limit`: use the quota limit (tokens/docs/bytes) when available
  - `scope`: stable string (`chat_tokens`, `tenant_docs`, `tenant_storage`)

---

### Task 5: Frontend: show friendlier 429 messaging

**Files:**
- Modify: `web/lib/api-client.ts`
- Optional: `web/lib/api-errors.ts`

**Steps:**
- For status 429, prefer parsing `data.detail.retry_after_sec` (fallback to the `Retry-After` header).
- Log/use a message like: `请求过于频繁（{scope}），请在 {retryAfter}s 后重试` when values exist.

---

### Task 6: Verify and land

**Steps:**
- Run: `make lint-py`
- Run: `make test`
- Update issue status: `bd close MimirQ-eh26.17`
- Sync + push:
  - `git pull --rebase origin main`
  - `bd sync`
  - `git push`
  - `git status` (must show up-to-date)

