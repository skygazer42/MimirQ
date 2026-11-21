/**
 * ChunkCard - 单个切片卡片
 */
'use client'

import { useCallback, useMemo } from 'react'
import {
  Copy,
  Braces,
  Pin,
  PinOff,
  Quote,
  Pencil,
  Eye,
  EyeOff,
  Link2,
  CheckCircle2,
  RotateCcw,
  MoreHorizontal,
  AlertCircle,
} from '@/components/icons'
import { toast } from 'sonner'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { HighlightedText } from '@/components/ui/highlighted-text'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import styles from './workbench/compare.module.css'
import {
  chunkIsReviewed,
  chunkNeedsReview,
  getChunkRole,
  getChunkReviewReasons,
} from '@/components/chunk-preview/utils/metadata'
import { cn } from '@/lib/utils'
import type { ChunkPreviewItem } from '@/types'
import { getChunkSectionLabel } from '@/components/chunk-preview/utils/sections'
import { getMarkdownCodeFence } from '@/components/chunk-preview/utils/export'

const REVIEW_REASON_LABELS: Record<string, string> = {
  incomplete: '内容不完整',
  low_density: '信息密度偏低',
  too_small: '内容偏短',
  too_large: '内容偏长',
}

type ChunkCardProps = {
  chunk: ChunkPreviewItem
  position: number
  unit: 'chars' | 'tokens'
  sourceFilename: string
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
  query: string
  onMouseEnter: () => void
  onMouseLeave: () => void
  onToggleSelect: () => void
  onEdit: () => void
  onToggleDisabled: () => void
  onToggleReviewed: () => void
}

