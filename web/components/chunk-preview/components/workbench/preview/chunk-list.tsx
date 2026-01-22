/**
 * ChunkList - ?????????
 */
'use client'

import { useMemo, useState } from 'react'
import { Layers, MousePointer2, Loader2, AlertCircle, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
      .filter(({ chunk }: { chunk: ChunkPreviewItem }) => (q ? (chunk.content || '').toLowerCase().includes(q) : true))
  }, [previewData, query])

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background/60">
      <div className="h-12 border-b border-border/60 bg-card/80 flex items-center justify-between px-4 shrink-0 gap-3 backdrop-blur">
        <span className="text-xs font-semibold text-primary flex items-center gap-2">
          <Layers className="w-3.5 h-3.5" />
          切片列表
          {previewData?.total_chunks ? (
            <span className="text-[10px] text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded-full">
              {previewData.total_chunks}
            </span>
          ) : null}
        </span>
        <div className="flex items-center gap-2 flex-1 justify-end">
          <div className="relative w-48">
            <Search className="w-3.5 h-3.5 text-muted-foreground absolute left-2 top-1/2 -translate-y-1/2" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索切片内容..."
              className="h-7 pl-7 pr-2 text-[11px] bg-card/80"
            />
          </div>
          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
            <MousePointer2 className="w-3 h-3" />
            悬停查看对应原文
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
        <div className="min-h-full rounded-2xl border border-border/60 bg-card/70 p-3 shadow-sm backdrop-blur ring-1 ring-border/40 space-y-3">
          {previewData?.chunks ? (
            filteredChunks.length > 0 ? (
              filteredChunks.map(({ chunk, index }: { chunk: ChunkPreviewItem; index: number }) => (
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
              <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
                <Search className="w-10 h-10 opacity-20" />
                <p className="text-xs text-muted-foreground">未找到匹配切片</p>
              </div>
            )
          ) : isLoading ? (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none opacity-20" />
              <p className="text-xs">生成中...</p>
            </div>
          ) : error ? (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <AlertCircle className="w-10 h-10 opacity-20" />
              <p className="text-xs text-muted-foreground">生成预览失败</p>
              <p className="text-[10px] text-muted-foreground max-w-xs text-center">{error}</p>
              <Button variant="outline" size="sm" className="mt-2 h-8 px-3 text-[11px]" onClick={() => runPreview()}>
                重试
              </Button>
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-2 py-12">
              <Layers className="w-12 h-12 opacity-10" />
              <p className="text-xs">等待生成预览</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
