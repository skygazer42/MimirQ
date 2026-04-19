/**
 * ChunkCard - 单个切片卡片
 */
'use client'

import { useCallback, useMemo } from 'react'
import type { ReactNode } from 'react'
import { Copy, Braces, Pin, PinOff, Quote, Pencil, Eye, EyeOff, Link2 } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { chunkNeedsReview, getChunkMetadata, getSemanticQualityMetadata, getStringValue } from '@/components/chunk-preview/utils/metadata'
import { cn, detachPromise } from '@/lib/utils'
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

  const out: ReactNode[] = []
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
}: Readonly<ChunkCardProps>) {
  const t = useTranslations('ChunkPreview')
  const rangeLabel = useMemo(() => `${chunk.start_index}-${chunk.end_index}`, [chunk.start_index, chunk.end_index])
  const tokens = useMemo(() => (typeof chunk.tokens_est === 'number' ? chunk.tokens_est : null), [chunk.tokens_est])
  const chunkMetadata = getChunkMetadata(chunk)
  const chunkRole = getStringValue(chunkMetadata, 'chunk_role')
  const sectionLabel = useMemo(() => getChunkSectionLabel(chunk), [chunk])
  const semanticQuality = getSemanticQualityMetadata(chunk)
  const needsReview = chunkNeedsReview(chunk)
  const needsReviewTitle = useMemo(() => {
    if (!needsReview) return undefined
    const reasons = semanticQuality?.reasons ?? []
    return reasons.length > 0 ? `needs_review: ${reasons.join(', ')}` : 'needs_review'
  }, [needsReview, semanticQuality?.reasons])
  const citationText = useMemo(() => {
    const name = (sourceFilename || '').trim() || t('chunkCard.documentFallback')
    const pageLabel = chunk.page_number == null ? '' : ` · P.${chunk.page_number}`
    const tokLabel = tokens == null ? '' : ` · ${tokens} tok`
    const fence = '````'
    const raw = String(chunk.content || '').trim()
    const excerpt = raw.length > 2000 ? `${raw.slice(0, 2000)}…` : raw
    return [
      `【${name} · chunk #${index + 1}${pageLabel}${tokLabel} · ${rangeLabel}】`,
      `${fence}text`,
      excerpt,
      fence,
    ].join('\n')
  }, [chunk.content, chunk.page_number, index, rangeLabel, sourceFilename, t, tokens])

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
    toast.error(t('chunkCard.copyClipboardUnsupported'))
  }, [t])

  return (
    <div
      className={cn(
        'group relative bg-card p-4 rounded-xl border transition-colors transition-shadow duration-200 motion-reduce:transition-none cursor-pointer focus-within:ring-1 focus-within:ring-ring/20',
        (() => {
    if (isSelected) {
        return 'border-primary/45 shadow-lg shadow-primary/10 ring-1 ring-primary/20';
    }
    else if (isHovered) {
            return 'border-primary/30 shadow-sm shadow-primary/10 ring-1 ring-ring/10 z-10';
        }
        else {
            return 'border-border hover:border-primary/25 hover:shadow-sm hover:shadow-primary/10';
        }
})(),
        isDisabled && !isSelected && !isHovered ? 'opacity-60' : ''
      )}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onClick={onToggleSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onToggleSelect()
        }
      }}
      aria-label={t('chunkCard.ariaLabel', { index: index + 1 })}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'text-[11px] font-mono font-bold px-1.5 py-0.5 rounded',
              isSelected || isHovered ? 'bg-primary/15 text-primary' : 'bg-primary/10 text-primary'
            )}
          >
            #{index + 1}
          </span>
          {isDisabled ? (
            <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground border border-border/60">
              SKIP
            </span>
          ) : null}

          {isEdited ? (
            <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-info/10 text-info border border-info/25">
              EDIT
            </span>
          ) : null}
          {isDuplicate ? (
            <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/25">
              DUP
            </span>
          ) : null}
          {isShort ? (
            <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/25">
              SHORT
            </span>
          ) : null}
          {isGap ? (
            <span
              className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-destructive/10 text-destructive border border-destructive/25"
              title={typeof gapBefore === 'number' ? `gap_before: ${gapBefore}` : undefined}
            >
              GAP
            </span>
          ) : null}
          {isOverlap ? (
            <span
              className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/25"
              title={typeof overlapPrev === 'number' ? `overlap_prev: ${overlapPrev}` : undefined}
            >
              OVR
            </span>
          ) : null}
          {needsReview ? (
            <span
              className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-destructive/10 text-destructive border border-destructive/25"
              title={needsReviewTitle}
            >
              REVIEW
            </span>
          ) : null}
          {(() => {
    if (chunkRole === 'parent') {
        return (<span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/25">
              PARENT
            </span>);
    }
    else if (chunkRole === 'child') {
            return (<span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground border border-border/60">
              CHILD
            </span>);
        }
        else {
            return null;
        }
})()}
          {sectionLabel ? (
            <span
              className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-muted/60 text-muted-foreground border border-border/60 max-w-[180px] truncate"
              title={sectionLabel.full}
            >
              {sectionLabel.short}
            </span>
          ) : null}
          {unit === 'tokens' ? (
            <>
              <span className="text-[11px] text-muted-foreground font-mono">{tokens ?? '-'} tok</span>
              <span className="text-[11px] text-muted-foreground font-mono">{chunk.length} chars</span>
            </>
          ) : (
            <span
              className="text-[11px] text-muted-foreground font-mono"
              title={tokens == null ? `${chunk.length} chars` : `${chunk.length} chars · ${tokens} tok`}
            >
              {chunk.length} chars
            </span>
          )}
          <span className="text-[11px] text-muted-foreground font-mono" title="start-end">
            {rangeLabel}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {chunk.page_number != null && (
            <span className="text-[11px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">P.{chunk.page_number}</span>
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
                aria-label={t('chunkCard.edit')}
                title={t('chunkCard.edit')}
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
                aria-label={isDisabled ? t('chunkCard.enable') : t('chunkCard.skip')}
                title={isDisabled ? t('chunkCard.enable') : t('chunkCard.skip')}
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
                detachPromise(copyText(citationText, t('chunkCard.copyCitationSuccess')))
              }}
              aria-label={t('chunkCard.copyCitation')}
              title={t('chunkCard.copyCitation')}
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
                  const url = new URL(globalThis.window.location.href)
                  url.searchParams.set('chunk', String(index + 1))
                  detachPromise(copyText(url.toString(), t('chunkCard.copyLinkSuccess')))
                } catch {
                  toast.error(t('chunkCard.cannotGenerateLink'))
                }
              }}
              aria-label={t('chunkCard.copyLink')}
              title={t('chunkCard.copyLink')}
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
                detachPromise(copyText(chunk.content || '', t('chunkCard.copyContentSuccess')))
              }}
              aria-label={t('chunkCard.copyContent')}
              title={t('chunkCard.copyContent')}
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
                detachPromise(copyText(JSON.stringify(chunk, null, 2), t('chunkCard.copyJsonSuccess')))
              }}
              aria-label={t('chunkCard.copyJson')}
              title={t('chunkCard.copyJson')}
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
              aria-label={isSelected ? t('chunkCard.unpin') : t('chunkCard.pin')}
              title={isSelected ? t('chunkCard.unpin') : t('chunkCard.pin')}
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
