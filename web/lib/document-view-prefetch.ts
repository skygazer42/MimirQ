import type { Document, DocumentChunk } from '@/types'

import { documentApi } from './api'
import { AUTH_SCOPE_CHANGED_EVENT, getAuthCacheScope } from './auth-storage'
import { saveDocContentToCache } from './doc-content-cache'
import { fetchAuthAssetUrl } from './image-auth-proxy'

type PrefetchDocumentViewOptions = Readonly<{
  documentId?: string | null
  chunkId?: string | null
  rawFileUrl?: string | null
}>

const prefetchedDocuments = new Map<string, Document>()
const prefetchedChunks = new Map<string, DocumentChunk>()
const documentInflight = new Map<string, Promise<void>>()
const chunkInflight = new Map<string, Promise<void>>()
const parsedInflight = new Map<string, Promise<unknown>>()
const fileInflight = new Map<string, Promise<unknown>>()

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
  fileInflight.clear()
}

globalThis.window?.addEventListener(AUTH_SCOPE_CHANGED_EVENT, clearPrefetchCaches)

export function getPrefetchedDocument(documentId?: string | null): Document | undefined {
  const id = String(documentId || '').trim()
  return id ? prefetchedDocuments.get(documentCacheKey(id)) : undefined
}

export function getPrefetchedChunk(documentId?: string | null, chunkId?: string | null): DocumentChunk | undefined {
  const docId = String(documentId || '').trim()
  const cid = String(chunkId || '').trim()
  return docId && cid ? prefetchedChunks.get(chunkCacheKey(docId, cid)) : undefined
}

export function prefetchDocumentView({ documentId, chunkId, rawFileUrl }: PrefetchDocumentViewOptions): void {
  const docId = String(documentId || '').trim()
  const cid = String(chunkId || '').trim()
  const fileUrl = String(rawFileUrl || '').trim()

  if (!docId) return

  const documentKey = documentCacheKey(docId)

  if (!prefetchedDocuments.has(documentKey) && !documentInflight.has(documentKey)) {
    const request = documentApi
      .get(docId, { includeChunks: false })
      .then((doc) => {
        if (documentKey !== documentCacheKey(docId)) return
        prefetchedDocuments.set(documentKey, doc)
      })
      .catch(() => undefined)
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
          if (key !== chunkCacheKey(docId, cid)) return
          prefetchedChunks.set(key, chunk)
        })
        .catch(() => undefined)
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
        if (!data?.available || documentKey !== documentCacheKey(docId)) return
        await saveDocContentToCache({
          id: docId,
          markdownContent: data.markdown_content || '',
          originalMarkdownContent: data.original_markdown_content || '',
        })
      })
      .catch(() => undefined)
    parsedInflight.set(documentKey, request)
    void request.finally(() => {
      if (parsedInflight.get(documentKey) === request) {
        parsedInflight.delete(documentKey)
      }
    })
  }

  if (fileUrl && !fileInflight.has(documentKey)) {
    const request = fetchAuthAssetUrl(fileUrl)
      .catch(() => null)
    fileInflight.set(documentKey, request)
    void request.finally(() => {
      if (fileInflight.get(documentKey) === request) {
        fileInflight.delete(documentKey)
      }
    })
  }
}
