// @vitest-environment happy-dom

import React, { act } from 'react'
import { focusManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
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

  it('refreshes a recently cached role when the user returns after administrator approval', async () => {
    accessState.getCurrentTenantAccess.mockResolvedValueOnce({ role: 'viewer', permissions: [] })
      .mockResolvedValue({ role: 'editor', permissions: ['feedback_triage.write'] })
    const hook = renderHook(() => useTenantAccess(), { wrapper: createWrapper() })
    try {
      await waitForAssertion(() => { expect(hook.result.current.data?.role).toBe('viewer') })
      act(() => { focusManager.setFocused(false) })
      act(() => { focusManager.setFocused(true) })
      await waitForAssertion(() => {
        expect(hook.result.current.data?.role).toBe('editor')
        expect(hook.result.current.data?.permissions).toContain('feedback_triage.write')
      })
    } finally {
      hook.unmount()
      focusManager.setFocused(undefined)
    }
  })
})
