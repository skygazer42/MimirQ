/**
 * 左侧边栏组件 - 展示文档列表
 */
'use client'

import { useState, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { FileText, Upload, Loader2, Trash2, CheckCircle2, AlertCircle, X, Clock, Search } from 'lucide-react'
import { useDocuments } from '@/hooks/use-documents'
import { useLocalSearch } from '@/hooks/use-local-search'
import { cn, formatFileSize, formatDate } from '@/lib/utils'
import type { Document } from '@/types'
import { ManualUploadDialog } from '@/components/manual-upload-dialog'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { getParserLabel } from '@/lib/parser-options'
import { PipelineVisualizer } from '@/components/ui/pipeline-visualizer'
import { Magnetic } from '@/components/ui/magnetic'
import { TiltCard } from '@/components/ui/tilt-card'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'

type SidebarVariant = 'app' | 'workbench'
type SidebarProps = Readonly<{ variant?: SidebarVariant }>

export function Sidebar({ variant = 'app' }: SidebarProps = {}) {
  const { documents, isLoading, uploadDocuments, cancelDocument, deleteDocument, loadDocuments } = useDocuments()
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([])
  const parentRef = useRef<HTMLDivElement>(null)
  const isWorkbench = variant === 'workbench'

  const { term, setTerm, results } = useLocalSearch(documents, {
    fields: ['filename', 'file_type'],
    storeFields: ['id']
  })

  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: results.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 100, // 估算高度，卡片大约 80-100px
    overscan: 5,
  })

  // 处理文件上传
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    try {
      await uploadDocuments(Array.from(files), { maxRetries: 1, maxConcurrent: 5 })
    } catch (error) {
      console.error('Upload failed:', error)
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
        return <CheckCircle2 className="size-4 text-success" />
      case 'failed':
        return <AlertCircle className="size-4 text-destructive" />
      case 'processing':
      case 'pending':
        return <Loader2 className="size-4 text-primary animate-spin motion-reduce:animate-none" />
      default:
        return <Clock className="size-4 text-muted-foreground" />
    }
  }

  return (
    <aside
      className={cn(
        'bg-sidebar/95 text-sidebar-foreground border-r border-sidebar-border/40 flex flex-col',
        isWorkbench ? 'w-full h-full min-h-0 overflow-hidden' : 'w-80 h-dvh shadow-sm relative z-20'
      )}
    >
      {/* 头部 - 增加空间感 */}
      <div className="p-6 border-b border-border/40">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <div className="size-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <FileText className="size-4 text-primary" />
            </div>
            <h2 className="text-lg font-semibold text-foreground/90">知识库</h2>
          </div>
          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground">
            {documents.length}
          </span>
        </div>

        <div className="space-y-3">
          <div className="relative group">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground group-focus-within:text-primary transition-colors" />
            <input
              type="text"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder="快速搜索文档..."
              className="w-full h-9 pl-9 pr-3 bg-background/35 border border-border/45 focus:bg-background/55 focus:border-primary/35 rounded-lg text-xs outline-none transition-colors placeholder:text-muted-foreground/60 focus-ring"
            />
            {term && (
              <button
                onClick={() => setTerm('')}
                aria-label="清除搜索"
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-secondary rounded-md focus-ring"
              >
                <X className="size-3 text-muted-foreground" />
              </button>
            )}
          </div>

          <Magnetic strength={0.3}>
            <label
              htmlFor="file-upload"
              className="group relative flex items-center justify-center gap-2 w-full px-4 py-3 bg-primary text-primary-foreground rounded-xl border border-primary/30 shadow-sm hover:bg-primary/90 transition-colors duration-200 cursor-pointer"
            >
              <Upload className="size-4" />
              <span className="text-sm font-medium">上传文档</span>
              <input
                id="file-upload"
                type="file"
                multiple
                accept={UPLOAD_ACCEPT}
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
            <div className="mt-4 flex items-center justify-between px-1 py-1 bg-accent/35 rounded-md border border-accent/60">
            <p className="text-xs text-muted-foreground pl-2">
              已选 {selectedDocIds.length} 项
            </p>
            <button
              onClick={() => setSelectedDocIds([])}
              aria-label="清除已选"
              className="p-1 hover:bg-background rounded-sm transition-colors"
            >
              <X className="size-3 text-muted-foreground" />
            </button>
          </div>
        )}
      </div>

      {/* 文档列表 - 优化滚动体验 (虚拟列表 + 本地搜索) */}
      <div
        ref={parentRef}
        data-page-scroll-container="true"
        className="flex-1 overflow-y-auto p-4 no-scrollbar"
      >
        {(() => {
    if (isLoading && documents.length === 0) {
        return (<div className="flex flex-col items-center justify-center h-40 gap-3">
            <Loader2 className="size-8 animate-spin motion-reduce:animate-none text-primary/30"/>
            <p className="text-sm text-muted-foreground animate-pulse motion-reduce:animate-none">加载中...</p>
          </div>);
    }
    else if (results.length === 0) {
            return (<div className="flex flex-col items-center justify-center h-64 text-muted-foreground/50 gap-4">
            <div
              aria-hidden="true"
              className="relative flex size-32 items-center justify-center rounded-[2rem] border border-border/50 bg-background/45 shadow-inner"
            >
              <div className="absolute -left-2 top-6 h-16 w-20 rotate-[-8deg] rounded-2xl border border-border/45 bg-card/70" />
              <div className="absolute right-1 top-3 h-20 w-16 rotate-[10deg] rounded-2xl border border-primary/20 bg-primary/8" />
              <div className="relative flex size-16 items-center justify-center rounded-2xl border border-border/50 bg-card shadow-sm">
                <FileText className="size-8 text-primary/45" />
              </div>
              <div className="absolute bottom-5 h-1.5 w-16 rounded-full bg-primary/15" />
            </div>
            <p className="text-sm font-medium">
              {documents.length > 0 ? "未找到匹配文档" : "暂无文档，请上传知识"}
            </p>
          </div>);
        }
        else {
            return (<div style={{
                    height: `${rowVirtualizer.getTotalSize()}px`,
                    width: '100%',
                    position: 'relative'
                }}>
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                    const doc = results[virtualRow.index];
                    if (!doc)
                        return null;
                    return (<div key={virtualRow.key} data-index={virtualRow.index} ref={rowVirtualizer.measureElement} style={{
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            width: '100%',
                            transform: `translateY(${virtualRow.start}px)`,
                        }} className="pb-3">
                  <DocumentCard document={doc} index={virtualRow.index} isSelected={selectedDocIds.includes(doc.id)} onSelect={() => toggleDocumentSelection(doc.id)} onCancel={() => cancelDocument(doc.id)} onDelete={() => deleteDocument(doc.id)} getStatusIcon={getStatusIcon}/>
                </div>);
                })}
          </div>);
        }
})()}
      </div>
    </aside>
  )
}

