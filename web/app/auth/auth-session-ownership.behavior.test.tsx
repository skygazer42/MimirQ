// @vitest-environment happy-dom

import React, { act, StrictMode, type ComponentProps } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AuthResponse } from '@/types/backend'

const ports = vi.hoisted(() => ({
  auth: { login: vi.fn(), signup: vi.fn(), policy: vi.fn() },
  router: { push: vi.fn(), replace: vi.fn() },
  fetch: vi.fn(),
}))
vi.hoisted(() => vi.stubGlobal('BroadcastChannel', undefined))
vi.mock('next/image', () => ({
  default: ({
    priority: _priority,
    unoptimized: _unoptimized,
    ...props
  }: ComponentProps<'img'> & { priority?: boolean; unoptimized?: boolean }) => React.createElement('img', props),
}))
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(window.location.search) }))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ports.router }))
vi.mock('@/lib/api', () => ({ authApi: ports.auth }))
vi.mock('@/lib/api/auth', () => ({ authApi: ports.auth }))
vi.mock('@/lib/oidc-providers', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/oidc-providers')>()),
  getOidcPublicProvidersFromEnv: () => [],
}))

import AuthPage from './page'
import OidcCallbackPage from './oidc/callback/page'
import SamlCallbackPage from './saml/callback/page'
import { clearAuthSession, getAuthSessionRevision, getStoredUser, setAuthSession } from '@/lib/auth-storage'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

function session(id: string): AuthResponse {
  return {
    user: {
      id,
      email: `${id}@example.com`,
      username: id,
      is_active: true,
      created_at: '2026-11-01T00:00:00Z',
      last_login_at: null,
    },
    token: { access_token: `${id}-access-token`, token_type: 'bearer', expires_in: 3600 },
  }
}

function idToken(id: string) {
  return `${btoa(JSON.stringify({ alg: 'none' }))}.${btoa(JSON.stringify({ sub: id, email: `${id}@example.com`, preferred_username: id }))}.fixture`
}

const mounted: Root[] = []
type EntryKind = 'credentials' | 'saml' | 'oidc'

function input(holder: HTMLElement, id: string, value: string) {
  const field = holder.querySelector<HTMLInputElement>(`#${id}`)
  expect(field).not.toBeNull()
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field, value)
    field!.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function submit(holder: HTMLElement) {
  holder.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
}

function mode(holder: HTMLElement, label: string) {
  const button = Array.from(holder.querySelectorAll('button')).find((item) => item.textContent?.trim() === label)
  expect(button).toBeDefined()
  act(() => button!.click())
}

async function begin(kind: EntryKind, pending: ReturnType<typeof deferred<AuthResponse>>, strict = false) {
  ports.auth.login.mockReturnValue(pending.promise)
  ports.fetch.mockImplementation(async (target: RequestInfo | URL) => {
    const url = String(target)
    if (url.endsWith('/.well-known/openid-configuration')) {
      return Response.json({
        authorization_endpoint: 'https://issuer.example.com/authorize',
        token_endpoint: 'https://issuer.example.com/token',
      })
    }
    if (url === 'https://issuer.example.com/token') {
      const value = await pending.promise
      return Response.json({ ...value.token, id_token: idToken(value.user.id) })
    }
    if (url === '/api/saml/session') {
      return Response.json({ ...(await pending.promise), return_to: '/saml-next' })
    }
    if (url === '/api/oidc/exchange') {
      return Response.json({ error: 'oidc_provider_unavailable' }, { status: 503 })
    }
    throw new Error(`Unexpected external request: ${url}`)
  })
  const holder = document.createElement('div')
  document.body.appendChild(holder)
  const root = createRoot(holder)
  mounted.push(root)
  if (kind === 'oidc') {
    window.history.replaceState({}, '', '/auth/oidc/callback?code=callback-code&state=callback-state')
    sessionStorage.setItem(
      'mimirq_oidc_tx:callback-state',
      JSON.stringify({
        v: 2,
        created_at_ms: Date.now(),
        provider_id: 'default',
        issuer: 'https://issuer.example.com',
        client_id: 'client-id',
        redirect_uri: 'http://localhost:3000/auth/oidc/callback',
        code_verifier: 'verifier',
        return_to: '/oidc-next',
      }),
    )
  } else window.history.replaceState({}, '', kind === 'saml' ? '/auth/saml/callback' : '/auth')
  const page = kind === 'credentials' ? <AuthPage /> : kind === 'saml' ? <SamlCallbackPage /> : <OidcCallbackPage />
  await act(async () => root.render(strict ? <StrictMode>{page}</StrictMode> : page))
  if (kind === 'credentials') {
    input(holder, 'identifier', 'old-user')
    input(holder, 'password', 'test-password')
    act(() => submit(holder))
    expect(ports.auth.login).toHaveBeenCalledOnce()
  } else {
    await act(async () => {
      await vi.waitFor(() =>
        expect(
          ports.fetch.mock.calls.some(
            ([url]) => String(url) === (kind === 'saml' ? '/api/saml/session' : 'https://issuer.example.com/token'),
          ),
        ).toBe(true),
      )
    })
  }
  return { root, holder }
}

