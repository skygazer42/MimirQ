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
          ? 'border-blue-400 shadow-md ring-1 ring-blue-100 -translate-y-0.5 z-10'
          : 'border-gray-200 hover:border-blue-300 hover:shadow-sm'
      )}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'text-[10px] font-mono font-bold px-1.5 py-0.5 rounded',
              isHovered ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
            )}
          >
            #{index + 1}
          </span>
          <span className="text-[10px] text-gray-400 font-mono">{chunk.length} chars</span>
        </div>
        {chunk.page_number && (
          <span className="text-[10px] text-gray-400 bg-gray-50 px-1.5 py-0.5 rounded">P.{chunk.page_number}</span>
        )}
      </div>

      <div className={cn('text-sm font-mono leading-relaxed whitespace-pre-wrap break-all transition-colors', isHovered ? 'text-gray-900' : 'text-gray-600')}>
        {chunk.content}
      </div>
    </div>
  )
}
