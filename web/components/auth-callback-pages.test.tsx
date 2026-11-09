// @vitest-environment happy-dom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ search: '', replace: vi.fn(), complete: vi.fn(), bridge: vi.fn(), session: vi.fn() }))
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(mocks.search) }))
vi.mock('@/i18n/navigation', () => ({ useRouter: () => ({ replace: mocks.replace }) }))
vi.mock('@/lib/oidc', () => ({ completeOidcLogin: mocks.complete }))
vi.mock('@/lib/saml-session', () => ({ consumeSamlBridgeState: mocks.bridge, getSamlCallbackErrorMessage: (error: string) => `登录失败：${error}` }))
vi.mock('@/lib/auth-storage', () => ({ setAuthSession: mocks.session }))
vi.mock('@/components/brand-logo', () => ({ BrandLogo: () => <span>ragvia</span> }))
import OidcCallback from '@/app/auth/oidc/callback/page'
import SamlCallback from '@/app/auth/saml/callback/page'
import { AuthCallbackState } from './auth-callback-state'

describe('SSO callback presentation preserves session and return contracts', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    mocks.search = ''; vi.clearAllMocks(); window.history.replaceState({}, '', '/')
    container = document.createElement('div'); document.body.append(container); root = createRoot(container)
  })
  afterEach(() => { act(() => root.unmount()); document.body.innerHTML = '' })

  it('rejects incomplete OIDC callbacks before exchanging a code', async () => {
    await act(async () => root.render(<OidcCallback />))
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('登录信息不完整')
    expect(mocks.complete).not.toHaveBeenCalled()
    expect(mocks.replace).not.toHaveBeenCalled()
  })
  it('uses the original OIDC completion helper and validated return target', async () => {
    mocks.search = 'code=local-code&state=local-state'
    mocks.complete.mockResolvedValue({ returnTo: '/history' })
    await act(async () => root.render(<OidcCallback />))
    expect(mocks.complete).toHaveBeenCalledOnce()
    expect(mocks.complete).toHaveBeenCalledWith({ code: 'local-code', state: 'local-state' })
    expect(mocks.replace).toHaveBeenCalledWith('/history')
  })
  it('retains an OIDC validation error and offers recovery', async () => {
    mocks.search = 'code=local-code&state=invalid-state'
    mocks.complete.mockRejectedValue(new Error('登录状态校验失败'))
    await act(async () => root.render(<OidcCallback />))
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('登录状态校验失败')
    expect(mocks.replace).not.toHaveBeenCalled()
    act(() => container.querySelector('button')!.click())
    expect(mocks.replace).toHaveBeenCalledWith('/auth')
  })
  it('establishes the original SAML session before returning to its target', async () => {
    const session = { accessToken: 'isolated-ui-test-token', refreshToken: 'isolated-ui-test-refresh', user: { id: 'test-user' } }
    mocks.bridge.mockResolvedValue({ kind: 'success', session, returnTo: '/datasets' })
    await act(async () => root.render(<SamlCallback />))
    expect(mocks.session).toHaveBeenCalledWith(session)
    expect(mocks.replace).toHaveBeenCalledWith('/datasets')
    expect(mocks.session.mock.invocationCallOrder[0]).toBeLessThan(mocks.replace.mock.invocationCallOrder[0])
  })
  it('does not establish a session for an invalid SAML bridge', async () => {
    mocks.bridge.mockResolvedValue({ kind: 'error', error: 'saml_session_missing' })
    await act(async () => root.render(<SamlCallback />))
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('登录失败')
    expect(mocks.session).not.toHaveBeenCalled()
    expect(mocks.replace).not.toHaveBeenCalled()
  })
  it.each(['working', 'success'] as const)('announces the %s status without a recovery action', async status => {
    await act(async () => root.render(<AuthCallbackState status={status} error={null} onBack={mocks.replace} />))
    expect(container.querySelector('[role="status"]')).not.toBeNull()
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector('h1')?.textContent).toBe(status === 'working' ? '正在验证登录信息' : '登录成功')
  })
})
