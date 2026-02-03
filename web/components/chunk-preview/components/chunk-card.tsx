/**
 * ChunkCard - 单个切片卡片
 */
'use client'

import { useCallback, useMemo } from 'react'
import { Copy, Braces, Pin, PinOff, Quote, Pencil, Eye, EyeOff, Link2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ChunkPreviewItem } from '@/types'
import { getChunkSectionLabel } from '@/components/chunk-preview/utils/sections'

interface ChunkCardProps {
  chunk: ChunkPreviewItem
  index: number
  unit?: 'chars' | 'tokens'
  sourceFilename?: string
  isHovered: boolean
  isSelected: boolean
  isShort?: boolean
  isDuplicate?: boolean
  isGap?: boolean
  gapBefore?: number
  isOverlap?: boolean
  overlapPrev?: number
  isEdited?: boolean
  isDisabled?: boolean
  query?: string
  onMouseEnter: () => void
  onMouseLeave: () => void
  onToggleSelect: () => void
  onEdit?: () => void
  onToggleDisabled?: () => void
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
  unit = 'chars',
  sourceFilename,
  isHovered,
  isSelected,
  isShort,
  isDuplicate,
  isGap,
  gapBefore,
  isOverlap,
  overlapPrev,
  isEdited,
  isDisabled,
  query,
  onMouseEnter,
  onMouseLeave,
  onToggleSelect,
  onEdit,
  onToggleDisabled,
}: ChunkCardProps) {
  const rangeLabel = useMemo(() => `${chunk.start_index}-${chunk.end_index}`, [chunk.start_index, chunk.end_index])
  const tokens = useMemo(() => (typeof chunk.tokens_est === 'number' ? chunk.tokens_est : null), [chunk.tokens_est])
  const chunkRole = (chunk.metadata as Record<string, any> | undefined)?.chunk_role as string | undefined
  const sectionLabel = useMemo(() => getChunkSectionLabel(chunk), [chunk])
  const citationText = useMemo(() => {
    const name = (sourceFilename || '').trim() || 'document'
    const pageLabel = chunk.page_number != null ? ` · P.${chunk.page_number}` : ''
    const tokLabel = tokens != null ? ` · ${tokens} tok` : ''
    const fence = '````'
    const raw = String(chunk.content || '').trim()
    const excerpt = raw.length > 2000 ? `${raw.slice(0, 2000)}…` : raw
    return [
      `【${name} · chunk #${index + 1}${pageLabel}${tokLabel} · ${rangeLabel}】`,
      `${fence}text`,
      excerpt,
      fence,
    ].join('\n')
  }, [chunk.content, chunk.page_number, index, rangeLabel, sourceFilename, tokens])

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
        'group relative bg-card p-4 rounded-xl border transition-colors transition-shadow duration-200 motion-reduce:transition-none cursor-pointer focus-within:ring-1 focus-within:ring-ring/20',
        isSelected
          ? 'border-primary/45 shadow-lg shadow-primary/10 ring-1 ring-primary/20'
          : isHovered
            ? 'border-primary/30 shadow-sm shadow-primary/10 ring-1 ring-ring/10 z-10'
            : 'border-border hover:border-primary/25 hover:shadow-sm hover:shadow-primary/10',
        isDisabled && !isSelected && !isHovered ? 'opacity-60' : ''
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
          {isDisabled ? (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground border border-border/60">
              SKIP
            </span>
          ) : null}

          {isEdited ? (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-info/10 text-info border border-info/25">
              EDIT
            </span>
          ) : null}
          {isDuplicate ? (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/25">
              DUP
            </span>
          ) : null}
          {isShort ? (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/25">
              SHORT
            </span>
          ) : null}
          {isGap ? (
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-destructive/10 text-destructive border border-destructive/25"
              title={typeof gapBefore === 'number' ? `gap_before: ${gapBefore}` : undefined}
            >
              GAP
            </span>
          ) : null}
          {isOverlap ? (
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/25"
              title={typeof overlapPrev === 'number' ? `overlap_prev: ${overlapPrev}` : undefined}
            >
              OVR
            </span>
          ) : null}
          {chunkRole === 'parent' ? (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/25">
              PARENT
            </span>
          ) : chunkRole === 'child' ? (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground border border-border/60">
              CHILD
            </span>
          ) : null}
          {sectionLabel ? (
            <span
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground border border-border/60 max-w-[180px] truncate"
              title={sectionLabel.full}
            >
              {sectionLabel.short}
            </span>
          ) : null}
          {unit === 'tokens' ? (
            <>
              <span className="text-[10px] text-muted-foreground font-mono">{tokens ?? '-'} tok</span>
              <span className="text-[10px] text-muted-foreground font-mono">{chunk.length} chars</span>
            </>
          ) : (
            <span
              className="text-[10px] text-muted-foreground font-mono"
              title={tokens != null ? `${chunk.length} chars · ${tokens} tok` : `${chunk.length} chars`}
            >
              {chunk.length} chars
            </span>
          )}
          <span className="text-[10px] text-muted-foreground font-mono" title="start-end">
            {rangeLabel}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {chunk.page_number != null && (
            <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">P.{chunk.page_number}</span>
          )}
          <div className={cn('flex items-center gap-1', 'opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity')}>
            {onEdit ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={(e) => {
                  e.stopPropagation()
                  onEdit()
                }}
                aria-label="编辑切片"
                title="编辑切片"
              >
                <Pencil className="h-4 w-4" />
              </Button>
            ) : null}
            {onToggleDisabled ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={(e) => {
                  e.stopPropagation()
                  onToggleDisabled()
                }}
                aria-label={isDisabled ? 'Enable chunk' : 'Skip chunk'}
                title={isDisabled ? 'Enable chunk' : 'Skip chunk'}
              >
                {isDisabled ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}
              </Button>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={(e) => {
                e.stopPropagation()
                void copyText(citationText, '已复制引用')
              }}
              aria-label="复制引用"
              title="复制引用"
            >
              <Quote className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={(e) => {
                e.stopPropagation()
                try {
                  const url = new URL(window.location.href)
                  url.searchParams.set('chunk', String(index + 1))
                  void copyText(url.toString(), '已复制链接')
                } catch {
                  toast.error('无法生成链接')
                }
              }}
              aria-label="复制链接"
              title="复制链接"
            >
              <Link2 className="h-4 w-4" />
            </Button>
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
          'text-sm font-sans leading-relaxed whitespace-pre-wrap break-words transition-colors',
          isSelected || isHovered ? 'text-foreground' : 'text-muted-foreground'
        )}
      >
        {highlightText(chunk.content || '', query)}
      </div>
    </div>
  )
}
