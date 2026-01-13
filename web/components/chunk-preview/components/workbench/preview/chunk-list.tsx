/**
 * ChunkList - 切片列表区（右侧）
 */
'use client'

import { useMemo, useState } from 'react'
import { Layers, MousePointer2, Loader2, AlertCircle, Search } from 'lucide-react'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkCard } from '../../chunk-card'
import type { ChunkPreviewItem } from '@/types'

export function ChunkList() {
  const { previewData, hoveredChunkIndex, setHoveredChunkIndex, isLoading, error, runPreview } = useChunkPreview()
  const [query, setQuery] = useState('')

  const filteredChunks = useMemo(() => {
    if (!previewData?.chunks) return []
    const q = query.trim().toLowerCase()
    return previewData.chunks
      .map((chunk: ChunkPreviewItem, index: number) => ({ chunk, index }))
      .filter(({ chunk }) => (q ? (chunk.content || '').toLowerCase().includes(q) : true))
  }, [previewData, query])

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-gray-50/30">
      <div className="h-12 border-b border-gray-200 bg-white flex items-center justify-between px-4 shrink-0 gap-3">
        <span className="text-xs font-semibold text-blue-600 flex items-center gap-2">
          <Layers className="w-3.5 h-3.5" />
          切片结果
          {previewData?.total_chunks ? (
            <span className="text-[10px] text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
              {previewData.total_chunks}
            </span>
          ) : null}
        </span>
        <div className="flex items-center gap-2 flex-1 justify-end">
          <div className="relative w-48">
            <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2 top-1/2 -translate-y-1/2" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索切片内容"
              className="w-full h-7 pl-7 pr-2 text-[11px] rounded-lg border border-gray-200 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-100"
            />
          </div>
          <div className="flex items-center gap-2 text-[10px] text-gray-400">
            <MousePointer2 className="w-3 h-3" />
            悬停卡片高亮原文
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
        {previewData?.chunks ? (
          filteredChunks.map(({ chunk, index }) => (
            <ChunkCard
              key={index}
              chunk={chunk}
              index={index}
              isHovered={hoveredChunkIndex === index}
              onMouseEnter={() => setHoveredChunkIndex(index)}
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
            <p className="text-[10px] text-gray-400 max-w-xs text-center">{error}</p>
            <button
              type="button"
              onClick={runPreview}
              className="mt-2 text-[10px] px-3 py-1 rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200"
            >
              重试预览
            </button>
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
