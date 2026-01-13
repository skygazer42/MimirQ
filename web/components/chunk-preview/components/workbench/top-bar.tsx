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
    <header className="flex-shrink-0 h-16 border-b border-gray-200 flex justify-between items-center px-6 bg-white/80 backdrop-blur z-20 shadow-sm relative">
      <div className="flex items-center gap-4">
        <div className="w-9 h-9 bg-gradient-to-br from-indigo-600 to-blue-600 rounded-xl flex items-center justify-center shadow-blue-200/70 shadow-md">
          <Layers className="text-white w-5 h-5" />
        </div>
        <div>
          <h1 className="text-sm font-bold text-gray-900 tracking-tight">切片预览工作台</h1>
          <p className="text-[10px] text-gray-500 font-mono mt-0.5 flex items-center gap-2">
            <span className="bg-gray-100 px-2 py-0.5 rounded-full text-gray-600 font-semibold">
              {currentFileIndex + 1}/{fileList.length}
            </span>
            <span>{currentFileItem?.displayName || currentFile.name}</span>
            {currentFileItem?.originalFileType && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
                {String(currentFileItem.originalFileType).toUpperCase()}
              </span>
            )}
            <span className="w-1 h-1 rounded-full bg-gray-300" />
            <span>{formatFileSize(currentFileItem?.originalFileSize ?? currentFile.size)}</span>
            {previewData && (
              <>
                <span className="w-1 h-1 rounded-full bg-gray-300" />
                <span className="text-blue-600 font-semibold">{previewData.total_chunks} Chunks</span>
              </>
            )}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-gray-500">
            <span className="px-2 py-0.5 rounded-full bg-gray-100">解析器: {parserBackend}</span>
            <span className="px-2 py-0.5 rounded-full bg-gray-100">策略: {chunkStrategy}</span>
            <span className="px-2 py-0.5 rounded-full bg-gray-100">
              大小: {chunkSize} / 重叠: {chunkOverlap}
            </span>
            {typeof lastPreviewDurationMs === 'number' && (
              <span className="px-2 py-0.5 rounded-full bg-gray-100">
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

        <div className="h-6 w-px bg-gray-200 mx-2" />

        <Button variant="ghost" size="sm" onClick={reset} className="text-gray-500 hover:text-gray-900 h-8 text-xs font-medium">
          <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
          重置
        </Button>

        {onClose && (
          <Button variant="ghost" size="sm" onClick={onClose} className="text-gray-500 hover:text-gray-900 h-8 w-8 p-0 rounded-full">
            <X className="w-4 h-4" />
          </Button>
        )}

        <Button
          onClick={submitChunks}
          disabled={!previewData || isSubmitting || submitSuccess}
          className={cn(
            'h-9 px-5 text-xs font-semibold rounded-lg shadow-lg transition-all',
            submitSuccess ? 'bg-green-600 hover:bg-green-700 shadow-green-200' : 'bg-blue-600 hover:bg-blue-700 shadow-blue-200'
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
