"use client"

import * as React from "react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { toast } from "sonner"

import { useResolvedAuthAssetUrl } from "@/components/auth-image"
import { documentApi, ragApi } from "@/lib/api"
import { formatApiError } from "@/lib/api-errors"
import { getDocContentFromCache, saveDocContentToCache } from "@/lib/doc-content-cache"
import { mapDocumentChunksToPreviewItems } from "@/lib/document-chunks"
import { API_V1_BASE_URL } from "@/lib/env"
import { detachPromise } from "@/lib/utils"
import { useDocumentView } from "@/store/document-view"
import type {
  Citation,
  Document,
  DocumentChunk,
  DocumentParsedContentResponse,
  DocumentQAGenerateResponse,
} from "@/types"

import { toCitation } from "./document-viewer-panel-utils"

function mapChunkMatchIds(items: ReadonlyArray<{ id: string }>): string[] {
  return items.map((item) => item.id)
}

export function useDocumentViewerPanelState() {
  const {
    isOpen,
    documentId,
    highlightChunkId,
    highlightRange,
    closeDocument,
    activeTab,
    setActiveTab,
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

    const raf = globalThis.window.requestAnimationFrame(() => {
      chunksListRef.current?.scrollTo({ top: 0, left: 0, behavior: "auto" })
    })

    setIsLoading(true)
    documentApi
      .get(documentId, { includeChunks: false })
      .then((data) => {
        setDoc(data)
      })
      .catch(console.error)
      .finally(() => setIsLoading(false))

    return () => globalThis.window.cancelAnimationFrame(raf)
  }, [documentId])

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

  React.useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
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
      }
    }

    globalThis.window.addEventListener("keydown", onKeyDown)
    return () => globalThis.window.removeEventListener("keydown", onKeyDown)
  }, [isOpen, activeTab, chunkQuery, closeDocument])

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
        console.error(err)
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

  const fileUrl = useResolvedAuthAssetUrl(rawFileUrl)
  const downloadUrl = useResolvedAuthAssetUrl(rawDownloadUrl)

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
      console.error(error)
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

  const openCreateChunk = React.useCallback(() => {
    setChunkEditorMode("create")
    setChunkEditorTarget(null)
    setChunkEditorContent("")
    setChunkEditorPageNumber("")
    setChunkEditorOpen(true)
    setActiveTab("chunks")
  }, [setActiveTab])

  const openEditChunk = React.useCallback(
    (chunk: DocumentChunk) => {
      setChunkEditorMode("edit")
      setChunkEditorTarget(chunk)
      setChunkEditorContent(chunk.content || "")
      setChunkEditorPageNumber(typeof chunk.page_number === "number" ? String(chunk.page_number) : "")
      setChunkEditorOpen(true)
      setActiveTab("chunks")
    },
    [setActiveTab]
  )

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
        setChunks((prev) => prev.map((chunk) => (chunk.id === updated.id ? updated : chunk)))
        setHighlightChunkState((prev) => (prev?.id === updated.id ? updated : prev))
      }

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
        console.error(err)
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
      console.error(err)
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

  const runRetrievePreview = React.useCallback(async () => {
    if (!documentId) return
    const query = retrieveQuery.trim()
    if (!query) return

    setRetrieveLoading(true)
    setRetrieveError(null)
    try {
      const res = await ragApi.retrievePreview({ query, document_ids: [documentId] })
      const raw = Array.isArray(res?.citations) ? res.citations : []
      const items = raw.map(toCitation).filter(Boolean) as Citation[]
      setRetrieveCitations(items.filter((citation) => citation.document_id === documentId))
    } catch (err) {
      console.error(err)
      setRetrieveError("检索测试失败，请稍后重试")
      setRetrieveCitations([])
    } finally {
      setRetrieveLoading(false)
    }
  }, [documentId, retrieveQuery])

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
      setActiveTab(value as "preview" | "text" | "chunks")
    },
    [setActiveTab]
  )

  return {
    activeTab,
    canEditChunks,
    canInlinePreview,
    chunkDeleteSubmitting,
    chunkEditorContent,
    chunkEditorMode,
    chunkEditorOpen,
    chunkEditorPageNumber,
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
    highlightChunk,
    highlightChunkId,
    highlightChunkLoading,
    highlightRange: highlightRange ?? null,
    isExpanded,
    isLoading,
    isOpen,
    jumpToMatch,
    loadAllChunks,
    matchCursor,
    matchChunkIds,
    openCreateChunk,
    openEditChunk,
    parsedContent,
    parsedContentError,
    parsedContentLoading,
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
    setChunkEditorContent,
    setChunkEditorPageNumber,
    setChunkQuery,
    setHighlightChunk,
    setIsExpanded,
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
    textMode,
    textValue,
  }
}

export type DocumentViewerPanelState = ReturnType<typeof useDocumentViewerPanelState>
