// @vitest-environment happy-dom

import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderHook, waitForAssertion } from '@/test/hook-harness'

const accessState = vi.hoisted(() => ({
  getCurrentTenantAccess: vi.fn(),
}))

vi.mock('@/lib/api/access', () => ({
  rbacApi: {
    getCurrentTenantAccess: accessState.getCurrentTenantAccess,
  },
}))

import { useTenantAccess } from './use-tenant-access'

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return function Wrapper({ children }: Readonly<{ children: React.ReactNode }>) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

describe('useTenantAccess', () => {
  beforeEach(() => {
    accessState.getCurrentTenantAccess.mockReset()
    accessState.getCurrentTenantAccess.mockResolvedValue({ role: 'owner', permissions: [] })
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('does not call the protected access endpoint when disabled', async () => {
    const hook = renderHook(() => useTenantAccess({ enabled: false }), {
      wrapper: createWrapper(),
    })

    await new Promise((resolve) => globalThis.setTimeout(resolve, 20))
    expect(accessState.getCurrentTenantAccess).not.toHaveBeenCalled()
    hook.unmount()
  })

  it('loads tenant access by default', async () => {
    const hook = renderHook(() => useTenantAccess(), { wrapper: createWrapper() })

    await waitForAssertion(() => {
      expect(accessState.getCurrentTenantAccess).toHaveBeenCalledTimes(1)
    })
    hook.unmount()
  })
})
