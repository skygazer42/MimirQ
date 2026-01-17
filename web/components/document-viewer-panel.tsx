"use client"

import * as React from "react"
import { X, Maximize2, Minimize2, FileText, List, ChevronRight, Loader2, Download } from "lucide-react"
import { cn } from "@/lib/utils"
import { useDocumentView } from "@/store/document-view"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { documentApi } from "@/lib/api-client"
import { API_V1_BASE_URL } from "@/lib/env"
import type { Document, DocumentChunk } from "@/types"
import { getAccessToken } from "@/lib/auth-storage"

export function DocumentViewerPanel() {
  const { isOpen, documentId, highlightChunkId, closeDocument, activeTab, setActiveTab } = useDocumentView()
  const [doc, setDoc] = React.useState<Document | null>(null)
  const [chunks, setChunks] = React.useState<DocumentChunk[]>([])
  const [isLoading, setIsLoading] = React.useState(false)
  const [isExpanded, setIsExpanded] = React.useState(false)
  const chunksListRef = React.useRef<HTMLDivElement>(null)

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

  if (!isOpen) return null

  const fileUrl = documentId ? `${API_V1_BASE_URL}/documents/${documentId}/download?token=${getAccessToken()}` : ''

  return (
    <div 
        className={cn(
            "fixed inset-y-0 right-0 z-50 flex flex-col bg-background border-l border-border shadow-2xl transition-all duration-300 ease-in-out",
            isExpanded ? "w-[80vw]" : "w-[40vw] min-w-[500px]"
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
            <Button variant="ghost" size="icon" onClick={() => setIsExpanded(!isExpanded)} title={isExpanded ? "收起" : "展开"}>
                {isExpanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="icon" onClick={closeDocument}>
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
                        PDF 原文
                    </TabsTrigger>
                    <TabsTrigger 
                        value="chunks" 
                        className="h-10 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent px-2 font-medium"
                    >
                        智能切片
                    </TabsTrigger>
                </TabsList>
            </div>

            <TabsContent value="preview" className="flex-1 m-0 h-full bg-slate-100 dark:bg-slate-900 relative">
                {fileUrl ? (
                    <iframe 
                        src={`${fileUrl}#toolbar=0`} 
                        className="w-full h-full border-none" 
                        title="PDF Preview"
                    />
                ) : (
                    <div className="flex items-center justify-center h-full text-muted-foreground">
                        <Loader2 className="h-8 w-8 animate-spin" />
                    </div>
                )}
            </TabsContent>

            <TabsContent value="chunks" className="flex-1 m-0 h-full overflow-hidden flex flex-col bg-slate-50/50 dark:bg-slate-950/50">
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
                                {chunk.content}
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
  )
}
