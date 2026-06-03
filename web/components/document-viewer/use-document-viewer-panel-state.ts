"use client"

import * as React from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { toast } from "sonner"

import { useResolvedAuthAssetUrl } from "@/components/auth-image"
import { documentApi, ragApi } from "@/lib/api"
import { formatApiError } from "@/lib/api-errors"
import { reportClientError } from "@/lib/client-logging"
import { getDocContentFromCache, saveDocContentToCache } from "@/lib/doc-content-cache"
import { mapDocumentChunksToPreviewItems } from "@/lib/document-chunks"
import {
  recoverDocumentPreviewAnchorFromChunkPositions,
  sanitizeDocumentPreviewAnchor,
} from "@/lib/document-preview-anchor"
import { getPrefetchedChunk, getPrefetchedDocument } from "@/lib/document-view-prefetch"
import { API_V1_BASE_URL } from "@/lib/env"
import { globalEventBus } from "@/lib/event-bus"
import { detachPromise } from "@/lib/utils"
import { useDocumentView, type DocumentViewTab } from "@/store/document-view"
import type {
  Citation,
  Document,
  DocumentChunk,
  DocumentParsedContentResponse,
  DocumentQAGenerateResponse,
} from "@/types"

import { resolveChunkKeyboardNavigation } from "./keyboard-shortcuts"
import { toCitation } from "./document-viewer-panel-utils"

function mapChunkMatchIds(items: ReadonlyArray<{ id: string }>): string[] {
  return items.map((item) => item.id)
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tagName = target.tagName
  return target.isContentEditable || tagName === "INPUT" || tagName === "TEXTAREA" || tagName === "SELECT"
}

function isDocumentViewTab(value: string): value is DocumentViewTab {
  return value === "preview" || value === "text" || value === "chunks"
}

