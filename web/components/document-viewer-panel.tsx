"use client"

import * as React from "react"
import { X, Maximize2, Minimize2, FileText, Loader2, Download, Copy, Link2 } from "lucide-react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { cn } from "@/lib/utils"
import { useDocumentView } from "@/store/document-view"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { documentApi, ragApi } from "@/lib/api-client"
import { API_V1_BASE_URL } from "@/lib/env"
import type { Citation, Document, DocumentChunk, DocumentParsedContentResponse } from "@/types"
import { getAccessToken, getTenantId } from "@/lib/auth-storage"
import { FloatingMenu } from "@/components/document-viewer/floating-menu"
import { mapDocumentChunksToPreviewItems } from "@/lib/document-chunks"
import { getDocContentFromCache, saveDocContentToCache } from "@/lib/doc-content-cache"
import { OriginalPreviewMonaco } from "@/components/chunk-preview/components/workbench/preview/original-preview-monaco"
import { toast } from "sonner"

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function highlightText(content: string, query: string) {
  const q = (query || "").trim()
  if (!q) return content
  const re = new RegExp(escapeRegExp(q), "ig")
  const out: React.ReactNode[] = []
  let lastIndex = 0
  let matchCount = 0

  for (const match of content.matchAll(re)) {
    const idx = match.index
    if (idx == null) continue
    const matched = match[0] || ""
    if (!matched) continue
    if (idx > lastIndex) out.push(content.slice(lastIndex, idx))
    out.push(
      <mark
        key={`${idx}-${matched}`}
        className="rounded bg-yellow-200/60 px-0.5 text-foreground dark:bg-yellow-400/20"
      >
        {content.slice(idx, idx + matched.length)}
      </mark>
    )
    lastIndex = idx + matched.length
    matchCount += 1
    if (matchCount >= 50) break
  }

  if (lastIndex < content.length) out.push(content.slice(lastIndex))
  return out.length ? out : content
}

