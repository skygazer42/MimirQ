// @vitest-environment happy-dom

import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderHook, waitForAssertion } from '@/test/hook-harness'

const authState = vi.hoisted(() => ({
  token: 'token',
  storedUser: { id: 'user-a', email: 'user@example.com' },
  clearAuthSession: vi.fn(),
  setStoredUser: vi.fn(),
  me: vi.fn(),
}))

vi.mock('@/lib/api/auth', () => ({
  authApi: {
    me: authState.me,
  },
}))

vi.mock('@/lib/auth-storage', () => ({
  clearAuthSession: authState.clearAuthSession,
  getAccessToken: () => authState.token,
  getStoredUser: () => authState.storedUser,
  setStoredUser: authState.setStoredUser,
}))

import { useAuth } from './use-auth'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return function Wrapper({
    children,
  }: Readonly<{ children: React.ReactNode }>) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }
}

describe('useAuth', () => {
  beforeEach(() => {
    ;(
      globalThis as typeof globalThis & {
        IS_REACT_ACT_ENVIRONMENT?: boolean
      }
    ).IS_REACT_ACT_ENVIRONMENT = true
    authState.token = 'token'
    authState.storedUser = { id: 'user-a', email: 'user@example.com' }
    authState.clearAuthSession.mockReset()
    authState.setStoredUser.mockReset()
    authState.me.mockReset()
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('keeps the active session when profile refresh fails with a server error', async () => {
    const failure = Object.assign(new Error('backend unavailable'), {
      response: { status: 500 },
    })
    authState.me.mockRejectedValue(failure)

    const hook = renderHook(() => useAuth(), { wrapper: createWrapper() })

    await hook.result.current.refresh()

    await waitForAssertion(() => {
      expect(hook.result.current.error).toBe(failure)
    })

    expect(authState.clearAuthSession).not.toHaveBeenCalled()
    expect(hook.result.current.user).toEqual(authState.storedUser)
    expect(hook.result.current.isAuthenticated).toBe(true)
    hook.unmount()
  })

  it('clears the active session on an unauthorized profile refresh', async () => {
    authState.me.mockRejectedValue(
      Object.assign(new Error('unauthorized'), {
        response: { status: 401 },
      })
    )

    const hook = renderHook(() => useAuth(), { wrapper: createWrapper() })

    await hook.result.current.refresh()

    await waitForAssertion(() => {
      expect(authState.clearAuthSession).toHaveBeenCalledTimes(1)
      expect(hook.result.current.user).toBeNull()
    })

    expect(hook.result.current.error).toBeNull()
    hook.unmount()
  })
})