export function useDocumentViewerPanelState() {
  const {
    isOpen,
    documentId,
    highlightChunkId,
    highlightRange,
    previewAnchor,
    sourceContext,
    closeDocument,
    activeTab,
    documentLayouts,
    setActiveTab,
    setDocumentLayout,
    setHighlightChunk,
  } = useDocumentView()

  const [doc, setDoc] = React.useState<Document | null>(null)
  const [chunks, setChunks] = React.useState<DocumentChunk[]>([])
  const [isLoading, setIsLoading] = React.useState(false)
  const [chunksLoaded, setChunksLoaded] = React.useState(false)
  const [chunksLoading, setChunksLoading] = React.useState(false)
  const [loadAllChunks, setLoadAllChunks] = React.useState(false)
  const [highlightChunk, setHighlightChunkState] = React.useState<DocumentChunk | null>(null)
  const [highlightChunkLoading, setHighlightChunkLoading] = React.useState(false)
  const [parsedContent, setParsedContent] = React.useState<DocumentParsedContentResponse | null>(null)
  const [parsedContentLoading, setParsedContentLoading] = React.useState(false)
  const [parsedContentError, setParsedContentError] = React.useState<string | null>(null)
  const [textMode, setTextMode] = React.useState<"cleaned" | "original">("cleaned")
  const [retrieveQuery, setRetrieveQuery] = React.useState("")
  const [retrieveLoading, setRetrieveLoading] = React.useState(false)
  const [retrieveError, setRetrieveError] = React.useState<string | null>(null)
  const [retrieveCitations, setRetrieveCitations] = React.useState<Citation[]>([])
  const [isExpanded, setIsExpanded] = React.useState(false)
  const [panelWidthPx, setPanelWidthPxState] = React.useState<number | null>(null)
  const chunksListRef = React.useRef<HTMLDivElement>(null)
  const chunkSearchRef = React.useRef<HTMLInputElement>(null)
  const previousDocumentIdRef = React.useRef<string | null>(null)
  const pendingChunksScrollRestoreRef = React.useRef<number | null>(null)
  const pendingTextScrollRestoreRef = React.useRef<number | null>(null)
  const persistedLayoutTimeoutRef = React.useRef<number | null>(null)
  const persistedLayoutDocIdRef = React.useRef<string | null>(null)
  const pendingLayoutPatchRef = React.useRef<Record<string, unknown>>({})
  const [chunkQuery, setChunkQuery] = React.useState("")
  const [matchCursor, setMatchCursor] = React.useState(0)
  const [serverMatchIds, setServerMatchIds] = React.useState<string[]>([])
  const [serverMatchTotal, setServerMatchTotal] = React.useState(0)
  const [serverMatchTruncated, setServerMatchTruncated] = React.useState(false)
  const [serverMatchLoading, setServerMatchLoading] = React.useState(false)
  const matchRequestSeqRef = React.useRef(0)
  const parsedContentServerKeyRef = React.useRef<string | null>(null)

  const [chunkEditorOpen, setChunkEditorOpen] = React.useState(false)
  const [chunkEditorMode, setChunkEditorMode] = React.useState<"create" | "edit">("create")
  const [chunkEditorTarget, setChunkEditorTarget] = React.useState<DocumentChunk | null>(null)
  const [chunkEditorContent, setChunkEditorContent] = React.useState("")
  const [chunkEditorPageNumber, setChunkEditorPageNumber] = React.useState<string>("")
  const [chunkEditorStartChar, setChunkEditorStartChar] = React.useState<string>("")
  const [chunkEditorEndChar, setChunkEditorEndChar] = React.useState<string>("")
  const [chunkEditorSubmitting, setChunkEditorSubmitting] = React.useState(false)
  const [chunkDeleteSubmitting, setChunkDeleteSubmitting] = React.useState<string | null>(null)

  const [qaDialogOpen, setQaDialogOpen] = React.useState(false)
  const [qaNumPairs, setQaNumPairs] = React.useState(20)
  const [qaReplaceExisting, setQaReplaceExisting] = React.useState(true)
  const [qaPreferLlm, setQaPreferLlm] = React.useState(true)
  const [qaMaxSourceChars, setQaMaxSourceChars] = React.useState(12000)
  const [qaSubmitting, setQaSubmitting] = React.useState(false)
  const [qaLastResult, setQaLastResult] = React.useState<DocumentQAGenerateResponse | null>(null)

  const rowVirtualizer = useVirtualizer({
    count: chunks.length,
    getScrollElement: () => chunksListRef.current,
    estimateSize: () => 220,
    overscan: 8,
  })

  const documentLayout = React.useMemo(
    () => (documentId ? documentLayouts[documentId] || null : null),
    [documentId, documentLayouts]
  )

  const flushPersistedLayoutPatch = React.useCallback(
    (targetDocumentId?: string | null) => {
      const documentIdToFlush = targetDocumentId || persistedLayoutDocIdRef.current
      if (!documentIdToFlush) return
      if (persistedLayoutTimeoutRef.current != null) {
        globalThis.window.clearTimeout(persistedLayoutTimeoutRef.current)
        persistedLayoutTimeoutRef.current = null
      }

      const patch = pendingLayoutPatchRef.current
      pendingLayoutPatchRef.current = {}

      if (!Object.keys(patch).length) return
      setDocumentLayout(documentIdToFlush, patch)
    },
    [setDocumentLayout]
  )

  const persistDocumentLayout = React.useCallback(
    (patch: Record<string, unknown>, immediate = false) => {
      if (!documentId) return

      if (persistedLayoutDocIdRef.current && persistedLayoutDocIdRef.current !== documentId) {
        flushPersistedLayoutPatch(persistedLayoutDocIdRef.current)
      }

      persistedLayoutDocIdRef.current = documentId
      pendingLayoutPatchRef.current = {
        ...pendingLayoutPatchRef.current,
        ...patch,
      }

      if (immediate) {
        flushPersistedLayoutPatch(documentId)
        return
      }

      if (persistedLayoutTimeoutRef.current != null) {
        globalThis.window.clearTimeout(persistedLayoutTimeoutRef.current)
      }
      persistedLayoutTimeoutRef.current = globalThis.window.setTimeout(() => {
        flushPersistedLayoutPatch(documentId)
      }, 120)
    },
    [documentId, flushPersistedLayoutPatch]
  )

  React.useEffect(() => {
    if (!documentId) {
      previousDocumentIdRef.current = null
      return
    }
    if (previousDocumentIdRef.current === documentId) return
    previousDocumentIdRef.current = documentId
    parsedContentServerKeyRef.current = null
    setDoc(null)
    setChunks([])
    setChunksLoaded(false)
    setChunksLoading(false)
    setLoadAllChunks(false)
    setHighlightChunkState(null)
    setHighlightChunkLoading(false)
    setParsedContent(null)
    setParsedContentLoading(false)
    setParsedContentError(null)
    setTextMode(documentLayout?.textMode === "original" ? "original" : "cleaned")
    setRetrieveQuery("")
    setRetrieveLoading(false)
    setRetrieveError(null)
    setRetrieveCitations([])
    setIsExpanded(Boolean(documentLayout?.isExpanded))
    setPanelWidthPxState(typeof documentLayout?.panelWidthPx === "number" ? documentLayout.panelWidthPx : null)
    setChunkQuery("")
    setMatchCursor(0)
    setServerMatchIds([])
    setServerMatchTotal(0)
    setServerMatchTruncated(false)
    setServerMatchLoading(false)
    pendingChunksScrollRestoreRef.current =
      typeof documentLayout?.chunksScrollTop === "number" ? documentLayout.chunksScrollTop : 0
    pendingTextScrollRestoreRef.current =
      typeof documentLayout?.textScrollTop === "number" ? documentLayout.textScrollTop : 0
    matchRequestSeqRef.current += 1

    const raf = globalThis.window.requestAnimationFrame(() => {
      const top = pendingChunksScrollRestoreRef.current ?? 0
      chunksListRef.current?.scrollTo({ top, left: 0, behavior: "auto" })
    })
    const prefetchedDoc = getPrefetchedDocument(documentId)
    if (prefetchedDoc) {
      setDoc(prefetchedDoc)
    }

    setIsLoading(!prefetchedDoc)
    documentApi
      .get(documentId, { includeChunks: false })
      .then((data) => {
        setDoc(data)
      })
      .catch((error: unknown) => reportClientError("Load document detail failed", error))
      .finally(() => setIsLoading(false))

    return () => globalThis.window.cancelAnimationFrame(raf)
  }, [documentId, documentLayout])

  React.useEffect(() => {
    const currentDocumentId = documentId
    return () => {
      if (!currentDocumentId) return
      flushPersistedLayoutPatch(currentDocumentId)
    }
  }, [documentId, flushPersistedLayoutPatch])

  React.useEffect(() => {
    return () => {
      flushPersistedLayoutPatch()
    }
  }, [flushPersistedLayoutPatch])

  React.useEffect(() => {
    if (!documentId) return

    let cancelled = false
    ;(async () => {
      try {
        const cached = await getDocContentFromCache(documentId)
        if (cancelled || !cached) return

        setParsedContent({
          document_id: documentId,
          available: true,
          markdown_content: cached.markdownContent || "",
          original_markdown_content: cached.originalMarkdownContent || "",
          persisted_meta: {},
          markdown_truncated: false,
          original_markdown_truncated: false,
          max_chars: 0,
        })
      } catch {
        // ignore cache errors
      }
    })()

    return () => {
      cancelled = true
    }
  }, [documentId])

  React.useEffect(() => {
    if (!documentId) return
    if (!highlightChunkId) {
      setHighlightChunkState(null)
      setHighlightChunkLoading(false)
      return
    }

    let cancelled = false
    const prefetchedChunk = getPrefetchedChunk(documentId, highlightChunkId)
    if (prefetchedChunk) {
      setHighlightChunkState(prefetchedChunk)
      setHighlightChunkLoading(false)
    } else {
      setHighlightChunkLoading(true)
    }
    documentApi
      .getChunk(documentId, highlightChunkId)
      .then((data) => {
        if (cancelled) return
        setHighlightChunkState(data)
      })
      .catch((err) => {
        if (cancelled) return
        reportClientError("Load highlighted chunk failed", err)
        setHighlightChunkState(null)
      })
      .finally(() => {
        if (cancelled) return
        setHighlightChunkLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [documentId, highlightChunkId])

  React.useEffect(() => {
    if (!documentId) return
    if (activeTab !== "text") return
    if (parsedContentServerKeyRef.current === documentId) return

    let cancelled = false
    setParsedContentError(null)
    setParsedContentLoading(true)

    documentApi
      .getParsedContent(documentId, { max_chars: 200_000 })
      .then((data) => {
        if (cancelled) return
        parsedContentServerKeyRef.current = documentId
        setParsedContent(data)
        if (data?.available) {
          detachPromise(
            saveDocContentToCache({
              id: documentId,
              markdownContent: data.markdown_content || "",
              originalMarkdownContent: data.original_markdown_content || "",
            })
          )
        }
      })
      .catch((err) => {
        if (cancelled) return
        reportClientError("Load parsed document content failed", err)
        setParsedContentError("加载解析文本失败")
      })
      .finally(() => {
        if (cancelled) return
        setParsedContentLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [documentId, activeTab])

  React.useEffect(() => {
    if (!documentId) return
    if (chunksLoaded) return
    const shouldLoadAll =
      (activeTab === "chunks" && (loadAllChunks || !highlightChunkId)) ||
      (activeTab === "text" && (loadAllChunks || !highlightChunkId))
    if (!shouldLoadAll) return

    setChunksLoading(true)
    let cancelled = false
    ;(async () => {
      const pageSize = 2000
      const all: DocumentChunk[] = []
      let total = 0

      for (let skip = 0; skip < 50_000; skip += pageSize) {
        const res = await documentApi.listChunks(documentId, { skip, limit: pageSize })
        if (cancelled) return
        total = res.total || 0
        all.push(...(res.items || []))
        setChunks([...all])
        if (!res.items?.length || (total > 0 && all.length >= total)) break
      }

      if (!cancelled) setChunksLoaded(true)
    })()
      .catch((error: unknown) => reportClientError("Load document chunks failed", error))
      .finally(() => {
        if (!cancelled) setChunksLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [documentId, activeTab, highlightChunkId, loadAllChunks, chunksLoaded])

  const highlightIndex = React.useMemo(() => {
    if (!highlightChunkId) return -1
    return chunks.findIndex((chunk) => chunk.id === highlightChunkId)
  }, [chunks, highlightChunkId])

  const textValue = React.useMemo(() => {
    if (!parsedContent?.available) return ""
    return textMode === "original"
      ? String(parsedContent.original_markdown_content || "")
      : String(parsedContent.markdown_content || "")
  }, [parsedContent, textMode])

  const textChunkItems = React.useMemo(() => {
    const base = (() => {
      if (chunksLoaded) return chunks
      if (highlightChunk) return [highlightChunk]
      return []
    })()

    return mapDocumentChunksToPreviewItems(base)
  }, [chunks, chunksLoaded, highlightChunk])

  const textActiveChunkIndex = React.useMemo(() => {
    if (!highlightChunk) return null
    const idx = textChunkItems.findIndex((item) => item.index === highlightChunk.chunk_index)
    return idx >= 0 ? idx : null
  }, [highlightChunk, textChunkItems])

  const resolvedPreviewAnchor = React.useMemo(
    () =>
      recoverDocumentPreviewAnchorFromChunkPositions(
        sanitizeDocumentPreviewAnchor({
          ...previewAnchor,
          pageNumber: previewAnchor?.pageNumber ?? highlightChunk?.page_number ?? undefined,
          searchText: previewAnchor?.searchText,
          bbox: previewAnchor?.bbox,
          bboxPageNumber: previewAnchor?.bboxPageNumber,
        }),
        highlightChunk,
        highlightRange
      ),
    [highlightChunk, highlightRange, previewAnchor]
  )

  React.useEffect(() => {
    if (!documentId) return
    persistDocumentLayout({ isExpanded }, true)
  }, [documentId, isExpanded, persistDocumentLayout])

  const setPanelWidthPx = React.useCallback(
    (nextWidthPx: number) => {
      if (!Number.isFinite(nextWidthPx)) return
      const width = Math.round(nextWidthPx)
      setPanelWidthPxState(width)
      persistDocumentLayout({ panelWidthPx: width }, true)
    },
    [persistDocumentLayout]
  )

  React.useEffect(() => {
    if (!documentId) return
    persistDocumentLayout({ textMode }, true)
  }, [documentId, textMode, persistDocumentLayout])

  React.useEffect(() => {
    if (!documentId) return
    const node = chunksListRef.current
    if (!node) return

    const handleScroll = () => {
      persistDocumentLayout({ chunksScrollTop: node.scrollTop })
    }

    node.addEventListener("scroll", handleScroll, { passive: true })
    return () => node.removeEventListener("scroll", handleScroll)
  }, [documentId, activeTab, isOpen, persistDocumentLayout])

  React.useEffect(() => {
    if (!documentId) return
    if (highlightChunkId && activeTab === "chunks") return
    const nextScrollTop = pendingChunksScrollRestoreRef.current
    const node = chunksListRef.current
    if (nextScrollTop == null || !node) return

    node.scrollTo({ top: nextScrollTop, left: 0, behavior: "auto" })
    const maxScrollableTop = Math.max(0, node.scrollHeight - node.clientHeight)
    if (nextScrollTop <= maxScrollableTop + 1 || nextScrollTop === 0) {
      pendingChunksScrollRestoreRef.current = null
    }
  }, [documentId, activeTab, chunks.length, chunksLoaded, highlightChunkId])

  React.useEffect(() => {
    if (!highlightChunkId || activeTab !== "chunks") return
    if (highlightIndex < 0) return
    rowVirtualizer.scrollToIndex(highlightIndex, { align: "center" })
  }, [highlightChunkId, activeTab, highlightIndex, rowVirtualizer])

  const localMatchChunkIds = React.useMemo(() => {
    const query = chunkQuery.trim().toLowerCase()
    if (!query) return []

    const ids: string[] = []
    for (const chunk of chunks) {
      const text = (chunk.content || "").toLowerCase()
      if (text.includes(query)) ids.push(chunk.id)
    }
    return ids
  }, [chunks, chunkQuery])

  const resetServerMatches = React.useCallback(() => {
    setServerMatchIds([])
    setServerMatchTotal(0)
    setServerMatchTruncated(false)
    setServerMatchLoading(false)
  }, [])

  React.useEffect(() => {
    const query = chunkQuery.trim()
    if (!documentId || !query) {
      resetServerMatches()
      matchRequestSeqRef.current += 1
      return
    }

    if (chunksLoaded) {
      resetServerMatches()
      matchRequestSeqRef.current += 1
      return
    }

    const seq = ++matchRequestSeqRef.current
    setServerMatchLoading(true)
    const loadServerMatches = async () => {
      try {
        const res = await documentApi.getChunkMatches(documentId, { q: query, limit: 5000 })
        if (seq !== matchRequestSeqRef.current) return
        const items = res?.items || []
        setServerMatchIds(mapChunkMatchIds(items))
        setServerMatchTotal(Number(res?.total) || 0)
        setServerMatchTruncated(Boolean(res?.truncated))
      } catch (err) {
        if (seq !== matchRequestSeqRef.current) return
        reportClientError("Load chunk search matches failed", err)
        setServerMatchIds([])
        setServerMatchTotal(0)
        setServerMatchTruncated(false)
      } finally {
        if (seq !== matchRequestSeqRef.current) return
        setServerMatchLoading(false)
      }
    }

    const timeoutId = globalThis.window.setTimeout(() => {
      detachPromise(loadServerMatches())
    }, 250)

    return () => globalThis.window.clearTimeout(timeoutId)
  }, [documentId, chunkQuery, chunksLoaded, resetServerMatches])

  const matchChunkIds = React.useMemo(() => {
    if (!chunkQuery.trim()) return []
    return chunksLoaded ? localMatchChunkIds : serverMatchIds
  }, [chunkQuery, chunksLoaded, localMatchChunkIds, serverMatchIds])

  const chunkSearchPlaceholder = React.useMemo(() => {
    if (serverMatchLoading) return "搜索中…"
    if (chunksLoaded) return "搜索切片内容…"
    return "搜索切片内容…（无需加载全部切片）"
  }, [chunksLoaded, serverMatchLoading])

  const chunkMatchSummary = React.useMemo(() => {
    if (!chunkQuery.trim()) return "—"
    if (serverMatchLoading) return "…"
    if (matchChunkIds.length) {
      return `${matchCursor + 1}/${chunksLoaded ? matchChunkIds.length : serverMatchTotal || matchChunkIds.length}${!chunksLoaded && serverMatchTruncated ? "+" : ""}`
    }
    return "0/0"
  }, [chunkQuery, chunksLoaded, matchChunkIds.length, matchCursor, serverMatchLoading, serverMatchTotal, serverMatchTruncated])

  const handleSelectTextChunkIndex = React.useCallback(
    (chunkIndex: number) => {
      const target =
        chunks.find((chunk) => chunk.chunk_index === chunkIndex) ||
        (highlightChunk?.chunk_index === chunkIndex ? highlightChunk : null)
      if (target) setHighlightChunk(target.id)
    },
    [chunks, highlightChunk, setHighlightChunk]
  )

  React.useEffect(() => {
    setMatchCursor(0)
  }, [chunkQuery])

  const rawFileUrl = React.useMemo(() => {
    if (!documentId) return null
    return `${API_V1_BASE_URL}/documents/${documentId}/download`
  }, [documentId])

  const rawDownloadUrl = React.useMemo(() => {
    if (!documentId) return null
    const url = new URL(`${API_V1_BASE_URL}/documents/${documentId}/download`)
    url.searchParams.set("inline", "0")
    return url.toString()
  }, [documentId])

  const shouldResolveDownloadUrl = isOpen && activeTab === "preview"
  const fileUrl = rawFileUrl
  const downloadUrl = useResolvedAuthAssetUrl(rawDownloadUrl, {
    enabled: shouldResolveDownloadUrl,
  })

  const buildChunkLink = React.useCallback(
    (chunkId: string, range?: { start?: number | null; end?: number | null }) => {
      if (!documentId) return ""
      try {
        const url = new URL("/", globalThis.window.location.origin)
        url.searchParams.set("doc", documentId)
        url.searchParams.set("chunk", chunkId)
        const start = range?.start
        const end = range?.end
        if (
          typeof start === "number" &&
          Number.isFinite(start) &&
          typeof end === "number" &&
          Number.isFinite(end) &&
          end > start
        ) {
          url.searchParams.set("start", String(Math.trunc(start)))
          url.searchParams.set("end", String(Math.trunc(end)))
        }
        return url.toString()
      } catch {
        return ""
      }
    },
    [documentId]
  )

  const copyText = React.useCallback(async (text: string, okMsg: string) => {
    const value = (text || "").trim()
    if (!value) return

    try {
      if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
        throw new Error("Clipboard API unavailable")
      }
      await navigator.clipboard.writeText(value)
      toast.success(okMsg)
    } catch (error) {
      reportClientError("Copy document viewer text failed", error)
      toast.error("复制失败")
    }
  }, [])

  const copyChunkContent = React.useCallback(
    (content: string) => {
      detachPromise(copyText(content, "已复制切片内容"))
    },
    [copyText]
  )

  const copyChunkLink = React.useCallback(
    (chunk: DocumentChunk) => {
      detachPromise(
        copyText(
          buildChunkLink(chunk.id, {
            start: typeof chunk.start_char === "number" ? chunk.start_char : null,
            end: typeof chunk.end_char === "number" ? chunk.end_char : null,
          }),
          "已复制定位链接"
        )
      )
    },
    [buildChunkLink, copyText]
  )

  const canEditChunks = Boolean(doc && !["pending", "processing"].includes(String(doc.status || "").toLowerCase()))
  const canRerunRetrieve = Boolean(retrieveQuery.trim())

  const parseOptionalChunkNumber = React.useCallback((value: string) => {
    const text = (value || "").trim()
    if (!text) return undefined
    const next = Number(text)
    return Number.isFinite(next) ? Math.max(0, Math.trunc(next)) : undefined
  }, [])

  const runRetrievePreviewForQuery = React.useCallback(
    async (query: string) => {
      if (!documentId) return
      const normalized = query.trim()
      if (!normalized) return

      setRetrieveLoading(true)
      setRetrieveError(null)
      try {
        const res = await ragApi.retrievePreview({
          query: normalized,
          document_ids: [documentId],
          include_structure_trace: false,
        })
        const raw = Array.isArray(res?.citations) ? res.citations : []
        const items = raw.map(toCitation).filter(Boolean) as Citation[]
        setRetrieveCitations(items.filter((citation) => citation.document_id === documentId))
      } catch (err) {
        reportClientError("Run retrieve preview failed", err)
        setRetrieveError("检索测试失败，请稍后重试")
        setRetrieveCitations([])
      } finally {
        setRetrieveLoading(false)
      }
    },
    [documentId]
  )

  const openCreateChunk = React.useCallback(() => {
    setChunkEditorMode("create")
    setChunkEditorTarget(null)
    setChunkEditorContent("")
    setChunkEditorPageNumber("")
    setChunkEditorStartChar("")
    setChunkEditorEndChar("")
    setChunkEditorOpen(true)
    setActiveTab("chunks")
  }, [setActiveTab])

  const openEditChunk = React.useCallback(
    (chunk: DocumentChunk) => {
      setChunkEditorMode("edit")
      setChunkEditorTarget(chunk)
      setChunkEditorContent(chunk.content || "")
      setChunkEditorPageNumber(typeof chunk.page_number === "number" ? String(chunk.page_number) : "")
      setChunkEditorStartChar(typeof chunk.start_char === "number" ? String(chunk.start_char) : "")
      setChunkEditorEndChar(typeof chunk.end_char === "number" ? String(chunk.end_char) : "")
      setChunkEditorOpen(true)
      setActiveTab("chunks")
    },
    [setActiveTab]
  )

  const submitChunkEditor = React.useCallback(async (mode: "save" | "save_reembed" | "save_rerun" = "save") => {
    if (!documentId) return
    if (!canEditChunks) return

    const content = (chunkEditorContent || "").trim()
    if (!content) {
      toast.error("切片内容不能为空")
      return
    }

    const pageNumber = parseOptionalChunkNumber(chunkEditorPageNumber)
    const startChar = parseOptionalChunkNumber(chunkEditorStartChar)
    const endChar = parseOptionalChunkNumber(chunkEditorEndChar)
    if (startChar != null && endChar != null && endChar <= startChar) {
      toast.error("End Char 必须大于 Start Char")
      return
    }

    setChunkEditorSubmitting(true)
    try {
      let savedChunk: DocumentChunk | null = null
      if (chunkEditorMode === "create") {
        const created = await documentApi.createChunk(documentId, {
          content,
          page_number: pageNumber,
          start_char: startChar,
          end_char: endChar,
          metadata: {},
        })
        toast.success("切片已创建")

        if (!chunksLoaded) setLoadAllChunks(true)

        setChunks((prev) => [...prev, created])
        setDoc((prev) =>
          prev
            ? {
                ...prev,
                chunk_count: typeof prev.chunk_count === "number" ? prev.chunk_count + 1 : prev.chunk_count,
              }
            : prev
        )
        setHighlightChunk(created.id)
        savedChunk = created
      } else {
        const target = chunkEditorTarget
        if (!target) return
        const updated = await documentApi.updateChunk(documentId, target.id, {
          content,
          page_number: pageNumber,
          start_char: startChar,
          end_char: endChar,
        })
        toast.success("切片已更新")
        setChunks((prev) => prev.map((chunk) => (chunk.id === updated.id ? updated : chunk)))
        setHighlightChunkState((prev) => (prev?.id === updated.id ? updated : prev))
        setHighlightChunk(updated.id)
        savedChunk = updated
      }

      globalThis.window.requestAnimationFrame(() => rowVirtualizer.measure())
      setChunkEditorOpen(false)

      if (savedChunk && mode !== "save") {
        try {
          const res = await documentApi.reembedChunks(documentId, {
            chunk_ids: [savedChunk.id],
            include_disabled: Boolean(savedChunk.disabled_at),
          })
          toast.success(`已重新嵌入 ${res.reembedded} 个切片`)

          if (mode === "save_rerun") {
            const query = retrieveQuery.trim()
            if (query) {
              await runRetrievePreviewForQuery(query)
            } else {
              toast.message("已保存并重新嵌入；当前没有检索 query 可复跑")
            }
          }
        } catch (err) {
          reportClientError("Re-embed saved chunk failed", err)
          toast.error(formatApiError(err, "切片已保存，但后续重嵌入失败"))
        }
      }
    } catch (err) {
      reportClientError("Save chunk failed", err)
      toast.error(formatApiError(err, "切片保存失败"))
    } finally {
      setChunkEditorSubmitting(false)
    }
  }, [
    canEditChunks,
    chunkEditorContent,
    chunkEditorEndChar,
    chunkEditorMode,
    chunkEditorPageNumber,
    chunkEditorStartChar,
    chunkEditorTarget,
    chunksLoaded,
    documentId,
    parseOptionalChunkNumber,
    retrieveQuery,
    rowVirtualizer,
    runRetrievePreviewForQuery,
    setHighlightChunk,
  ])

  const deleteChunk = React.useCallback(
    async (chunk: DocumentChunk) => {
      if (!documentId) return
      if (!canEditChunks) return

      setChunkDeleteSubmitting(chunk.id)
      try {
        await documentApi.deleteChunk(documentId, chunk.id)
        toast.success("切片已删除")
        setChunks((prev) => prev.filter((item) => item.id !== chunk.id))
        setDoc((prev) =>
          prev
            ? {
                ...prev,
                chunk_count:
                  typeof prev.chunk_count === "number" ? Math.max(0, prev.chunk_count - 1) : prev.chunk_count,
              }
            : prev
        )
        if (highlightChunkId === chunk.id) {
          setHighlightChunk(null)
          setHighlightChunkState(null)
        }

        globalThis.window.requestAnimationFrame(() => rowVirtualizer.measure())
      } catch (err) {
        reportClientError("Delete chunk failed", err)
        toast.error(formatApiError(err, "切片删除失败"))
      } finally {
        setChunkDeleteSubmitting(null)
      }
    },
    [canEditChunks, documentId, highlightChunkId, rowVirtualizer, setHighlightChunk]
  )

  const handleDeleteChunk = React.useCallback(
    (chunk: DocumentChunk) => {
      detachPromise(deleteChunk(chunk))
    },
    [deleteChunk]
  )

  const runQaGeneration = React.useCallback(async () => {
    if (!documentId) return
    if (!canEditChunks) return

    setQaSubmitting(true)
    try {
      const res = await documentApi.generateQa(documentId, {
        num_pairs: Math.max(1, Math.trunc(Number(qaNumPairs) || 0)),
        replace_existing: Boolean(qaReplaceExisting),
        prefer_llm: Boolean(qaPreferLlm),
        max_source_chars: Math.max(500, Math.trunc(Number(qaMaxSourceChars) || 0)),
        preview_pairs: 5,
      })
      setQaLastResult(res)
      toast.success(`Q&A: +${res.created} (-${res.deleted}) [${res.mode}]`)

      setDoc((prev) =>
        prev
          ? {
              ...prev,
              chunk_count: (prev.chunk_count || 0) + (res.created || 0) - (res.deleted || 0),
            }
          : prev
      )

      setLoadAllChunks(true)
      setChunksLoaded(false)
      setChunks([])

      if (res.chunk_ids?.length) {
        setHighlightChunk(res.chunk_ids[0])
      }
    } catch (err) {
      reportClientError("Generate document Q&A failed", err)
      toast.error(formatApiError(err, "问答生成失败"))
    } finally {
      setQaSubmitting(false)
    }
  }, [canEditChunks, documentId, qaMaxSourceChars, qaNumPairs, qaPreferLlm, qaReplaceExisting, setHighlightChunk])

  const canInlinePreview = (doc?.file_type || "").toLowerCase() === "pdf"

  const jumpToMatch = React.useCallback(
    (nextIndex: number) => {
      if (!matchChunkIds.length) return
      const clamped = ((nextIndex % matchChunkIds.length) + matchChunkIds.length) % matchChunkIds.length
      setMatchCursor(clamped)
      setActiveTab("chunks")
      setHighlightChunk(matchChunkIds[clamped] || null)
    },
    [matchChunkIds, setActiveTab, setHighlightChunk]
  )

  const handleChunkSearchKeyDown = React.useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (event.key !== "Enter") return
      event.preventDefault()
      if (!matchChunkIds.length) return

      const currentId = matchChunkIds[matchCursor]
      if (currentId && highlightChunkId === currentId) {
        jumpToMatch(matchCursor + (event.shiftKey ? -1 : 1))
        return
      }

      jumpToMatch(matchCursor)
    },
    [highlightChunkId, jumpToMatch, matchChunkIds, matchCursor]
  )

  React.useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      const noModifier = !event.metaKey && !event.ctrlKey && !event.altKey
      const typingTarget = isTypingTarget(event.target)

      if (event.key === "Escape") {
        if (activeTab === "chunks" && chunkQuery.trim()) {
          event.preventDefault()
          setChunkQuery("")
          return
        }
        event.preventDefault()
        closeDocument()
        return
      }

      const isFind = (event.key === "f" || event.key === "F") && (event.metaKey || event.ctrlKey)
      if (isFind && activeTab === "chunks") {
        event.preventDefault()
        chunkSearchRef.current?.focus()
        chunkSearchRef.current?.select()
        return
      }

      if (activeTab !== "chunks" || !noModifier) return

      if (event.key === "/" && !typingTarget) {
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
      if (navigation.type === "match") {
        jumpToMatch(navigation.nextIndex)
        return
      }

      const nextChunk = chunks[navigation.nextIndex]
      if (nextChunk) {
        setActiveTab("chunks")
        setHighlightChunk(nextChunk.id)
      }
    }

    globalThis.window.addEventListener("keydown", onKeyDown)
    return () => globalThis.window.removeEventListener("keydown", onKeyDown)
  }, [isOpen, activeTab, chunkQuery, closeDocument, matchChunkIds.length, matchCursor, chunks, highlightIndex, jumpToMatch, setActiveTab, setHighlightChunk])

  const runRetrievePreview = React.useCallback(async () => {
    const query = retrieveQuery.trim()
    if (!query) return
    await runRetrievePreviewForQuery(query)
  }, [retrieveQuery, runRetrievePreviewForQuery])

  const handleTextScrollTopChange = React.useCallback(
    (textScrollTop: number) => {
      pendingTextScrollRestoreRef.current = textScrollTop
      persistDocumentLayout({ textScrollTop })
    },
    [persistDocumentLayout]
  )

  const handleChunkEditorOpenChange = React.useCallback((open: boolean) => {
    if (!open) {
      setChunkEditorOpen(false)
      setChunkEditorSubmitting(false)
      return
    }
    setChunkEditorOpen(true)
  }, [])

  const handleQaDialogOpenChange = React.useCallback((open: boolean) => {
    setQaDialogOpen(open)
    if (open) setQaLastResult(null)
  }, [])

  const handleActiveTabChange = React.useCallback(
    (value: string) => {
      if (isDocumentViewTab(value)) setActiveTab(value)
    },
    [setActiveTab]
  )

  const jumpToSource = React.useCallback(() => {
    if (sourceContext?.kind !== 'chat-citation') return

    globalEventBus.emit('chat:focus-message', {
      messageId: sourceContext.messageId,
      documentId: sourceContext.documentId,
      chunkId: sourceContext.chunkId ?? null,
    })
  }, [sourceContext])

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
    closeDocument,
    copyChunkContent,
    copyChunkLink,
    doc,
    documentId,
    downloadUrl,
    fileUrl,
    handleActiveTabChange,
    handleChunkEditorOpenChange,
    handleChunkSearchKeyDown,
    handleDeleteChunk,
    handleQaDialogOpenChange,
    handleSelectTextChunkIndex,
    handleTextScrollTopChange,
    highlightChunk,
    highlightChunkId,
    highlightChunkLoading,
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
    qaMaxSourceChars,
    qaNumPairs,
    qaPreferLlm,
    qaReplaceExisting,
    qaSubmitting,
    rawFileUrl,
    retrieveCitations,
    retrieveError,
    retrieveLoading,
    retrieveQuery,
    rowVirtualizer,
    runQaGeneration,
    runRetrievePreview,
    serverMatchTruncated,
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
    setQaMaxSourceChars,
    setQaNumPairs,
    setQaPreferLlm,
    setQaReplaceExisting,
    setRetrieveCitations,
    setRetrieveError,
    setRetrieveQuery,
    setTextMode,
    submitChunkEditor,
    textActiveChunkIndex,
    textChunkItems,
    textInitialScrollTop: pendingTextScrollRestoreRef.current ?? 0,
    textMode,
    textValue,
  }
}

export type DocumentViewerPanelState = ReturnType<typeof useDocumentViewerPanelState>
