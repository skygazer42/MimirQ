// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderHook, waitForAssertion } from '@/test/hook-harness'
import { queryKeys } from '@/lib/query-keys'

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
  getStoredUser: () => (authState.token ? authState.storedUser : null),
  setStoredUser: authState.setStoredUser,
}))

import { useAuth } from './use-auth'

function createWrapper(
  queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  }),
) {
  function Wrapper({ children }: Readonly<{ children: React.ReactNode }>) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }

  return Wrapper
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
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
      }),
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

  it('keeps a replacement identity when a cancelled profile refresh returns late', async () => {
    const request = deferred<typeof authState.storedUser>()
    authState.me.mockReturnValue(request.promise)
    authState.setStoredUser.mockImplementation((profile: typeof authState.storedUser) => {
      authState.storedUser = profile
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const hook = renderHook(() => useAuth(), { wrapper: createWrapper(queryClient) })
    let refresh!: Promise<void>
    act(() => {
      refresh = hook.result.current.refresh()
    })
    await waitForAssertion(() => expect(authState.me).toHaveBeenCalledOnce())

    const replacement = { id: 'user-b', email: 'replacement@example.com' }
    act(() => {
      authState.token = 'replacement-token'
      authState.storedUser = replacement
      queryClient.clear()
    })
    hook.rerender()
    await waitForAssertion(() => expect(hook.result.current.user).toEqual(replacement))
    await act(async () => {
      request.resolve({ id: 'user-a', email: 'old@example.com' })
      await request.promise
      await refresh
    })

    expect(authState.storedUser).toEqual(replacement)
    expect(authState.setStoredUser).not.toHaveBeenCalled()
    expect(queryClient.getQueryData(queryKeys.auth.profile)).toEqual(replacement)
    expect(hook.result.current.user).toEqual(replacement)
    hook.unmount()
  })

  it('keeps a refreshed token when the previous token receives an unauthorized response', async () => {
    const request = deferred<never>()
    authState.me.mockReturnValue(request.promise)
    authState.clearAuthSession.mockImplementation(() => {
      authState.token = ''
    })
    const hook = renderHook(() => useAuth(), { wrapper: createWrapper() })
    let refresh!: Promise<void>
    act(() => {
      refresh = hook.result.current.refresh()
    })
    await waitForAssertion(() => expect(authState.me).toHaveBeenCalledOnce())
    authState.token = 'refreshed-token'

    await act(async () => {
      request.reject(Object.assign(new Error('previous token expired'), { response: { status: 401 } }))
      await refresh
    })

    expect(authState.token).toBe('refreshed-token')
    expect(authState.clearAuthSession).not.toHaveBeenCalled()
    expect(hook.result.current.user).toEqual(authState.storedUser)
    expect(hook.result.current.error).toBeNull()
    hook.unmount()
  })

  it('stores the returned profile when the API refreshes the token within the same query', async () => {
    const profile = { id: 'user-a', email: 'updated@example.com' }
    authState.me.mockImplementation(async () => {
      authState.token = 'refreshed-token'
      return profile
    })
    const hook = renderHook(() => useAuth(), { wrapper: createWrapper() })

    await act(async () => hook.result.current.refresh())

    await waitForAssertion(() => expect(hook.result.current.user).toEqual(profile))
    expect(authState.setStoredUser).toHaveBeenCalledWith(profile)
    expect(authState.clearAuthSession).not.toHaveBeenCalled()
    hook.unmount()
  })
})
