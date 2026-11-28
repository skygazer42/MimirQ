'use client'

import * as React from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { toast } from 'sonner'

import { downloadBlob } from '@/lib/download'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { documentApi, ragApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import { getDocContentFromCache, cacheDocContentIfMissing } from '@/lib/doc-content-cache'
import { mapDocumentChunksToPreviewItems } from '@/lib/document-chunks'
import { createCodePointToUtf16Converter } from '@/lib/text-offsets'
import { recoverDocumentPreviewAnchorFromChunkPositions } from '@/lib/document-preview-anchor'
import { getPrefetchedChunk, getPrefetchedDocument } from '@/lib/document-view-prefetch'
import { API_V1_BASE_URL } from '@/lib/env'
import { globalEventBus } from '@/lib/event-bus'
import {
  useDocumentView,
  type DocumentTextMode,
  type DocumentViewLayout,
  type DocumentViewSourceContext,
  type DocumentViewTab,
  type HighlightRange,
} from '@/store/document-view'
import type {
  Document,
  DocumentChunk,
  DocumentChunkMatchList,
  DocumentParsedContentResponse,
  DocumentQAGenerateResponse,
} from '@/types/backend'
import type { Citation } from '@/types/processing'

import { resolveChunkKeyboardNavigation } from './keyboard-shortcuts'
import { parseRetrievalCitation } from './retrieval-citation'
import type { CitationSnapshot, DocumentChunkLocation, DocumentViewerHighlight } from './document-viewer-models'

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tagName = target.tagName
  return target.isContentEditable || tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT'
}

function isDocumentViewTab(value: string): value is DocumentViewTab {
  return value === 'preview' || value === 'text' || value === 'chunks'
}

function buildCitationSnapshot(params: {
  documentId: string
  chunkId: string
  sourceContext: DocumentViewSourceContext | null
  range: HighlightRange | null
}): CitationSnapshot | null {
  const context = params.sourceContext
  if (context === null || context.documentId !== params.documentId || context.chunkId !== params.chunkId) return null
  const content = context.chunkContent
  if (typeof content !== 'string') return null

  return {
    chunkId: params.chunkId,
    content,
    pageNumber: context.pageNumber,
    chunkIndex: context.chunkIndex,
    range: params.range,
  }
}

function parseIntegerInput(value: string, { label, min, max }: { label: string; min: number; max: number }): number {
  const next = Number(value)
  if (value.trim().length === 0 || !Number.isInteger(next) || next < min || next > max) {
    throw new Error(`${label}必须为 ${min} 到 ${max} 之间的整数`)
  }
  return next
}

function parseOptionalChunkNumber(value: string, { label, max }: { label: string; max: number }): number | undefined {
  const text = value.trim()
  if (text.length === 0) return undefined
  return parseIntegerInput(text, { label, min: 0, max })
}

function parseChunkPositions(values: { pageNumber: string; startChar: string; endChar: string }) {
  const pageNumber = parseOptionalChunkNumber(values.pageNumber, { label: '页码', max: 100_000 })
  const startChar = parseOptionalChunkNumber(values.startChar, { label: '开始字符位置', max: 10_000_000 })
  const endChar = parseOptionalChunkNumber(values.endChar, { label: '结束字符位置', max: 10_000_000 })
  return { page_number: pageNumber, start_char: startChar, end_char: endChar }
}

type DocumentDownloadRequest = Readonly<{
  visit: Readonly<{ documentId: string | null }>
  sessionKey: string
}>

type DocumentDownloadResult = Readonly<
  { request: DocumentDownloadRequest } & ({ status: 'processing' } | { status: 'error'; message: string })
>

