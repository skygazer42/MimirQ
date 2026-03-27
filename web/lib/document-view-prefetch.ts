import type { Document, DocumentChunk } from '@/types'

import { documentApi } from './api'
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
const parsedInflight = new Set<string>()
const fileInflight = new Set<string>()

function chunkCacheKey(documentId: string, chunkId: string): string {
  return `${documentId}:${chunkId}`
}

export function getPrefetchedDocument(documentId?: string | null): Document | undefined {
  const id = String(documentId || '').trim()
  return id ? prefetchedDocuments.get(id) : undefined
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

  if (!prefetchedDocuments.has(docId) && !documentInflight.has(docId)) {
    const request = documentApi
      .get(docId, { includeChunks: false })
      .then((doc) => {
        prefetchedDocuments.set(docId, doc)
      })
      .catch(() => undefined)
      .finally(() => {
        documentInflight.delete(docId)
      })
    documentInflight.set(docId, request)
  }

  if (cid) {
    const key = chunkCacheKey(docId, cid)
    if (!prefetchedChunks.has(key) && !chunkInflight.has(key)) {
      const request = documentApi
        .getChunk(docId, cid)
        .then((chunk) => {
          prefetchedChunks.set(key, chunk)
        })
        .catch(() => undefined)
        .finally(() => {
          chunkInflight.delete(key)
        })
      chunkInflight.set(key, request)
    }
  }

  if (!parsedInflight.has(docId)) {
    parsedInflight.add(docId)
    void documentApi
      .getParsedContent(docId, { max_chars: 200_000 })
      .then(async (data) => {
        if (!data?.available) return
        await saveDocContentToCache({
          id: docId,
          markdownContent: data.markdown_content || '',
          originalMarkdownContent: data.original_markdown_content || '',
        })
      })
      .catch(() => undefined)
      .finally(() => {
        parsedInflight.delete(docId)
      })
  }

  if (fileUrl && !fileInflight.has(docId)) {
    fileInflight.add(docId)
    void fetchAuthAssetUrl(fileUrl)
      .catch(() => null)
      .finally(() => {
        fileInflight.delete(docId)
      })
  }
}
