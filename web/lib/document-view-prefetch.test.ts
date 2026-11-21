// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  scope: 'tenant:user-a',
  generation: 0,
  getDocument: vi.fn(),
  getChunk: vi.fn(),
  getParsedContent: vi.fn(),
  cacheContent: vi.fn(),
  warning: vi.fn(),
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
  isDocCacheScopeGuardCurrent: (scopeGuard: { scope: string; authGeneration: number; scopeWriteGeneration: number }) =>
    scopeGuard.scope === mocks.scope &&
    scopeGuard.authGeneration === mocks.generation &&
    scopeGuard.scopeWriteGeneration === mocks.generation,
  cacheDocContentIfMissing: mocks.cacheContent,
}))
vi.mock('./client-logging', () => ({ reportClientWarning: mocks.warning }))

import { getPrefetchedChunk, getPrefetchedDocument, prefetchDocumentView } from './document-view-prefetch'

describe('document view prefetch auth scope', () => {
  beforeEach(() => {
    mocks.scope = 'tenant:user-a'
    mocks.generation += 1
    window.dispatchEvent(new Event('mimirq:auth-scope-changed'))
    mocks.getDocument.mockReset().mockResolvedValue({ id: 'doc-1' })
    mocks.getChunk.mockReset().mockResolvedValue({ id: 'chunk-1', document_id: 'doc-1' })
    mocks.getParsedContent.mockReset().mockResolvedValue({ available: false })
    mocks.cacheContent.mockReset()
    mocks.warning.mockReset()
    window.addEventListener('mimirq:auth-scope-changed', handleAuthScopeChanged)
  })

  afterEach(() => {
    window.removeEventListener('mimirq:auth-scope-changed', handleAuthScopeChanged)
  })

  it.each(['markdown_truncated', 'original_markdown_truncated'] as const)(
    'does not put a preview with %s into the complete content cache',
    async (field) => {
      mocks.getParsedContent.mockResolvedValue({
        available: true,
        markdown_content: 'Preview only',
        original_markdown_content: 'Original preview',
        markdown_truncated: false,
        original_markdown_truncated: false,
        [field]: true,
      })
      prefetchDocumentView({ documentId: `truncated-${field}` })
      await Promise.resolve()
      await Promise.resolve()
      expect(mocks.cacheContent).not.toHaveBeenCalled()
    },
  )

  it('caches an available complete empty response without substituting content', async () => {
    mocks.getParsedContent.mockResolvedValue({
      available: true,
      markdown_content: '',
      original_markdown_content: '',
      markdown_truncated: false,
      original_markdown_truncated: false,
    })
    prefetchDocumentView({ documentId: 'complete-empty' })
    await vi.waitFor(() =>
      expect(mocks.cacheContent).toHaveBeenCalledWith(
        {
          id: 'complete-empty',
          markdownContent: '',
          originalMarkdownContent: '',
        },
        expect.objectContaining({ scope: 'tenant:user-a' }),
      ),
    )
  })

  it('records an optional prefetch failure without publishing a result', async () => {
    const error = new Error('Prefetch is unavailable')
    mocks.getParsedContent.mockRejectedValue(error)
    prefetchDocumentView({ documentId: 'prefetch-error' })
    await vi.waitFor(() =>
      expect(mocks.warning).toHaveBeenCalledWith('Failed to prefetch parsed document content', error),
    )
    expect(mocks.cacheContent).not.toHaveBeenCalled()
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
      }),
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
      }),
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
      }),
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
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveOld = resolve
        }),
      )
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveReplacement = resolve
        }),
      )

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
      }),
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

    expect(mocks.cacheContent).not.toHaveBeenCalled()
  })
})
