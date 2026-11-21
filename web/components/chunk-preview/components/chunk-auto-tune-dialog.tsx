/**
 * ChunkAutoTuneDialog
 * Auto-search chunk_size/chunk_overlap for a given file + strategy constraints.
 *
 * Notes:
 * - Uses /documents/chunk-preview/by-sha with include_chunks=false to keep payload small.
 * - Intended for "enterprise tuning" workflows (TopN recommendations + one-click apply).
 */
'use client'

import { useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Wand2, Loader2, X, Download } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { downloadTextFile, sanitizeFilename } from '@/components/chunk-preview/utils/export'
import { detachPromise } from '@/lib/utils'
import { getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import type { ChunkPreviewStats } from '@/types/processing'

type TuneCandidate = {
  chunkSize: number
  chunkOverlap: number
  ok: boolean
  error?: string
  durationMs?: number
  stats?: Pick<ChunkPreviewStats, 'avg' | 'p90' | 'short_count' | 'coverage_ratio' | 'overlap_waste_ratio'> & {
    count: number
  }
  quality?: { grade?: string; reasons?: string[] } | null
}

function clampInt(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.trunc(value)))
}

function roundToStep(value: number, step: number) {
  if (step <= 1) return Math.trunc(value)
  return Math.round(value / step) * step
}

function uniqSorted(nums: number[]) {
  return Array.from(new Set(nums.filter((n) => Number.isFinite(n)))).sort((a, b) => a - b)
}

