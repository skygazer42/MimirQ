// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  scope: 'tenant:user-a',
  getDocument: vi.fn(),
  getParsedContent: vi.fn(),
  saveContent: vi.fn(),
}))

vi.mock('./auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  getAuthCacheScope: () => mocks.scope,
}))
vi.mock('./api', () => ({
  documentApi: {
    get: mocks.getDocument,
    getParsedContent: mocks.getParsedContent,
  },
}))
vi.mock('./doc-content-cache', () => ({ saveDocContentToCache: mocks.saveContent }))
vi.mock('./image-auth-proxy', () => ({ fetchAuthAssetUrl: vi.fn() }))

import { getPrefetchedDocument, prefetchDocumentView } from './document-view-prefetch'

describe('document view prefetch auth scope', () => {
  beforeEach(() => {
    mocks.scope = 'tenant:user-a'
    mocks.getDocument.mockReset().mockResolvedValue({ id: 'doc-1' })
    mocks.getParsedContent.mockReset().mockResolvedValue({ available: false })
    mocks.saveContent.mockReset()
  })

  it('does not expose one user cache to another user', async () => {
    prefetchDocumentView({ documentId: 'doc-1' })
    await vi.waitFor(() => expect(getPrefetchedDocument('doc-1')).toMatchObject({ id: 'doc-1' }))

    mocks.scope = 'tenant:user-b'
    expect(getPrefetchedDocument('doc-1')).toBeUndefined()
    prefetchDocumentView({ documentId: 'doc-1' })
    await vi.waitFor(() => expect(mocks.getDocument).toHaveBeenCalledTimes(2))
  })

  it('discards a document response that finishes after the auth scope changes', async () => {
    let resolveDocument!: (document: { id: string }) => void
    mocks.getDocument.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveDocument = resolve
      })
    )

    prefetchDocumentView({ documentId: 'doc-late' })
    mocks.scope = 'tenant:user-b'
    resolveDocument({ id: 'doc-late' })
    await Promise.resolve()
    await Promise.resolve()

    mocks.scope = 'tenant:user-a'
    expect(getPrefetchedDocument('doc-late')).toBeUndefined()
  })

  it('keeps a replacement parsed-content request marked in flight', async () => {
    let resolveOld!: (value: { available: boolean }) => void
    let resolveReplacement!: (value: { available: boolean }) => void
    mocks.getParsedContent
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveOld = resolve
      }))
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveReplacement = resolve
      }))

    prefetchDocumentView({ documentId: 'doc-race' })
    mocks.scope = 'tenant:user-b'
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    mocks.scope = 'tenant:user-a'
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    prefetchDocumentView({ documentId: 'doc-race' })

    resolveOld({ available: false })
    await new Promise((resolve) => setTimeout(resolve, 0))
    prefetchDocumentView({ documentId: 'doc-race' })

    expect(mocks.getParsedContent).toHaveBeenCalledTimes(2)
    resolveReplacement({ available: false })
  })
})
