# SAML ACS Productionization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current SAML ACS stub with a production-grade flow that validates SAML assertions, maps the user to an existing MimirQ account, issues a normal MimirQ JWT session, and bridges that session into the frontend.

**Architecture:** The backend becomes the source of truth for SAML validation and app-session issuance. The Next.js ACS route stays as the public browser-facing bridge: it receives the IdP POST, forwards the raw assertion to a backend `/api/v1/auth/saml/exchange` endpoint, then redirects the browser into a frontend callback that stores the returned MimirQ session using the existing localStorage contract. Replay protection uses Redis when available and falls back to an in-process TTL cache.

**Tech Stack:** FastAPI, SQLAlchemy, Next.js App Router, TypeScript, Vitest, pytest, `python-jose`, `cryptography`, `signxml`.

---

### Task 1: Add the backend contract and the first failing SAML validation tests

**Files:**
- Modify: `requirements.txt`
- Modify: `app/api/schemas/auth.py`
- Create: `tests/test_saml_auth_exchange.py`

**Step 1: Write the failing test**

```python
def test_exchange_saml_response_returns_auth_session_for_valid_assertion():
    session = exchange_saml_response(...)
    assert session.user.email == "alice@example.com"
    assert session.token.access_token
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_saml_auth_exchange.py -k valid -v`
Expected: FAIL because `exchange_saml_response` and the SAML request/response schema do not exist yet.

**Step 3: Add minimal schema/dependency plumbing**

```python
class SamlExchangeRequest(BaseModel):
    provider_id: str | None = None
    saml_response: str
    relay_state: str | None = None
    acs_url: str | None = None


class SamlExchangeResponse(AuthResponse):
    return_to: str = "/"
```

**Step 4: Re-run the same test**

Run: `pytest tests/test_saml_auth_exchange.py -k valid -v`
Expected: FAIL deeper inside the missing backend SAML service.

**Step 5: Commit**

```bash
git add requirements.txt app/api/schemas/auth.py tests/test_saml_auth_exchange.py
git commit -m "test: add backend saml exchange contract"
```

### Task 2: Implement backend SAML validation, replay protection, and app JWT issuance

**Files:**
- Modify: `app/api/v1/auth.py`
- Modify: `app/core/config.py`
- Modify: `app/core/jwt_utils.py`
- Modify: `app/services/user_service.py`
- Create: `app/services/saml_service.py`
- Create: `app/services/saml_replay_service.py`
- Test: `tests/test_saml_auth_exchange.py`

**Step 1: Write the next failing tests**

```python
def test_exchange_saml_response_rejects_expired_assertion(): ...
def test_exchange_saml_response_rejects_replayed_assertion(): ...
def test_exchange_saml_response_rejects_invalid_signature(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_saml_auth_exchange.py -k "expired or replay or invalid" -v`
Expected: FAIL because signature/time-window/replay checks are not implemented.

**Step 3: Write minimal implementation**

```python
def create_access_token(..., extra_claims: dict[str, Any] | None = None) -> tuple[str, int]:
    payload = {"sub": subject, "exp": expire_at, "iat": issued_at}
    payload.update(extra_claims or {})


def exchange_saml_response(db: Session, payload: SamlExchangeRequest) -> SamlExchangeResponse:
    assertion = validate_saml_response(...)
    user = resolve_saml_user(db, assertion)
    token, expires_in = create_access_token(str(user.id), tenant_id=tenant_id, extra_claims=group_claims)
    return SamlExchangeResponse(user=user, token=TokenResponse(access_token=token, expires_in=expires_in), return_to=return_to)
```

**Step 4: Add the endpoint wrapper**

```python
@router.post("/saml/exchange", response_model=SamlExchangeResponse)
def saml_exchange(payload: SamlExchangeRequest, db: Session = Depends(get_db)) -> SamlExchangeResponse:
    return exchange_saml_response(db, payload)
```

**Step 5: Re-run backend tests**

