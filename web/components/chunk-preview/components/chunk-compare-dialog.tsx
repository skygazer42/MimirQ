/**
 * ChunkCompareDialog - Compare two preview runs (A/B)
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
import { Download, GitCompareArrows, Info } from '@/components/icons'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { readMetadataString } from '@/components/chunk-preview/utils/metadata'
import { cn } from '@/lib/utils'
import type { ChunkPreviewResponse } from '@/types'
import {
  buildSemanticEvidenceHighlights,
  chunkPreviewDiffToExport,
  computeChunkPreviewDiff,
  getComparisonCandidates,
} from '@/components/chunk-preview/utils/ab-diff'
import { downloadTextFile, sanitizeFilename } from '@/components/chunk-preview/utils/export'
import type { ChunkPreviewState } from '../types'

function formatDelta(n: number) {
  if (n === 0) return '0'
  return n > 0 ? `+${n}` : String(n)
}

function formatPct(ratio: number | null) {
  if (ratio === null) return '-'
  return `${Math.round(ratio * 100)}%`
}

function formatDeltaPct(deltaRatio: number) {
  if (deltaRatio === 0) return '0%'
  const v = Math.round(deltaRatio * 100)
  return v > 0 ? `+${v}%` : `${v}%`
}

function getEvidenceToneClass(tone: 'added' | 'removed'): string {
  if (tone === 'added') return 'border-info/30 bg-info/5 text-info'
  return 'border-warning/30 bg-warning/5 text-warning'
}

function getEvidenceMarkClass(tone: 'added' | 'removed'): string {
  if (tone === 'added') return 'bg-info/15 text-info'
  return 'bg-warning/15 text-warning'
}

function getChunkCompareDeltaClass(deltaCount: number): string {
  if (deltaCount === 0) return 'text-muted-foreground'
  if (deltaCount > 0) return 'text-info'
  return 'text-warning'
}

function extractHierarchyBasis(preview: ChunkPreviewResponse): string[] {
  const bases = new Set<string>()
  for (const chunk of preview.chunks) {
    const basis = readMetadataString(chunk.metadata?.hierarchy_basis)
    if (!basis) continue
    bases.add(basis)
  }
  return Array.from(bases).sort((a, b) => a.localeCompare(b))
}

function EvidenceHighlightsPanel(
  props: Readonly<{
    title: string
    emptyLabel: string
    tone: 'added' | 'removed'
    items: ReturnType<typeof buildSemanticEvidenceHighlights>['added']
  }>,
) {
  const t = useTranslations('ChunkPreview')
  const { title, emptyLabel, tone, items } = props
  const toneClass = getEvidenceToneClass(tone)
  let content: React.ReactNode
  if (items.length === 0) {
    content = (
      <div className="mt-3 rounded-xl border border-dashed border-border/60 bg-muted/20 px-3 py-4 text-xs text-muted-foreground">
        {emptyLabel}
      </div>
    )
  } else {
    content = (
      <div className="mt-3 space-y-3">
        {items.map((item) => (
          <div
            key={`${tone}:${item.index}:${item.example.slice(0, 24)}`}
            className="rounded-xl border border-border/60 bg-background/80 p-3"
          >
            <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
              <span>{t('compareDialog.evidence.itemLabel', { index: item.index })}</span>
              <span className="font-mono">{t('compareDialog.evidence.countLabel', { count: item.count })}</span>
            </div>
            <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/90">
              {item.segments.map((segment, index) => {
                if (!segment.emphasis) {
                  return <span key={`${tone}:${item.index}:${index}`}>{segment.text}</span>
                }

                return (
                  <mark
                    key={`${tone}:${item.index}:${index}`}
                    className={cn('rounded px-0.5', getEvidenceMarkClass(tone))}
                  >
                    {segment.text}
                  </mark>
                )
              })}
            </div>
            {item.referenceExample ? (
              <div className="mt-3 border-t border-border/50 pt-3">
                <div className="text-[11px] font-medium uppercase text-muted-foreground">
                  {t('compareDialog.evidence.referenceLabel')}
                </div>
                <div className="mt-1 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
                  {item.referenceExample}
                </div>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-border/60 bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-foreground">{title}</div>
        <div className={cn('rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase', toneClass)}>
          {items.length}
        </div>
      </div>
      {content}
    </div>
  )
}

export function ChunkCompareDialog(
  props: Readonly<{
    open: boolean
    onOpenChange: (open: boolean) => void
    current: ChunkPreviewResponse
    currentFileId: string
    currentFileName: string
    runHistory: ChunkPreviewState['runHistory']
    getCachedPreview: (cacheKey: string) => ChunkPreviewResponse | null
  }>,
) {
  const { open, onOpenChange, current, currentFileId, currentFileName, runHistory, getCachedPreview } = props
  const t = useTranslations('ChunkPreview')

  const candidates = useMemo(() => {
    return getComparisonCandidates(runHistory, currentFileId)
  }, [runHistory, currentFileId])

  const [baselineKey, setBaselineKey] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setBaselineKey((selected) =>
      candidates.slice(1).some((item) => item.cacheKey === selected) ? selected : (candidates[1]?.cacheKey ?? null),
    )
  }, [open, candidates])

  const baselineMeta = candidates.slice(1).find((item) => item.cacheKey === baselineKey)
  const baseline = baselineMeta === undefined ? null : getCachedPreview(baselineMeta.cacheKey)

  const currentHierarchyBasis = useMemo(() => extractHierarchyBasis(current), [current])
  const baselineHierarchyBasis = useMemo(() => (baseline ? extractHierarchyBasis(baseline) : []), [baseline])

  const diff = useMemo(() => {
    if (!baseline) return null
    return computeChunkPreviewDiff(baseline, current)
  }, [baseline, current])
  const evidenceHighlights = useMemo(() => (diff ? buildSemanticEvidenceHighlights(diff) : null), [diff])

  const currentHierarchyBasisLabel = currentHierarchyBasis.length
    ? t('compareDialog.hierarchyBasis', { value: currentHierarchyBasis.join(',') })
    : ''

  let diffSection: React.ReactNode = null
  if (baseline && diff) {
    const aUnit = t(`compareDialog.units.${diff.aUnit}`)
    const bUnit = t(`compareDialog.units.${diff.bUnit}`)
    const sameLengthUnit = diff.aUnit === diff.bUnit
    const lengthUnit = sameLengthUnit ? bUnit : t('compareDialog.mixedUnits', { baseline: aUnit, current: bUnit })
    const evidenceHighlightsContent = evidenceHighlights ? (
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <EvidenceHighlightsPanel
          title={t('compareDialog.evidence.addedTitle')}
          emptyLabel={t('compareDialog.evidence.addedEmpty')}
          tone="added"
          items={evidenceHighlights.added}
        />
        <EvidenceHighlightsPanel
          title={t('compareDialog.evidence.removedTitle')}
          emptyLabel={t('compareDialog.evidence.removedEmpty')}
          tone="removed"
          items={evidenceHighlights.removed}
        />
      </div>
    ) : null

    diffSection = (
      <div className="space-y-3">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
          <div className="bg-card border border-border/60 rounded-xl p-4">
            <div className="text-[11px] text-muted-foreground uppercase font-medium">
              {t('compareDialog.cards.chunkCount')}
            </div>
            <div className="mt-2 flex items-end justify-between">
              <div className="text-sm font-mono text-foreground/90">{diff.bCount}</div>
              <div className={cn('text-xs font-mono', getChunkCompareDeltaClass(diff.deltaCount))}>
                {formatDelta(diff.deltaCount)}
              </div>
            </div>
            <div className="mt-2 text-[11px] text-muted-foreground">
              {t('compareDialog.cards.countSummary', { aCount: diff.aCount, bCount: diff.bCount })}
            </div>
          </div>

          <section
            className="bg-card border border-border/60 rounded-xl p-4"
            aria-label={t('compareDialog.cards.lengthDistribution', { unit: lengthUnit })}
          >
            <div className="text-[11px] text-muted-foreground uppercase font-medium">
              {t('compareDialog.cards.lengthDistribution', { unit: lengthUnit })}
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
              <div className="text-muted-foreground">
                {t('compareDialog.cards.metrics.p10')}
                <br />
                <span className="font-mono text-foreground/90">
                  A: {diff.aP10 ?? '-'} / B: {diff.bP10 ?? '-'}
                </span>
                {diff.deltaP10 !== null && (
                  <span className="ml-1 text-muted-foreground">({formatDelta(diff.deltaP10)})</span>
                )}
              </div>
              <div className="text-muted-foreground">
                {t('compareDialog.cards.metrics.avg')}
                <br />
                <span className="font-mono text-foreground/90">
                  A: {diff.aAvg ?? '-'} / B: {diff.bAvg ?? '-'}
                </span>
                {diff.deltaAvg !== null && (
                  <span className="ml-1 text-muted-foreground">({formatDelta(diff.deltaAvg)})</span>
                )}
              </div>
              <div className="text-muted-foreground">
                {t('compareDialog.cards.metrics.p95')}
                <br />
                <span className="font-mono text-foreground/90">
                  A: {diff.aP95 ?? '-'} / B: {diff.bP95 ?? '-'}
                </span>
                {diff.deltaP95 !== null && (
                  <span className="ml-1 text-muted-foreground">({formatDelta(diff.deltaP95)})</span>
                )}
              </div>
            </div>
            {!sameLengthUnit && (
              <p className="mt-2 text-[11px] text-muted-foreground">{t('compareDialog.incompatibleLengthUnits')}</p>
            )}
          </section>

          <div className="bg-card border border-border/60 rounded-xl p-4">
            <div className="text-[11px] text-muted-foreground uppercase font-medium">
              {t('compareDialog.cards.contentOverlap')}
            </div>
            <div className="mt-2 flex items-end justify-between">
              <div className="text-sm font-mono text-foreground/90">{formatPct(diff.overlap)}</div>
              <div className="text-[11px] text-muted-foreground">
                {t('compareDialog.cards.addedRemoved', { added: diff.added, removed: diff.removed })}
              </div>
            </div>
            <div className="mt-2 text-[11px] text-muted-foreground">
              {t('compareDialog.cards.contentOverlapDescription')}
            </div>
          </div>

          <section
            className="bg-card border border-border/60 rounded-xl p-4"
            aria-label={t('compareDialog.cards.qualityOverview')}
          >
            <div className="text-[11px] text-muted-foreground uppercase font-medium">
              {t('compareDialog.cards.qualityOverview')}
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
              <div className="text-muted-foreground">
                {t('compareDialog.cards.metrics.coverage')}
                <br />
                <span className="font-mono text-foreground/90">{formatPct(diff.bCoverage)}</span>
                {diff.deltaCoverage !== null && (
                  <span className="ml-1 text-muted-foreground">({formatDeltaPct(diff.deltaCoverage)})</span>
                )}
              </div>
              <div className="text-muted-foreground">
                {t('compareDialog.cards.metrics.waste')}
                <br />
                <span className="font-mono text-foreground/90">{formatPct(diff.bWaste)}</span>
                {diff.deltaWaste !== null && (
                  <span className="ml-1 text-muted-foreground">({formatDeltaPct(diff.deltaWaste)})</span>
                )}
              </div>
              <div className="text-muted-foreground">
                {t('compareDialog.cards.metrics.gaps')}
                <br />
                <span className="font-mono text-foreground/90">{diff.bGapCount ?? '-'}</span>
                {diff.deltaGapCount !== null && (
                  <span className="ml-1 text-muted-foreground">({formatDelta(diff.deltaGapCount)})</span>
                )}
              </div>
            </div>
            <div className="mt-2 text-[11px] text-muted-foreground">
              {t('compareDialog.cards.qualitySummary', {
                baseline: baseline.quality_gate?.grade ?? '-',
                current: current.quality_gate?.grade ?? '-',
              })}
            </div>
          </section>
        </div>

        {evidenceHighlightsContent}
      </div>
    )
  }

  let baselineMetaContent: React.ReactNode = null
  if (baselineMeta) {
    const cacheHitSuffix = baselineMeta.cacheHit ? t('compareDialog.cacheHitSuffix') : ''
    const hierarchyBasisSuffix = baselineHierarchyBasis.length
      ? t('compareDialog.hierarchyBasis', { value: baselineHierarchyBasis.join(',') })
      : ''

    baselineMetaContent = (
      <div className="text-[11px] text-muted-foreground">
        {t('compareDialog.baselineSource', {
          strategy: baselineMeta.strategy,
          chunkSize: baselineMeta.chunkSize,
          chunkOverlap: baselineMeta.chunkOverlap,
          durationMs: baselineMeta.durationMs,
        })}
        {cacheHitSuffix}
        {hierarchyBasisSuffix}
      </div>
    )
  }

  let dialogBody: React.ReactNode
  let dialogFooter: React.ReactNode = null
  if (candidates.length < 2) {
    dialogBody = (
      <div className="flex items-start gap-2 text-sm text-muted-foreground bg-muted/40 border border-border/60 rounded-xl p-4">
        <Info className="w-4 h-4 mt-0.5" />
        <div>{t('compareDialog.needTwoRuns')}</div>
      </div>
    )
  } else {
    dialogBody = (
      <>
        <div className="flex flex-col md:flex-row md:items-center gap-3">
          <div className="text-xs text-muted-foreground min-w-[72px]">{t('compareDialog.baselineLabel')}</div>
          <Select value={baselineMeta === undefined ? '' : baselineMeta.cacheKey} onValueChange={setBaselineKey}>
            <SelectTrigger className="h-9 w-full md:w-[520px] text-xs bg-card/80">
              <SelectValue placeholder={t('compareDialog.baselinePlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              {candidates.slice(1).map((item) => (
                <SelectItem key={item.id} value={item.cacheKey}>
                  {t('compareDialog.candidateSummary', {
                    timestamp: new Date(item.createdAt).toLocaleString([], {
                      month: '2-digit',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    }),
                    strategy: item.strategy,
                    chunkSize: item.chunkSize,
                    chunkOverlap: item.chunkOverlap,
                    totalChunks: item.totalChunks,
                  })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="text-xs text-muted-foreground flex-1">
            {t('compareDialog.currentSummary', {
              strategy: current.chunk_strategy,
              chunkSize: current.params?.chunk_size ?? '-',
              chunkOverlap: current.params?.chunk_overlap ?? '-',
              totalChunks: current.total_chunks,
            })}
            {currentHierarchyBasisLabel}
          </div>
        </div>

        {baseline === null ? (
          <p role="status" className="text-sm text-muted-foreground">
            {t('compareDialog.baselineUnavailable')}
          </p>
        ) : (
          diffSection
        )}
        {baselineMetaContent}
      </>
    )
    dialogFooter = (
      <DialogFooter className="shrink-0 flex-row justify-end gap-2 border-t border-border/60 px-6 py-4">
        <Button
          type="button"
          variant="outline"
          disabled={!baseline}
          onClick={() => {
            if (!baseline) return
            const payload = chunkPreviewDiffToExport(baseline, current, {
              baseline_cache_key: baselineMeta?.cacheKey,
            })
            const filename = `${sanitizeFilename(currentFileName)}.chunk-preview.diff.json`
            downloadTextFile(filename, JSON.stringify(payload, null, 2), 'application/json;charset=utf-8')
          }}
        >
          <Download className="mr-2 h-4 w-4" />
          {t('compareDialog.actions.exportDiff')}
        </Button>
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
          {t('compareDialog.actions.close')}
        </Button>
      </DialogFooter>
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100dvh-2rem)] w-[92vw] max-w-[980px] flex-col gap-0 p-0 overflow-hidden">
        <div className="shrink-0 p-6 border-b border-border/60 bg-card/80">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <GitCompareArrows className="w-5 h-5 text-primary" />
              {t('compareDialog.title')}
            </DialogTitle>
            <DialogDescription className="text-xs">{t('compareDialog.description')}</DialogDescription>
          </DialogHeader>
        </div>

        <div className="min-h-0 overflow-y-auto p-6 space-y-4">{dialogBody}</div>
        {dialogFooter}
      </DialogContent>
    </Dialog>
  )
}