export function useDocumentViewerPanelState() {
  const {
    authScope,
    isOpen,
    documentId,
    highlightChunkId,
    highlightRange,
    previewAnchor,
    sourceContext,
    closeDocument,
    activeTab,
    getDocumentLayout,
    setActiveTab,
    setDocumentLayout,
    setHighlightChunk,
  } = useDocumentView()

  const [documentResult, setDoc] = React.useState<Document | null>(null)
  const doc = documentResult?.id === documentId ? documentResult : null
  const [chunks, setChunks] = React.useState<DocumentChunk[]>([])
  const [isLoading, setIsLoading] = React.useState(false)
  const [documentError, setDocumentError] = React.useState<string | null>(null)
  const [documentReadAttempt, setDocumentReadAttempt] = React.useState(0)
  const [chunksLoaded, setChunksLoaded] = React.useState(false)
  const [chunksLoading, setChunksLoading] = React.useState(false)
  const [chunksError, setChunksError] = React.useState<string | null>(null)
  const [chunksReadAttempt, setChunksReadAttempt] = React.useState(0)
  const chunksReadControllerRef = React.useRef<AbortController | null>(null)
  const [loadAllChunks, setLoadAllChunks] = React.useState(false)
  const [highlightChunkState, setHighlightChunkState] = React.useState<{
    documentId: string
    chunk: DocumentChunk
  } | null>(null)
  const highlightChunk =
    highlightChunkState?.documentId === documentId && highlightChunkState.chunk.id === highlightChunkId
      ? highlightChunkState.chunk
      : null
  const [highlightChunkLoading, setHighlightChunkLoading] = React.useState(false)
  const highlightReadControllerRef = React.useRef<AbortController | null>(null)
  const [highlightFailure, setHighlightFailure] = React.useState<{
    documentId: string
    chunkId: string
    error: string
  } | null>(null)
  const highlightChunkError =
    highlightFailure?.documentId === documentId && highlightFailure.chunkId === highlightChunkId
      ? highlightFailure.error
      : null
  const highlightContent = React.useMemo<DocumentViewerHighlight | null>(() => {
    if (highlightChunk !== null) return { kind: 'chunk', chunk: highlightChunk }
    if (documentId === null || highlightChunkId === null) return null
    const snapshot = buildCitationSnapshot({
      documentId,
      chunkId: highlightChunkId,
      sourceContext,
      range: highlightRange,
    })
    return snapshot === null ? null : { kind: 'citation', snapshot }
  }, [documentId, highlightChunkId, highlightChunk, sourceContext, highlightRange])
  const [highlightReadAttempt, setHighlightReadAttempt] = React.useState(0)
  const [parsedContentResult, setParsedContent] = React.useState<DocumentParsedContentResponse | null>(null)
  const parsedContent = parsedContentResult?.document_id === documentId ? parsedContentResult : null
  const [parsedContentLoading, setParsedContentLoading] = React.useState(false)
  const [parsedContentError, setParsedContentError] = React.useState<string | null>(null)
  const [parsedReadAttempt, setParsedReadAttempt] = React.useState(0)
  const layout = getDocumentLayout(documentId)
  const textMode = layout?.textMode ?? 'cleaned'
  const [retrieveQuery, setRetrieveQuery] = React.useState('')
  const latestRetrieveQueryRef = React.useRef(retrieveQuery)
  const [retrieveLoading, setRetrieveLoading] = React.useState(false)
  const [retrieveResult, setRetrieveResult] = React.useState<{ query: string; citations: Citation[] } | null>(null)
  const [retrieveFailure, setRetrieveFailure] = React.useState<{ query: string; error: string } | null>(null)
  const retrieveCitations = retrieveResult?.citations ?? []
  const retrieveResultQuery = retrieveResult?.query ?? null
  const retrieveError = retrieveFailure?.error ?? null
  const retrieveFailedQuery = retrieveFailure?.query ?? null
  const documentVisit = React.useMemo(() => ({ documentId }), [documentId])
  const activeDocumentVisitRef = React.useRef<typeof documentVisit | null>(documentVisit)
  const authSession = React.useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const activeDownloadRef = React.useRef<DocumentDownloadRequest | null>(null)
  const [downloadResult, setDownloadResult] = React.useState<DocumentDownloadResult | null>(null)
  const currentDownloadResult =
    downloadResult?.request.visit === documentVisit && downloadResult.request.sessionKey === authSession
      ? downloadResult
      : null
  const downloadLoading = currentDownloadResult?.status === 'processing'
  const downloadError = currentDownloadResult?.status === 'error' ? currentDownloadResult.message : null
  const canDownloadOriginalFile = doc !== null && doc.id === documentId
  const retrieveRequestSeqRef = React.useRef(0)
  const retrieveReadControllerRef = React.useRef<AbortController | null>(null)
  const cancelRetrieveRead = React.useCallback(() => {
    retrieveRequestSeqRef.current += 1
    retrieveReadControllerRef.current?.abort()
    retrieveReadControllerRef.current = null
  }, [])
  const isCurrentDocumentVisit = React.useCallback(
    () => documentVisit === activeDocumentVisitRef.current,
    [documentVisit],
  )
  const isExpanded = layout?.isExpanded ?? false
  const panelWidthPx = layout?.panelWidthPx ?? null
  const chunksListRef = React.useRef<HTMLDivElement>(null)
  const chunkSearchRef = React.useRef<HTMLInputElement>(null)
  const pendingChunksScrollRestoreRef = React.useRef<number | null>(null)
  const pendingTextScrollRestoreRef = React.useRef<number | null>(null)
  const persistedLayoutTimeoutRef = React.useRef<number | null>(null)
  const pendingLayoutRef = React.useRef<{ authScope: string; documentId: string; patch: DocumentViewLayout } | null>(
    null,
  )
  const [chunkQuery, setChunkQuery] = React.useState('')
  const [matchCursor, setMatchCursor] = React.useState(0)
  const [serverMatches, setServerMatches] = React.useState<{
    query: string
    response: Required<DocumentChunkMatchList>
  } | null>(null)
  const [serverMatchFailure, setServerMatchFailure] = React.useState<{ query: string; error: string } | null>(null)
  const [searchReadAttempt, setSearchReadAttempt] = React.useState(0)
  const [serverMatchLoading, setServerMatchLoading] = React.useState(false)
  const matchReadControllerRef = React.useRef<AbortController | null>(null)
  const cancelMatchRead = React.useCallback(() => {
    matchReadControllerRef.current?.abort()
    matchReadControllerRef.current = null
  }, [])
  const parsedContentServerKeyRef = React.useRef<string | null>(null)

  const [chunkEditorOpen, setChunkEditorOpen] = React.useState(false)
  const [chunkEditorMode, setChunkEditorMode] = React.useState<'create' | 'edit'>('create')
  const [chunkEditorTarget, setChunkEditorTarget] = React.useState<DocumentChunk | null>(null)
  const [chunkEditorContent, setChunkEditorContent] = React.useState('')
  const [chunkEditorPageNumber, setChunkEditorPageNumber] = React.useState<string>('')
  const [chunkEditorStartChar, setChunkEditorStartChar] = React.useState<string>('')
  const [chunkEditorEndChar, setChunkEditorEndChar] = React.useState<string>('')
  const [chunkEditorSubmitting, setChunkEditorSubmitting] = React.useState(false)
  const chunkEditorEpochRef = React.useRef(0)
  const chunkMutationSeqRef = React.useRef(0)
  const appliedChunkMutationSeqRef = React.useRef(new Map<string, number>())
  const [chunkDeleteSubmitting, setChunkDeleteSubmitting] = React.useState<string | null>(null)

  const [qaDialogOpen, setQaDialogOpen] = React.useState(false)
  const [qaNumPairsInput, setQaNumPairsInput] = React.useState('20')
  const [qaReplaceExisting, setQaReplaceExisting] = React.useState(true)
  const [qaPreferLlm, setQaPreferLlm] = React.useState(true)
  const [qaMaxSourceCharsInput, setQaMaxSourceCharsInput] = React.useState('12000')
  const [qaSubmitting, setQaSubmitting] = React.useState(false)
  const [qaLastResult, setQaLastResult] = React.useState<DocumentQAGenerateResponse | null>(null)
  const qaDialogEpochRef = React.useRef(0)

  const getChunkKey = React.useCallback((index: number) => chunks[index].id, [chunks])

  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: chunks.length,
    getItemKey: getChunkKey,
    getScrollElement: () => chunksListRef.current,
    estimateSize: () => 220,
    overscan: 8,
  })

  React.useLayoutEffect(() => {
    latestRetrieveQueryRef.current = retrieveQuery
  }, [retrieveQuery])

  React.useLayoutEffect(() => {
    // Returning to the same document starts a new owner for pending UI work.
    activeDocumentVisitRef.current = documentVisit
    return () => {
      activeDocumentVisitRef.current = null
      cancelRetrieveRead()
      cancelMatchRead()
    }
  }, [cancelMatchRead, cancelRetrieveRead, documentVisit])

  const flushPersistedLayoutPatch = React.useCallback(() => {
    if (persistedLayoutTimeoutRef.current !== null) {
      globalThis.window.clearTimeout(persistedLayoutTimeoutRef.current)
      persistedLayoutTimeoutRef.current = null
    }
    const pending = pendingLayoutRef.current
    if (pending === null) return
    pendingLayoutRef.current = null
    if (pending.authScope !== useDocumentView.getState().authScope) return
    setDocumentLayout(pending.documentId, pending.patch)
  }, [setDocumentLayout])

  const persistDocumentLayout = React.useCallback(
    (patch: DocumentViewLayout, immediate = false) => {
      if (!documentId || !isCurrentDocumentVisit()) return
      const pending = pendingLayoutRef.current
      if (pending !== null && pending.authScope === authScope && pending.documentId === documentId) {
        pending.patch = { ...pending.patch, ...patch }
      } else {
        flushPersistedLayoutPatch()
        pendingLayoutRef.current = { authScope, documentId, patch: { ...patch } }
      }
      if (immediate) {
        flushPersistedLayoutPatch()
        return
      }
      if (persistedLayoutTimeoutRef.current !== null) {
        globalThis.window.clearTimeout(persistedLayoutTimeoutRef.current)
      }
      persistedLayoutTimeoutRef.current = globalThis.window.setTimeout(flushPersistedLayoutPatch, 120)
    },
    [authScope, documentId, flushPersistedLayoutPatch, isCurrentDocumentVisit],
  )

  React.useLayoutEffect(() => {
    if (!documentId) return
    const documentLayout = getDocumentLayout(documentId)
    parsedContentServerKeyRef.current = null
    setDoc(null)
    setDocumentError(null)
    setChunks([])
    setChunksLoaded(false)
    setChunksLoading(false)
    setChunksError(null)
    setLoadAllChunks(false)
    setHighlightChunkState(null)
    setHighlightFailure(null)
    setHighlightChunkLoading(false)
    setParsedContent(null)
    setParsedContentLoading(false)
    setParsedContentError(null)
    setRetrieveQuery('')
    setRetrieveLoading(false)
    setRetrieveFailure(null)
    setRetrieveResult(null)
    setChunkEditorOpen(false)
    setChunkEditorTarget(null)
    setChunkEditorSubmitting(false)
    appliedChunkMutationSeqRef.current.clear()
    setChunkDeleteSubmitting(null)
    setQaDialogOpen(false)
    setQaSubmitting(false)
    setQaLastResult(null)
    setChunkQuery('')
    setMatchCursor(0)
    setServerMatches(null)
    setServerMatchFailure(null)
    setServerMatchLoading(false)
    pendingChunksScrollRestoreRef.current =
      typeof documentLayout?.chunksScrollTop === 'number' ? documentLayout.chunksScrollTop : 0
    pendingTextScrollRestoreRef.current =
      typeof documentLayout?.textScrollTop === 'number' ? documentLayout.textScrollTop : 0
    cancelMatchRead()

    const raf = globalThis.window.requestAnimationFrame(() => {
      const top = pendingChunksScrollRestoreRef.current ?? 0
      chunksListRef.current?.scrollTo({ top, left: 0, behavior: 'auto' })
    })
    const prefetchedDoc = getPrefetchedDocument(documentId)
    if (prefetchedDoc) {
      setDoc(prefetchedDoc)
    }

    return () => globalThis.window.cancelAnimationFrame(raf)
  }, [cancelMatchRead, documentId, getDocumentLayout])

  React.useEffect(() => {
    if (documentId === null) return
    setDocumentError(null)
    setIsLoading(true)
    let cancelled = false
    documentApi
      .get(documentId, { includeChunks: false })
      .then((data) => {
        if (cancelled) return
        setDoc(data)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        reportClientError('Load document detail failed', error)
        setDocumentError(formatApiError(error, '读取文档信息失败'))
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [documentId, documentReadAttempt])

  React.useEffect(() => flushPersistedLayoutPatch, [documentId, flushPersistedLayoutPatch])

  React.useEffect(() => {
    if (!documentId) return

    let cancelled = false
    ;(async () => {
      try {
        const cached = await getDocContentFromCache(documentId)
        if (cancelled || cached === null || parsedContentServerKeyRef.current === documentId) return

        setParsedContent({
          document_id: documentId,
          available: true,
          markdown_content: cached.markdownContent,
          original_markdown_content: cached.originalMarkdownContent ?? '',
          persisted_meta: {},
          markdown_truncated: false,
          original_markdown_truncated: false,
          max_chars: 0,
        })
      } catch (error) {
        if (!cancelled) reportClientError('Read cached document content failed', error)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [documentId])

  React.useEffect(() => {
    if (!documentId) return
    setHighlightFailure(null)
    if (!highlightChunkId) {
      setHighlightChunkState(null)
      setHighlightChunkLoading(false)
      return
    }

    const controller = new AbortController()
    highlightReadControllerRef.current = controller
    const prefetchedChunk = getPrefetchedChunk(documentId, highlightChunkId)
    if (prefetchedChunk) {
      setHighlightChunkState({ documentId, chunk: prefetchedChunk })
      setHighlightChunkLoading(false)
    } else {
      setHighlightChunkLoading(true)
    }
    documentApi
      .getChunk(documentId, highlightChunkId, { signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return
        setHighlightChunkState({ documentId, chunk: data })
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        reportClientError('Load highlighted chunk failed', err)
        setHighlightFailure({ documentId, chunkId: highlightChunkId, error: formatApiError(err, '读取引用切片失败') })
      })
      .finally(() => {
        if (highlightReadControllerRef.current === controller) highlightReadControllerRef.current = null
        if (controller.signal.aborted) return
        setHighlightChunkLoading(false)
      })

    return () => {
      controller.abort()
      if (highlightReadControllerRef.current === controller) highlightReadControllerRef.current = null
    }
  }, [documentId, highlightChunkId, highlightReadAttempt])

  React.useEffect(() => {
    if (!documentId) return
    if (activeTab !== 'text') return

    const controller = new AbortController()
    setParsedContentError(null)
    setParsedContentLoading(true)

    documentApi
      .getParsedContent(documentId, { max_chars: 200_000 }, { signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return
        parsedContentServerKeyRef.current = documentId
        setParsedContent(data)
        if (data.available && !data.markdown_truncated && !data.original_markdown_truncated) {
          void cacheDocContentIfMissing({
            id: documentId,
            markdownContent: data.markdown_content,
            originalMarkdownContent: data.original_markdown_content,
          }).catch((error) => reportClientError('Cache parsed document content failed', error))
        }
      })
      .catch((err) => {
        if (controller.signal.aborted) return
        reportClientError('Load parsed document content failed', err)
        setParsedContentError(formatApiError(err, '读取解析文本失败'))
      })
      .finally(() => {
        if (!controller.signal.aborted) setParsedContentLoading(false)
      })

    return () => {
      controller.abort()
    }
  }, [documentId, activeTab, parsedReadAttempt])

  const restartPendingChunkRead = React.useCallback(() => {
    const controller = chunksReadControllerRef.current
    if (controller === null) return
    controller.abort()
    setChunksReadAttempt((attempt) => attempt + 1)
  }, [])

  const acceptChunkMutation = React.useCallback((chunkId: string, sequence: number) => {
    const appliedSequence = appliedChunkMutationSeqRef.current.get(chunkId)
    if (appliedSequence !== undefined && appliedSequence > sequence) return false
    appliedChunkMutationSeqRef.current.set(chunkId, sequence)
    return true
  }, [])

  const cancelHighlightRead = React.useCallback((chunkId: string) => {
    if (useDocumentView.getState().highlightChunkId !== chunkId) return
    highlightReadControllerRef.current?.abort()
    setHighlightChunkLoading(false)
  }, [])

  const shouldLoadAllChunks =
    (activeTab === 'chunks' || activeTab === 'text') && (loadAllChunks || highlightChunkId === null)
  React.useEffect(() => {
    if (documentId === null || chunksLoaded || !shouldLoadAllChunks) {
      setChunksLoading(false)
      return
    }

    setChunksLoading(true)
    setChunksError(null)
    const controller = new AbortController()
    chunksReadControllerRef.current = controller
    ;(async () => {
      const pageSize = 2000
      const all: DocumentChunk[] = []
      for (let skip = 0; ; skip += pageSize) {
        const res = await documentApi.listChunks(documentId, { skip, limit: pageSize }, { signal: controller.signal })
        if (controller.signal.aborted) return
        all.push(...res.items)
        setChunks([...all])
        if (res.items.length === 0 || all.length >= res.total) break
      }

      if (!controller.signal.aborted) setChunksLoaded(true)
    })()
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        reportClientError('Load document chunks failed', error)
        setChunksError(formatApiError(error, '读取切片失败'))
      })
      .finally(() => {
        if (chunksReadControllerRef.current === controller) chunksReadControllerRef.current = null
        if (!controller.signal.aborted) setChunksLoading(false)
      })

    return () => {
      controller.abort()
      if (chunksReadControllerRef.current === controller) chunksReadControllerRef.current = null
    }
  }, [documentId, shouldLoadAllChunks, chunksLoaded, chunksReadAttempt])

  const highlightIndex = React.useMemo(() => {
    if (!highlightChunkId) return -1
    return chunks.findIndex((chunk) => chunk.id === highlightChunkId)
  }, [chunks, highlightChunkId])

  const textValue = !parsedContent?.available
    ? ''
    : textMode === 'original'
      ? parsedContent.original_markdown_content
      : parsedContent.markdown_content

  const { items: textChunkItems, unpositionedCount: textUnpositionedChunkCount } = React.useMemo(() => {
    const base = chunksLoaded ? chunks : highlightChunk ? [highlightChunk] : []
    if (!parsedContent?.available) return { items: [], unpositionedCount: 0 }
    const items = mapDocumentChunksToPreviewItems(base, parsedContent.markdown_content)
    return { items, unpositionedCount: base.length - items.length }
  }, [chunks, chunksLoaded, highlightChunk, parsedContent])

  const textHighlightRange = React.useMemo(() => {
    if (highlightRange === null || !parsedContent?.available) return null
    const converter = createCodePointToUtf16Converter(parsedContent.markdown_content)
    const start = converter.toUtf16(highlightRange.start)
    const end = converter.toUtf16(highlightRange.end)
    return start === undefined || end === undefined ? null : { start, end }
  }, [highlightRange, parsedContent])

  const textActiveChunkIndex = React.useMemo(() => {
    const chunk = chunksLoaded && highlightIndex >= 0 ? chunks[highlightIndex] : highlightChunk
    if (chunk === null) return null
    const idx = textChunkItems.findIndex((item) => item.index === chunk.chunk_index)
    return idx >= 0 ? idx : null
  }, [chunks, chunksLoaded, highlightChunk, highlightIndex, textChunkItems])

  const resolvedPreviewAnchor = React.useMemo(() => {
    const pageNumber =
      previewAnchor?.pageNumber ??
      (highlightRange === null && previewAnchor?.searchText === undefined
        ? (highlightChunk?.page_number ??
          (highlightContent?.kind === 'citation' ? (highlightContent.snapshot.pageNumber ?? undefined) : undefined))
        : undefined)
    return recoverDocumentPreviewAnchorFromChunkPositions(
      { ...previewAnchor, pageNumber },
      highlightChunk,
      highlightRange,
    )
  }, [highlightChunk, highlightContent, highlightRange, previewAnchor])

  const setIsExpanded = React.useCallback(
    (expanded: boolean) => persistDocumentLayout({ isExpanded: expanded }, true),
    [persistDocumentLayout],
  )

  const setPanelWidthPx = React.useCallback(
    (nextWidthPx: number) => persistDocumentLayout({ panelWidthPx: nextWidthPx }, true),
    [persistDocumentLayout],
  )

  const setTextMode = React.useCallback(
    (mode: DocumentTextMode) => persistDocumentLayout({ textMode: mode }, true),
    [persistDocumentLayout],
  )

  React.useEffect(() => {
    if (!documentId) return
    const node = chunksListRef.current
    if (!node) return

    const handleScroll = () => {
      persistDocumentLayout({ chunksScrollTop: node.scrollTop })
    }

    node.addEventListener('scroll', handleScroll, { passive: true })
    return () => node.removeEventListener('scroll', handleScroll)
  }, [documentId, activeTab, isOpen, persistDocumentLayout])

  React.useEffect(() => {
    if (!documentId) return
    if (highlightChunkId && activeTab === 'chunks') return
    const nextScrollTop = pendingChunksScrollRestoreRef.current
    const node = chunksListRef.current
    if (nextScrollTop == null || !node) return

    node.scrollTo({ top: nextScrollTop, left: 0, behavior: 'auto' })
    const maxScrollableTop = Math.max(0, node.scrollHeight - node.clientHeight)
    if (nextScrollTop <= maxScrollableTop + 1 || nextScrollTop === 0) {
      pendingChunksScrollRestoreRef.current = null
    }
  }, [documentId, activeTab, chunks.length, chunksLoaded, highlightChunkId])

  React.useEffect(() => {
    if (!highlightChunkId || activeTab !== 'chunks') return
    if (highlightIndex < 0) return
    rowVirtualizer.scrollToIndex(highlightIndex, { align: 'center' })
  }, [highlightChunkId, activeTab, highlightIndex, rowVirtualizer])

  const localMatchChunkIds = React.useMemo(() => {
    const query = chunkQuery.trim().toLowerCase()
    if (!query) return []

    const ids: string[] = []
    for (const chunk of chunks) {
      const text = chunk.content.toLowerCase()
      if (text.includes(query)) ids.push(chunk.id)
    }
    return ids
  }, [chunks, chunkQuery])

  const resetServerMatches = React.useCallback(() => {
    setServerMatches(null)
    setServerMatchFailure(null)
    setServerMatchLoading(false)
  }, [])

  React.useEffect(() => {
    const query = chunkQuery.trim()
    if (!documentId || !query || chunksLoaded) {
      resetServerMatches()
      return
    }

    const controller = new AbortController()
    matchReadControllerRef.current = controller
    const isCurrentRead = () => !controller.signal.aborted && isCurrentDocumentVisit()
    setServerMatchFailure(null)
    setServerMatchLoading(true)
    const loadServerMatches = async () => {
      if (!isCurrentRead()) return
      try {
        const response = await documentApi.getChunkMatches(
          documentId,
          { q: query, limit: 5000 },
          { signal: controller.signal },
        )
        if (!isCurrentRead()) return
        setServerMatches({ query, response })
        setMatchCursor(0)
      } catch (err) {
        if (!isCurrentRead()) return
        reportClientError('Load chunk search matches failed', err)
        setServerMatchFailure({ query, error: formatApiError(err, '搜索切片失败') })
      } finally {
        if (isCurrentRead()) setServerMatchLoading(false)
      }
    }

    const timeoutId = globalThis.window.setTimeout(() => {
      void loadServerMatches()
    }, 250)

    return () => {
      globalThis.window.clearTimeout(timeoutId)
      controller.abort()
      if (matchReadControllerRef.current === controller) matchReadControllerRef.current = null
    }
  }, [documentId, chunkQuery, chunksLoaded, isCurrentDocumentVisit, resetServerMatches, searchReadAttempt])

  const serverMatchError = serverMatchFailure?.query === chunkQuery.trim() ? serverMatchFailure.error : null
  const serverMatchTruncated = serverMatches?.query === chunkQuery.trim() && serverMatches.response.truncated

  const matchChunkIds = React.useMemo(() => {
    if (!chunkQuery.trim()) return []
    if (chunksLoaded) return localMatchChunkIds
    if (serverMatchLoading || serverMatchError !== null || serverMatches?.query !== chunkQuery.trim()) return []
    return serverMatches.response.items.map((item) => item.id)
  }, [chunkQuery, chunksLoaded, localMatchChunkIds, serverMatches, serverMatchLoading, serverMatchError])

  const chunkSearchPlaceholder = serverMatchLoading
    ? '搜索中…'
    : chunksLoaded
      ? '搜索切片内容…'
      : '搜索切片内容…（无需加载全部切片）'

  const chunkMatchSummary = React.useMemo(() => {
    if (!chunkQuery.trim()) return '—'
    if (!chunksLoaded && serverMatchError !== null) return '搜索失败'
    if (!chunksLoaded && (serverMatchLoading || serverMatches?.query !== chunkQuery.trim())) return '…'
    if (matchChunkIds.length) {
      return `${matchCursor + 1}/${chunksLoaded ? matchChunkIds.length : serverMatches?.response.total}${!chunksLoaded && serverMatchTruncated ? '+' : ''}`
    }
    return '0/0'
  }, [
    chunkQuery,
    chunksLoaded,
    matchChunkIds.length,
    matchCursor,
    serverMatchLoading,
    serverMatchError,
    serverMatches,
    serverMatchTruncated,
  ])

  const handleSelectTextChunkIndex = React.useCallback(
    (chunkIndex: number) => {
      if (!isCurrentDocumentVisit()) return
      const target =
        chunks.find((chunk) => chunk.chunk_index === chunkIndex) ||
        (highlightChunk?.chunk_index === chunkIndex ? highlightChunk : null)
      if (target) setHighlightChunk(target.id)
    },
    [chunks, highlightChunk, isCurrentDocumentVisit, setHighlightChunk],
  )

  React.useEffect(() => {
    setMatchCursor(0)
  }, [chunkQuery])

  const fileUrl = documentId === null ? null : `${API_V1_BASE_URL}/documents/${documentId}/download`

  const downloadOriginalFile = React.useCallback(async () => {
    if (documentId === null || doc === null || doc.id !== documentId || !isCurrentDocumentVisit()) return
    const sessionKey = getAuthSessionKey()
    if (activeDownloadRef.current?.visit === documentVisit && activeDownloadRef.current.sessionKey === sessionKey)
      return
    const request: DocumentDownloadRequest = { visit: documentVisit, sessionKey }
    activeDownloadRef.current = request
    setDownloadResult({ request, status: 'processing' })
    try {
      const blob = await documentApi.download(documentId, { inline: false })
      if (
        !isCurrentDocumentVisit() ||
        activeDownloadRef.current !== request ||
        request.sessionKey !== getAuthSessionKey()
      )
        return
      downloadBlob(doc.filename, blob)
    } catch (error: unknown) {
      if (
        isCurrentDocumentVisit() &&
        activeDownloadRef.current === request &&
        request.sessionKey === getAuthSessionKey()
      ) {
        setDownloadResult({ request, status: 'error', message: formatApiError(error, '下载原文件失败') })
      }
    } finally {
      if (activeDownloadRef.current === request) activeDownloadRef.current = null
      if (isCurrentDocumentVisit()) {
        setDownloadResult((previous) =>
          previous?.request === request && previous.status === 'processing' ? null : previous,
        )
      }
    }
  }, [documentId, doc, documentVisit, isCurrentDocumentVisit])

  const copyText = React.useCallback(
    async (text: string, okMsg: string) => {
      if (!isCurrentDocumentVisit()) return
      try {
        if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
          throw new Error('Clipboard API unavailable')
        }
        await navigator.clipboard.writeText(text)
        if (isCurrentDocumentVisit()) toast.success(okMsg)
      } catch (error) {
        if (!isCurrentDocumentVisit()) return
        reportClientError('Copy document viewer text failed', error)
        toast.error('复制失败')
      }
    },
    [isCurrentDocumentVisit],
  )

  const copyChunkContent = React.useCallback((content: string) => copyText(content, '已复制切片内容'), [copyText])

  const copyChunkLink = React.useCallback(
    async (location: DocumentChunkLocation) => {
      if (documentId === null || !isCurrentDocumentVisit()) return
      const url = new URL('/', globalThis.window.location.origin)
      url.searchParams.set('doc', documentId)
      url.searchParams.set('chunk', location.id)
      const start = location.start_char
      const end = location.end_char
      if (typeof start === 'number' && typeof end === 'number' && end > start) {
        url.searchParams.set('start', String(start))
        url.searchParams.set('end', String(end))
      }
      await copyText(url.toString(), '已复制定位链接')
    },
    [copyText, documentId, isCurrentDocumentVisit],
  )

  const canEditChunks = doc !== null && doc.status !== 'pending' && doc.status !== 'processing'
  const canRerunRetrieve = retrieveQuery.trim() !== ''

  const clearRetrievePreview = React.useCallback(() => {
    if (!isCurrentDocumentVisit()) return
    cancelRetrieveRead()
    setRetrieveResult(null)
    setRetrieveFailure(null)
    setRetrieveLoading(false)
  }, [cancelRetrieveRead, isCurrentDocumentVisit])

  const runRetrievePreviewForQuery = React.useCallback(
    async (query: string) => {
      if (!documentId || !isCurrentDocumentVisit()) return
      const normalized = query.trim()
      if (!normalized) return

      cancelRetrieveRead()
      const requestSeq = retrieveRequestSeqRef.current
      const controller = new AbortController()
      retrieveReadControllerRef.current = controller
      setRetrieveLoading(true)
      setRetrieveFailure(null)
      try {
        const res = await ragApi.retrievePreview(
          {
            query: normalized,
            document_ids: [documentId],
            include_structure_trace: false,
          },
          { signal: controller.signal },
        )
        if (requestSeq !== retrieveRequestSeqRef.current) return
        const items = res.citations.map(parseRetrievalCitation)
        setRetrieveResult({
          query: normalized,
          citations: items.filter((citation) => citation.document_id === documentId),
        })
      } catch (err) {
        if (requestSeq !== retrieveRequestSeqRef.current) return
        reportClientError('Run retrieve preview failed', err)
        setRetrieveFailure({ query: normalized, error: '检索测试失败，请稍后重试' })
      } finally {
        if (requestSeq === retrieveRequestSeqRef.current) {
          retrieveReadControllerRef.current = null
          setRetrieveLoading(false)
        }
      }
    },
    [cancelRetrieveRead, documentId, isCurrentDocumentVisit],
  )

  const openCreateChunk = React.useCallback(() => {
    if (!isCurrentDocumentVisit()) return
    chunkEditorEpochRef.current += 1
    setChunkEditorSubmitting(false)
    setChunkEditorMode('create')
    setChunkEditorTarget(null)
    setChunkEditorContent('')
    setChunkEditorPageNumber('')
    setChunkEditorStartChar('')
    setChunkEditorEndChar('')
    setChunkEditorOpen(true)
    setActiveTab('chunks')
  }, [isCurrentDocumentVisit, setActiveTab])

  const openEditChunk = React.useCallback(
    (chunk: DocumentChunk) => {
      if (!isCurrentDocumentVisit()) return
      chunkEditorEpochRef.current += 1
      setChunkEditorSubmitting(false)
      setChunkEditorMode('edit')
      setChunkEditorTarget(chunk)
      setChunkEditorContent(chunk.content)
      setChunkEditorPageNumber(typeof chunk.page_number === 'number' ? String(chunk.page_number) : '')
      setChunkEditorStartChar(typeof chunk.start_char === 'number' ? String(chunk.start_char) : '')
      setChunkEditorEndChar(typeof chunk.end_char === 'number' ? String(chunk.end_char) : '')
      setChunkEditorOpen(true)
      setActiveTab('chunks')
    },
    [isCurrentDocumentVisit, setActiveTab],
  )

  const submitChunkEditor = React.useCallback(
    async (mode: 'save' | 'save_reembed' | 'save_rerun' = 'save') => {
      if (!documentId || !isCurrentDocumentVisit()) return
      if (!canEditChunks) return

      const content = chunkEditorContent
      if (chunkEditorMode === 'create' && content.length === 0) {
        toast.error('切片内容不能为空')
        return
      }

      let positions: ReturnType<typeof parseChunkPositions>
      try {
        positions = parseChunkPositions({
          pageNumber: chunkEditorPageNumber,
          startChar: chunkEditorStartChar,
          endChar: chunkEditorEndChar,
        })
      } catch (error) {
        toast.error(formatApiError(error, '位置输入不正确'))
        return
      }

      const previewRequestAtSave = retrieveRequestSeqRef.current
      const saveSessionKey = getAuthSessionKey()
      const targetChunkId = chunkEditorTarget?.id
      const editorEpoch = ++chunkEditorEpochRef.current
      const mutationSequence = ++chunkMutationSeqRef.current
      setChunkEditorSubmitting(true)
      try {
        let savedChunk: DocumentChunk | null = null
        if (chunkEditorMode === 'create') {
          const created = await documentApi.createChunk(documentId, {
            content,
            ...positions,
            metadata: {},
          })
          if (isCurrentDocumentVisit() && acceptChunkMutation(created.id, mutationSequence)) {
            restartPendingChunkRead()
            if (chunkEditorEpochRef.current === editorEpoch) toast.success('切片已创建')
            if (!chunksLoaded) setLoadAllChunks(true)
            setChunks((prev) => [...prev, created])
            setDoc((prev) =>
              prev
                ? {
                    ...prev,
                    chunk_count: typeof prev.chunk_count === 'number' ? prev.chunk_count + 1 : prev.chunk_count,
                  }
                : prev,
            )
            if (chunkEditorEpochRef.current === editorEpoch) setHighlightChunk(created.id)
          }
          savedChunk = created
        } else {
          const target = chunkEditorTarget
          if (!target) return
          const updated = await documentApi.updateChunk(documentId, target.id, {
            content,
            ...positions,
          })
          if (isCurrentDocumentVisit() && acceptChunkMutation(updated.id, mutationSequence)) {
            restartPendingChunkRead()
            if (!chunksLoaded) {
              matchReadControllerRef.current?.abort()
              resetServerMatches()
              setSearchReadAttempt((attempt) => attempt + 1)
            }
            cancelHighlightRead(updated.id)
            if (chunkEditorEpochRef.current === editorEpoch) toast.success('切片已更新')
            setChunks((prev) => prev.map((chunk) => (chunk.id === updated.id ? updated : chunk)))
            if (useDocumentView.getState().highlightChunkId === updated.id) {
              setHighlightChunkState({ documentId, chunk: updated })
            }
            if (chunkEditorEpochRef.current === editorEpoch) setHighlightChunk(updated.id)
          }
          savedChunk = updated
        }

        if (isCurrentDocumentVisit()) {
          globalThis.window.requestAnimationFrame(() => {
            if (isCurrentDocumentVisit()) rowVirtualizer.measure()
          })
          // Automatic close after a successful save preserves its pending re-embed/rerun intent.
          if (chunkEditorEpochRef.current === editorEpoch) setChunkEditorOpen(false)
        }

        // Finish the accepted write against its original chunk, including requested re-embedding.
        if (savedChunk && mode !== 'save' && getAuthSessionKey() === saveSessionKey) {
          const savedChunkId = savedChunk.id
          try {
            const res = await documentApi.reembedChunks(documentId, {
              chunk_ids: [savedChunkId],
              include_disabled: Boolean(savedChunk.disabled_at),
            })
            if (res.reembedded !== 1) throw new Error('重嵌入未更新目标切片')
            if (isCurrentDocumentVisit() && chunkEditorEpochRef.current === editorEpoch) {
              toast.success(`已重新嵌入 ${res.reembedded} 个切片`)
            }

            if (
              mode === 'save_rerun' &&
              isCurrentDocumentVisit() &&
              chunkEditorEpochRef.current === editorEpoch &&
              previewRequestAtSave === retrieveRequestSeqRef.current &&
              latestRetrieveQueryRef.current === retrieveQuery
            ) {
              const query = retrieveQuery.trim()
              if (query) {
                await runRetrievePreviewForQuery(query)
              } else {
                toast.message('已保存并重新嵌入；当前没有检索 query 可复跑')
              }
            }
          } catch (err) {
            reportClientError('Re-embed saved chunk failed', err, {
              tags: { document_id: documentId, chunk_id: savedChunkId },
            })
            if (isCurrentDocumentVisit() && chunkEditorEpochRef.current === editorEpoch) {
              toast.warning(`切片已保存，重嵌入失败。 ${formatApiError(err, '请重试向量更新')}`)
            }
          }
        }
      } catch (err) {
        reportClientError('Save chunk failed', err, {
          tags: targetChunkId ? { document_id: documentId, chunk_id: targetChunkId } : { document_id: documentId },
        })
        if (isCurrentDocumentVisit() && chunkEditorEpochRef.current === editorEpoch) {
          toast.error(formatApiError(err, '切片保存失败'))
        }
      } finally {
        if (isCurrentDocumentVisit() && chunkEditorEpochRef.current === editorEpoch) setChunkEditorSubmitting(false)
      }
    },
    [
      acceptChunkMutation,
      cancelHighlightRead,
      canEditChunks,
      chunkEditorContent,
      chunkEditorEndChar,
      chunkEditorMode,
      chunkEditorPageNumber,
      chunkEditorStartChar,
      chunkEditorTarget,
      chunksLoaded,
      documentId,
      isCurrentDocumentVisit,
      retrieveQuery,
      rowVirtualizer,
      restartPendingChunkRead,
      resetServerMatches,
      runRetrievePreviewForQuery,
      setHighlightChunk,
    ],
  )

  const handleDeleteChunk = React.useCallback(
    async (chunk: DocumentChunk) => {
      if (!documentId || !isCurrentDocumentVisit()) return
      if (!canEditChunks) return

      const chunkId = chunk.id
      const mutationSequence = ++chunkMutationSeqRef.current
      setChunkDeleteSubmitting(chunkId)
      try {
        await documentApi.deleteChunk(documentId, chunkId)
        if (!isCurrentDocumentVisit() || !acceptChunkMutation(chunkId, mutationSequence)) return
        restartPendingChunkRead()
        cancelHighlightRead(chunkId)
        toast.success('切片已删除')
        setChunks((prev) => prev.filter((item) => item.id !== chunkId))
        setDoc((prev) =>
          prev
            ? {
                ...prev,
                chunk_count:
                  typeof prev.chunk_count === 'number' ? Math.max(0, prev.chunk_count - 1) : prev.chunk_count,
              }
            : prev,
        )
        if (useDocumentView.getState().highlightChunkId === chunkId) {
          setHighlightChunk(null)
          setHighlightChunkState(null)
        }

        globalThis.window.requestAnimationFrame(() => {
          if (isCurrentDocumentVisit()) rowVirtualizer.measure()
        })
      } catch (err) {
        reportClientError('Delete chunk failed', err, { tags: { document_id: documentId, chunk_id: chunkId } })
        if (isCurrentDocumentVisit()) throw err
      } finally {
        if (isCurrentDocumentVisit()) {
          setChunkDeleteSubmitting((current) => (current === chunkId ? null : current))
        }
      }
    },
    [
      acceptChunkMutation,
      cancelHighlightRead,
      canEditChunks,
      documentId,
      isCurrentDocumentVisit,
      restartPendingChunkRead,
      rowVirtualizer,
      setHighlightChunk,
    ],
  )

  const runQaGeneration = React.useCallback(async () => {
    if (!documentId || !isCurrentDocumentVisit()) return
    if (!canEditChunks) return

    let numPairs: number
    let maxSourceChars: number
    try {
      numPairs = parseIntegerInput(qaNumPairsInput, { label: '问答数量', min: 1, max: 200 })
      maxSourceChars = parseIntegerInput(qaMaxSourceCharsInput, { label: '来源字符数', min: 500, max: 200_000 })
    } catch (error) {
      toast.error(formatApiError(error, '问答设置不正确'))
      return
    }

    const qaEpoch = ++qaDialogEpochRef.current
    setQaSubmitting(true)
    try {
      const res = await documentApi.generateQa(documentId, {
        num_pairs: numPairs,
        replace_existing: qaReplaceExisting,
        prefer_llm: qaPreferLlm,
        max_source_chars: maxSourceChars,
        preview_pairs: 5,
      })
      if (!isCurrentDocumentVisit()) return
      restartPendingChunkRead()
      if (qaDialogEpochRef.current === qaEpoch) {
        setQaLastResult(res)
        toast.success(`Q&A: +${res.created} (-${res.deleted}) [${res.mode}]`)
      }

      setDoc((prev) =>
        prev
          ? {
              ...prev,
              chunk_count: prev.chunk_count + res.created - res.deleted,
            }
          : prev,
      )

      setLoadAllChunks(true)
      setChunksLoaded(false)
      setChunks([])

      if (qaDialogEpochRef.current === qaEpoch && res.chunk_ids?.length) {
        setHighlightChunk(res.chunk_ids[0])
      }
    } catch (err) {
      reportClientError('Generate document Q&A failed', err, { tags: { document_id: documentId } })
      if (isCurrentDocumentVisit() && qaDialogEpochRef.current === qaEpoch) {
        toast.error(formatApiError(err, '问答生成失败'))
      }
    } finally {
      // This job keeps the current visit busy until it finishes, even if the dialog is reopened.
      if (isCurrentDocumentVisit()) setQaSubmitting(false)
    }
  }, [
    canEditChunks,
    documentId,
    isCurrentDocumentVisit,
    qaMaxSourceCharsInput,
    qaNumPairsInput,
    qaPreferLlm,
    qaReplaceExisting,
    restartPendingChunkRead,
    setHighlightChunk,
  ])

  const canInlinePreview = doc?.file_type?.toLowerCase() === 'pdf'

  const jumpToMatch = React.useCallback(
    (nextIndex: number) => {
      if (!isCurrentDocumentVisit()) return
      if (!matchChunkIds.length) return
      const clamped = ((nextIndex % matchChunkIds.length) + matchChunkIds.length) % matchChunkIds.length
      setMatchCursor(clamped)
      setActiveTab('chunks')
      setHighlightChunk(matchChunkIds[clamped])
    },
    [isCurrentDocumentVisit, matchChunkIds, setActiveTab, setHighlightChunk],
  )

  const handleChunkSearchKeyDown = React.useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (event.key !== 'Enter') return
      event.preventDefault()
      if (!matchChunkIds.length) return

      const currentId = matchChunkIds[matchCursor]
      if (currentId && highlightChunkId === currentId) {
        jumpToMatch(matchCursor + (event.shiftKey ? -1 : 1))
        return
      }

      jumpToMatch(matchCursor)
    },
    [highlightChunkId, jumpToMatch, matchChunkIds, matchCursor],
  )

  React.useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || !isCurrentDocumentVisit()) return
      const noModifier = !event.metaKey && !event.ctrlKey && !event.altKey
      const typingTarget = isTypingTarget(event.target)

      if (event.key === 'Escape') {
        if (activeTab === 'chunks' && chunkQuery.trim()) {
          event.preventDefault()
          setChunkQuery('')
          return
        }
        event.preventDefault()
        closeDocument()
        return
      }

      const isFind = (event.key === 'f' || event.key === 'F') && (event.metaKey || event.ctrlKey)
      if (isFind && activeTab === 'chunks') {
        event.preventDefault()
        chunkSearchRef.current?.focus()
        chunkSearchRef.current?.select()
        return
      }

      if (activeTab !== 'chunks' || !noModifier) return

      if (event.key === '/' && !typingTarget) {
        event.preventDefault()
        chunkSearchRef.current?.focus()
        chunkSearchRef.current?.select()
        return
      }

      if (typingTarget) return

      const navigation = resolveChunkKeyboardNavigation({
        key: event.key,
        matchCount: matchChunkIds.length,
        matchCursor,
        loadedChunkCount: chunks.length,
        highlightIndex,
      })

      if (!navigation) return

      event.preventDefault()
      if (navigation.type === 'match') {
        jumpToMatch(navigation.nextIndex)
        return
      }

      const nextChunk = chunks[navigation.nextIndex]
      if (nextChunk) {
        setActiveTab('chunks')
        setHighlightChunk(nextChunk.id)
      }
    }

    globalThis.window.addEventListener('keydown', onKeyDown)
    return () => globalThis.window.removeEventListener('keydown', onKeyDown)
  }, [
    isOpen,
    isCurrentDocumentVisit,
    activeTab,
    chunkQuery,
    closeDocument,
    matchChunkIds.length,
    matchCursor,
    chunks,
    highlightIndex,
    jumpToMatch,
    setActiveTab,
    setHighlightChunk,
  ])

  const runRetrievePreview = React.useCallback(async () => {
    const query = retrieveQuery.trim()
    if (!query) return
    await runRetrievePreviewForQuery(query)
  }, [retrieveQuery, runRetrievePreviewForQuery])

  const handleTextScrollTopChange = React.useCallback(
    (textScrollTop: number) => {
      if (!isCurrentDocumentVisit()) return
      pendingTextScrollRestoreRef.current = textScrollTop
      persistDocumentLayout({ textScrollTop })
    },
    [isCurrentDocumentVisit, persistDocumentLayout],
  )

  const handleChunkEditorOpenChange = React.useCallback(
    (open: boolean) => {
      if (!isCurrentDocumentVisit()) return
      chunkEditorEpochRef.current += 1
      setChunkEditorSubmitting(false)
      if (!open) {
        setChunkEditorOpen(false)
        return
      }
      setChunkEditorOpen(true)
    },
    [isCurrentDocumentVisit],
  )

  const handleQaDialogOpenChange = React.useCallback(
    (open: boolean) => {
      if (!isCurrentDocumentVisit()) return
      qaDialogEpochRef.current += 1
      setQaDialogOpen(open)
      if (open) setQaLastResult(null)
    },
    [isCurrentDocumentVisit],
  )

  const handleActiveTabChange = React.useCallback(
    (value: string) => {
      if (!isCurrentDocumentVisit()) return
      if (isDocumentViewTab(value)) setActiveTab(value)
    },
    [isCurrentDocumentVisit, setActiveTab],
  )

  const jumpToSource = React.useCallback(() => {
    if (!isCurrentDocumentVisit()) return
    if (sourceContext?.kind !== 'chat-citation') return

    globalEventBus.emit('chat:focus-message', {
      messageId: sourceContext.messageId,
      documentId: sourceContext.documentId,
      chunkId: sourceContext.chunkId ?? null,
    })
  }, [isCurrentDocumentVisit, sourceContext])

  const retryDocument = React.useCallback(() => {
    if (isCurrentDocumentVisit()) setDocumentReadAttempt((attempt) => attempt + 1)
  }, [isCurrentDocumentVisit])

  const retryChunks = React.useCallback(() => {
    if (!isCurrentDocumentVisit()) return
    setLoadAllChunks(true)
    setChunksLoaded(false)
    setChunksReadAttempt((attempt) => attempt + 1)
  }, [isCurrentDocumentVisit])

  const retryParsedContent = React.useCallback(() => {
    if (isCurrentDocumentVisit()) setParsedReadAttempt((attempt) => attempt + 1)
  }, [isCurrentDocumentVisit])

  const retryChunkSearch = React.useCallback(() => {
    if (isCurrentDocumentVisit()) setSearchReadAttempt((attempt) => attempt + 1)
  }, [isCurrentDocumentVisit])

  const retryHighlightedChunk = React.useCallback(() => {
    if (isCurrentDocumentVisit()) setHighlightReadAttempt((attempt) => attempt + 1)
  }, [isCurrentDocumentVisit])

  return {
    activeTab,
    canEditChunks,
    canInlinePreview,
    canRerunRetrieve,
    chunkDeleteSubmitting,
    chunkEditorContent,
    chunkEditorEndChar,
    chunkEditorMode,
    chunkEditorOpen,
    chunkEditorPageNumber,
    chunkEditorStartChar,
    chunkEditorSubmitting,
    chunkEditorTarget,
    chunkMatchSummary,
    chunkQuery,
    chunkSearchPlaceholder,
    chunkSearchRef,
    chunks,
    chunksListRef,
    chunksLoaded,
    chunksLoading,
    chunksError,
    clearRetrievePreview,
    closeDocument,
    copyChunkContent,
    copyChunkLink,
    doc,
    documentError,
    documentId,
    canDownloadOriginalFile,
    downloadOriginalFile,
    downloadLoading,
    downloadError,
    fileUrl,
    handleActiveTabChange,
    handleChunkEditorOpenChange,
    handleChunkSearchKeyDown,
    handleDeleteChunk,
    handleQaDialogOpenChange,
    handleSelectTextChunkIndex,
    handleTextScrollTopChange,
    highlightContent,
    highlightChunkId,
    highlightChunkLoading,
    highlightChunkError,
    highlightRange: highlightRange ?? null,
    isExpanded,
    isLoading,
    isOpen,
    jumpToMatch,
    jumpToSource,
    loadAllChunks,
    matchCursor,
    matchChunkIds,
    openCreateChunk,
    openEditChunk,
    parsedContent,
    parsedContentError,
    parsedContentLoading,
    panelWidthPx,
    previewAnchor: resolvedPreviewAnchor,
    qaDialogOpen,
    qaLastResult,
    qaMaxSourceCharsInput,
    qaNumPairsInput,
    qaPreferLlm,
    qaReplaceExisting,
    qaSubmitting,
    retrieveCitations,
    retrieveError,
    retrieveFailedQuery,
    retrieveLoading,
    retrieveQuery,
    retrieveResultQuery,
    retryDocument,
    retryChunks,
    retryParsedContent,
    retryChunkSearch,
    retryHighlightedChunk,
    rowVirtualizer,
    runQaGeneration,
    runRetrievePreview,
    serverMatchTruncated,
    serverMatchError,
    sourceContext,
    setChunkEditorContent,
    setChunkEditorEndChar,
    setChunkEditorPageNumber,
    setChunkEditorStartChar,
    setChunkQuery,
    setHighlightChunk,
    setIsExpanded,
    setPanelWidthPx,
    setLoadAllChunks,
    setQaMaxSourceCharsInput,
    setQaNumPairsInput,
    setQaPreferLlm,
    setQaReplaceExisting,
    setRetrieveQuery,
    setTextMode,
    submitChunkEditor,
    textActiveChunkIndex,
    textChunkItems,
    textHighlightRange,
    textUnpositionedChunkCount,
    textInitialScrollTop: pendingTextScrollRestoreRef.current ?? 0,
    textMode,
    textValue,
  }
}

export type DocumentViewerPanelState = ReturnType<typeof useDocumentViewerPanelState>
