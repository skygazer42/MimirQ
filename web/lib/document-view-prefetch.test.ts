// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  scope: 'tenant:user-a',
  generation: 0,
  getDocument: vi.fn(),
  getChunk: vi.fn(),
  getParsedContent: vi.fn(),
  fetchAsset: vi.fn(),
  saveContent: vi.fn(),
}))

const handleAuthScopeChanged = () => {
  mocks.generation += 1
}

vi.mock('./auth-storage', () => ({
  AUTH_SCOPE_CHANGED_EVENT: 'mimirq:auth-scope-changed',
  getAuthCacheScope: () => mocks.scope,
}))
vi.mock('./api', () => ({
  documentApi: {
    get: mocks.getDocument,
    getChunk: mocks.getChunk,
    getParsedContent: mocks.getParsedContent,
  },
}))
vi.mock('./doc-content-cache', () => ({
  getDocCacheScopeGuard: () => ({
    scope: mocks.scope,
    authGeneration: mocks.generation,
    scopeWriteGeneration: mocks.generation,
  }),
  isDocCacheScopeGuardCurrent: (scopeGuard: {
    scope: string
    authGeneration: number
    scopeWriteGeneration: number
  }) =>
    scopeGuard.scope === mocks.scope &&
    scopeGuard.authGeneration === mocks.generation &&
    scopeGuard.scopeWriteGeneration === mocks.generation,
  saveDocContentToCache: mocks.saveContent,
}))
vi.mock('./image-auth-proxy', () => ({ fetchAuthAssetUrl: mocks.fetchAsset }))

import { getPrefetchedChunk, getPrefetchedDocument, prefetchDocumentView } from './document-view-prefetch'

describe('document view prefetch auth scope', () => {
  beforeEach(() => {
    mocks.scope = 'tenant:user-a'
    mocks.generation = 0
    mocks.getDocument.mockReset().mockResolvedValue({ id: 'doc-1' })
    mocks.getChunk.mockReset().mockResolvedValue({ id: 'chunk-1', document_id: 'doc-1' })
    mocks.getParsedContent.mockReset().mockResolvedValue({ available: false })
    mocks.fetchAsset.mockReset().mockResolvedValue('https://example.test/file')
    mocks.saveContent.mockReset()
    window.addEventListener('mimirq:auth-scope-changed', handleAuthScopeChanged)
  })

  afterEach(() => {
    window.removeEventListener('mimirq:auth-scope-changed', handleAuthScopeChanged)
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

  it('discards a document response that finishes after same-scope invalidation', async () => {
    let resolveDocument!: (document: { id: string }) => void
    mocks.getDocument.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveDocument = resolve
      })
    )

    prefetchDocumentView({ documentId: 'doc-stale' })
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    resolveDocument({ id: 'doc-stale' })
    await Promise.resolve()
    await Promise.resolve()

    expect(getPrefetchedDocument('doc-stale')).toBeUndefined()
  })

  it('discards a chunk response that finishes after same-scope invalidation', async () => {
    let resolveChunk!: (chunk: { id: string; document_id: string }) => void
    mocks.getChunk.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveChunk = resolve
      })
    )

    prefetchDocumentView({ documentId: 'doc-1', chunkId: 'chunk-late' })
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    resolveChunk({ id: 'chunk-late', document_id: 'doc-1' })
    await Promise.resolve()
    await Promise.resolve()

    expect(getPrefetchedChunk('doc-1', 'chunk-late')).toBeUndefined()
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

  it('does not save parsed content fetched before same-scope invalidation', async () => {
    let resolveParsed!: (value: {
      available: boolean
      markdown_content?: string
      original_markdown_content?: string
    }) => void
    mocks.getParsedContent.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveParsed = resolve
      })
    )

    prefetchDocumentView({ documentId: 'doc-parsed-stale' })
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    resolveParsed({
      available: true,
      markdown_content: 'stale-content',
      original_markdown_content: 'stale-content',
    })
    await Promise.resolve()
    await Promise.resolve()

    expect(mocks.saveContent).not.toHaveBeenCalled()
  })

  it('allows a replacement raw-file prefetch after same-scope invalidation', async () => {
    let resolveFirstFetch!: (value: string) => void
    let resolveReplacementFetch!: (value: string) => void
    mocks.fetchAsset
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveFirstFetch = resolve
      }))
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveReplacementFetch = resolve
      }))

    prefetchDocumentView({ documentId: 'doc-file', rawFileUrl: '/files/doc-file' })
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    prefetchDocumentView({ documentId: 'doc-file', rawFileUrl: '/files/doc-file' })

    resolveFirstFetch('https://example.test/stale')
    await Promise.resolve()
    await Promise.resolve()

    expect(mocks.fetchAsset).toHaveBeenCalledTimes(2)
    resolveReplacementFetch('https://example.test/fresh')
  })
})
