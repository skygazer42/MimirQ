/**
 * ChunkCard - 单个切片卡片
 */
'use client'

import { useCallback, useMemo } from 'react'
import { Copy, Braces, Pin, PinOff } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ChunkPreviewItem } from '@/types'

interface ChunkCardProps {
  chunk: ChunkPreviewItem
  index: number
  isHovered: boolean
  isSelected: boolean
  query?: string
  onMouseEnter: () => void
  onMouseLeave: () => void
  onToggleSelect: () => void
}

function highlightText(text: string, rawQuery?: string) {
  const query = (rawQuery || '').trim()
  if (!query) return text

  const qLower = query.toLowerCase()
  const lower = text.toLowerCase()

  const out: Array<string | JSX.Element> = []
  let cursor = 0
  let matches = 0
  const MAX_MATCHES = 50

  while (cursor < text.length) {
    const idx = lower.indexOf(qLower, cursor)
    if (idx === -1) {
      out.push(text.slice(cursor))
      break
    }
    if (idx > cursor) out.push(text.slice(cursor, idx))
    const end = Math.min(text.length, idx + query.length)
    out.push(
      <mark
        key={`${idx}-${end}-${matches}`}
        className="rounded bg-primary/15 text-foreground px-0.5 py-[1px]"
      >
        {text.slice(idx, end)}
      </mark>
    )
    cursor = end
    matches += 1
    if (matches >= MAX_MATCHES) {
      out.push(text.slice(cursor))
      break
    }
  }

  return out
}

export function ChunkCard({
  chunk,
  index,
  isHovered,
  isSelected,
  query,
  onMouseEnter,
  onMouseLeave,
  onToggleSelect,
}: ChunkCardProps) {
  const rangeLabel = useMemo(() => `${chunk.start_index}-${chunk.end_index}`, [chunk.start_index, chunk.end_index])

  const copyText = useCallback(async (text: string, okMsg: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
        toast.success(okMsg)
        return
      }
    } catch {
      // ignore
    }
    toast.error('复制失败：浏览器不支持 Clipboard API')
  }, [])

  return (
    <div
      className={cn(
        'group relative bg-card/85 p-4 rounded-xl border transition-all duration-200 cursor-pointer backdrop-blur focus-within:ring-1 focus-within:ring-ring/20',
        isSelected
          ? 'border-primary/45 shadow-lg shadow-primary/10 ring-1 ring-primary/20'
          : isHovered
            ? 'border-primary/30 shadow-md shadow-primary/10 ring-1 ring-ring/10 motion-safe:-translate-y-0.5 z-10'
            : 'border-border hover:border-primary/25 hover:shadow-sm hover:shadow-primary/10'
      )}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onClick={onToggleSelect}
      role="button"
      aria-label={`切片 #${index + 1}`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'text-[10px] font-mono font-bold px-1.5 py-0.5 rounded',
              isSelected || isHovered ? 'bg-primary/15 text-primary' : 'bg-primary/10 text-primary'
            )}
          >
            #{index + 1}
          </span>
          <span className="text-[10px] text-muted-foreground font-mono">{chunk.length} chars</span>
          <span className="text-[10px] text-muted-foreground font-mono" title="start-end">
            {rangeLabel}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {chunk.page_number != null && (
            <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">P.{chunk.page_number}</span>
          )}
          <div className={cn('flex items-center gap-1', 'opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity')}>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={(e) => {
                e.stopPropagation()
                void copyText(chunk.content || '', '已复制切片内容')
              }}
              aria-label="复制切片内容"
              title="复制切片内容"
            >
              <Copy className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={(e) => {
                e.stopPropagation()
                void copyText(JSON.stringify(chunk, null, 2), '已复制切片 JSON')
              }}
              aria-label="复制切片 JSON"
              title="复制切片 JSON"
            >
              <Braces className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={(e) => {
                e.stopPropagation()
                onToggleSelect()
              }}
              aria-label={isSelected ? '取消锁定切片' : '锁定切片'}
              title={isSelected ? '取消锁定切片' : '锁定切片'}
            >
              {isSelected ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </div>

      <div
        className={cn(
          'text-sm font-mono leading-relaxed whitespace-pre-wrap break-words transition-colors',
          isSelected || isHovered ? 'text-foreground' : 'text-muted-foreground'
        )}
      >
        {highlightText(chunk.content || '', query)}
      </div>
    </div>
  )
}