// Alias export: keep a stable, explicit name for the knowledge-library sidebar.
export const KnowledgeSidebar = Sidebar

// 文档卡片组件 - 玻璃拟态与微交互
function DocumentCard({
  document,
  index,
  isSelected,
  onSelect,
  onCancel,
  onDelete,
  getStatusIcon,
}: Readonly<{
  document: Document
  index: number
  isSelected: boolean
  onSelect: () => void
  onCancel: () => void
  onDelete: () => void
  getStatusIcon: (status: string) => React.ReactNode
}>) {
  const parserBackend = (document.metadata?.parser_backend as string) || ''
  const parserLabel = parserBackend ? getParserLabel(parserBackend) : null
		    return (
		      <TiltCard
		      className={cn(
		        'group relative p-3 rounded-xl border cursor-pointer h-full transition-colors duration-200',
		        isSelected
		          ? 'bg-primary/8 border-primary/35 shadow-xs'
		          : 'bg-background/25 hover:bg-background/45 border-border/45 hover:border-primary/15'
	      )}
	      onClick={onSelect}
        selected={isSelected}
        ariaLabel={`选择文档：${document.filename}`}
	    >
      <div className="flex items-start gap-3">
        {/* 文件图标容器 */}
        <div className={cn(
          "p-2 rounded-lg transition-colors flex items-center justify-center",
          isSelected ? "bg-primary/10 text-primary" : "bg-secondary/70 text-muted-foreground group-hover:text-foreground"
        )}>
          <FileTypeIcon type={document.file_type} className="size-5" />
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
            <span className="text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-secondary text-secondary-foreground/70">
              {formatFileSize(document.file_size)}
            </span>
            <span className="text-[11px] text-muted-foreground/60">
              {formatDate(document.created_at)}
            </span>
          </div>

          {/* 处理进度 */}
          {(document.status === 'processing' || document.status === 'pending') && (
            <div className="mt-3">
              <PipelineVisualizer progress={document.processing_progress} className="py-2 scale-90 origin-left w-[110%]" />
              <div className="flex justify-between items-center mt-6">
                <p className="text-[11px] text-muted-foreground">
                  {document.current_stage || '处理中'}
                </p>
                <span className="text-[11px] font-mono text-primary/80">
                  {document.processing_progress}%
                </span>
              </div>
            </div>
          )}

	          {/* 属性标签 */}
	          {document.status === 'completed' && (
	            <div className="mt-2 flex flex-wrap gap-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100 motion-reduce:transition-none">
	              <span className="text-[11px] px-1.5 py-0.5 bg-secondary/80 rounded text-muted-foreground">
	                {document.chunk_count} 片段
	              </span>
              {parserLabel && (
                <span className="text-[11px] px-1.5 py-0.5 bg-secondary/80 rounded text-muted-foreground">
                  {parserLabel}
                </span>
              )}
            </div>
          )}

          {/* 错误信息 */}
          {(document.status === 'failed' || document.status === 'quarantined') && (
            <p
              className={cn(
                'text-[11px] mt-1 font-medium px-1.5 py-0.5 rounded inline-block',
                document.status === 'quarantined'
                  ? 'text-warning bg-warning/10 border border-warning/25'
                  : 'text-destructive bg-destructive/5'
              )}
            >
              {document.status === 'quarantined' ? '已隔离' : '处理失败'}
            </p>
          )}
        </div>
      </div>

		      {/* 悬浮操作栏 */}
		      <div className={cn(
		        "pointer-events-auto absolute right-2 top-2 flex flex-col gap-1 opacity-0 transition-opacity duration-200 ease-out group-hover:opacity-100 group-focus-within:opacity-100 motion-reduce:transition-none"
		      )}>
	        <DocumentDetailDialog document={document} trigger={
	          <Button
	            type="button"
	            variant="outline"
	            size="icon"
              onClick={(e) => {
                // Avoid triggering the card's click handler.
                e.stopPropagation()
              }}
	            className="size-8 rounded-md bg-background/80 shadow-xs hover:bg-primary hover:text-primary-foreground"
	            aria-label="查看详情"
	            title="查看详情"
	          >
	            <FileText className="size-3.5" aria-hidden="true" />
	          </Button>
	        } />

        {(document.status === 'processing' || document.status === 'pending') ? (
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={(e) => {
              e.stopPropagation()
              onCancel()
            }}
            aria-label="取消处理"
            title="取消处理"
            className="size-8 rounded-md bg-background/80 shadow-xs hover:bg-warning/10 hover:text-warning"
          >
            <X className="size-3.5" aria-hidden="true" />
          </Button>
        ) : (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={(e) => {
                  // Avoid triggering the card's click handler.
                  e.stopPropagation()
                }}
                aria-label="删除文档"
                title="删除文档"
                className="size-8 rounded-md bg-background/80 shadow-xs hover:bg-destructive hover:text-destructive-foreground"
              >
                <Trash2 className="size-3.5" aria-hidden="true" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>删除文档？</AlertDialogTitle>
                <AlertDialogDescription>
                  你将删除 <span className="font-mono">{document.filename}</span>。此操作不可撤销。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel onClick={(e) => e.stopPropagation()}>取消</AlertDialogCancel>
                <AlertDialogAction
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete()
                  }}
                >
                  删除
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
	      </div>
	    </TiltCard>
	  )
}
