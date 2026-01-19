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
        'group relative bg-card/85 p-4 rounded-xl border transition-all duration-200 cursor-default backdrop-blur',
        isHovered
          ? 'border-sky-400/70 shadow-lg shadow-sky-500/10 ring-1 ring-sky-500/20 -translate-y-0.5 z-10'
          : 'border-border hover:border-sky-300/50 hover:shadow-md hover:shadow-sky-500/10'
      )}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'text-[10px] font-mono font-bold px-1.5 py-0.5 rounded',
              isHovered
                ? 'bg-sky-500/20 text-sky-700 dark:text-sky-300'
                : 'bg-sky-500/10 text-sky-700 dark:text-sky-300'
            )}
          >
            #{index + 1}
          </span>
          <span className="text-[10px] text-muted-foreground font-mono">{chunk.length} chars</span>
        </div>
        {chunk.page_number && (
          <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">P.{chunk.page_number}</span>
        )}
      </div>

      <div
        className={cn(
          'text-sm font-mono leading-relaxed whitespace-pre-wrap break-all transition-colors',
          isHovered ? 'text-foreground' : 'text-muted-foreground'
        )}
      >
        {chunk.content}
      </div>
    </div>
  )
}