export function DocumentViewerPanel() {
  const { isOpen, documentId, highlightChunkId, closeDocument, activeTab, setActiveTab, setHighlightChunk } = useDocumentView()
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
    const raf = window.requestAnimationFrame(() => {
      chunksListRef.current?.scrollTo({ top: 0, left: 0, behavior: "auto" })
    })

    setIsLoading(true)
    documentApi.get(documentId, { includeChunks: false })
      .then(data => {
        setDoc(data)
      })
      .catch(console.error)
      .finally(() => setIsLoading(false))

    return () => window.cancelAnimationFrame(raf)
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
          void saveDocContentToCache({
            id: documentId,
            markdownContent: data.markdown_content || "",
            originalMarkdownContent: data.original_markdown_content || "",
          })
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
    const base = chunksLoaded ? chunks : highlightChunk ? [highlightChunk] : []
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
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
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
    const t = window.setTimeout(() => {
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

    return () => window.clearTimeout(t)
  }, [documentId, chunkQuery, chunksLoaded])

  const matchChunkIds = React.useMemo(() => {
    if (!chunkQuery.trim()) return []
    return chunksLoaded ? localMatchChunkIds : serverMatchIds
  }, [chunkQuery, chunksLoaded, localMatchChunkIds, serverMatchIds])

  React.useEffect(() => {
    setMatchCursor(0)
  }, [chunkQuery])

  const fileUrl = React.useMemo(() => {
    if (!documentId) return ""
    const url = new URL(`${API_V1_BASE_URL}/documents/${documentId}/download`)
    const token = getAccessToken()
    const tenantId = getTenantId()
    if (tenantId) url.searchParams.set("tenant_id", tenantId)
    if (token) url.searchParams.set("token", token)
    return url.toString()
  }, [documentId])

  const downloadUrl = React.useMemo(() => {
    if (!documentId) return ""
    const url = new URL(`${API_V1_BASE_URL}/documents/${documentId}/download`)
    const token = getAccessToken()
    const tenantId = getTenantId()
    if (tenantId) url.searchParams.set("tenant_id", tenantId)
    if (token) url.searchParams.set("token", token)
    url.searchParams.set("inline", "0")
    return url.toString()
  }, [documentId])

  const buildChunkLink = React.useCallback((chunkId: string) => {
    if (!documentId) return ""
    try {
      const url = new URL("/", window.location.origin)
      url.searchParams.set("doc", documentId)
      url.searchParams.set("chunk", chunkId)
      return url.toString()
    } catch {
      return ""
    }
  }, [documentId])

  const copyText = React.useCallback(async (text: string, okMsg: string) => {
    const value = (text || "").trim()
    if (!value) return

    let ok = false
    try {
      await navigator.clipboard.writeText(value)
      ok = true
    } catch {
      try {
        const textarea = document.createElement("textarea")
        textarea.value = value
        textarea.setAttribute("readonly", "")
        textarea.style.position = "fixed"
        textarea.style.left = "0"
        textarea.style.top = "0"
        textarea.style.opacity = "0"
        document.body.appendChild(textarea)
        textarea.focus()
        textarea.select()
        ok = document.execCommand("copy")
        document.body.removeChild(textarea)
      } catch {
        ok = false
      }
    }

    if (ok) toast.success(okMsg)
  }, [])

  const canInlinePreview = (doc?.file_type || "").toLowerCase() === "pdf"

  const jumpToMatch = React.useCallback((nextIndex: number) => {
    if (!matchChunkIds.length) return
    const clamped = ((nextIndex % matchChunkIds.length) + matchChunkIds.length) % matchChunkIds.length
    setMatchCursor(clamped)
    setActiveTab("chunks")
    setHighlightChunk(matchChunkIds[clamped] || null)
  }, [matchChunkIds, setActiveTab, setHighlightChunk])

  const runRetrievePreview = React.useCallback(async () => {
    if (!documentId) return
    const q = retrieveQuery.trim()
    if (!q) return

    setRetrieveLoading(true)
    setRetrieveError(null)
    try {
      const res = await ragApi.retrievePreview({ query: q, document_ids: [documentId] })
      const items = (res?.citations || []).filter((c) => c.document_id === documentId)
      setRetrieveCitations(items)
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
    <div 
        className={cn(
            "fixed inset-y-0 right-0 z-50 flex flex-col bg-background border-l border-border shadow-2xl transition-all duration-300 ease-in-out",
           // Keep width aligned with AppFrame's right padding:
           // - md: 40vw
           // - lg: fixed 500px
           // - xl+: 40vw
           isExpanded ? "w-full md:w-[80vw]" : "w-full md:w-[40vw] lg:w-[500px] xl:w-[40vw]"
        )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-muted/30 backdrop-blur-sm">
        <div className="flex items-center gap-3 overflow-hidden">
            <div className="p-2 bg-primary/10 rounded-lg">
                <FileText className="h-5 w-5 text-primary" />
            </div>
            <div className="flex flex-col min-w-0">
                <h3 className="text-sm font-semibold truncate max-w-[200px]" title={doc?.filename}>
                    {doc?.filename || '加载中...'}
                </h3>
                <span className="text-xs text-muted-foreground">
                    {(doc?.chunk_count ?? chunks.length)} 个切片
                </span>
            </div>
        </div>
        
        <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" asChild title="下载原文件" aria-label="下载原文件">
              <a href={downloadUrl || "#"} target="_blank" rel="noopener noreferrer">
                <Download className="h-4 w-4" />
              </a>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setIsExpanded(!isExpanded)}
              title={isExpanded ? "收起" : "展开"}
              aria-label={isExpanded ? "收起" : "展开"}
            >
                {isExpanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="icon" onClick={closeDocument} aria-label="关闭">
                <X className="h-4 w-4" />
            </Button>
        </div>
      </div>

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
	                {isLoading && !doc ? (
	                  <div className="flex items-center justify-center h-full text-muted-foreground">
	                    <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
	                  </div>
	                ) : canInlinePreview && fileUrl ? (
                  <iframe
                    src={`${fileUrl}#toolbar=0`}
                    className="w-full h-full border-none"
                    title="Document Preview"
                  />
                ) : (
                  <div className="h-full flex items-center justify-center p-6">
                    <div className="max-w-md w-full rounded-xl border border-border bg-background p-6 shadow-sm">
                      <div className="flex items-start gap-3">
                        <div className="p-2 rounded-lg bg-primary/10">
                          <FileText className="h-5 w-5 text-primary" />
                        </div>
                        <div className="flex-1">
                          <h4 className="text-sm font-semibold">暂不支持内嵌预览</h4>
                          <p className="text-xs text-muted-foreground mt-1">
                            当前文件类型为 <span className="font-mono">{doc?.file_type || "-"}</span>。你可以下载原文件，
                            或切换到「智能切片」查看内容。
                          </p>
                          <div className="mt-4 flex items-center gap-2">
                            <Button size="sm" variant="outline" asChild>
                              <a href={downloadUrl || "#"} target="_blank" rel="noopener noreferrer">
                                下载原文件
                              </a>
                            </Button>
                            <Button size="sm" onClick={() => setActiveTab("chunks")}>
                              查看切片
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
            </TabsContent>

            <TabsContent value="text" className="flex-1 m-0 h-full overflow-hidden flex flex-col bg-muted/20 dark:bg-muted/10">
                 <div className="p-4 border-b border-border bg-background/60 backdrop-blur-sm">
                   <div className="flex flex-col gap-2">
                     <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                       <div className="flex items-center flex-wrap gap-2">
                         <Button
                           type="button"
                           size="sm"
                           variant={textMode === "cleaned" ? "secondary" : "outline"}
                           onClick={() => setTextMode("cleaned")}
                         >
                           清洗后
                         </Button>
                         <Button
                           type="button"
                           size="sm"
                           variant={textMode === "original" ? "secondary" : "outline"}
                           onClick={() => setTextMode("original")}
                         >
                           原始解析
                         </Button>

                         {highlightChunkId && !loadAllChunks && !chunksLoaded ? (
                           <span className="text-[11px] text-muted-foreground">
                             仅加载引用切片位置；如需展示全部切片位置，请点右侧「加载全部切片」。
                           </span>
                         ) : null}
                       </div>

                       <div className="flex items-center gap-2 justify-end">
                         {highlightChunkId ? (
                           <Button
                             type="button"
                             size="sm"
                             variant="outline"
                             onClick={() => setHighlightChunk(null)}
                           >
                             清除定位
                           </Button>
                         ) : null}

                         {!chunksLoaded ? (
                           <Button
                             type="button"
                             size="sm"
                             onClick={() => setLoadAllChunks(true)}
                             disabled={chunksLoading}
                           >
                             加载全部切片
                           </Button>
                         ) : null}
                       </div>
                     </div>

                     <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                       <input
                         value={retrieveQuery}
                         onChange={(e) => setRetrieveQuery(e.target.value)}
                         onKeyDown={(e) => {
                           if (e.key !== "Enter") return
                           e.preventDefault()
                           void runRetrievePreview()
                         }}
                         placeholder="检索测试：输入问题，查看真实检索命中的切片…"
                         className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                       />
                       <div className="flex items-center gap-2 justify-end">
                         <Button
                           type="button"
                           size="sm"
                           variant="outline"
                           disabled={!retrieveQuery.trim() || retrieveLoading}
                           onClick={() => void runRetrievePreview()}
                         >
                           {retrieveLoading ? (
                             <span className="inline-flex items-center gap-2">
                               <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                               检索中…
                             </span>
                           ) : (
                             "检索"
                           )}
                         </Button>
                         {retrieveCitations.length ? (
                           <Button
                             type="button"
                             size="sm"
                             variant="outline"
                             onClick={() => {
                               setRetrieveCitations([])
                               setRetrieveError(null)
                             }}
                           >
                             清空
                           </Button>
                         ) : null}
                       </div>
                     </div>

                     {retrieveError ? (
                       <div className="text-[11px] text-destructive bg-destructive/10 border border-destructive/25 px-2 py-1 rounded-lg">
                         {retrieveError}
                       </div>
                     ) : null}

                     {retrieveCitations.length ? (
                       <div className="rounded-xl border border-border/60 bg-background/60 p-3 max-h-[220px] overflow-auto">
                         <div className="text-xs font-semibold text-foreground mb-2">检索命中</div>
                         <div className="space-y-2">
                           {retrieveCitations.slice(0, 6).map((c, idx) => {
                             const hasChunk = Boolean(c.chunk_id)
                             return (
                               <button
                                 key={`${c.chunk_id || idx}-${idx}`}
                                 type="button"
                                 className={cn(
                                   "w-full text-left rounded-lg border border-border bg-background px-3 py-2",
                                   "hover:border-primary/30 hover:bg-muted/30 transition-colors"
                                 )}
                                 disabled={!hasChunk}
                                 onClick={() => {
                                   if (!c.chunk_id) return
                                   setActiveTab("text")
                                   setHighlightChunk(c.chunk_id)
                                 }}
                               >
                                 <div className="flex items-center justify-between gap-2">
                                   <div className="text-[11px] text-muted-foreground">
                                     score <span className="font-mono">{Number(c.relevance_score || 0).toFixed(4)}</span>
                                     {typeof c.page_number === "number" ? (
                                       <span className="ml-2">P.{c.page_number}</span>
                                     ) : null}
                                   </div>
                                   <div className="text-[11px] text-muted-foreground">
                                     {hasChunk ? "点击定位" : "无 chunk_id"}
                                   </div>
                                 </div>
                                 <div className="mt-1 text-xs leading-relaxed text-foreground/90 font-mono whitespace-pre-wrap line-clamp-3">
                                   {c.chunk_content || ""}
                                 </div>
                               </button>
                             )
                           })}
                         </div>
                       </div>
                     ) : null}

                     {textMode === "original" ? (
                       <div className="text-[11px] text-muted-foreground">
                         提示：切片的 start/end 偏移通常基于「清洗后」文本；在「原始解析」视图中高亮定位可能不准确。
                       </div>
                     ) : null}

                     {parsedContent?.markdown_truncated || parsedContent?.original_markdown_truncated ? (
                       <div className="text-[11px] text-muted-foreground">
                         文本已截断显示（max_chars={parsedContent?.max_chars ?? 0}）。如需完整内容，请提高 persist_parsed_content_max_chars 或缩小文件。
                       </div>
                     ) : null}

                     {parsedContentError ? (
                       <div className="text-[11px] text-destructive bg-destructive/10 border border-destructive/25 px-2 py-1 rounded-lg">
                         {parsedContentError}
                       </div>
                     ) : null}
                   </div>
                 </div>

                 <div className="flex-1 overflow-hidden p-4">
                   {parsedContentLoading && !parsedContent ? (
                     <div className="h-full flex items-center justify-center text-muted-foreground">
                       <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
                     </div>
                   ) : parsedContent?.available && textValue ? (
                     <OriginalPreviewMonaco
                       text={textValue}
                       chunks={textMode === "cleaned" ? textChunkItems : []}
                       activeChunkIndex={textMode === "cleaned" ? textActiveChunkIndex : null}
                       onSelectChunkIndex={(chunkIndex) => {
                         const target =
                           chunks.find((c) => c.chunk_index === chunkIndex) ||
                           (highlightChunk && highlightChunk.chunk_index === chunkIndex ? highlightChunk : null)
                         if (target) setHighlightChunk(target.id)
                       }}
                     />
                   ) : (
                     <div className="h-full flex items-center justify-center p-6">
                       <div className="max-w-md w-full rounded-xl border border-border bg-background p-6 shadow-sm">
                         <div className="flex items-start gap-3">
                           <div className="p-2 rounded-lg bg-primary/10">
                             <FileText className="h-5 w-5 text-primary" />
                           </div>
                           <div className="flex-1">
                             <h4 className="text-sm font-semibold">未持久化解析文本</h4>
                             <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                               当前文档未开启 <span className="font-mono">persist_parsed_content</span>，因此无法在此处高亮定位切片位置。
                               你可以在上传/流水线配置中开启该选项后重新入库，或继续使用「智能切片」查看内容。
                             </p>
                             <div className="mt-4 flex items-center gap-2">
                               <Button size="sm" variant="outline" onClick={() => setActiveTab("chunks")}>
                                 查看切片
                               </Button>
                               <Button size="sm" variant="outline" onClick={() => setActiveTab("preview")}>
                                 返回原文
                               </Button>
                             </div>
                           </div>
                         </div>
                       </div>
                     </div>
                   )}
                 </div>
            </TabsContent>

            <TabsContent value="chunks" className="flex-1 m-0 h-full overflow-hidden flex flex-col bg-muted/20 dark:bg-muted/10">
                 <div className="p-4 border-b border-border bg-background/60 backdrop-blur-sm">
                   <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                     <input
                       ref={chunkSearchRef}
                       value={chunkQuery}
                       onChange={(e) => setChunkQuery(e.target.value)}
                       onKeyDown={(e) => {
                         if (e.key !== "Enter") return
                         e.preventDefault()
                         if (!matchChunkIds.length) return

                         const currentId = matchChunkIds[matchCursor]
                         // First Enter jumps to the current match; subsequent Enter goes next.
                         if (currentId && highlightChunkId === currentId) {
                           jumpToMatch(matchCursor + (e.shiftKey ? -1 : 1))
                           return
                         }

                         jumpToMatch(matchCursor)
                       }}
                       placeholder={
                         serverMatchLoading
                           ? "搜索中…"
                           : chunksLoaded
                             ? "搜索切片内容…"
                             : "搜索切片内容…（无需加载全部切片）"
                       }
                       className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                     />
                     <div className="flex items-center gap-2">
                       <div className="text-xs text-muted-foreground tabular-nums min-w-[88px] text-right">
                         {chunkQuery.trim() ? (
                           serverMatchLoading ? (
                             <span>…</span>
                           ) : matchChunkIds.length ? (
                             <span>
                               {matchCursor + 1}/
                               {chunksLoaded ? matchChunkIds.length : (serverMatchTotal || matchChunkIds.length)}
                               {!chunksLoaded && serverMatchTruncated ? "+" : ""}
                             </span>
                           ) : (
                             <span>0/0</span>
                           )
                         ) : (
                           <span>—</span>
                         )}
                       </div>
                       <Button
                         size="sm"
                         variant="outline"
                         disabled={!matchChunkIds.length}
                         onClick={() => jumpToMatch(matchCursor - 1)}
                       >
                         上一个
                       </Button>
                       <Button
                         size="sm"
                         variant="outline"
                         disabled={!matchChunkIds.length}
                         onClick={() => jumpToMatch(matchCursor + 1)}
                       >
                         下一个
                       </Button>
                     </div>
                   </div>

                   {!chunksLoaded && chunkQuery.trim() && serverMatchTruncated ? (
                     <div className="mt-2 text-[11px] text-muted-foreground">
                       匹配结果过多，仅返回前 {matchChunkIds.length} 条（计数后缀 “+” 表示截断）。
                     </div>
                   ) : null}

                   {highlightChunkId && !loadAllChunks && !chunksLoaded ? (
                     <div className="mt-3 rounded-xl border border-border/60 bg-background/60 p-4">
                       <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                         <div className="min-w-0">
                           <div className="text-xs font-semibold text-foreground">引用切片</div>
                           <div className="mt-1 text-[11px] text-muted-foreground">
                             为避免一次性加载大量切片，先展示命中内容；需要全文切片可点击「加载全部切片」。
                           </div>
                         </div>
                         <div className="flex items-center gap-2 justify-end">
                           <Button
                             type="button"
                             size="sm"
                             variant="outline"
                             onClick={() => setHighlightChunk(null)}
                             disabled={highlightChunkLoading}
                           >
                             清除定位
                           </Button>
                           <Button
                             type="button"
                             size="sm"
                             onClick={() => setLoadAllChunks(true)}
                             disabled={chunksLoading}
                           >
                             加载全部切片
                           </Button>
                         </div>
                       </div>

                       <div className="mt-3">
                         {highlightChunkLoading ? (
                           <div className="flex items-center gap-2 text-xs text-muted-foreground">
                             <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                             <span>加载命中切片…</span>
                           </div>
                         ) : highlightChunk ? (
                           <div className="rounded-xl border border-border bg-background p-4">
                             <div className="flex items-center justify-between mb-2">
                               <span className="text-xs font-mono font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                                 #{highlightChunk.chunk_index}
                               </span>
                               <div className="flex items-center gap-2">
                                 {highlightChunk.page_number != null ? (
                                   <span className="text-xs text-muted-foreground">P.{highlightChunk.page_number}</span>
                                 ) : null}
                                 <div className="flex items-center gap-1">
                                   <Button
                                     type="button"
                                     variant="ghost"
                                     size="icon"
                                     className="h-7 w-7"
                                     onClick={() => copyText(highlightChunk.content, "已复制切片内容")}
                                     aria-label="复制切片内容"
                                     title="复制切片内容"
                                   >
                                     <Copy className="h-4 w-4" />
                                   </Button>
                                   <Button
                                     type="button"
                                     variant="ghost"
                                     size="icon"
                                     className="h-7 w-7"
                                     onClick={() => copyText(buildChunkLink(highlightChunk.id), "已复制定位链接")}
                                     aria-label="复制定位链接"
                                     title="复制定位链接"
                                   >
                                     <Link2 className="h-4 w-4" />
                                   </Button>
                                 </div>
                               </div>
                             </div>
                             <p className="text-sm leading-relaxed text-foreground/90 font-mono whitespace-pre-wrap">
                               {highlightText(highlightChunk.content, chunkQuery)}
                             </p>
                           </div>
                         ) : (
                           <div className="text-xs text-muted-foreground">未找到命中切片（可能已被删除或无权限）</div>
                         )}
                       </div>
                     </div>
                   ) : null}
                 </div>
                 <div className="flex-1 overflow-y-auto overscroll-contain p-4 scroll-smooth no-scrollbar" ref={chunksListRef}>
                    {chunksLoading && chunks.length === 0 ? (
                      <div className="flex items-center justify-center py-10 text-muted-foreground">
                        <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none" />
                      </div>
                    ) : null}

                    {chunks.length > 0 ? (
                      <div
                        style={{
                          height: `${rowVirtualizer.getTotalSize()}px`,
                          width: "100%",
                          position: "relative",
                        }}
                      >
                        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                          const chunk = chunks[virtualRow.index]
                          if (!chunk) return null

                          return (
                            <div
                              key={virtualRow.key}
                              data-index={virtualRow.index}
                              ref={rowVirtualizer.measureElement}
                              style={{
                                position: "absolute",
                                top: 0,
                                left: 0,
                                width: "100%",
                                transform: `translateY(${virtualRow.start}px)`,
                              }}
                              className="pb-4"
                            >
                              <div
                                id={`chunk-${chunk.id}`}
                                className={cn(
                                  "group p-4 rounded-xl border transition-all duration-300",
                                  highlightChunkId === chunk.id
                                    ? "bg-primary/5 border-primary shadow-[0_0_0_1px_rgba(var(--primary),0.2)] ring-1 ring-primary/20"
                                    : "bg-background border-border hover:border-primary/30 hover:shadow-sm"
                                )}
                              >
                                <div className="flex items-center justify-between mb-2">
                                  <span className="text-xs font-mono font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                                    #{chunk.chunk_index}
                                  </span>
                                  <div className="flex items-center gap-2">
                                    {chunk.page_number != null ? (
                                      <span className="text-xs text-muted-foreground">P.{chunk.page_number}</span>
                                    ) : null}
                                    <div className="flex items-center gap-1 opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity">
                                      <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        className="h-7 w-7"
                                        onClick={() => copyText(chunk.content, "已复制切片内容")}
                                        aria-label="复制切片内容"
                                        title="复制切片内容"
                                      >
                                        <Copy className="h-4 w-4" />
                                      </Button>
                                      <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        className="h-7 w-7"
                                        onClick={() => copyText(buildChunkLink(chunk.id), "已复制定位链接")}
                                        aria-label="复制定位链接"
                                        title="复制定位链接"
                                      >
                                        <Link2 className="h-4 w-4" />
                                      </Button>
                                    </div>
                                  </div>
                                </div>
                                <p className="text-sm leading-relaxed text-foreground/90 font-mono whitespace-pre-wrap">
                                  {highlightText(chunk.content, chunkQuery)}
                                </p>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    ) : null}

                    {chunksLoaded && !chunksLoading && chunks.length === 0 && (
                      <div className="text-center py-10 text-muted-foreground">暂无切片数据</div>
                    )}
                 </div>
            </TabsContent>
         </Tabs>
      </div>
    </div>
    </>
  )
}
