/**
 * ChunkCard - 单个切片卡片
 */
'use client'

import { useCallback, useMemo } from 'react'
import type { ReactNode } from 'react'
import { Copy, Braces, Pin, PinOff, Quote, Pencil, Eye, EyeOff, Link2, CheckCircle2, RotateCcw, MoreHorizontal, AlertCircle } from '@/components/icons'
import { toast } from 'sonner'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import styles from './workbench/compare.module.css'
import { chunkIsReviewed, chunkNeedsReview, getChunkMetadata, getSemanticQualityMetadata, getStringValue } from '@/components/chunk-preview/utils/metadata'
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
  isReviewed?: boolean
  query?: string
  onMouseEnter: () => void
  onMouseLeave: () => void
  onToggleSelect: () => void
  onEdit?: () => void
  onToggleDisabled?: () => void
  onToggleReviewed?: () => void
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
        className={styles.chunkMark}
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
  isReviewed,
  query,
  onMouseEnter,
  onMouseLeave,
  onToggleSelect,
  onEdit,
  onToggleDisabled,
  onToggleReviewed,
}: Readonly<ChunkCardProps>) {
  const t = useTranslations('ChunkPreview')
  const rangeLabel = useMemo(() => `${chunk.start_index}-${chunk.end_index}`, [chunk.start_index, chunk.end_index])
  const tokens = useMemo(() => (typeof chunk.tokens_est === 'number' ? chunk.tokens_est : null), [chunk.tokens_est])
  const chunkMetadata = getChunkMetadata(chunk)
  const chunkRole = getStringValue(chunkMetadata, 'chunk_role')
  const sectionLabel = useMemo(() => getChunkSectionLabel(chunk), [chunk])
  const semanticQuality = getSemanticQualityMetadata(chunk)
  const reviewed = Boolean(isReviewed) || chunkIsReviewed(chunk)
  const needsReview = chunkNeedsReview(chunk)
  const needsReviewTitle = useMemo(() => {
    if (!needsReview) return undefined
    const reasons = semanticQuality?.reasons ?? []
    return reasons.length > 0
      ? `${t('chunkCard.needsReviewTitle')}：${reasons.join(', ')}`
      : t('chunkCard.needsReviewTitle')
  }, [needsReview, semanticQuality?.reasons, t])
  const chunkMetricLabel = unit === 'tokens' ? `${tokens ?? '-'} token` : `${chunk.length} 字`
  const chunkMetricTitle = [
    `${chunk.length} chars`,
    tokens == null ? null : `${tokens} tokens`,
    rangeLabel,
  ].filter(Boolean).join(' · ')
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

  const firstTableRow = chunk.content?.split('\n').find(line => line.trim().startsWith('|'))
  const tableCells = firstTableRow?.split(/(?<!\\)\|/).map(value => value.trim()).filter(Boolean) || []
  const tableTitle = tableCells.find(value => !/^[-:\s]+$/.test(value) && !/^D\d+$/.test(value))
  const heading = sectionLabel?.short || chunk.content?.match(/^#{1,6}\s+(.+)$/m)?.[1] || tableTitle || '正文片段'
  const reasonLabels: Record<string, string> = { incomplete: '内容不完整', low_density: '信息密度偏低', too_small: '内容偏短', too_large: '内容偏长' }
  const visibleReasons = (semanticQuality?.reasons || []).map(reason => reasonLabels[reason] || reason).join('、')
  return <article className={styles.chunk} data-chunk-card data-chunk-index={index} data-selected={isSelected} data-hovered={isHovered} data-disabled={isDisabled} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave} aria-label={t('chunkCard.ariaLabel', { index: index + 1 })}>
    <button type="button" className={styles.chunkSelect} onClick={onToggleSelect} aria-label={t('chunkCard.ariaLabel', { index: index + 1 })} aria-pressed={isSelected} />
    <div className={styles.chunkHeading}>
      <span className={styles.chunkNumber}>{String(index + 1).padStart(2, '0')}</span>
      <h3 className={styles.chunkTitle} title={sectionLabel?.full}>{heading}</h3>
      {reviewed ? <span className={cn(styles.chunkReview,styles.chunkReviewed)}><CheckCircle2 />已复核</span> : needsReview ? <span className={styles.chunkReview} title={visibleReasons || needsReviewTitle}><AlertCircle />待复核</span> : null}
      <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className={styles.chunkMenu} aria-label={`切块 ${index + 1} 更多操作`}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end" className="text-[13px]">
        {onEdit && <DropdownMenuItem onSelect={onEdit}><Pencil />{t('chunkCard.edit')}</DropdownMenuItem>}
        {onToggleReviewed && <DropdownMenuItem onSelect={onToggleReviewed}>{reviewed ? <RotateCcw /> : <CheckCircle2 />}{reviewed ? t('chunkCard.restoreReview') : '标记已复核'}</DropdownMenuItem>}
        {onToggleDisabled && <DropdownMenuItem onSelect={onToggleDisabled}>{isDisabled ? <Eye /> : <EyeOff />}{isDisabled ? t('chunkCard.enable') : t('chunkCard.skip')}</DropdownMenuItem>}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void copyText(citationText,t('chunkCard.copyCitationSuccess'))}><Quote />{t('chunkCard.copyCitation')}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => { try { const url = new URL(window.location.href); url.searchParams.set('chunk',String(index + 1)); void copyText(url.toString(),t('chunkCard.copyLinkSuccess')) } catch { toast.error(t('chunkCard.cannotGenerateLink')) } }}><Link2 />{t('chunkCard.copyLink')}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void copyText(chunk.content || '', t('chunkCard.copyContentSuccess'))}><Copy />{t('chunkCard.copyContent')}</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void copyText(JSON.stringify(chunk,null,2),t('chunkCard.copyJsonSuccess'))}><Braces />{t('chunkCard.copyJson')}</DropdownMenuItem>
        <DropdownMenuItem onSelect={onToggleSelect}>{isSelected ? <PinOff /> : <Pin />}{isSelected ? t('chunkCard.unpin') : t('chunkCard.pin')}</DropdownMenuItem>
      </DropdownMenuContent></DropdownMenu>
    </div>
    <div className={styles.chunkMeta} title={chunkMetricTitle}>
      <span>{chunkMetricLabel}</span>
      {chunk.page_number != null && <span>第 {chunk.page_number} 页</span>}
      {chunkRole && <span>{chunkRole === 'parent' ? '父块' : chunkRole === 'child' ? '子块' : chunkRole}</span>}
      {isGap && <span title={typeof gapBefore === 'number' ? `前方缺口 ${gapBefore} 字符` : undefined}>存在缺口</span>}
      {isOverlap && <span title={typeof overlapPrev === 'number' ? `与前块重叠 ${overlapPrev} 字符` : undefined}>内容重叠</span>}
      {isShort && <span>内容偏短</span>}{isDuplicate && <span>疑似重复</span>}{isEdited && <span>已编辑</span>}{isDisabled && <span>已跳过</span>}
      {isSelected && <span>位置 {rangeLabel}</span>}
    </div>
    {isSelected && <div className={styles.chunkFooter}>
      {onEdit && <Button variant="outline" onClick={onEdit}><Pencil />编辑内容</Button>}
      {onToggleReviewed && <Button variant="outline" onClick={onToggleReviewed}>{reviewed ? <RotateCcw /> : <CheckCircle2 />}{reviewed ? '撤销复核' : '标记已复核'}</Button>}
      <span className={styles.metadata}>第 {index + 1} 块</span>
    </div>}
    <div className={styles.chunkContent}>
      {isSelected && !query?.trim() ? <MarkdownRenderer markdown={chunk.content || ''} enableTocAnchors={false} autoScrollToHash={false} /> : highlightText(chunk.content || '',query)}
    </div>
  </article>
}
