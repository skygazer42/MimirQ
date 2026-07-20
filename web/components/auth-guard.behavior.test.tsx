// @vitest-environment jsdom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const authMock = vi.hoisted(() => ({
  token: 'token' as string | null,
}))
const routerMock = vi.hoisted(() => ({
  replace: vi.fn(),
}))

vi.mock('@/lib/auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  getAccessToken: () => authMock.token,
}))
vi.mock('@/hooks/use-backend-meta', () => ({
  useBackendMeta: () => ({ data: { features: { auth_mode: 'jwt' } } }),
}))
vi.mock('@/i18n/navigation', () => ({
  usePathname: () => '/datasets',
  useRouter: () => routerMock,
}))

import { AuthGuard } from './auth-guard'

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

afterEach(() => {
  vi.clearAllMocks()
  authMock.token = 'token'
  document.body.innerHTML = ''
})

describe('AuthGuard session changes', () => {
  it('redirects when the active session is cleared asynchronously', () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(
        <AuthGuard>
          <div>private</div>
        </AuthGuard>
      )
    })
    expect(routerMock.replace).not.toHaveBeenCalled()

    authMock.token = null
    act(() => {
      window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    })

    expect(routerMock.replace).toHaveBeenCalledWith('/auth')
    expect(container.textContent).toBe('')
    act(() => root.unmount())
  })

  it('remounts private page state when the authenticated user changes', () => {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    function PrivateState() {
      const [value, setValue] = React.useState('')
      return <button onClick={() => setValue('private-a')}>{value || 'empty'}</button>
    }

    act(() => {
      root.render(
        <AuthGuard>
          <PrivateState />
        </AuthGuard>
      )
    })
    act(() => container.querySelector('button')?.click())
    expect(container.textContent).toBe('private-a')

    act(() => {
      window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    })

    expect(container.textContent).toBe('empty')
    act(() => root.unmount())
  })
})
