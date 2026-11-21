import type { Document, DocumentChunk } from '@/types'

import { documentApi } from './api'
import { AUTH_SCOPE_CHANGED_EVENT, getAuthCacheScope } from './auth-storage'
import { getDocCacheScopeGuard, isDocCacheScopeGuardCurrent, cacheDocContentIfMissing } from './doc-content-cache'
import { reportClientWarning } from './client-logging'

type PrefetchDocumentViewOptions = Readonly<{
  documentId?: string | null
  chunkId?: string | null
}>

const prefetchedDocuments = new Map<string, Document>()
const prefetchedChunks = new Map<string, DocumentChunk>()
const documentInflight = new Map<string, Promise<void>>()
const chunkInflight = new Map<string, Promise<void>>()
const parsedInflight = new Map<string, Promise<void>>()

function chunkCacheKey(documentId: string, chunkId: string): string {
  return `${getAuthCacheScope()}:${documentId}:${chunkId}`
}

function documentCacheKey(documentId: string): string {
  return `${getAuthCacheScope()}:${documentId}`
}

function clearPrefetchCaches() {
  prefetchedDocuments.clear()
  prefetchedChunks.clear()
  documentInflight.clear()
  chunkInflight.clear()
  parsedInflight.clear()
}

globalThis.window?.addEventListener(AUTH_SCOPE_CHANGED_EVENT, clearPrefetchCaches)

export function getPrefetchedDocument(documentId?: string | null): Document | undefined {
  const id = documentId?.trim()
  return id ? prefetchedDocuments.get(documentCacheKey(id)) : undefined
}

export function getPrefetchedChunk(documentId?: string | null, chunkId?: string | null): DocumentChunk | undefined {
  const docId = documentId?.trim()
  const cid = chunkId?.trim()
  return docId && cid ? prefetchedChunks.get(chunkCacheKey(docId, cid)) : undefined
}

export function prefetchDocumentView({ documentId, chunkId }: PrefetchDocumentViewOptions): void {
  const docId = documentId?.trim()
  const cid = chunkId?.trim()

  if (!docId) return

  const documentKey = documentCacheKey(docId)
  const scopeGuard = getDocCacheScopeGuard()

  if (!prefetchedDocuments.has(documentKey) && !documentInflight.has(documentKey)) {
    const request = documentApi
      .get(docId, { includeChunks: false })
      .then((doc) => {
        if (!isDocCacheScopeGuardCurrent(scopeGuard) || documentKey !== documentCacheKey(docId)) return
        prefetchedDocuments.set(documentKey, doc)
      })
      .catch((error) => {
        if (isDocCacheScopeGuardCurrent(scopeGuard)) reportClientWarning('Failed to prefetch document details', error)
      })
    documentInflight.set(documentKey, request)
    void request.finally(() => {
      if (documentInflight.get(documentKey) === request) {
        documentInflight.delete(documentKey)
      }
    })
  }

  if (cid) {
    const key = chunkCacheKey(docId, cid)
    if (!prefetchedChunks.has(key) && !chunkInflight.has(key)) {
      const request = documentApi
        .getChunk(docId, cid)
        .then((chunk) => {
          if (!isDocCacheScopeGuardCurrent(scopeGuard) || key !== chunkCacheKey(docId, cid)) return
          prefetchedChunks.set(key, chunk)
        })
        .catch((error) => {
          if (isDocCacheScopeGuardCurrent(scopeGuard)) reportClientWarning('Failed to prefetch document chunk', error)
        })
      chunkInflight.set(key, request)
      void request.finally(() => {
        if (chunkInflight.get(key) === request) {
          chunkInflight.delete(key)
        }
      })
    }
  }

  if (!parsedInflight.has(documentKey)) {
    const request = documentApi
      .getParsedContent(docId, { max_chars: 200_000 })
      .then(async (data) => {
        if (!data.available || !isDocCacheScopeGuardCurrent(scopeGuard) || documentKey !== documentCacheKey(docId))
          return
        if (data.markdown_truncated || data.original_markdown_truncated) return
        await cacheDocContentIfMissing(
          {
            id: docId,
            markdownContent: data.markdown_content,
            originalMarkdownContent: data.original_markdown_content,
          },
          scopeGuard,
        )
      })
      .catch((error) => {
        if (isDocCacheScopeGuardCurrent(scopeGuard))
          reportClientWarning('Failed to prefetch parsed document content', error)
      })
    parsedInflight.set(documentKey, request)
    void request.finally(() => {
      if (parsedInflight.get(documentKey) === request) {
        parsedInflight.delete(documentKey)
      }
    })
  }
}
