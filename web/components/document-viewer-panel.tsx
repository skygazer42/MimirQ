"use client"

import * as React from "react"
import { Loader2 } from "lucide-react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { cn, detachPromise } from '@/lib/utils'
import { useResolvedAuthAssetUrl } from "@/components/auth-image"
import { ChunksTabPanel } from "@/components/document-viewer/chunks-tab-panel"
import { DocumentViewerHeader } from "@/components/document-viewer/document-viewer-header"
import { useDocumentView } from "@/store/document-view"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { documentApi, ragApi } from "@/lib/api"
import { API_V1_BASE_URL } from "@/lib/env"
import type { Citation, Document, DocumentChunk, DocumentParsedContentResponse, DocumentQAGenerateResponse } from "@/types"
import { ChunkEditorDialog } from "@/components/document-viewer/chunk-editor-dialog"
import { FloatingMenu } from "@/components/document-viewer/floating-menu"
import { PreviewTabPanel } from "@/components/document-viewer/preview-tab-panel"
import { QAGenerationDialog } from "@/components/document-viewer/qa-generation-dialog"
import { TextTabPanel } from "@/components/document-viewer/text-tab-panel"
import { mapDocumentChunksToPreviewItems } from "@/lib/document-chunks"
import { getDocContentFromCache, saveDocContentToCache } from "@/lib/doc-content-cache"
import { formatApiError } from "@/lib/api-errors"
import { toast } from "sonner"

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function toFiniteNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function toCitation(value: unknown): Citation | null {
  if (!isRecord(value)) return null
  const document_id = typeof value.document_id === "string" ? value.document_id : ""
  const document_name = typeof value.document_name === "string" ? value.document_name : ""
  const chunk_content = typeof value.chunk_content === "string" ? value.chunk_content : ""
  const relevance_score = toFiniteNumber(value.relevance_score) ?? 0
  if (!document_id || !document_name) return null
  const matched_terms = Array.isArray(value.matched_terms)
    ? value.matched_terms.filter((item): item is string => typeof item === "string")
    : undefined
  const chunk_id = typeof value.chunk_id === "string" ? value.chunk_id : undefined
  const page_number = toFiniteNumber(value.page_number)
  const chunk_index = toFiniteNumber(value.chunk_index)
  const start_char = toFiniteNumber(value.start_char)
  const end_char = toFiniteNumber(value.end_char)

  return {
    document_id,
    document_name,
    chunk_content,
    relevance_score,
    ...(chunk_id ? { chunk_id } : {}),
    ...(matched_terms?.length ? { matched_terms } : {}),
    ...(page_number !== undefined ? { page_number } : {}),
    ...(chunk_index !== undefined ? { chunk_index } : {}),
    ...(start_char !== undefined ? { start_char } : {}),
    ...(end_char !== undefined ? { end_char } : {}),
  }
}