function unmount(root: Root) {
  act(() => root.unmount())
  mounted.splice(mounted.indexOf(root), 1)
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  sessionStorage.clear()
  localStorage.clear()
  clearAuthSession()
  ports.auth.login.mockReset()
  ports.auth.signup.mockReset()
  ports.auth.policy.mockResolvedValue({ initialized: true, registration_enabled: true })
  ports.router.push.mockReset()
  ports.router.replace.mockReset()
  ports.fetch.mockReset()
  vi.stubGlobal('fetch', ports.fetch)
})

afterEach(() => {
  for (const root of mounted.splice(0)) act(() => root.unmount())
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe.each([
  ['credentials', '/'],
  ['saml', '/saml-next'],
  ['oidc', '/oidc-next'],
] as const)('%s sign-in result ownership', (kind, returnTo) => {
  it('does not replace a newer explicitly established account', async () => {
    const pending = deferred<AuthResponse>()
    await begin(kind, pending)
    setAuthSession(session('new-user'))

    await act(async () => pending.resolve(session('old-user')))

    expect(getStoredUser()?.id).toBe('new-user')
    expect(ports.router.push).not.toHaveBeenCalled()
    expect(ports.router.replace).not.toHaveBeenCalled()
  })

  it('does not establish a session after its page is unmounted', async () => {
    const pending = deferred<AuthResponse>()
    const view = await begin(kind, pending)
    unmount(view.root)

    await act(async () => pending.resolve(session('old-user')))

    expect(getStoredUser()).toBeNull()
    expect(ports.router.push).not.toHaveBeenCalled()
    expect(ports.router.replace).not.toHaveBeenCalled()
  })

  it('does not republish after an explicit login using the same account and token', async () => {
    const pending = deferred<AuthResponse>()
    await begin(kind, pending)
    setAuthSession(session('old-user'))
    const revision = getAuthSessionRevision()

    await act(async () => pending.resolve(session('old-user')))

    expect(getAuthSessionRevision()).toBe(revision)
    expect(ports.router.push).not.toHaveBeenCalled()
    expect(ports.router.replace).not.toHaveBeenCalled()
  })

  it('keeps its current sign-in failure visible without establishing a session', async () => {
    const pending = deferred<AuthResponse>()
    const view = await begin(kind, pending)

    await act(async () => pending.reject(new Error(kind === 'oidc' ? 'Failed to fetch' : 'current sign-in rejected')))

    expect(getStoredUser()).toBeNull()
    expect(ports.router.push).not.toHaveBeenCalled()
    expect(ports.router.replace).not.toHaveBeenCalled()
    expect(view.holder.textContent).toContain(
      kind === 'saml'
        ? '登录会话已失效，请返回登录页重新发起登录。'
        : kind === 'oidc'
          ? 'oidc_provider_unavailable'
          : 'current sign-in rejected',
    )
  })

  it('completes its current sign-in once through StrictMode effect replay', async () => {
    const pending = deferred<AuthResponse>()
    await begin(kind, pending, true)

    await act(async () => pending.resolve(session('old-user')))

    expect(getStoredUser()?.id).toBe('old-user')
    const navigate = kind === 'credentials' ? ports.router.push : ports.router.replace
    expect(navigate).toHaveBeenCalledExactlyOnceWith(returnTo)
  })
})

describe('credential form request ownership', () => {
  it('does not issue a second request for two synchronous submissions', async () => {
    const pending = deferred<AuthResponse>()
    const view = await begin('credentials', pending)
    await act(async () => pending.resolve(session('old-user')))
    ports.auth.login.mockClear()
    clearAuthSession()
    const next = deferred<AuthResponse>()
    ports.auth.login.mockReturnValue(next.promise)

    act(() => {
      submit(view.holder)
      submit(view.holder)
    })

    expect(ports.auth.login).toHaveBeenCalledOnce()
    await act(async () => next.resolve(session('old-user')))
  })

  it('keeps the pending mode fixed and clears a completed failure when revisiting login', async () => {
    const pending = deferred<AuthResponse>()
    const view = await begin('credentials', pending)
    expect(view.holder.querySelector<HTMLButtonElement>('[data-auth-mode-switch] button')?.disabled).toBe(true)
    await act(async () => pending.reject(new Error('retired-login-failure')))
    mode(view.holder, '注册')
    mode(view.holder, '登录')

    expect(view.holder.querySelector('[role="alert"]')).toBeNull()
    expect(view.holder.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(false)
  })
})
