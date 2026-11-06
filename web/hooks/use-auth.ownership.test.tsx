// @vitest-environment happy-dom

import { act, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { QueryProvider } from '@/components/providers/query-provider'
import { apiClient } from '@/lib/api/core'
import { AUTH_SCOPE_CHANGED_EVENT, getAccessToken, getStoredUser, setAuthSession } from '@/lib/auth-storage'
import { __resetOidcRefreshForTests } from '@/lib/oidc-session'
import { queryKeys } from '@/lib/query-keys'
import { renderHook, waitForAssertion } from '@/test/hook-harness'
import type { AuthToken, UserProfile } from '@/types/backend'
import { useAuth } from './use-auth'

const token: AuthToken = { access_token: 'same-session-token', token_type: 'bearer', expires_in: 3600 }
const profile: UserProfile = {
  id: 'user-a',
  email: 'initial@example.com',
  username: 'a',
  is_active: true,
  created_at: '2026-11-04T00:00:00Z',
}
const originalAdapter = apiClient.defaults.adapter
const cleanups: Array<() => void> = []

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => {
    resolve = done
    reject = fail
  })
  return { promise, resolve, reject }
}

function Provider({ children }: Readonly<{ children: ReactNode }>) {
  return <QueryProvider>{children}</QueryProvider>
}

function mountAuth() {
  const hook = renderHook(() => ({ auth: useAuth(), queryClient: useQueryClient() }), { wrapper: Provider })
  cleanups.push(hook.unmount)
  return hook
}

describe('useAuth session ownership across the real client chain', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    __resetOidcRefreshForTests()
    setAuthSession({ token, user: profile })
    window.history.replaceState({}, '', '/auth')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('No refresh was expected')))
  })

  afterEach(() => {
    cleanups.splice(0).forEach((cleanup) => cleanup())
    apiClient.defaults.adapter = originalAdapter
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it.each(['success', '401', '500'] as const)(
    'keeps a same-user same-token replacement session when its previous profile request returns %s',
    async (settlement) => {
      const response = deferred<AxiosResponse<UserProfile>>()
      let request!: InternalAxiosRequestConfig
      const adapter = vi.fn((config: InternalAxiosRequestConfig) => {
        request = config
        return response.promise
      })
      apiClient.defaults.adapter = adapter
      const hook = mountAuth()
      let completion!: Promise<void>
      act(() => {
        completion = hook.result.current.auth.refresh()
      })
      await waitForAssertion(() => expect(adapter).toHaveBeenCalledOnce())

      const replacement = { ...profile, email: 'replacement@example.com' }
      const scopeEvent = vi.fn()
      window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, scopeEvent)
      cleanups.push(() => window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, scopeEvent))
      act(() => setAuthSession({ token, user: replacement }))
      expect(scopeEvent).not.toHaveBeenCalled()

      await act(async () => {
        if (settlement === 'success') {
          response.resolve({
            config: request,
            data: { ...profile, email: 'old-response@example.com' },
            status: 200,
            statusText: 'OK',
            headers: {},
          })
        } else {
          response.reject(
            Object.assign(new Error('previous profile failed'), {
              config: request,
              response: { status: Number(settlement), data: {}, headers: {} },
            }),
          )
        }
        await completion
      })

      expect(getAccessToken()).toBe('same-session-token')
      expect(getStoredUser()).toEqual(replacement)
      await waitForAssertion(() => expect(hook.result.current.auth.user).toEqual(replacement))
      expect(hook.result.current.queryClient.getQueryData(queryKeys.auth.profile)).toEqual(replacement)
      expect(hook.result.current.auth.error).toBeNull()
      expect(scopeEvent).not.toHaveBeenCalled()
      expect(fetch).not.toHaveBeenCalled()
    },
  )

  it('stores a valid profile after OIDC token rotation within the original session', async () => {
    const updated = { ...profile, email: 'current-profile@example.com' }
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ ...token, access_token: 'rotated-token' }), { status: 200 }),
    )
    const seen: string[] = []
    apiClient.defaults.adapter = vi.fn(async (config) => {
      const authorization = String(config.headers.Authorization)
      seen.push(authorization)
      if (authorization === 'Bearer same-session-token') {
        throw Object.assign(new Error('expired token'), { config, response: { status: 401, data: {}, headers: {} } })
      }
      return { config, data: updated, status: 200, statusText: 'OK', headers: {} }
    })
    const hook = mountAuth()
    await act(async () => hook.result.current.auth.refresh())
    await waitForAssertion(() => expect(hook.result.current.auth.user).toEqual(updated))
    expect(getStoredUser()).toEqual(updated)
    expect(getAccessToken()).toBe('rotated-token')
    expect(hook.result.current.queryClient.getQueryData(queryKeys.auth.profile)).toEqual(updated)
    expect(hook.result.current.auth.error).toBeNull()
    expect(fetch).toHaveBeenCalledOnce()
    expect(seen).toEqual(['Bearer same-session-token', 'Bearer rotated-token'])
  })
})