export function ChunkCard({
  chunk,
  position,
  unit,
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
  onToggleReviewed,
}: Readonly<ChunkCardProps>) {
  const t = useTranslations('ChunkPreview')
  const rangeLabel = `${chunk.start_index}-${chunk.end_index}`
  const tokens = typeof chunk.tokens_est === 'number' ? chunk.tokens_est : null
  const chunkRole = getChunkRole(chunk)
  const sectionLabel = useMemo(() => getChunkSectionLabel(chunk), [chunk])
  const reviewReasons = getChunkReviewReasons(chunk)
  const reviewed = chunkIsReviewed(chunk)
  const needsReview = chunkNeedsReview(chunk)
  const chunkMetricLabel = unit === 'tokens' ? `${tokens ?? '-'} token` : `${chunk.length} 字`
  const chunkMetricTitle = [`${chunk.length} chars`, tokens == null ? null : `${tokens} tokens`, rangeLabel]
    .filter(Boolean)
    .join(' · ')
  function copyCitation() {
    const pageLabel = chunk.page_number == null ? '' : ` · P.${chunk.page_number}`
    const tokLabel = tokens == null ? '' : ` · ${tokens} tok`
    const characters = Array.from(chunk.content)
    const excerpt = characters.length > 2000 ? `${characters.slice(0, 2000).join('')}…` : chunk.content
    const fence = getMarkdownCodeFence(excerpt)
    const citation = [
      `【${sourceFilename} · chunk #${position + 1}${pageLabel}${tokLabel} · ${rangeLabel}】`,
      `${fence}text`,
      excerpt,
      fence,
    ].join('\n')
    return copyText(citation, t('chunkCard.copyCitationSuccess'))
  }

  const copyText = useCallback(
    async (text: string, okMsg: string) => {
      if (!navigator.clipboard?.writeText) {
        toast.error(t('chunkCard.copyClipboardUnsupported'))
        return
      }
      try {
        await navigator.clipboard.writeText(text)
        toast.success(okMsg)
      } catch {
        toast.error(t('chunkCard.copyFailed'))
      }
    },
    [t],
  )

  const heading = useMemo(() => {
    if (sectionLabel !== null) return sectionLabel.short
    const markdownHeading = chunk.content.match(/^#{1,6}\s+(.+)$/m)?.[1]
    if (markdownHeading !== undefined) return markdownHeading
    const firstTableRow = chunk.content.split('\n').find((line) => line.trim().startsWith('|'))
    const tableTitle = firstTableRow
      ?.split(/(?<!\\)\|/)
      .map((value) => value.trim())
      .find((value) => value !== '' && !/^[-:\s]+$/.test(value) && !/^D\d+$/.test(value))
    return tableTitle ?? '正文片段'
  }, [chunk.content, sectionLabel])
  const visibleReasons = reviewReasons
    ?.filter((reason) => reason.trim().length > 0)
    .map((reason) => (Object.hasOwn(REVIEW_REASON_LABELS, reason) ? REVIEW_REASON_LABELS[reason] : reason))
    .join('、')
  return (
    <article
      className={styles.chunk}
      data-chunk-card
      data-chunk-index={position}
      data-selected={isSelected}
      data-hovered={isHovered}
      data-disabled={isDisabled}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      aria-label={t('chunkCard.ariaLabel', { index: position + 1 })}
    >
      <button
        type="button"
        className={styles.chunkSelect}
        onClick={onToggleSelect}
        aria-label={t('chunkCard.ariaLabel', { index: position + 1 })}
        aria-pressed={isSelected}
      />
      <div className={styles.chunkHeading}>
        <span className={styles.chunkNumber}>{String(position + 1).padStart(2, '0')}</span>
        <h3 className={styles.chunkTitle} title={sectionLabel?.full}>
          {heading}
        </h3>
        {reviewed ? (
          <span className={cn(styles.chunkReview, styles.chunkReviewed)}>
            <CheckCircle2 />
            已复核
          </span>
        ) : needsReview ? (
          <span
            className={styles.chunkReview}
            title={
              visibleReasons === undefined || visibleReasons === '' ? t('chunkCard.needsReviewTitle') : visibleReasons
            }
          >
            <AlertCircle />
            待复核
          </span>
        ) : null}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className={styles.chunkMenu}
              aria-label={`切块 ${position + 1} 更多操作`}
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="text-[13px]">
            <DropdownMenuItem onSelect={onEdit}>
              <Pencil />
              {t('chunkCard.edit')}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onToggleReviewed}>
              {reviewed ? <RotateCcw /> : <CheckCircle2 />}
              {reviewed ? t('chunkCard.restoreReview') : '标记已复核'}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onToggleDisabled}>
              {isDisabled ? <Eye /> : <EyeOff />}
              {isDisabled ? t('chunkCard.enable') : t('chunkCard.skip')}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => void copyCitation()}>
              <Quote />
              {t('chunkCard.copyCitation')}
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => {
                const url = new URL(window.location.href)
                url.searchParams.set('chunk', String(position + 1))
                void copyText(url.toString(), t('chunkCard.copyLinkSuccess'))
              }}
            >
              <Link2 />
              {t('chunkCard.copyLink')}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void copyText(chunk.content, t('chunkCard.copyContentSuccess'))}>
              <Copy />
              {t('chunkCard.copyContent')}
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => void copyText(JSON.stringify(chunk, null, 2), t('chunkCard.copyJsonSuccess'))}
            >
              <Braces />
              {t('chunkCard.copyJson')}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onToggleSelect}>
              {isSelected ? <PinOff /> : <Pin />}
              {isSelected ? t('chunkCard.unpin') : t('chunkCard.pin')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className={styles.chunkMeta} title={chunkMetricTitle}>
        <span>{chunkMetricLabel}</span>
        {chunk.page_number != null && <span>第 {chunk.page_number} 页</span>}
        {chunkRole && <span>{chunkRole === 'parent' ? '父块' : chunkRole === 'child' ? '子块' : chunkRole}</span>}
        {isGap && (
          <span title={typeof gapBefore === 'number' ? `前方缺口 ${gapBefore} 字符` : undefined}>存在缺口</span>
        )}
        {isOverlap && (
          <span title={typeof overlapPrev === 'number' ? `与前块重叠 ${overlapPrev} 字符` : undefined}>内容重叠</span>
        )}
        {isShort && <span>内容偏短</span>}
        {isDuplicate && <span>疑似重复</span>}
        {isEdited && <span>已编辑</span>}
        {isDisabled && <span>已跳过</span>}
        {isSelected && <span>位置 {rangeLabel}</span>}
      </div>
      {isSelected && (
        <div className={styles.chunkFooter}>
          <Button type="button" variant="outline" onClick={onEdit}>
            <Pencil />
            编辑内容
          </Button>
          <Button type="button" variant="outline" onClick={onToggleReviewed}>
            {reviewed ? <RotateCcw /> : <CheckCircle2 />}
            {reviewed ? '撤销复核' : '标记已复核'}
          </Button>
          <span className={styles.metadata}>第 {position + 1} 块</span>
        </div>
      )}
      <div className={styles.chunkContent}>
        {isSelected && query.trim().length === 0 ? (
          <MarkdownRenderer markdown={chunk.content} enableTocAnchors={false} autoScrollToHash={false} />
        ) : (
          <HighlightedText content={chunk.content} query={query} markClassName={styles.chunkMark} />
        )}
      </div>
    </article>
  )
}
