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
        'group relative bg-white/85 p-4 rounded-xl border transition-all duration-200 cursor-default backdrop-blur',
        isHovered
          ? 'border-sky-400 shadow-lg shadow-sky-200/30 ring-1 ring-sky-100 -translate-y-0.5 z-10'
          : 'border-slate-200 hover:border-sky-300 hover:shadow-md hover:shadow-sky-200/20'
      )}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'text-[10px] font-mono font-bold px-1.5 py-0.5 rounded',
              isHovered ? 'bg-sky-100 text-sky-700' : 'bg-sky-100/70 text-sky-700'
            )}
          >
            #{index + 1}
          </span>
          <span className="text-[10px] text-slate-400 font-mono">{chunk.length} chars</span>
        </div>
        {chunk.page_number && (
          <span className="text-[10px] text-slate-400 bg-slate-50 px-1.5 py-0.5 rounded">P.{chunk.page_number}</span>
        )}
      </div>

      <div className={cn('text-sm font-mono leading-relaxed whitespace-pre-wrap break-all transition-colors', isHovered ? 'text-slate-900' : 'text-slate-600')}>
        {chunk.content}
      </div>
    </div>
  )
}
