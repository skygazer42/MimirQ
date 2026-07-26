// @vitest-environment happy-dom

import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const authMock = vi.hoisted(() => ({
  token: 'token' as string | null,
}))
const backendMetaMock = vi.hoisted(() => ({
  authMode: 'jwt' as string | null,
  isPending: false,
  isError: false,
}))
const navigationMock = vi.hoisted(() => ({
  pathname: '/datasets',
}))
const routerMock = vi.hoisted(() => ({
  replace: vi.fn(),
}))

vi.mock('@/lib/auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  getAccessToken: () => authMock.token,
}))
vi.mock('@/hooks/use-backend-meta', () => ({
  useBackendMeta: () => ({
    data:
      typeof backendMetaMock.authMode === 'string'
        ? { features: { auth_mode: backendMetaMock.authMode } }
        : undefined,
    isPending: backendMetaMock.isPending,
    isError: backendMetaMock.isError,
  }),
}))
vi.mock('@/i18n/navigation', () => ({
  usePathname: () => navigationMock.pathname,
  useRouter: () => routerMock,
}))

import { AuthGuard } from './auth-guard'

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

afterEach(() => {
  vi.clearAllMocks()
  authMock.token = 'token'
  backendMetaMock.authMode = 'jwt'
  backendMetaMock.isPending = false
  backendMetaMock.isError = false
  navigationMock.pathname = '/datasets'
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

  it('keeps protected children unmounted while backend auth mode is unresolved', () => {
    backendMetaMock.authMode = null
    backendMetaMock.isPending = true
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

    expect(container.textContent).toBe('')
    expect(routerMock.replace).not.toHaveBeenCalled()
    act(() => root.unmount())
  })

  it('renders auth routes while backend auth mode is unresolved', () => {
    backendMetaMock.authMode = null
    backendMetaMock.isPending = true
    navigationMock.pathname = '/auth'
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)

    act(() => {
      root.render(
        <AuthGuard>
          <div>sign-in</div>
        </AuthGuard>
      )
    })

    expect(container.textContent).toBe('sign-in')
    expect(routerMock.replace).not.toHaveBeenCalled()
    act(() => root.unmount())
  })

  it('fails closed when backend auth mode cannot be resolved on a protected route', () => {
    backendMetaMock.authMode = null
    backendMetaMock.isError = true
    authMock.token = null
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

    expect(container.textContent).toBe('')
    expect(routerMock.replace).toHaveBeenCalledWith('/auth')
    act(() => root.unmount())
  })
})
