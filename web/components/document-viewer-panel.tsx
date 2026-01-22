"use client"

import * as React from "react"
import { X, Maximize2, Minimize2, FileText, Loader2, Download } from "lucide-react"
import { cn } from "@/lib/utils"
import { useDocumentView } from "@/store/document-view"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { documentApi } from "@/lib/api-client"
import { API_V1_BASE_URL } from "@/lib/env"
import type { Document, DocumentChunk } from "@/types"
import { getAccessToken, getTenantId } from "@/lib/auth-storage"
import { FloatingMenu } from "@/components/document-viewer/floating-menu"

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
  const [isExpanded, setIsExpanded] = React.useState(false)
  const chunksListRef = React.useRef<HTMLDivElement>(null)
  const [chunkQuery, setChunkQuery] = React.useState("")
  const [matchCursor, setMatchCursor] = React.useState(0)

  // Load document metadata and chunks
  React.useEffect(() => {
    if (!documentId) return
    setIsLoading(true)
    documentApi.get(documentId, { includeChunks: true })
      .then(data => {
        setDoc(data)
        setChunks(data.chunks || [])
      })
      .catch(console.error)
      .finally(() => setIsLoading(false))
  }, [documentId])

  // Scroll to highlighted chunk
  React.useEffect(() => {
    if (!highlightChunkId || activeTab !== 'chunks') return
    // Simple timeout to allow rendering
    setTimeout(() => {
        const el = document.getElementById(`chunk-${highlightChunkId}`)
        if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'center' })
            el.classList.add('bg-primary/10')
            setTimeout(() => el.classList.remove('bg-primary/10'), 2000)
        }
    }, 100)
  }, [highlightChunkId, activeTab, chunks])

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
                    {chunks.length} 个切片
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
                       value={chunkQuery}
                       onChange={(e) => setChunkQuery(e.target.value)}
                       onKeyDown={(e) => {
                         if (e.key === "Enter") jumpToMatch(matchCursor)
                       }}
                       placeholder="搜索切片内容…"
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
                 </div>
                 <div className="flex-1 overflow-y-auto p-4 space-y-4 scroll-smooth" ref={chunksListRef}>
                    {chunks.map((chunk) => (
                        <div 
                            key={chunk.id} 
                            id={`chunk-${chunk.id}`}
                            className={cn(
                                "p-4 rounded-xl border transition-all duration-300",
                                highlightChunkId === chunk.id 
                                    ? "bg-primary/5 border-primary shadow-[0_0_0_1px_rgba(var(--primary),0.2)] ring-1 ring-primary/20" 
                                    : "bg-background border-border hover:border-primary/30 hover:shadow-sm"
                            )}
                        >
                            <div className="flex items-center justify-between mb-2">
                                <span className="text-xs font-mono font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                                    #{chunk.chunk_index}
                                </span>
                                {chunk.page_number && (
                                    <span className="text-xs text-muted-foreground">P.{chunk.page_number}</span>
                                )}
                            </div>
                            <p className="text-sm leading-relaxed text-foreground/90 font-mono whitespace-pre-wrap">
                                {highlightText(chunk.content, chunkQuery)}
                            </p>
                        </div>
                    ))}
                    {chunks.length === 0 && !isLoading && (
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
