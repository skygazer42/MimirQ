// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ headers: { 'X-Workspace': 'actual-workspace' } }))
vi.mock('./env', () => ({ API_BASE_URL: '' }))
vi.mock('./auth-headers', () => ({ getAuthHeaders: () => mocks.headers }))

import { readPdfSourceData } from './pdf-source'

const fetchPdf = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('fetch', fetchPdf)
  fetchPdf.mockResolvedValue({ ok: true, arrayBuffer: async () => new Uint8Array([1, 2]).buffer })
})

it('passes the owning cancellation signal through to the actual download request', async () => {
  fetchPdf.mockImplementation(
    (_url: string, { signal }: { signal: AbortSignal }) =>
      new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true })),
  )
  const controller = new AbortController()
  const download = readPdfSourceData('/api/v1/documents/source-a/file', controller.signal)
  controller.abort()

  await expect(download).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetchPdf.mock.calls[0][1].signal).toBe(controller.signal)
})

afterEach(() => vi.unstubAllGlobals())

describe('actual PDF source transport', () => {
  it('includes existing API headers for same-origin document URLs when the API base is empty', async () => {
    await readPdfSourceData('/api/v1/documents/source-a/file', new AbortController().signal)

    expect(fetchPdf.mock.calls[0][1].headers).toEqual(mocks.headers)
  })

  it('does not attach application headers to an unrelated origin', async () => {
    await readPdfSourceData('https://files.example.com/api/file.pdf', new AbortController().signal)

    expect(fetchPdf.mock.calls[0][1].headers).toBeUndefined()
  })

  it('preserves the actual download error', async () => {
    fetchPdf.mockResolvedValue({ ok: false, status: 503 })

    await expect(readPdfSourceData('/api/v1/documents/source-a/file', new AbortController().signal)).rejects.toThrow(
      '503',
    )
  })
})