export function DocumentViewerPanel() {
  const { isOpen, documentId, highlightChunkId, highlightRange, closeDocument, activeTab, setActiveTab, setHighlightChunk } = useDocumentView()
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
  const chunksListRef = React.useRef<HTMLDivElement>(null)
  const chunkSearchRef = React.useRef<HTMLInputElement>(null)
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

  // Load document metadata (lazy-load chunks separately).
  React.useEffect(() => {
    if (!documentId) return
    parsedContentServerKeyRef.current = null
    setDoc(null)
    setChunks([])
    setChunksLoaded(false)
    setLoadAllChunks(false)
    setHighlightChunkState(null)
    setHighlightChunkLoading(false)
    setParsedContent(null)
    setParsedContentLoading(false)
    setParsedContentError(null)
    setTextMode("cleaned")
    setRetrieveQuery("")
    setRetrieveLoading(false)
    setRetrieveError(null)
    setRetrieveCitations([])
    setChunkQuery("")
    setMatchCursor(0)
    setServerMatchIds([])
    setServerMatchTotal(0)
    setServerMatchTruncated(false)
    setServerMatchLoading(false)
    matchRequestSeqRef.current += 1

    // Reset scroll position when switching documents so the panel doesn't open "half scrolled".
    const raf = globalThis.window.requestAnimationFrame(() => {
      chunksListRef.current?.scrollTo({ top: 0, left: 0, behavior: "auto" })
    })

    setIsLoading(true)
    documentApi.get(documentId, { includeChunks: false })
      .then(data => {
        setDoc(data)
      })
      .catch(console.error)
      .finally(() => setIsLoading(false))

    return () => globalThis.window.cancelAnimationFrame(raf)
  }, [documentId])

  // Best-effort cache: show parsed markdown quickly (used by the "text" tab).
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

  // If a citation requests a highlight, fetch just that chunk first (fast path).
  React.useEffect(() => {
    if (!documentId) return
    if (!highlightChunkId) {
      setHighlightChunkState(null)
      setHighlightChunkLoading(false)
      return
    }

    let cancelled = false
    setHighlightChunkLoading(true)
    documentApi
      .getChunk(documentId, highlightChunkId)
      .then((data) => {
        if (cancelled) return
        setHighlightChunkState(data)
      })
      .catch((err) => {
        if (cancelled) return
        console.error(err)
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

  // Load parsed markdown on demand (text tab).
  React.useEffect(() => {
    if (!documentId) return
    if (activeTab !== "text") return

    // Avoid re-fetching on tab switches once we have a server response.
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
          detachPromise(saveDocContentToCache({
            id: documentId,
            markdownContent: data.markdown_content || "",
            originalMarkdownContent: data.original_markdown_content || "",
          }))
        }
      })
      .catch((err) => {
        if (cancelled) return
        console.error(err)
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

  // Load chunks on demand (when user opens the "chunks" tab or a citation requests a highlight).
  React.useEffect(() => {
    if (!documentId) return
    if (chunksLoaded || chunksLoading) return
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
      .catch(console.error)
      .finally(() => {
        if (!cancelled) setChunksLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [documentId, activeTab, highlightChunkId, loadAllChunks, chunksLoaded, chunksLoading])

  const highlightIndex = React.useMemo(() => {
    if (!highlightChunkId) return -1
    return chunks.findIndex((c) => c.id === highlightChunkId)
  }, [chunks, highlightChunkId])

  const textValue = React.useMemo(() => {
    if (!parsedContent?.available) return ""
    return textMode === "original"
      ? String(parsedContent.original_markdown_content || "")
      : String(parsedContent.markdown_content || "")
  }, [parsedContent, textMode])

  const textChunkItems = React.useMemo(() => {
    // Only show the active chunk when we haven't loaded the full chunk list yet.
    const base = (() => {
    if (chunksLoaded) {
        return chunks;
    }
    else if (highlightChunk) {
            return [highlightChunk];
        }
        else {
            return [];
        }
})()
    return mapDocumentChunksToPreviewItems(base)
  }, [chunks, chunksLoaded, highlightChunk])

  const textActiveChunkIndex = React.useMemo(() => {
    if (!highlightChunk) return null
    const idx = textChunkItems.findIndex((it) => it.index === highlightChunk.chunk_index)
    return idx >= 0 ? idx : null
  }, [highlightChunk, textChunkItems])

  // Keyboard UX: Esc closes (or clears search first); Cmd/Ctrl+F focuses chunk search.
  React.useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (activeTab === "chunks" && chunkQuery.trim()) {
          e.preventDefault()
          setChunkQuery("")
          return
        }
        e.preventDefault()
        closeDocument()
        return
      }
      const isFind = (e.key === "f" || e.key === "F") && (e.metaKey || e.ctrlKey)
      if (isFind && activeTab === "chunks") {
        e.preventDefault()
        chunkSearchRef.current?.focus()
        chunkSearchRef.current?.select()
      }
    }
    globalThis.window.addEventListener("keydown", onKeyDown)
    return () => globalThis.window.removeEventListener("keydown", onKeyDown)
  }, [isOpen, activeTab, chunkQuery, closeDocument])

  // Scroll to highlighted chunk
  React.useEffect(() => {
    if (!highlightChunkId || activeTab !== 'chunks') return
    if (highlightIndex < 0) return
    // Virtual list: scroll by index (ensures the row is rendered).
    rowVirtualizer.scrollToIndex(highlightIndex, { align: "center" })
  }, [highlightChunkId, activeTab, highlightIndex, rowVirtualizer])

  const localMatchChunkIds = React.useMemo(() => {
    const q = chunkQuery.trim().toLowerCase()
    if (!q) return []
    const ids: string[] = []
    for (const c of chunks) {
      const text = (c.content || "").toLowerCase()
      if (text.includes(q)) ids.push(c.id)
    }
    return ids
  }, [chunks, chunkQuery])

  // When we haven't loaded the full chunk list, use a lightweight server search
  // (IDs + indices) to support "find in document" without pulling huge payloads.
  React.useEffect(() => {
    const q = chunkQuery.trim()
    if (!documentId || !q) {
      setServerMatchIds([])
      setServerMatchTotal(0)
      setServerMatchTruncated(false)
      setServerMatchLoading(false)
      matchRequestSeqRef.current += 1
      return
    }

    if (chunksLoaded) {
      // Prefer local matching once full content is loaded (enables in-list highlighting).
      setServerMatchIds([])
      setServerMatchTotal(0)
      setServerMatchTruncated(false)
      setServerMatchLoading(false)
      matchRequestSeqRef.current += 1
      return
    }

    const seq = ++matchRequestSeqRef.current
    setServerMatchLoading(true)
    const t = globalThis.window.setTimeout(() => {
      documentApi
        .getChunkMatches(documentId, { q, limit: 5000 })
        .then((res) => {
          if (seq !== matchRequestSeqRef.current) return
          const items = res?.items || []
          setServerMatchIds(items.map((it) => it.id))
          setServerMatchTotal(Number(res?.total) || 0)
          setServerMatchTruncated(Boolean(res?.truncated))
        })
        .catch((err) => {
          if (seq !== matchRequestSeqRef.current) return
          console.error(err)
          setServerMatchIds([])
          setServerMatchTotal(0)
          setServerMatchTruncated(false)
        })
        .finally(() => {
          if (seq !== matchRequestSeqRef.current) return
          setServerMatchLoading(false)
        })
    }, 250)

    return () => globalThis.window.clearTimeout(t)
  }, [documentId, chunkQuery, chunksLoaded])

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
      return `${matchCursor + 1}/${chunksLoaded ? matchChunkIds.length : (serverMatchTotal || matchChunkIds.length)}${!chunksLoaded && serverMatchTruncated ? "+" : ""}`
    }
    return "0/0"
  }, [chunkQuery, chunksLoaded, matchChunkIds.length, matchCursor, serverMatchLoading, serverMatchTotal, serverMatchTruncated])

  const handleSelectTextChunkIndex = React.useCallback((chunkIndex: number) => {
    const target = chunks.find((c) => c.chunk_index === chunkIndex) || (highlightChunk?.chunk_index === chunkIndex ? highlightChunk : null)
    if (target) setHighlightChunk(target.id)
  }, [chunks, highlightChunk, setHighlightChunk])

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
  const fileUrl = useResolvedAuthAssetUrl(rawFileUrl)
  const downloadUrl = useResolvedAuthAssetUrl(rawDownloadUrl)

  const buildChunkLink = React.useCallback((chunkId: string, range?: { start?: number | null; end?: number | null }) => {
    if (!documentId) return ""
    try {
      const url = new URL("/", globalThis.window.location.origin)
      url.searchParams.set("doc", documentId)
      url.searchParams.set("chunk", chunkId)
      const start = range?.start
      const end = range?.end
      if (typeof start === "number" && Number.isFinite(start) && typeof end === "number" && Number.isFinite(end) && end > start) {
        url.searchParams.set("start", String(Math.trunc(start)))
        url.searchParams.set("end", String(Math.trunc(end)))
      }
      return url.toString()
    } catch {
      return ""
    }
  }, [documentId])

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
      console.error(error)
      toast.error("复制失败")
    }
  }, [])

  const copyChunkContent = React.useCallback((content: string) => {
    detachPromise(copyText(content, "已复制切片内容"))
  }, [copyText])

  const copyChunkLink = React.useCallback((chunk: DocumentChunk) => {
    detachPromise(copyText(
      buildChunkLink(chunk.id, {
        start: typeof chunk.start_char === "number" ? chunk.start_char : null,
        end: typeof chunk.end_char === "number" ? chunk.end_char : null,
      }),
      "已复制定位链接"
    ))
  }, [buildChunkLink, copyText])

  const canEditChunks = Boolean(doc && !["pending", "processing"].includes(String(doc.status || "").toLowerCase()))

  const openCreateChunk = React.useCallback(() => {
    setChunkEditorMode("create")
    setChunkEditorTarget(null)
    setChunkEditorContent("")
    setChunkEditorPageNumber("")
    setChunkEditorOpen(true)
    setActiveTab("chunks")
  }, [setActiveTab])

  const openEditChunk = React.useCallback((chunk: DocumentChunk) => {
    setChunkEditorMode("edit")
    setChunkEditorTarget(chunk)
    setChunkEditorContent(chunk.content || "")
    setChunkEditorPageNumber(typeof chunk.page_number === "number" ? String(chunk.page_number) : "")
    setChunkEditorOpen(true)
    setActiveTab("chunks")
  }, [setActiveTab])

  const submitChunkEditor = React.useCallback(async () => {
    if (!documentId) return
    if (!canEditChunks) return

    const content = (chunkEditorContent || "").trim()
    if (!content) {
      toast.error("切片内容不能为空")
      return
    }

    const pageText = (chunkEditorPageNumber || "").trim()
    const pageNumber =
      pageText && Number.isFinite(Number(pageText)) ? Math.max(0, Math.trunc(Number(pageText))) : undefined

    setChunkEditorSubmitting(true)
    try {
      if (chunkEditorMode === "create") {
        const created = await documentApi.createChunk(documentId, {
          content,
          page_number: pageNumber,
          metadata: {},
        })
        toast.success("切片已创建")

        // If we haven't loaded all chunks, switch to full load so the new chunk can be discovered/browsed.
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
      } else {
        const target = chunkEditorTarget
        if (!target) return
        const updated = await documentApi.updateChunk(documentId, target.id, { content, page_number: pageNumber })
        toast.success("切片已更新")
        setChunks((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
        setHighlightChunkState((prev) => (prev?.id === updated.id ? updated : prev))
      }

      // Re-measure virtualization after content changes (best-effort).
      globalThis.window.requestAnimationFrame(() => rowVirtualizer.measure())

      setChunkEditorOpen(false)
    } catch (err) {
      console.error(err)
      toast.error(formatApiError(err, "切片保存失败"))
    } finally {
      setChunkEditorSubmitting(false)
    }
  }, [
    canEditChunks,
    chunkEditorContent,
    chunkEditorMode,
    chunkEditorPageNumber,
    chunkEditorTarget,
    chunksLoaded,
    documentId,
    rowVirtualizer,
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
        setChunks((prev) => prev.filter((c) => c.id !== chunk.id))
        setDoc((prev) =>
          prev
            ? {
                ...prev,
                chunk_count: typeof prev.chunk_count === "number" ? Math.max(0, prev.chunk_count - 1) : prev.chunk_count,
              }
            : prev
        )
        if (highlightChunkId === chunk.id) {
          setHighlightChunk(null)
          setHighlightChunkState(null)
        }

        globalThis.window.requestAnimationFrame(() => rowVirtualizer.measure())
      } catch (err) {
        console.error(err)
        toast.error(formatApiError(err, "切片删除失败"))
      } finally {
        setChunkDeleteSubmitting(null)
      }
    },
    [canEditChunks, documentId, highlightChunkId, rowVirtualizer, setHighlightChunk]
  )

  const handleDeleteChunk = React.useCallback((chunk: DocumentChunk) => {
    detachPromise(deleteChunk(chunk))
  }, [deleteChunk])

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

      // Refresh chunk list (best-effort) so the new QA chunks are visible.
      setLoadAllChunks(true)
      setChunksLoaded(false)
      setChunks([])

      if (res.chunk_ids?.length) {
        setHighlightChunk(res.chunk_ids[0])
      }
    } catch (err) {
      console.error(err)
      toast.error(formatApiError(err, "问答生成失败"))
    } finally {
      setQaSubmitting(false)
    }
  }, [canEditChunks, documentId, qaMaxSourceChars, qaNumPairs, qaPreferLlm, qaReplaceExisting, setHighlightChunk])

  const canInlinePreview = (doc?.file_type || "").toLowerCase() === "pdf"

  const jumpToMatch = React.useCallback((nextIndex: number) => {
    if (!matchChunkIds.length) return
    const clamped = ((nextIndex % matchChunkIds.length) + matchChunkIds.length) % matchChunkIds.length
    setMatchCursor(clamped)
    setActiveTab("chunks")
    setHighlightChunk(matchChunkIds[clamped] || null)
  }, [matchChunkIds, setActiveTab, setHighlightChunk])

  const handleChunkSearchKeyDown = React.useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter") return
    e.preventDefault()
    if (!matchChunkIds.length) return

    const currentId = matchChunkIds[matchCursor]
    if (currentId && highlightChunkId === currentId) {
      jumpToMatch(matchCursor + (e.shiftKey ? -1 : 1))
      return
    }

    jumpToMatch(matchCursor)
  }, [highlightChunkId, jumpToMatch, matchChunkIds, matchCursor])

  const runRetrievePreview = React.useCallback(async () => {
    if (!documentId) return
    const q = retrieveQuery.trim()
    if (!q) return

    setRetrieveLoading(true)
    setRetrieveError(null)
    try {
      const res = await ragApi.retrievePreview({ query: q, document_ids: [documentId] })
      const raw = Array.isArray(res?.citations) ? res.citations : []
      const items = raw.map(toCitation).filter(Boolean) as Citation[]
      setRetrieveCitations(items.filter((c) => c.document_id === documentId))
    } catch (err) {
      console.error(err)
      setRetrieveError("检索测试失败，请稍后重试")
      setRetrieveCitations([])
    } finally {
      setRetrieveLoading(false)
    }
  }, [documentId, retrieveQuery])

  if (!isOpen) return null

  return (
    <>
    <FloatingMenu />
    <ChunkEditorDialog
      open={chunkEditorOpen}
      mode={chunkEditorMode}
      target={chunkEditorTarget}
      content={chunkEditorContent}
      pageNumber={chunkEditorPageNumber}
      submitting={chunkEditorSubmitting}
      canEditChunks={canEditChunks}
      onOpenChange={(open) => {
        if (!open) {
          setChunkEditorOpen(false)
          setChunkEditorSubmitting(false)
          return
        }
        setChunkEditorOpen(true)
      }}
      onContentChange={setChunkEditorContent}
      onPageNumberChange={setChunkEditorPageNumber}
      onSubmit={() => detachPromise(submitChunkEditor())}
    />
    <QAGenerationDialog
      open={qaDialogOpen}
      qaNumPairs={qaNumPairs}
      qaMaxSourceChars={qaMaxSourceChars}
      qaReplaceExisting={qaReplaceExisting}
      qaPreferLlm={qaPreferLlm}
      qaSubmitting={qaSubmitting}
      qaLastResult={qaLastResult}
      canEditChunks={canEditChunks}
      documentId={documentId}
      onOpenChange={(open) => {
        setQaDialogOpen(open)
        if (open) setQaLastResult(null)
      }}
      onNumPairsChange={setQaNumPairs}
      onMaxSourceCharsChange={setQaMaxSourceChars}
      onReplaceExistingChange={setQaReplaceExisting}
      onPreferLlmChange={setQaPreferLlm}
      onSubmit={() => detachPromise(runQaGeneration())}
    />
	    <div 
	        className={cn(
	            "fixed inset-y-0 right-0 z-50 flex flex-col bg-background border-l border-border shadow-strong",
	           // Keep width aligned with AppFrame's right padding:
	           // - md: 40vw
	           // - lg: fixed 500px
	           // - xl+: 40vw
	           isExpanded ? "w-full md:w-[80vw]" : "w-full md:w-[40vw] lg:w-[500px] xl:w-[40vw]"
	        )}
	    >
      <DocumentViewerHeader
        filename={doc?.filename}
        chunkCount={doc?.chunk_count ?? chunks.length}
        isExpanded={isExpanded}
        downloadUrl={downloadUrl}
        onToggleExpanded={() => setIsExpanded(!isExpanded)}
        onClose={closeDocument}
      />

      {/* Main Content */}
      <div className="flex-1 overflow-hidden flex flex-col">
         <Tabs
           value={activeTab}
           onValueChange={(v) => setActiveTab(v as "preview" | "text" | "chunks")}
           className="flex-1 flex flex-col"
         >
            <div className="px-4 border-b border-border bg-background">
                <TabsList className="w-full justify-start h-10 bg-transparent p-0 gap-6">
                    <TabsTrigger 
                        value="preview" 
                        className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent px-2 font-medium"
                    >
                        原文
                    </TabsTrigger>
                    <TabsTrigger 
                        value="text" 
                        className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent px-2 font-medium"
                    >
                        文本定位
                    </TabsTrigger>
                    <TabsTrigger 
                        value="chunks" 
                        className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent px-2 font-medium"
                    >
                        智能切片
                    </TabsTrigger>
                </TabsList>
            </div>

            <TabsContent value="preview" className="flex-1 m-0 h-full bg-muted/30 dark:bg-muted/20 relative">
              <PreviewTabPanel
                isLoading={isLoading}
                doc={doc}
                canInlinePreview={canInlinePreview}
                fileUrl={fileUrl}
                rawFileUrl={rawFileUrl}
                downloadUrl={downloadUrl}
                onViewChunks={() => setActiveTab("chunks")}
              />
            </TabsContent>

            <TabsContent value="text" className="flex-1 m-0 h-full overflow-hidden">
              <TextTabPanel
                textMode={textMode}
                highlightChunkId={highlightChunkId}
                loadAllChunks={loadAllChunks}
                chunksLoaded={chunksLoaded}
                chunksLoading={chunksLoading}
                retrieveQuery={retrieveQuery}
                retrieveLoading={retrieveLoading}
                retrieveError={retrieveError}
                retrieveCitations={retrieveCitations}
                parsedContent={parsedContent}
                parsedContentLoading={parsedContentLoading}
                parsedContentError={parsedContentError}
                textValue={textValue}
                textChunkItems={textChunkItems}
                textActiveChunkIndex={textActiveChunkIndex}
                highlightRange={highlightRange ?? null}
                onTextModeChange={setTextMode}
                onClearHighlight={() => setHighlightChunk(null)}
                onLoadAllChunks={() => setLoadAllChunks(true)}
                onRetrieveQueryChange={setRetrieveQuery}
                onRunRetrieve={() => detachPromise(runRetrievePreview())}
                onClearRetrieve={() => {
                  setRetrieveCitations([])
                  setRetrieveError(null)
                }}
                onSelectRetrieveChunk={(chunkId) => {
                  setActiveTab("text")
                  setHighlightChunk(chunkId)
                }}
                onSelectChunkIndex={handleSelectTextChunkIndex}
                onGoToChunks={() => setActiveTab("chunks")}
                onGoToPreview={() => setActiveTab("preview")}
              />
            </TabsContent>

            <TabsContent value="chunks" className="flex-1 m-0 h-full overflow-hidden">
                 <ChunksTabPanel
                   chunkSearchRef={chunkSearchRef}
                   chunksListRef={chunksListRef}
                   rowVirtualizer={rowVirtualizer}
                   chunkQuery={chunkQuery}
                   searchPlaceholder={chunkSearchPlaceholder}
                   matchSummary={chunkMatchSummary}
                   canJumpMatches={Boolean(matchChunkIds.length)}
                   canEditChunks={canEditChunks}
                   serverMatchTruncatedHint={Boolean(!chunksLoaded && chunkQuery.trim() && serverMatchTruncated)}
                   highlightChunkId={highlightChunkId}
                   loadAllChunks={loadAllChunks}
                   chunksLoaded={chunksLoaded}
                   chunksLoading={chunksLoading}
                   highlightChunkLoading={highlightChunkLoading}
                   highlightChunk={highlightChunk}
                   chunkEditorSubmitting={chunkEditorSubmitting}
                   chunkDeleteSubmitting={chunkDeleteSubmitting}
                   matchCursor={matchCursor}
                   chunks={chunks}
                   onChunkQueryChange={setChunkQuery}
                   onSearchKeyDown={handleChunkSearchKeyDown}
                   onJumpToMatch={jumpToMatch}
                   onOpenCreateChunk={openCreateChunk}
                   onOpenQaDialog={() => setQaDialogOpen(true)}
                   onClearHighlight={() => setHighlightChunk(null)}
                   onLoadAllChunks={() => setLoadAllChunks(true)}
                   onCopyContent={copyChunkContent}
                   onCopyLink={copyChunkLink}
                   onEditChunk={openEditChunk}
                   onDeleteChunk={handleDeleteChunk}
                 />
            </TabsContent>
         </Tabs>
      </div>
    </div>
    </>
  )
}
