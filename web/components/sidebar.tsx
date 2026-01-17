/**
 * 左侧边栏组件 - 展示文档列表
 */
'use client'

import { useState } from 'react'
import {
  FileText,
  Upload,
  Loader2,
  Trash2,
  CheckCircle2,
  AlertCircle,
  X,
  Clock,
  MoreVertical,
  File,
} from 'lucide-react'
import { useDocuments } from '@/hooks/use-documents'
import { formatFileSize, formatDate, getFileIcon } from '@/lib/utils'
import { cn } from '@/lib/utils'
import type { Document } from '@/types'
import { ManualUploadDialog } from '@/components/manual-upload-dialog'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { getParserLabel } from '@/lib/parser-options'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { LottieAnimation, LOTTIE_URLS } from '@/components/ui/lottie-animation'
import { PipelineVisualizer } from '@/components/ui/pipeline-visualizer'
import { Magnetic } from '@/components/ui/magnetic'
import { TiltCard } from '@/components/ui/tilt-card'

export function Sidebar() {
  const { documents, isLoading, uploadDocument, cancelDocument, deleteDocument, loadDocuments } = useDocuments()
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])

  // 处理文件上传
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    for (const file of Array.from(files)) {
      try {
        await uploadDocument(file)
      } catch (error) {
        console.error('Upload failed:', error)
      }
    }
    e.target.value = ''
  }

  // 切换文档选择
  const toggleDocumentSelection = (docId: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(docId)
        ? prev.filter((id) => id !== docId)
        : [...prev, docId]
    )
  }

  // 获取状态图标 - 更精致的版本
  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="h-4 w-4 text-emerald-500" />
      case 'failed':
        return <AlertCircle className="h-4 w-4 text-destructive" />
      case 'processing':
      case 'pending':
        return <Loader2 className="h-4 w-4 text-primary animate-spin" />
      default:
        return <Clock className="h-4 w-4 text-muted-foreground" />
    }
  }

  return (
    <aside className="w-80 h-screen bg-sidebar-background/95 backdrop-blur-xl border-r border-sidebar-border flex flex-col shadow-[1px_0_20px_rgba(0,0,0,0.02)] transition-colors duration-300">
      {/* 头部 - 增加空间感 */}
      <div className="p-6 border-b border-sidebar-border/60">
        <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-2">
                <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center">
                    <FileText className="h-4 w-4 text-primary" />
                </div>
                <h2 className="text-lg font-semibold tracking-tight text-foreground/90">知识库</h2>
            </div>
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground">
                {documents.length}
            </span>
        </div>

        {/* 上传按钮组 - 更有层次感 */}
        <div className="space-y-3">
            <Magnetic strength={0.3}>
                <label htmlFor="file-upload" className="group relative overflow-hidden flex items-center justify-center gap-2 w-full px-4 py-3 bg-primary text-primary-foreground rounded-xl shadow-md shadow-primary/20 hover:shadow-lg hover:shadow-primary/30 hover:-translate-y-0.5 active:translate-y-0 cursor-pointer transition-all duration-300">
                    <div className="absolute inset-0 bg-gradient-to-tr from-white/0 via-white/10 to-white/0 opacity-0 group-hover:opacity-100 transition-opacity" />
                    <Upload className="h-4 w-4" />
                    <span className="text-sm font-medium">上传文档</span>
                    <input
                        id="file-upload"
                        type="file"
                        multiple
                        accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.csv,.html,.json"
                        className="hidden"
                        onChange={handleFileUpload}
                    />
                </label>
            </Magnetic>

            <div className="grid grid-cols-1">
                 <ManualUploadDialog onUploaded={loadDocuments} />
            </div>
        </div>

        {selectedDocIds.length > 0 && (
          <div className="mt-4 flex items-center justify-between px-1 py-1 bg-accent/50 rounded-md border border-accent">
            <p className="text-xs text-muted-foreground pl-2">
              已选 {selectedDocIds.length} 项
            </p>
            <button 
                onClick={() => setSelectedDocIds([])}
                className="p-1 hover:bg-background rounded-sm transition-colors"
            >
                <X className="h-3 w-3 text-muted-foreground" />
            </button>
          </div>
        )}
      </div>

      {/* 文档列表 - 优化滚动体验 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 scrollbar-hide">
        {isLoading && documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 gap-3">
            <Loader2 className="h-8 w-8 animate-spin text-primary/30" />
            <p className="text-sm text-muted-foreground animate-pulse">加载中...</p>
          </div>
        ) : documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-muted-foreground/50 gap-4">
            <div className="h-16 w-16 rounded-2xl bg-secondary/50 flex items-center justify-center">
                <File className="h-8 w-8" />
            </div>
            <p className="text-sm">暂无文档，请上传</p>
          </div>
        ) : (
          documents.map((doc, index) => (
            <DocumentCard
              key={doc.id}
              document={doc}
              index={index}
              isSelected={selectedDocIds.includes(doc.id)}
              onSelect={() => toggleDocumentSelection(doc.id)}
              onCancel={() => cancelDocument(doc.id)}
              onDelete={() => deleteDocument(doc.id)}
              getStatusIcon={getStatusIcon}
            />
          ))
        )}
      </div>
    </aside>
  )
}

// 文档卡片组件 - 玻璃拟态与微交互
function DocumentCard({
  document,
  index,
  isSelected,
  onSelect,
  onCancel,
  onDelete,
  getStatusIcon,
}: {
  document: Document
  index: number
  isSelected: boolean
  onSelect: () => void
  onCancel: () => void
  onDelete: () => void
  getStatusIcon: (status: string) => React.ReactNode
}) {
  const [isHovered, setIsHovered] = useState(false)
  const parserBackend = (document.metadata?.parser_backend as string) || ''
  const parserLabel = parserBackend ? getParserLabel(parserBackend) : null
  const chunkStrategyValue = (document.metadata?.chunk_strategy as string) || ''
  const chunkStrategyLabel = chunkStrategyValue ? getChunkStrategyLabel(chunkStrategyValue) : null

  return (
    <TiltCard
      className={cn(
        'group relative p-3 rounded-xl border cursor-pointer animate-fade-in-up h-full',
        isSelected
          ? 'bg-primary/5 border-primary/30 shadow-[0_0_0_1px_rgba(var(--primary),0.2)]'
          : 'bg-card/50 hover:bg-card border-border/50 hover:border-border/80 hover:shadow-md hover:shadow-black/5'
      )}
      onClick={onSelect}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="flex items-start gap-3">
        {/* 文件图标容器 */}
        <div className={cn(
            "p-2 rounded-lg transition-colors text-xl",
            isSelected ? "bg-primary/10 text-primary" : "bg-secondary text-muted-foreground group-hover:text-foreground"
        )}>
          {getFileIcon(document.file_type)}
        </div>

        {/* 文档信息 */}
        <div className="flex-1 min-w-0 py-0.5">
          <div className="flex items-start justify-between gap-2">
             <h3 className={cn(
                 "text-sm font-medium truncate transition-colors",
                 isSelected ? "text-primary" : "text-foreground"
             )}>
                {document.filename}
            </h3>
            <div className="shrink-0 pt-0.5 opacity-70">
                {getStatusIcon(document.status)}
            </div>
          </div>
          
          <div className="flex items-center gap-2 mt-1.5">
            <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-secondary text-secondary-foreground/70">
              {formatFileSize(document.file_size)}
            </span>
            <span className="text-[10px] text-muted-foreground/60">
              {formatDate(document.created_at)}
            </span>
          </div>

          {/* 处理进度 */}
          {(document.status === 'processing' || document.status === 'pending') && (
            <div className="mt-3">
              <PipelineVisualizer progress={document.processing_progress} className="py-2 scale-90 origin-left w-[110%]" />
              <div className="flex justify-between items-center mt-6">
                 <p className="text-[10px] text-muted-foreground">
                    {document.current_stage || '处理中'}
                 </p>
                 <span className="text-[10px] font-mono text-primary/80">
                    {document.processing_progress}%
                 </span>
              </div>
            </div>
          )}

          {/* 属性标签 */}
          {document.status === 'completed' && isHovered && (
             <div className="mt-2 flex flex-wrap gap-1 animate-fade-in">
                <span className="text-[10px] px-1.5 py-0.5 bg-secondary/80 rounded text-muted-foreground">
                    {document.chunk_count} 片段
                </span>
                {parserLabel && (
                    <span className="text-[10px] px-1.5 py-0.5 bg-secondary/80 rounded text-muted-foreground">
                        {parserLabel}
                    </span>
                )}
             </div>
          )}

          {/* 错误信息 */}
          {document.status === 'failed' && (
            <p className="text-[10px] text-destructive mt-1 font-medium bg-destructive/5 px-1.5 py-0.5 rounded inline-block">
                处理失败
            </p>
          )}
        </div>
      </div>

      {/* 悬浮操作栏 */}
      <div className={cn(
          "absolute right-2 top-2 flex flex-col gap-1 transition-all duration-200",
          isHovered ? "opacity-100 translate-x-0" : "opacity-0 translate-x-2 pointer-events-none"
      )}>
        <DocumentDetailDialog document={document} trigger={
            <button className="p-1.5 bg-background/80 backdrop-blur border shadow-sm rounded-md hover:bg-primary hover:text-primary-foreground transition-colors" title="查看详情">
                <FileText className="h-3.5 w-3.5" />
            </button>
        } />
        
        {(document.status === 'processing' || document.status === 'pending') ? (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onCancel()
              }}
              className="p-1.5 bg-background/80 backdrop-blur border shadow-sm rounded-md hover:bg-amber-100 hover:text-amber-600 transition-colors"
              title="取消处理"
            >
              <X className="h-3.5 w-3.5" />
            </button>
        ) : (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
              className="p-1.5 bg-background/80 backdrop-blur border shadow-sm rounded-md hover:bg-destructive hover:text-destructive-foreground transition-colors"
              title="删除文档"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
        )}
      </div>
    </TiltCard>
  )
}