Run: `pytest tests/test_saml_auth_exchange.py -v`
Expected: PASS for valid, invalid, expired, replay, and unknown-user coverage.

**Step 6: Commit**

```bash
git add app/api/v1/auth.py app/core/config.py app/core/jwt_utils.py app/services/user_service.py app/services/saml_service.py app/services/saml_replay_service.py tests/test_saml_auth_exchange.py
git commit -m "feat: validate saml assertions and issue app sessions"
```

### Task 3: Add frontend ACS bridge tests before implementing the route and callback

**Files:**
- Create: `web/app/api/saml/acs/route.test.ts`
- Create: `web/app/auth/saml/callback/page.tsx`
- Create: `web/lib/saml-session.ts`
- Test: `web/app/api/saml/saml.no-store.test.ts`

**Step 1: Write the failing tests**

```ts
it('forwards SAMLResponse to backend exchange and redirects to callback on success', async () => {
  const res = await POST(requestWithFormData)
  expect(res.status).toBe(303)
  expect(res.headers.get('location')).toBe('/auth/saml/callback')
})
```

**Step 2: Run test to verify it fails**

Run: `pnpm --dir web vitest run app/api/saml/acs/route.test.ts`
Expected: FAIL because the ACS route still returns `501 saml_not_implemented`.

**Step 3: Implement the minimal bridge**

```ts
const backendRes = await fetch(`${API_V1_BASE_URL}/auth/saml/exchange`, { method: 'POST', body: JSON.stringify(...) })
response.cookies.set({ name: SAML_SESSION_COOKIE, value: encodedSession, path: '/auth/saml/callback', maxAge: 60 })
return NextResponse.redirect(new URL('/auth/saml/callback', req.url), 303)
```

**Step 4: Re-run frontend tests**

Run: `pnpm --dir web vitest run app/api/saml/acs/route.test.ts app/api/saml/saml.no-store.test.ts`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/app/api/saml/acs/route.ts web/app/api/saml/acs/route.test.ts web/app/auth/saml/callback/page.tsx web/lib/saml-session.ts web/app/api/saml/saml.no-store.test.ts
git commit -m "feat: bridge saml acs into frontend session callback"
```

### Task 4: Update auth messaging/docs and run focused verification

**Files:**
- Modify: `web/app/auth/page.tsx`
- Modify: `web/README.md`
- Modify: `docs/guides/saml_sso.md`
- Test: `tests/test_saml_auth_exchange.py`
- Test: `web/app/api/saml/acs/route.test.ts`

**Step 1: Write the failing doc/UI expectation test if needed**

```ts
expect(authPageSource).toContain('SAML')
```

**Step 2: Implement minimal messaging/docs**

```tsx
<p className="text-xs text-muted-foreground">Enterprise SSO supports OIDC and IdP-initiated SAML when configured.</p>
```

**Step 3: Run focused verification**

Run: `pytest tests/test_saml_auth_exchange.py -v`
Expected: PASS

Run: `pnpm --dir web vitest run app/api/saml/acs/route.test.ts app/api/saml/saml.no-store.test.ts`
Expected: PASS

Run: `pnpm --dir web test -- --runInBand`
Expected: PASS or bounded known-failure set explained before landing.

**Step 4: Commit**

```bash
git add web/app/auth/page.tsx web/README.md docs/guides/saml_sso.md
git commit -m "docs: document production saml acs flow"
```

### Task 5: Land the branch with the required session-close workflow

**Files:**
- Update issue: `MimirQ-ygdj.1`

**Step 1: Sync issue state**

Run: `bd close MimirQ-ygdj.1`
Expected: issue closes only after code/tests/docs are complete.

**Step 2: Pull, sync, and push**

Run: `git pull --rebase`
Expected: branch rebases cleanly.

Run: `bd sync`
Expected: issue metadata sync succeeds.

Run: `git push --set-upstream origin mimirq-ygdj1-saml-acs`
Expected: push succeeds.

**Step 3: Verify clean handoff**

Run: `git status`
Expected: clean working tree and branch up to date with remote.
