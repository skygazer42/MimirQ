/**
 * ChunkAutoTuneDialog
 * Auto-search chunk_size/chunk_overlap for a given file + strategy constraints.
 *
 * Notes:
 * - Uses /documents/chunk-preview/by-sha with include_chunks=false to keep payload small.
 * - Intended for "enterprise tuning" workflows (TopN recommendations + one-click apply).
 */
'use client'

import { useMemo, useRef, useState } from 'react'
import { Wand2, Loader2, X, Download } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { downloadTextFile, sanitizeFilename } from '@/components/chunk-preview/utils/export'
import { detachPromise } from '@/lib/utils'


type TuneCandidate = {
  chunkSize: number
  chunkOverlap: number
  ok: boolean
  error?: string
  durationMs?: number
  stats?: {
    count: number
    avg: number
    p90: number
    short_count: number
    coverage_ratio: number
    overlap_waste_ratio: number
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
  const {
    currentFile,
    currentFileItem,
    previewData,
    isLoading,
    chunkSize,
    chunkOverlap,
    chunkStrategy,
    parserBackend,
    datasetId,
    parentChildRatio,
    parentChildMinChildSize,
    updateSettings,
    runPreview,
  } = useChunkPreview()
  const pipelineCtx = usePipelineOptions()

  const [open, setOpen] = useState(false)
  const [running, setRunning] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const [minCoveragePct, setMinCoveragePct] = useState(98)
  const [maxOverlapWastePct, setMaxOverlapWastePct] = useState(35)
  const [maxChunksCap, setMaxChunksCap] = useState(0)
  const [topN, setTopN] = useState(5)

  const [results, setResults] = useState<TuneCandidate[]>([])

  const sha = previewData?.file_sha256
  const fileType = previewData?.file_type
  const fileSize = previewData?.file_size
  const filename = currentFile?.name || currentFileItem?.displayName || previewData?.filename || 'file'

  const isTokenStrategy = previewData?.params?.unit === 'tokens' || chunkStrategy === 'langchain_token'
  const isSeparatorStrategy = chunkStrategy === 'separator' || previewData?.chunk_strategy === 'separator'
  const isAutoTuneAvailable = Boolean(sha && currentFile && !isSeparatorStrategy)

  const effectiveStep = isTokenStrategy ? 50 : 100
  const sizeMin = isTokenStrategy ? 50 : 100
  const sizeMax = isTokenStrategy ? 2000 : 4000

  const candidates = useMemo(() => {
    const base = clampInt(chunkSize || 1000, sizeMin, sizeMax)
    const multipliers = [0.6, 0.8, 1.0, 1.2, 1.5, 1.8]
    const sizes = uniqSorted(
      multipliers.map((m) => clampInt(roundToStep(base * m, effectiveStep), sizeMin, sizeMax))
    )

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
    const minCoverage = Math.max(0, Math.min(1, (Number(minCoveragePct) || 0) / 100))
    const maxWaste = Math.max(0, Math.min(1, (Number(maxOverlapWastePct) || 0) / 100))
    const maxChunks = Math.max(0, Math.trunc(Number(maxChunksCap) || 0))
    const keep = results
      .filter((r) => r.ok && r.stats)
      .map((r) => {
        const s = r.stats!
        const passCoverage = Number.isFinite(s.coverage_ratio) ? s.coverage_ratio >= minCoverage : true
        const passWaste = Number.isFinite(s.overlap_waste_ratio) ? s.overlap_waste_ratio <= maxWaste : true
        const passChunks = maxChunks > 0 ? s.count <= maxChunks : true
        const pass = passCoverage && passWaste && passChunks
        return { ...r, pass }
      })
      .filter((r) => r.pass)

    keep.sort((a, b) => {
      const wa = a.stats?.overlap_waste_ratio ?? 1
      const wb = b.stats?.overlap_waste_ratio ?? 1
      if (wa !== wb) return wa - wb
      const ca = a.stats?.coverage_ratio ?? 0
      const cb = b.stats?.coverage_ratio ?? 0
      if (ca !== cb) return cb - ca
      const na = a.stats?.count ?? 0
      const nb = b.stats?.count ?? 0
      if (na !== nb) return na - nb
      const sa = a.stats?.short_count ?? 0
      const sb = b.stats?.short_count ?? 0
      return sa - sb
    })

    const n = clampInt(Number(topN) || 5, 1, 20)
    return keep.slice(0, n)
  }, [maxChunksCap, maxOverlapWastePct, minCoveragePct, results, topN])

  const runTune = async () => {
    if (!isAutoTuneAvailable) {
      toast.error(
        isSeparatorStrategy
          ? t('autoTune.unavailable.separatorStrategy')
          : t('autoTune.unavailable.previewRequired')
      )
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setRunning(true)
    setResults([])

    const baseParams = {
    file_sha256: String(sha),
    file_type: fileType || undefined,
    filename: String(filename),
    file_size: typeof fileSize === 'number' ? fileSize : currentFile?.size,
    parser_backend: parserBackend || 'auto',
    chunk_strategy: chunkStrategy || 'langchain_recursive',
    dataset_id: datasetId || undefined,
    pipeline: pipelineCtx.enabled ? pipelineCtx.options : undefined,
    // Performance: stats-only, no original text.
    include_original_text: false,
    include_chunks: false,
    max_chunks: 0,
    use_parse_cache: true,
    // Strategy-specific.
    child_ratio: chunkStrategy === 'parent_child' ? parentChildRatio : undefined,
    min_child_size: chunkStrategy === 'parent_child' ? parentChildMinChildSize : undefined,
}

    const started = performance.now()
    const out: TuneCandidate[] = []

    try {
      for (let i = 0; i < candidates.length; i += 1) {
        if (controller.signal.aborted) break
        const c = candidates[i]
        const t0 = performance.now()
        try {
          const res = await documentApi.chunkPreviewBySha(
            {
              ...baseParams,
              chunk_size: c.chunkSize,
              chunk_overlap: c.chunkOverlap,
            },
            { signal: controller.signal }
          )
          const dur = Math.max(0, Math.round(performance.now() - t0))
          const s = res.stats
          out.push({
            chunkSize: c.chunkSize,
            chunkOverlap: c.chunkOverlap,
            ok: true,
            durationMs: dur,
            stats: s
              ? {
                  count: Math.max(0, Math.trunc(Number(res.total_chunks ?? s.count ?? 0) || 0)),
                  avg: Math.max(0, Math.trunc(Number(s.avg ?? 0) || 0)),
                  p90: Math.max(0, Math.trunc(Number(s.p90 ?? 0) || 0)),
                  short_count: Math.max(0, Math.trunc(Number(s.short_count ?? 0) || 0)),
                  coverage_ratio: Number(s.coverage_ratio ?? 0) || 0,
                  overlap_waste_ratio: Number(s.overlap_waste_ratio ?? 0) || 0,
                }
              : undefined,
            quality: res.quality_gate ?? null,
          })
        } catch (err: unknown) {
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
      setResults([...out])
      setRunning(false)
      const total = Math.max(0, Math.round(performance.now() - started))
      if (!controller.signal.aborted) {
        toast.success(
          t('autoTune.toasts.completed', {
            okCount: out.filter((x) => x.ok).length,
            totalCount: out.length,
            durationMs: total,
          })
        )
      }
    }
  }

  const exportJson = () => {
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

  const applyCandidate = async (c: TuneCandidate) => {
    updateSettings({ chunkSize: c.chunkSize, chunkOverlap: c.chunkOverlap })
    setOpen(false)
    // Force a fresh preview so the user sees the actual chunk output.
    await runPreview({ force: true })
  }

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="h-6 rounded-md border-border/50 bg-background/75 px-2 text-[10px] font-medium text-muted-foreground shadow-none hover:bg-muted/45"
        onClick={() => setOpen(true)}
        disabled={!previewData || isLoading}
        title={isAutoTuneAvailable ? t('autoTune.trigger.readyTitle') : t('autoTune.trigger.disabledTitle')}
      >
        <Wand2 className="mr-1 h-3 w-3 text-sky-700 dark:text-sky-200" />
        {t('autoTune.trigger.label')}
      </Button>

      <Dialog
        open={open}
        onOpenChange={(v) => {
          if (!v) abortRef.current?.abort()
          setOpen(v)
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t('autoTune.dialog.title')}</DialogTitle>
            <DialogDescription>
              {t('autoTune.dialog.description')}
            </DialogDescription>
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
                  filename,
                  sha: sha ? String(sha).slice(0, 10) : '-',
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
                <Label className="text-xs">{t('autoTune.labels.minCoverage')}</Label>
                <Input
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
                <Label className="text-xs">{t('autoTune.labels.maxOverlapWaste')}</Label>
                <Input
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
                <Label className="text-xs">{t('autoTune.labels.maxChunks')}</Label>
                <Input
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
                <Label className="text-xs">{t('autoTune.labels.topN')}</Label>
                <Input
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
        return (scoredTop.map((r) => (<tr key={`${r.chunkSize}:${r.chunkOverlap}`} className="border-t border-border/60">
                        <td className="px-3 py-2 font-mono">
                          {t('autoTune.table.paramsValue', {
                            chunkSize: r.chunkSize,
                            chunkOverlap: r.chunkOverlap,
                          })}
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {r.stats ? `${Math.round((r.stats.coverage_ratio || 0) * 100)}%` : '-'}
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {r.stats ? `${Math.round((r.stats.overlap_waste_ratio || 0) * 100)}%` : '-'}
                        </td>
                        <td className="px-3 py-2 font-mono">{r.stats ? r.stats.count : '-'}</td>
                        <td className="px-3 py-2 font-mono">
                          {r.stats ? `${r.stats.avg}/${r.stats.p90}` : '-'}
                        </td>
                        <td className="px-3 py-2 font-mono">{r.quality?.grade || '-'}</td>
                        <td className="px-3 py-2 text-right">
                          <Button type="button" size="sm" className="h-7 px-2 text-[11px]" onClick={() => detachPromise(applyCandidate(r))}>
                            {t('autoTune.actions.applyAndPreview')}
                          </Button>
                        </td>
                      </tr>)));
    }
    else if (results.length) {
            return (<tr className="border-t border-border/60">
                      <td className="px-3 py-3 text-muted-foreground" colSpan={7}>
                        {t('autoTune.empty.noMatches')}
                      </td>
                    </tr>);
        }
        else {
            return (<tr className="border-t border-border/60">
                      <td className="px-3 py-3 text-muted-foreground" colSpan={7}>
                        {t('autoTune.empty.noResults')}
                      </td>
                    </tr>);
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