export function ChunkAutoTuneDialog() {
  const t = useTranslations('ChunkPreview')
  const formId = useId()
  const {
    currentFile,
    previewData,
    previewSourceFile,
    isLoading,
    chunkSize,
    chunkOverlap,
    chunkStrategy,
    parserBackend,
    buildChunkPreviewRequestParams,
    updateSettings,
    runPreview,
  } = useChunkPreview()

  const [open, setOpen] = useState(false)
  const [running, setRunning] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const [minCoveragePct, setMinCoveragePct] = useState(98)
  const [maxOverlapWastePct, setMaxOverlapWastePct] = useState(35)
  const [maxChunksCap, setMaxChunksCap] = useState(0)
  const [topN, setTopN] = useState(5)

  const [results, setResults] = useState<TuneCandidate[]>([])

  const preview = currentFile === previewSourceFile ? previewData : null
  const sha = preview?.file_sha256

  useLayoutEffect(() => {
    setResults([])
    setRunning(false)
    return () => {
      abortRef.current?.abort()
      abortRef.current = null
    }
  }, [currentFile, preview, buildChunkPreviewRequestParams])

  const isTokenStrategy = chunkStrategy === 'langchain_token'
  const isSeparatorStrategy = chunkStrategy === 'separator'
  const isAutoTuneAvailable = typeof sha === 'string' && sha.length > 0 && currentFile !== null && !isSeparatorStrategy

  const effectiveStep = isTokenStrategy ? 50 : 100
  const sizeMin = isTokenStrategy ? 50 : 100
  const sizeMax = isTokenStrategy ? 2000 : 4000

  const candidates = useMemo(() => {
    const base = clampInt(chunkSize, sizeMin, sizeMax)
    const multipliers = [0.6, 0.8, 1, 1.2, 1.5, 1.8]
    const sizes = uniqSorted(multipliers.map((m) => clampInt(roundToStep(base * m, effectiveStep), sizeMin, sizeMax)))

    const ratios = [0.1, 0.15, 0.2, 0.25]
    const out: Array<{ chunkSize: number; chunkOverlap: number }> = []
    for (const s of sizes) {
      for (const r of ratios) {
        const overlap = clampInt(Math.round(s * r), 0, Math.min(1000, s - 1))
        out.push({ chunkSize: s, chunkOverlap: overlap })
      }
    }

    // Always include current params as a candidate.
    const currentOverlap = clampInt(chunkOverlap || 0, 0, Math.min(1000, base - 1))
    out.push({ chunkSize: base, chunkOverlap: currentOverlap })

    // Dedup.
    const seen = new Set<string>()
    return out.filter((c) => {
      const key = `${c.chunkSize}:${c.chunkOverlap}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [chunkOverlap, chunkSize, effectiveStep, sizeMax, sizeMin])

  const scoredTop = useMemo(() => {
    const minCoverage = minCoveragePct / 100
    const maxWaste = maxOverlapWastePct / 100
    const candidatesPassingConstraints = results.flatMap((candidate) => {
      const { stats } = candidate
      if (!candidate.ok || stats === undefined) return []
      const { coverage_ratio: coverage, overlap_waste_ratio: waste, count } = stats
      if (typeof coverage !== 'number' || typeof waste !== 'number') return []
      if (coverage < minCoverage || waste > maxWaste || (maxChunksCap > 0 && count > maxChunksCap)) return []

      return [{ ...candidate, stats: { ...stats, coverage_ratio: coverage, overlap_waste_ratio: waste }, pass: true }]
    })

    candidatesPassingConstraints.sort((left, right) => {
      const wasteDifference = left.stats.overlap_waste_ratio - right.stats.overlap_waste_ratio
      if (wasteDifference !== 0) return wasteDifference
      const coverageDifference = right.stats.coverage_ratio - left.stats.coverage_ratio
      if (coverageDifference !== 0) return coverageDifference
      const chunkCountDifference = left.stats.count - right.stats.count
      if (chunkCountDifference !== 0) return chunkCountDifference
      const leftShortCount = left.stats.short_count
      const rightShortCount = right.stats.short_count
      if (typeof leftShortCount !== 'number') return typeof rightShortCount === 'number' ? 1 : 0
      if (typeof rightShortCount !== 'number') return -1
      return leftShortCount - rightShortCount
    })

    return candidatesPassingConstraints.slice(0, topN)
  }, [maxChunksCap, maxOverlapWastePct, minCoveragePct, results, topN])

  const runTune = async () => {
    if (!isAutoTuneAvailable) {
      toast.error(
        isSeparatorStrategy ? t('autoTune.unavailable.separatorStrategy') : t('autoTune.unavailable.previewRequired'),
      )
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const authScope = getAuthCacheScope()
    const sessionRevision = getAuthSessionRevision()
    const isCurrent = () =>
      abortRef.current === controller &&
      !controller.signal.aborted &&
      getAuthCacheScope() === authScope &&
      getAuthSessionRevision() === sessionRevision

    setRunning(true)
    setResults([])

    const baseParams = {
      ...buildChunkPreviewRequestParams(),
      file_sha256: sha,
      file_type: preview?.file_type,
      filename: currentFile.name,
      file_size: preview?.file_size ?? currentFile.size,
      include_original_text: false,
      include_chunks: false,
      include_review_signals: false,
      max_chunks: 0,
      use_parse_cache: true,
    }

    const started = performance.now()
    const out: TuneCandidate[] = []

    try {
      for (let i = 0; i < candidates.length; i += 1) {
        if (!isCurrent()) break
        const c = candidates[i]
        const t0 = performance.now()
        try {
          const res = await documentApi.chunkPreviewBySha(
            {
              ...baseParams,
              chunk_size: c.chunkSize,
              chunk_overlap: c.chunkOverlap,
            },
            { signal: controller.signal },
          )
          if (!isCurrent()) break
          const dur = Math.max(0, Math.round(performance.now() - t0))
          const stats = res.stats
          out.push({
            chunkSize: c.chunkSize,
            chunkOverlap: c.chunkOverlap,
            ok: true,
            durationMs: dur,
            stats: stats
              ? {
                  count: res.total_chunks,
                  avg: stats.avg,
                  p90: stats.p90,
                  short_count: stats.short_count,
                  coverage_ratio: stats.coverage_ratio,
                  overlap_waste_ratio: stats.overlap_waste_ratio,
                }
              : undefined,
            quality: res.quality_gate ?? null,
          })
        } catch (err: unknown) {
          if (!isCurrent()) break
          out.push({
            chunkSize: c.chunkSize,
            chunkOverlap: c.chunkOverlap,
            ok: false,
            error: formatApiError(err, t('autoTune.toasts.requestFailed')),
          })
        }
        // Keep UI responsive for long runs.
        if (i % 2 === 1) setResults([...out])
      }
    } finally {
      const completed = isCurrent()
      if (completed) setResults(out)
      if (abortRef.current === controller) {
        abortRef.current = null
        setRunning(false)
      }
      const total = Math.max(0, Math.round(performance.now() - started))
      if (completed) {
        const okCount = out.filter((result) => result.ok).length
        if (okCount === 0) toast.error(out[0]?.error ?? t('autoTune.toasts.requestFailed'))
        else toast.success(t('autoTune.toasts.completed', { okCount, totalCount: out.length, durationMs: total }))
      }
    }
  }

  const exportJson = () => {
    if (!isAutoTuneAvailable) return
    const filename = currentFile.name
    const payload = {
      filename,
      file_sha256: sha,
      strategy: chunkStrategy,
      parser_backend: parserBackend,
      constraints: {
        min_coverage_pct: minCoveragePct,
        max_overlap_waste_pct: maxOverlapWastePct,
        max_chunks: maxChunksCap,
        top_n: topN,
      },
      candidates: results,
      recommendations: scoredTop,
    }
    const safe = sanitizeFilename(filename)
    downloadTextFile(`${safe}.chunk-auto-tune.json`, JSON.stringify(payload, null, 2))
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) abortRef.current?.abort()
    setOpen(nextOpen)
  }

  const applyCandidate = async (c: TuneCandidate) => {
    updateSettings({ chunkSize: c.chunkSize, chunkOverlap: c.chunkOverlap })
    handleOpenChange(false)
    // Force a fresh preview so the user sees the actual chunk output.
    await runPreview({ force: true, settings: { chunkSize: c.chunkSize, chunkOverlap: c.chunkOverlap } })
  }

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-6 rounded-md border-border/50 bg-background/75 px-2 text-[11px] font-medium text-muted-foreground shadow-none hover:bg-muted/45 hover:text-muted-foreground"
        onClick={() => setOpen(true)}
        disabled={!previewData || isLoading}
        title={isAutoTuneAvailable ? t('autoTune.trigger.readyTitle') : t('autoTune.trigger.disabledTitle')}
      >
        <Wand2 className="mr-1 h-3 w-3 text-info" />
        {t('autoTune.trigger.label')}
      </Button>

      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t('autoTune.dialog.title')}</DialogTitle>
            <DialogDescription>{t('autoTune.dialog.description')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="rounded-xl border border-border/60 bg-muted/10 p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-sm font-medium">{t('autoTune.currentFile.title')}</div>
                {running ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2 text-[11px]"
                    onClick={() => abortRef.current?.abort()}
                  >
                    <X className="w-3.5 h-3.5 mr-1" />
                    {t('autoTune.currentFile.cancel')}
                  </Button>
                ) : null}
              </div>
              <div className="mt-1 text-xs text-muted-foreground font-mono break-all">
                {t('autoTune.currentFile.summary', {
                  filename: currentFile?.name ?? previewData?.filename ?? '-',
                  sha: sha?.slice(0, 10) ?? '-',
                  strategy: chunkStrategy,
                  unit: isTokenStrategy ? 'tokens' : 'chars',
                })}
              </div>
              {isAutoTuneAvailable ? null : (
                <div className="mt-2 text-xs text-warning">
                  {isSeparatorStrategy
                    ? t('autoTune.unavailable.separatorStrategyDetail')
                    : t('autoTune.unavailable.previewRequiredDetail')}
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor={`${formId}-coverage`} className="text-xs">
                  {t('autoTune.labels.minCoverage')}
                </Label>
                <Input
                  id={`${formId}-coverage`}
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={100}
                  step={1}
                  value={minCoveragePct}
                  onChange={(e) => setMinCoveragePct(clampInt(Number(e.target.value), 0, 100))}
                  className="h-8 font-mono text-xs"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor={`${formId}-overlap`} className="text-xs">
                  {t('autoTune.labels.maxOverlapWaste')}
                </Label>
                <Input
                  id={`${formId}-overlap`}
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={100}
                  step={1}
                  value={maxOverlapWastePct}
                  onChange={(e) => setMaxOverlapWastePct(clampInt(Number(e.target.value), 0, 100))}
                  className="h-8 font-mono text-xs"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor={`${formId}-chunks`} className="text-xs">
                  {t('autoTune.labels.maxChunks')}
                </Label>
                <Input
                  id={`${formId}-chunks`}
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={20000}
                  step={10}
                  value={maxChunksCap}
                  onChange={(e) => setMaxChunksCap(clampInt(Number(e.target.value), 0, 20000))}
                  className="h-8 font-mono text-xs"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor={`${formId}-top`} className="text-xs">
                  {t('autoTune.labels.topN')}
                </Label>
                <Input
                  id={`${formId}-top`}
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={20}
                  step={1}
                  value={topN}
                  onChange={(e) => setTopN(clampInt(Number(e.target.value), 1, 20))}
                  className="h-8 font-mono text-xs"
                />
              </div>
            </div>

            <div className="flex items-center justify-between gap-2">
              <div className="text-xs text-muted-foreground">
                {t('autoTune.labels.searchSpace', {
                  count: candidates.length,
                  sizeMin,
                  sizeMax,
                  step: effectiveStep,
                })}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 px-3 text-xs"
                  onClick={() => exportJson()}
                  disabled={!results.length}
                >
                  <Download className="w-3.5 h-3.5 mr-1" />
                  {t('autoTune.actions.exportJson')}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  className="h-8 px-3 text-xs"
                  onClick={() => detachPromise(runTune())}
                  disabled={!isAutoTuneAvailable || running}
                >
                  {running ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin motion-reduce:animate-none" /> : null}
                  {t('autoTune.actions.start')}
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-border/60 overflow-hidden">
              <table aria-label={t('autoTune.table.ariaLabel')} className="w-full text-xs">
                <thead className="bg-muted/40 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">{t('autoTune.table.params')}</th>
                    <th className="px-3 py-2 text-left font-medium">{t('autoTune.table.coverage')}</th>
                    <th className="px-3 py-2 text-left font-medium">{t('autoTune.table.waste')}</th>
                    <th className="px-3 py-2 text-left font-medium">{t('autoTune.table.chunks')}</th>
                    <th className="px-3 py-2 text-left font-medium">{t('autoTune.table.avgP90')}</th>
                    <th className="px-3 py-2 text-left font-medium">{t('autoTune.table.grade')}</th>
                    <th className="px-3 py-2 text-right font-medium">{t('autoTune.table.action')}</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    if (scoredTop.length) {
                      return scoredTop.map((r) => (
                        <tr key={`${r.chunkSize}:${r.chunkOverlap}`} className="border-t border-border/60">
                          <td className="px-3 py-2 font-mono">
                            {t('autoTune.table.paramsValue', {
                              chunkSize: r.chunkSize,
                              chunkOverlap: r.chunkOverlap,
                            })}
                          </td>
                          <td className="px-3 py-2 font-mono">{Math.round(r.stats.coverage_ratio * 100)}%</td>
                          <td className="px-3 py-2 font-mono">{Math.round(r.stats.overlap_waste_ratio * 100)}%</td>
                          <td className="px-3 py-2 font-mono">{r.stats.count}</td>
                          <td className="px-3 py-2 font-mono">
                            {typeof r.stats.avg === 'number' ? Math.trunc(r.stats.avg) : '-'}/
                            {typeof r.stats.p90 === 'number' ? Math.trunc(r.stats.p90) : '-'}
                          </td>
                          <td className="px-3 py-2 font-mono">{r.quality?.grade ?? '-'}</td>
                          <td className="px-3 py-2 text-right">
                            <Button
                              type="button"
                              size="sm"
                              className="h-7 px-2 text-[11px]"
                              onClick={() => detachPromise(applyCandidate(r))}
                            >
                              {t('autoTune.actions.applyAndPreview')}
                            </Button>
                          </td>
                        </tr>
                      ))
                    } else if (results.length) {
                      return (
                        <tr className="border-t border-border/60">
                          <td className="px-3 py-3 text-muted-foreground" colSpan={7}>
                            {results.some((result) => result.ok)
                              ? t('autoTune.empty.noMatches')
                              : (results[0].error ?? t('autoTune.toasts.requestFailed'))}
                          </td>
                        </tr>
                      )
                    } else {
                      return (
                        <tr className="border-t border-border/60">
                          <td className="px-3 py-3 text-muted-foreground" colSpan={7}>
                            {t('autoTune.empty.noResults')}
                          </td>
                        </tr>
                      )
                    }
                  })()}
                </tbody>
              </table>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
