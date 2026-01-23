"use client"

import * as React from "react"
import { X, Maximize2, Minimize2, FileText, Loader2, Download, Copy, Link2 } from "lucide-react"
import { useVirtualizer } from "@tanstack/react-virtual"
import { cn } from "@/lib/utils"
import { useDocumentView } from "@/store/document-view"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { documentApi } from "@/lib/api-client"
import { API_V1_BASE_URL } from "@/lib/env"
import type { Document, DocumentChunk } from "@/types"
import { getAccessToken, getTenantId } from "@/lib/auth-storage"
import { FloatingMenu } from "@/components/document-viewer/floating-menu"
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
  const [isExpanded, setIsExpanded] = React.useState(false)
  const chunksListRef = React.useRef<HTMLDivElement>(null)
  const chunkSearchRef = React.useRef<HTMLInputElement>(null)
  const [chunkQuery, setChunkQuery] = React.useState("")
  const [matchCursor, setMatchCursor] = React.useState(0)

  const rowVirtualizer = useVirtualizer({
    count: chunks.length,
    getScrollElement: () => chunksListRef.current,
    estimateSize: () => 220,
    overscan: 8,
  })

  // Load document metadata (lazy-load chunks separately).
  React.useEffect(() => {
    if (!documentId) return
    setDoc(null)
    setChunks([])
    setChunksLoaded(false)
    setLoadAllChunks(false)
    setHighlightChunkState(null)
    setHighlightChunkLoading(false)
    setChunkQuery("")
    setMatchCursor(0)
    setIsLoading(true)
    documentApi.get(documentId, { includeChunks: false })
      .then(data => {
        setDoc(data)
      })
      .catch(console.error)
      .finally(() => setIsLoading(false))
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

  // Load chunks on demand (when user opens the "chunks" tab or a citation requests a highlight).
  React.useEffect(() => {
    if (!documentId) return
    if (chunksLoaded || chunksLoading) return
    const shouldLoadAll = activeTab === "chunks" && (loadAllChunks || !highlightChunkId)
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

  const matchChunkIds = React.useMemo(() => {
    const q = chunkQuery.trim().toLowerCase()
    if (!q) return []
    const ids: string[] = []
    for (const c of chunks) {
      const text = (c.content || "").toLowerCase()
      if (text.includes(q)) ids.push(c.id)
    }
    return ids
  }, [chunks, chunkQuery])

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

  if (!isOpen) return null

  return (
    <>
    <FloatingMenu />
    <div 
        className={cn(
            "fixed inset-y-0 right-0 z-50 flex flex-col bg-background border-l border-border shadow-2xl transition-all duration-300 ease-in-out",
           isExpanded ? "w-full md:w-[80vw]" : "w-full md:w-[40vw] md:min-w-[500px]"
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
         <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as any)} className="flex-1 flex flex-col">
            <div className="px-4 border-b border-border bg-background">
                <TabsList className="w-full justify-start h-10 bg-transparent p-0 gap-6">
                    <TabsTrigger 
                        value="preview" 
                        className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent px-2 font-medium"
                    >
                        原文
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

            <TabsContent value="chunks" className="flex-1 m-0 h-full overflow-hidden flex flex-col bg-muted/20 dark:bg-muted/10">
                 <div className="p-4 border-b border-border bg-background/60 backdrop-blur-sm">
                   <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                     <input
                       ref={chunkSearchRef}
                       value={chunkQuery}
                       onChange={(e) => setChunkQuery(e.target.value)}
                       onKeyDown={(e) => {
                         if (e.key === "Enter") jumpToMatch(matchCursor)
                       }}
                       placeholder={
                         chunksLoading && !chunksLoaded
                           ? "切片加载中…"
                           : highlightChunkId && !loadAllChunks && !chunksLoaded
                             ? "已定位引用切片（加载全部后可搜索）"
                             : "搜索切片内容…"
                       }
                       disabled={(chunksLoading && !chunksLoaded) || (highlightChunkId && !loadAllChunks && !chunksLoaded)}
                       className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                     />
                     <div className="flex items-center gap-2">
                       <div className="text-xs text-muted-foreground tabular-nums min-w-[88px] text-right">
                         {chunkQuery.trim() ? (
                           matchChunkIds.length ? (
                             <span>{matchCursor + 1}/{matchChunkIds.length}</span>
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
                                     onClick={() => copyText(highlightChunk.content, \"已复制切片内容\")}
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
                                     onClick={() => copyText(buildChunkLink(highlightChunk.id), \"已复制定位链接\")}
                                     aria-label="复制定位链接"
                                     title="复制定位链接"
                                   >
                                     <Link2 className="h-4 w-4" />
                                   </Button>
                                 </div>
                               </div>
                             </div>
                             <p className="text-sm leading-relaxed text-foreground/90 font-mono whitespace-pre-wrap">
                               {highlightChunk.content}
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
