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
    <header className="flex-shrink-0 h-20 border-b border-slate-200/80 flex justify-between items-center px-6 bg-white/80 backdrop-blur z-20 shadow-sm relative">
      <div className="flex items-center gap-4">
        {/* Logo Icon */}
        <div className="w-10 h-10 bg-gradient-to-br from-sky-500 to-blue-600 rounded-xl flex items-center justify-center shadow-sky-200/70 shadow-lg ring-1 ring-white/50">
          <Layers className="text-white w-5 h-5" />
        </div>
        
        <div className="flex flex-col justify-center min-w-0">
          {/* Row 1: Title & File Info */}
          <div className="flex items-center gap-3">
            <h1 className="text-xs font-bold text-slate-500 uppercase tracking-wider">切片预览</h1>
            <div className="h-3 w-px bg-slate-300" />
            <div className="flex items-center gap-2 min-w-0">
               <span className="text-sm font-bold text-slate-800 truncate max-w-[300px]" title={currentFileItem?.displayName || currentFile.name}>
                 {currentFileItem?.displayName || currentFile.name}
               </span>
               <div className="flex items-center gap-1.5">
                 <span className="text-[10px] font-bold bg-sky-100 text-sky-700 px-1.5 py-0.5 rounded-md min-w-[2rem] text-center">
                   #{currentFileIndex + 1}
                 </span>
                 {currentFileItem?.originalFileType && (
                    <span className="text-[10px] font-mono font-medium text-slate-500 border border-slate-200 px-1.5 py-0.5 rounded bg-slate-50">
                      {String(currentFileItem.originalFileType).toUpperCase()}
                    </span>
                 )}
                 <span className="text-[10px] text-slate-400 font-mono">
                   {formatFileSize(currentFileItem?.originalFileSize ?? currentFile.size)}
                 </span>
               </div>
            </div>
          </div>

          {/* Row 2: Process Configs & Stats */}
          <div className="flex items-center gap-3 mt-1.5">
             <div className="flex items-center gap-2 text-[11px] text-slate-600 bg-slate-50 border border-slate-100 px-2 py-0.5 rounded-md">
                <span className="text-slate-400">解析:</span>
                <span className="font-medium text-sky-700">{parserBackend}</span>
                <span className="w-px h-2.5 bg-slate-200 mx-0.5" />
                <span className="text-slate-400">策略:</span>
                <span className="font-medium text-sky-700">{chunkStrategy}</span>
                <span className="w-px h-2.5 bg-slate-200 mx-0.5" />
                <span className="text-slate-400">参数:</span>
                <span className="font-medium font-mono text-slate-700">{chunkSize}/{chunkOverlap}</span>
             </div>

             {(typeof lastPreviewDurationMs === 'number' || previewData) && (
               <div className="flex items-center gap-2 text-[11px]">
                  {typeof lastPreviewDurationMs === 'number' && (
                    <span className="text-slate-400 flex items-center gap-1">
                       <span className="w-1.5 h-1.5 rounded-full bg-slate-300" />
                       {lastPreviewDurationMs}ms
                    </span>
                  )}
                  {previewData && (
                    <span className="text-slate-600 font-medium flex items-center gap-1">
                       <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                       {previewData.total_chunks} Chunks
                    </span>
                  )}
               </div>
             )}

             {cacheHit && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-600 border border-emerald-100 font-medium">
                  Hit Cache
                </span>
             )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {submitSuccess && (
          <div className="flex items-center gap-1.5 text-green-600 text-xs font-medium bg-green-50 px-3 py-1.5 rounded-full border border-green-100 animate-in fade-in slide-in-from-right-4">
            <Check className="w-3.5 h-3.5" />
            已成功入库
          </div>
        )}

        {error && (
          <div className="flex items-center gap-1.5 text-red-600 text-xs bg-red-50 px-3 py-1.5 rounded-full border border-red-100 max-w-[300px] truncate">
            <AlertCircle className="w-3.5 h-3.5" />
            {error}
          </div>
        )}

        <div className="h-8 w-px bg-slate-200 mx-2" />

        <Button variant="ghost" size="sm" onClick={reset} className="text-slate-500 hover:text-slate-900 h-9 px-3 text-xs font-medium hover:bg-slate-100">
          <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
          重置
        </Button>

        {onClose && (
          <Button variant="ghost" size="sm" onClick={onClose} className="text-slate-400 hover:text-slate-700 h-9 w-9 p-0 rounded-full hover:bg-slate-100">
            <X className="w-4 h-4" />
          </Button>
        )}

        <Button
          onClick={submitChunks}
          disabled={!previewData || isSubmitting || submitSuccess}
          className={cn(
            'h-9 px-5 text-xs font-semibold rounded-lg shadow-lg transition-all',
            submitSuccess ? 'bg-green-600 hover:bg-green-700 shadow-green-200' : 'bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-600 hover:to-blue-700 shadow-sky-200'
          )}
        >
          {isSubmitting ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin mr-2" />
          ) : submitSuccess ? (
            <Check className="w-3.5 h-3.5 mr-2" />
          ) : (
            <Save className="w-3.5 h-3.5 mr-2" />
          )}
          {submitSuccess ? '已完成' : '确认入库'}
        </Button>
      </div>
      <div className="absolute inset-x-6 bottom-0 h-px bg-gradient-to-r from-transparent via-sky-200/70 to-transparent" />
    </header>
  )
}
