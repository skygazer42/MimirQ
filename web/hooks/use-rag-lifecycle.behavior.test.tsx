// @vitest-environment happy-dom

import React, { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const authStorage = vi.hoisted(() => ({
  clearAuthSession: vi.fn(),
  getAccessToken: vi.fn(() => null as string | null),
  getStoredUser: vi.fn(() => null),
  setStoredUser: vi.fn(),
}))

const documentApiMock = vi.hoisted(() => ({
  get: vi.fn(),
  getStatus: vi.fn(),
}))

const miniSearchMock = vi.hoisted(() => ({
  addAll: vi.fn(),
  instances: 0,
  removeAll: vi.fn(),
  search: vi.fn((_term: string) => []),
}))

vi.mock('@/lib/auth-storage', () => authStorage)
vi.mock('@/lib/api/auth', () => ({ authApi: { me: vi.fn() } }))
vi.mock('@/lib/api/documents', () => ({ documentApi: documentApiMock }))
vi.mock('@/lib/client-logging', () => ({ reportClientError: vi.fn() }))
vi.mock('minisearch', () => ({
  default: class MiniSearchMock {
    constructor() {
      miniSearchMock.instances += 1
    }

    addAll(data: unknown[]) {
      miniSearchMock.addAll(data)
    }

    removeAll() {
      miniSearchMock.removeAll()
    }

    search(term: string) {
      return miniSearchMock.search(term)
    }
  },
}))

import { useAuth } from './use-auth'
import { useDocumentPolling } from './use-document-polling'
import { useLocalSearch } from './use-local-search'

type HookHarness<T> = {
  current: () => T
  render: (hook: () => T) => void
  unmount: () => void
}

function renderHook<T>(hook: () => T, wrapper?: (children: React.ReactNode) => React.ReactElement): HookHarness<T> {
  let value: T
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root: Root = createRoot(container)

  function Probe({ callback }: { callback: () => T }) {
    value = callback()
    return null
  }

  const render = (callback: () => T) => {
    const probe = React.createElement(Probe, { callback })
    act(() => root.render(wrapper ? wrapper(probe) : probe))
  }

  render(hook)
  return {
    current: () => value,
    render,
    unmount: () => {
      act(() => root.unmount())
      container.remove()
    },
  }
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  miniSearchMock.instances = 0
  authStorage.getAccessToken.mockReturnValue(null)
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 204 }))))
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('RAG hook lifecycle behavior', () => {
  it('clears every cached query when logging out', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['private', 'documents'], { secret: true })
    const harness = renderHook(useAuth, (children) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ))

    act(() => harness.current().logout())

    expect(authStorage.clearAuthSession).toHaveBeenCalledOnce()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    harness.unmount()
  })

  it('does not register another polling timer after unmount', async () => {
    let resolveStatus: (value: { status: string }) => void = () => undefined
    documentApiMock.getStatus.mockReturnValue(
      new Promise((resolve) => {
        resolveStatus = resolve
      })
    )
    const setTimeoutSpy = vi.spyOn(window, 'setTimeout')
    const harness = renderHook(() =>
      useDocumentPolling({ updateCachedDocuments: vi.fn() })
    )

    act(() => harness.current().pollDocumentStatus('doc-1'))
    setTimeoutSpy.mockClear()
    harness.unmount()
    await act(async () => {
      resolveStatus({ status: 'processing' })
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(setTimeoutSpy).not.toHaveBeenCalled()
  })

  it('does not rebuild MiniSearch for equal field arrays', () => {
    const data = [{ id: '1', title: 'Alpha' }]
    const harness = renderHook(() =>
      useLocalSearch(data, { fields: ['title'], storeFields: ['title'] })
    )

    harness.render(() =>
      useLocalSearch(data, { fields: ['title'], storeFields: ['title'] })
    )

    expect(miniSearchMock.instances).toBe(1)
    expect(miniSearchMock.addAll).toHaveBeenCalledOnce()
    harness.unmount()
  })
})
