/**
 * TopBar - 工作台顶部栏
 */
'use client'

import {
  Layers,
  Save,
  RotateCcw,
  X,
  Check,
  AlertCircle,
  Loader2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useChunkPreview } from '@/components/chunk-preview/context'

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function TopBar() {
  const {
    currentFileIndex,
    fileList,
    currentFileItem,
    currentFile,
    previewData,
    parserBackend,
    chunkStrategy,
    chunkSize,
    chunkOverlap,
    lastPreviewDurationMs,
    cacheHit,
    submitSuccess,
    error,
    isSubmitting,
    submitChunks,
    reset,
    onClose,
  } = useChunkPreview()

  if (!currentFile || !currentFileItem) return null

  return (
    <header className="flex-shrink-0 h-20 border-b border-border/60 flex justify-between items-center px-6 bg-card/80 backdrop-blur z-20 shadow-sm relative">
      <div className="flex items-center gap-4">
        {/* Logo Icon */}
        <div className="w-10 h-10 bg-gradient-to-br from-primary to-info rounded-xl flex items-center justify-center shadow-primary/20 dark:shadow-primary/10 shadow-lg ring-1 ring-border/60">
          <Layers className="text-primary-foreground w-5 h-5" />
        </div>
        
        <div className="flex flex-col justify-center min-w-0">
          {/* Row 1: Title & File Info */}
          <div className="flex items-center gap-3">
            <h1 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">切片预览</h1>
            <div className="h-3 w-px bg-muted-foreground/40" />
            <div className="flex items-center gap-2 min-w-0">
               <span className="text-sm font-bold text-foreground truncate max-w-[300px]" title={currentFileItem?.displayName || currentFile.name}>
                 {currentFileItem?.displayName || currentFile.name}
               </span>
               <div className="flex items-center gap-1.5">
                 <span className="text-[10px] font-bold bg-primary/15 text-primary px-1.5 py-0.5 rounded-md min-w-[2rem] text-center">
                   #{currentFileIndex + 1}
                 </span>
                 {currentFileItem?.originalFileType && (
                    <span className="text-[10px] font-mono font-medium text-muted-foreground border border-border px-1.5 py-0.5 rounded bg-muted">
                      {String(currentFileItem.originalFileType).toUpperCase()}
                    </span>
                 )}
                 <span className="text-[10px] text-muted-foreground font-mono">
                   {formatFileSize(currentFileItem?.originalFileSize ?? currentFile.size)}
                 </span>
               </div>
            </div>
          </div>

          {/* Row 2: Process Configs & Stats */}
          <div className="flex items-center gap-3 mt-1.5">
             <div className="flex items-center gap-2 text-[11px] text-muted-foreground bg-muted border border-border px-2 py-0.5 rounded-md">
                <span className="text-muted-foreground">解析:</span>
                <span className="font-medium text-primary">{parserBackend}</span>
                <span className="w-px h-2.5 bg-border mx-0.5" />
                <span className="text-muted-foreground">策略:</span>
                <span className="font-medium text-primary">{chunkStrategy}</span>
                <span className="w-px h-2.5 bg-border mx-0.5" />
                <span className="text-muted-foreground">参数:</span>
                <span className="font-medium font-mono text-foreground/80">{chunkSize}/{chunkOverlap}</span>
             </div>

             {(typeof lastPreviewDurationMs === 'number' || previewData) && (
               <div className="flex items-center gap-2 text-[11px]">
                  {typeof lastPreviewDurationMs === 'number' && (
                    <span className="text-muted-foreground flex items-center gap-1">
                       <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40" />
                       {lastPreviewDurationMs}ms
                    </span>
                  )}
                  {previewData && (
                    <span className="text-muted-foreground font-medium flex items-center gap-1">
                       <span className="w-1.5 h-1.5 rounded-full bg-success" />
                       {previewData.total_chunks} Chunks
                    </span>
                  )}
               </div>
             )}

             {cacheHit && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-success/10 text-success border border-success/30 font-medium">
                  Hit Cache
                </span>
             )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {submitSuccess && (
          <div className="flex items-center gap-1.5 text-success text-xs font-medium bg-success/10 px-3 py-1.5 rounded-full border border-success/30 animate-in fade-in slide-in-from-right-4 motion-reduce:animate-none">
            <Check className="w-3.5 h-3.5" />
            已成功入库
          </div>
        )}

        {error && (
          <div className="flex items-center gap-1.5 text-destructive text-xs bg-destructive/10 px-3 py-1.5 rounded-full border border-destructive/30 max-w-[300px] truncate">
            <AlertCircle className="w-3.5 h-3.5" />
            {error}
          </div>
        )}

        <div className="h-8 w-px bg-border mx-2" />

        <Button variant="ghost" size="sm" onClick={reset} className="text-muted-foreground hover:text-foreground h-9 px-3 text-xs font-medium hover:bg-muted">
          <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
          重置
        </Button>

	        {onClose && (
	          <Button
	            variant="ghost"
	            size="sm"
	            onClick={onClose}
	            className="text-muted-foreground hover:text-foreground/80 h-9 w-9 p-0 rounded-full hover:bg-muted"
	            aria-label="关闭"
	            title="关闭"
	          >
	            <X className="w-4 h-4" />
	          </Button>
	        )}

        <Button
          onClick={submitChunks}
          disabled={!previewData || isSubmitting || submitSuccess}
          className={cn(
            'h-9 px-5 text-xs font-semibold rounded-lg shadow-lg transition-all motion-reduce:transition-none',
            submitSuccess
              ? 'bg-success text-success-foreground hover:bg-success/90 shadow-success/20'
              : 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-primary/20'
          )}
        >
	          {isSubmitting ? (
	            <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none mr-2" />
	          ) : submitSuccess ? (
            <Check className="w-3.5 h-3.5 mr-2" />
          ) : (
            <Save className="w-3.5 h-3.5 mr-2" />
          )}
          {submitSuccess ? '已完成' : '确认入库'}
        </Button>
      </div>
      <div className="absolute inset-x-6 bottom-0 h-px bg-gradient-to-r from-transparent via-primary/20 to-transparent" />
    </header>
  )
}
