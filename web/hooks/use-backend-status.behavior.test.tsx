// @vitest-environment happy-dom

import React, { type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderHook, waitForAssertion } from '@/test/hook-harness'

const api = vi.hoisted(() => ({ health: vi.fn(), ready: vi.fn(), meta: vi.fn(), metaDetails: vi.fn() }))
vi.mock('@/lib/api/health', () => ({ healthApi: { details: api.health, ready: api.ready } }))
vi.mock('@/lib/api/meta', () => ({ metaApi: { get: api.meta, details: api.metaDetails } }))

import { useBackendHealth } from './use-backend-health'
import { useBackendReady } from './use-backend-ready'
import { useBackendMeta, useBackendMetaDetails } from './use-backend-meta'

const cleanups = new Set<() => void>()

function createQueryWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  function QueryWrapper({ children }: Readonly<{ children: ReactNode }>) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return QueryWrapper
}

beforeEach(() => {
  vi.resetAllMocks()
  api.health.mockResolvedValue({ ok: true, status: 'healthy' })
  api.ready.mockResolvedValue({ ok: true, status: 'ready' })
  api.meta.mockResolvedValue({ version: 'test' })
  api.metaDetails.mockResolvedValue({ features: { kg_enabled: true } })
})

afterEach(() => {
  for (const cleanup of cleanups) cleanup()
  cleanups.clear()
})

describe('shared backend status ownership', () => {
  it('reads public readiness without requesting administrative health details', async () => {
    const hook = renderHook(useBackendReady, { wrapper: createQueryWrapper() })
    cleanups.add(hook.unmount)
    await waitForAssertion(() => expect(hook.result.current.isSuccess).toBe(true))
    expect(api.ready).toHaveBeenCalledOnce()
    expect(api.health).not.toHaveBeenCalled()
  })

  it('does not fetch administrative health details when disabled', () => {
    const hook = renderHook(() => useBackendHealth({ enabled: false }), { wrapper: createQueryWrapper() })
    cleanups.add(hook.unmount)
    expect(api.health).not.toHaveBeenCalled()
  })

  it('shares one health result between navigation and diagnostics consumers', async () => {
    const hook = renderHook(() => ({ navigation: useBackendHealth(), diagnostics: useBackendHealth() }), {
      wrapper: createQueryWrapper(),
    })
    cleanups.add(hook.unmount)

    await waitForAssertion(() => expect(hook.result.current.navigation.isSuccess).toBe(true))
    expect(api.health).toHaveBeenCalledOnce()
    expect(hook.result.current.navigation.data).toMatchObject({ ok: true, status: 'healthy' })
    expect(hook.result.current.navigation.data).toBe(hook.result.current.diagnostics.data)
  })

  it.each([['health'], ['meta'], ['metaDetails']] as const)(
    'cancels the %s request when its observer unmounts',
    async (kind) => {
      let signal: AbortSignal | undefined
      api[kind].mockImplementation((options: { signal: AbortSignal }) => {
        signal = options.signal
        return new Promise(() => {})
      })
      const useStatus = kind === 'health' ? useBackendHealth : kind === 'meta' ? useBackendMeta : useBackendMetaDetails
      const hook = renderHook(() => useStatus(), { wrapper: createQueryWrapper() })
      cleanups.add(hook.unmount)

      await waitForAssertion(() => expect(signal).toBeDefined())
      expect(signal?.aborted).toBe(false)
      hook.unmount()
      cleanups.delete(hook.unmount)
      expect(signal?.aborted).toBe(true)
    },
  )
})
