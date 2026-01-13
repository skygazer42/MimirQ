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
    <header className="flex-shrink-0 h-16 border-b border-amber-100/80 flex justify-between items-center px-6 bg-amber-50/70 backdrop-blur z-20 shadow-sm relative">
      <div className="flex items-center gap-4">
        <div className="w-9 h-9 bg-gradient-to-br from-amber-500 to-rose-500 rounded-xl flex items-center justify-center shadow-amber-200/70 shadow-md">
          <Layers className="text-white w-5 h-5" />
        </div>
        <div>
          <h1 className="text-sm font-bold text-stone-900 tracking-tight">切片预览工作台</h1>
          <p className="text-[10px] text-stone-500 font-mono mt-0.5 flex items-center gap-2">
            <span className="bg-amber-100/80 px-2 py-0.5 rounded-full text-amber-800 font-semibold">
              {currentFileIndex + 1}/{fileList.length}
            </span>
            <span>{currentFileItem?.displayName || currentFile.name}</span>
            {currentFileItem?.originalFileType && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-100/70 text-amber-700">
                {String(currentFileItem.originalFileType).toUpperCase()}
              </span>
            )}
            <span className="w-1 h-1 rounded-full bg-amber-200" />
            <span>{formatFileSize(currentFileItem?.originalFileSize ?? currentFile.size)}</span>
            {previewData && (
              <>
                <span className="w-1 h-1 rounded-full bg-amber-200" />
                <span className="text-amber-700 font-semibold">{previewData.total_chunks} Chunks</span>
              </>
            )}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-stone-500">
            <span className="px-2 py-0.5 rounded-full bg-amber-100/70 text-amber-700">解析器: {parserBackend}</span>
            <span className="px-2 py-0.5 rounded-full bg-amber-100/70 text-amber-700">策略: {chunkStrategy}</span>
            <span className="px-2 py-0.5 rounded-full bg-amber-100/70 text-amber-700">
              大小: {chunkSize} / 重叠: {chunkOverlap}
            </span>
            {typeof lastPreviewDurationMs === 'number' && (
              <span className="px-2 py-0.5 rounded-full bg-amber-100/70 text-amber-700">
                用时: {lastPreviewDurationMs}ms
              </span>
            )}
            {cacheHit && (
              <span className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-100">
                缓存命中
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

        <div className="h-6 w-px bg-amber-100 mx-2" />

        <Button variant="ghost" size="sm" onClick={reset} className="text-stone-500 hover:text-stone-900 h-8 text-xs font-medium">
          <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
          重置
        </Button>

        {onClose && (
          <Button variant="ghost" size="sm" onClick={onClose} className="text-stone-500 hover:text-stone-900 h-8 w-8 p-0 rounded-full">
            <X className="w-4 h-4" />
          </Button>
        )}

        <Button
          onClick={submitChunks}
          disabled={!previewData || isSubmitting || submitSuccess}
          className={cn(
            'h-9 px-5 text-xs font-semibold rounded-lg shadow-lg transition-all',
            submitSuccess ? 'bg-green-600 hover:bg-green-700 shadow-green-200' : 'bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-600 hover:to-rose-600 shadow-amber-200'
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
    </header>
  )
}
