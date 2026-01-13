/**
 * ChunkCard - 单个切片卡片
 */
'use client'

import { cn } from '@/lib/utils'
import type { ChunkPreviewItem } from '@/types'

interface ChunkCardProps {
  chunk: ChunkPreviewItem
  index: number
  isHovered: boolean
  onMouseEnter: () => void
  onMouseLeave: () => void
}

export function ChunkCard({ chunk, index, isHovered, onMouseEnter, onMouseLeave }: ChunkCardProps) {
  return (
    <div
      className={cn(
        'group relative bg-white p-4 rounded-xl border transition-all duration-200 cursor-default',
        isHovered
          ? 'border-amber-400 shadow-md ring-1 ring-amber-100 -translate-y-0.5 z-10'
          : 'border-amber-200 hover:border-amber-300 hover:shadow-sm'
      )}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'text-[10px] font-mono font-bold px-1.5 py-0.5 rounded',
              isHovered ? 'bg-amber-100 text-amber-700' : 'bg-amber-100/70 text-amber-700'
            )}
          >
            #{index + 1}
          </span>
          <span className="text-[10px] text-stone-400 font-mono">{chunk.length} chars</span>
        </div>
        {chunk.page_number && (
          <span className="text-[10px] text-stone-400 bg-amber-50 px-1.5 py-0.5 rounded">P.{chunk.page_number}</span>
        )}
      </div>

      <div className={cn('text-sm font-mono leading-relaxed whitespace-pre-wrap break-all transition-colors', isHovered ? 'text-stone-900' : 'text-stone-600')}>
        {chunk.content}
      </div>
    </div>
  )
}
