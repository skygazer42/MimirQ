// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest'

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'dataset-1' }),
}))

vi.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/lib/api', () => ({
  datasetApi: {},
  sseApi: {},
}))

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

import { isCurrentPrecheckSseStream, shouldFallbackToPrecheckPolling } from './page-client'

describe('precheck SSE guards', () => {
  it('does not fallback to polling for a superseded aborted stream', () => {
    const staleController = new AbortController()
    const activeController = new AbortController()
    const abortError = new DOMException('The operation was aborted.', 'AbortError')

    expect(isCurrentPrecheckSseStream(staleController, activeController, 'run-old', 'run-new')).toBe(false)
    expect(
      shouldFallbackToPrecheckPolling(
        abortError,
        staleController,
        activeController,
        'run-old',
        'run-new'
      )
    ).toBe(false)
  })

  it('does not fallback or stay current after unmount abort clears the stream identity', () => {
    const controller = new AbortController()
    const abortError = new DOMException('The operation was aborted.', 'AbortError')

    expect(isCurrentPrecheckSseStream(controller, null, 'run-1', null)).toBe(false)
    expect(shouldFallbackToPrecheckPolling(abortError, controller, null, 'run-1', null)).toBe(false)
  })

  it('falls back to polling for an active stream with a real network failure', () => {
    const controller = new AbortController()
    const networkError = new Error('network down')

    expect(isCurrentPrecheckSseStream(controller, controller, 'run-1', 'run-1')).toBe(true)
    expect(
      shouldFallbackToPrecheckPolling(
        networkError,
        controller,
        controller,
        'run-1',
        'run-1'
      )
    ).toBe(true)
  })
})
