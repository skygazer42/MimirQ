/**
 * ChunkList - 切片列表区（右侧）
 */
'use client'

import { Layers, MousePointer2, Loader2, AlertCircle } from 'lucide-react'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkCard } from '../../chunk-card'
import type { ChunkPreviewItem } from '@/types'

export function ChunkList() {
  const { previewData, hoveredChunkIndex, setHoveredChunkIndex, isLoading, error } = useChunkPreview()

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-gray-50/30">
      <div className="h-10 border-b border-gray-200 bg-white flex items-center justify-between px-4 shrink-0">
        <span className="text-xs font-semibold text-blue-600 flex items-center gap-2">
          <Layers className="w-3.5 h-3.5" />
          切片结果
        </span>
        <div className="flex items-center gap-2 text-[10px] text-gray-400">
          <MousePointer2 className="w-3 h-3" />
          悬停卡片高亮原文
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
        {previewData?.chunks ? (
          previewData.chunks.map((chunk: ChunkPreviewItem, idx: number) => (
            <ChunkCard
              key={idx}
              chunk={chunk}
              index={idx}
              isHovered={hoveredChunkIndex === idx}
              onMouseEnter={() => setHoveredChunkIndex(idx)}
              onMouseLeave={() => setHoveredChunkIndex(null)}
            />
          ))
        ) : isLoading ? (
          <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-2">
            <Loader2 className="w-8 h-8 animate-spin opacity-20" />
            <p className="text-xs">切片中...</p>
          </div>
        ) : error ? (
          <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-2">
            <AlertCircle className="w-10 h-10 opacity-20" />
            <p className="text-xs text-gray-500">预览生成失败</p>
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-gray-300 gap-2">
            <Layers className="w-12 h-12 opacity-10" />
            <p className="text-xs">等待生成预览</p>
          </div>
        )}
      </div>
    </div>
  )
}
