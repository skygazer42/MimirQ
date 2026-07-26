// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  consume: vi.fn(),
  setAuthSession: vi.fn(),
}))

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ replace: mocks.replace }),
}))
vi.mock('@/lib/saml-session', () => ({
  consumeSamlBridgeState: mocks.consume,
  getSamlCallbackErrorMessage: (code: string) =>
    code === 'saml_invalid_response'
      ? 'The identity provider returned an invalid SAML response.'
      : 'SAML sign-in failed. Please try again.',
}))
vi.mock('@/lib/auth-storage', () => ({
  setAuthSession: mocks.setAuthSession,
}))
vi.mock('@/components/full-screen-frame', () => ({
  FullScreenFrame: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div className={className}>{children}</div>
  ),
}))
vi.mock('@/components/ui/button', () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props}>{children}</button>,
}))

import SamlCallbackPage from './page'

describe('SAML callback page', () => {
  beforeEach(() => {
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    vi.clearAllMocks()
    window.history.replaceState({}, '', '/auth/saml/callback')
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('redeems the bridge session and redirects on success', async () => {
    mocks.consume.mockResolvedValue({
      kind: 'success',
      returnTo: '/datasets/123',
      session: {
        user: { id: 'user-1' },
        token: { access_token: 'jwt-token', token_type: 'bearer', expires_in: 3600 },
      },
    })

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<SamlCallbackPage />)
      await Promise.resolve()
    })

    expect(mocks.setAuthSession).toHaveBeenCalledWith(
      expect.objectContaining({
        token: expect.objectContaining({ access_token: 'jwt-token' }),
      })
    )
    expect(mocks.replace).toHaveBeenCalledWith('/datasets/123')

    act(() => root.unmount())
  })

  it('maps a routed error code without redeeming a session', async () => {
    window.history.replaceState({}, '', '/auth/saml/callback?error=saml_invalid_response')

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<SamlCallbackPage />)
      await Promise.resolve()
    })

    expect(mocks.consume).not.toHaveBeenCalled()
    expect(container.textContent).toContain('The identity provider returned an invalid SAML response.')
    expect(container.textContent).not.toContain('saml_invalid_response')
    act(() => root.unmount())
  })

  it('does not echo arbitrary routed error text', async () => {
    window.history.replaceState({}, '', '/auth/saml/callback?error=debug%20stack%20trace')

    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<SamlCallbackPage />)
      await Promise.resolve()
    })

    expect(mocks.consume).not.toHaveBeenCalled()
    expect(container.textContent).toContain('SAML sign-in failed. Please try again.')
    expect(container.textContent).not.toContain('debug stack trace')
    act(() => root.unmount())
  })
})
