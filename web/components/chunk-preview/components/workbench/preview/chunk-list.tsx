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
    <div className="flex-1 flex flex-col min-w-0 bg-amber-50/40">
      <div className="h-12 border-b border-amber-100/70 bg-white/80 flex items-center justify-between px-4 shrink-0 gap-3">
        <span className="text-xs font-semibold text-amber-700 flex items-center gap-2">
          <Layers className="w-3.5 h-3.5" />
          切片结果
          {previewData?.total_chunks ? (
            <span className="text-[10px] text-amber-700 bg-amber-100/70 px-2 py-0.5 rounded-full">
              {previewData.total_chunks}
            </span>
          ) : null}
        </span>
        <div className="flex items-center gap-2 flex-1 justify-end">
          <div className="relative w-48">
            <Search className="w-3.5 h-3.5 text-stone-400 absolute left-2 top-1/2 -translate-y-1/2" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索切片内容"
              className="w-full h-7 pl-7 pr-2 text-[11px] rounded-lg border border-amber-100/70 bg-white/80 focus:outline-none focus:ring-2 focus:ring-amber-200"
            />
          </div>
          <div className="flex items-center gap-2 text-[10px] text-stone-400">
            <MousePointer2 className="w-3 h-3" />
            悬停卡片高亮原文
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
        {previewData?.chunks ? (
          filteredChunks.length > 0 ? (
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
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-stone-300 gap-2">
              <Search className="w-10 h-10 opacity-20" />
              <p className="text-xs text-stone-400">没有匹配的切片</p>
            </div>
          )
        ) : isLoading ? (
          <div className="h-full flex flex-col items-center justify-center text-stone-400 gap-2">
            <Loader2 className="w-8 h-8 animate-spin opacity-20" />
            <p className="text-xs">切片中...</p>
          </div>
        ) : error ? (
          <div className="h-full flex flex-col items-center justify-center text-stone-400 gap-2">
            <AlertCircle className="w-10 h-10 opacity-20" />
            <p className="text-xs text-stone-500">预览生成失败</p>
            <p className="text-[10px] text-stone-400 max-w-xs text-center">{error}</p>
            <button
              type="button"
              onClick={runPreview}
              className="mt-2 text-[10px] px-3 py-1 rounded-full bg-amber-100/70 text-amber-700 hover:bg-amber-100"
            >
              重试预览
            </button>
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-stone-300 gap-2">
            <Layers className="w-12 h-12 opacity-10" />
            <p className="text-xs">等待生成预览</p>
          </div>
        )}
      </div>
    </div>
  )
}
