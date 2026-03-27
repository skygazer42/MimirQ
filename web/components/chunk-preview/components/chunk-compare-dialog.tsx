/**
 * ChunkCompareDialog - Compare two preview runs (A/B)
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
import { Download, GitCompareArrows, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { getChunkMetadata, getStringValue } from '@/components/chunk-preview/utils/metadata'
import { cn } from '@/lib/utils'
import type { ChunkPreviewResponse } from '@/types'
import { buildSemanticEvidenceHighlights, chunkPreviewDiffToExport, computeChunkPreviewDiff } from '@/components/chunk-preview/utils/ab-diff'
import { downloadTextFile, sanitizeFilename } from '@/components/chunk-preview/utils/export'

type RunHistoryItem = {
  id: string
  fileName: string
  parserBackend: string
  strategy: string
  chunkSize: number
  chunkOverlap: number
  totalChunks: number
  durationMs: number
  createdAt: number
  cacheHit: boolean
  cacheKey?: string
}

function formatDelta(n: number) {
  if (!Number.isFinite(n) || n === 0) return '0'
  return n > 0 ? `+${n}` : String(n)
}

function formatPct(ratio: number | null) {
  if (ratio == null || !Number.isFinite(ratio)) return '-'
  return `${Math.round(ratio * 100)}%`
}

function formatDeltaPct(deltaRatio: number | null) {
  if (deltaRatio == null || !Number.isFinite(deltaRatio) || deltaRatio === 0) return '0%'
  const v = Math.round(deltaRatio * 100)
  return v > 0 ? `+${v}%` : `${v}%`
}

function extractHierarchyBasis(preview: ChunkPreviewResponse): string[] {
  const bases = new Set<string>()
  for (const c of preview?.chunks || []) {
    const basis = getStringValue(getChunkMetadata(c), 'hierarchy_basis')
    if (!basis) continue
    bases.add(basis)
  }
  return Array.from(bases).sort()
}

function EvidenceHighlightsPanel(props: Readonly<{
  title: string
  emptyLabel: string
  tone: 'added' | 'removed'
  items: ReturnType<typeof buildSemanticEvidenceHighlights>['added']
}>) {
  const { title, emptyLabel, tone, items } = props
  const toneClass =
    tone === 'added'
      ? 'border-info/30 bg-info/5 text-info'
      : 'border-warning/30 bg-warning/5 text-warning'

  return (
    <div className="rounded-2xl border border-border/60 bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-foreground">{title}</div>
        <div className={cn('rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase', toneClass)}>
          {items.length}
        </div>
      </div>

      {items.length === 0 ? (
        <div className="mt-3 rounded-xl border border-dashed border-border/60 bg-muted/20 px-3 py-4 text-xs text-muted-foreground">
          {emptyLabel}
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          {items.map((item) => (
            <div key={`${tone}:${item.index}:${item.example.slice(0, 24)}`} className="rounded-xl border border-border/60 bg-background/80 p-3">
              <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                <span>Chunk #{item.index}</span>
                <span className="font-mono">x{item.count}</span>
              </div>
              <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/90">
                {item.segments.map((segment, index) =>
                  segment.emphasis ? (
                    <mark
                      key={`${tone}:${item.index}:${index}`}
                      className={cn(
                        'rounded px-0.5',
                        tone === 'added'
                          ? 'bg-info/15 text-info'
                          : 'bg-warning/15 text-warning'
                      )}
                    >
                      {segment.text}
                    </mark>
                  ) : (
                    <span key={`${tone}:${item.index}:${index}`}>{segment.text}</span>
                  )
                )}
              </div>
              {item.referenceExample ? (
                <div className="mt-3 border-t border-border/50 pt-3">
                  <div className="text-[10px] font-medium uppercase text-muted-foreground">Closest opposite evidence</div>
                  <div className="mt-1 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
                    {item.referenceExample}
                  </div>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function ChunkCompareDialog(props: Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  current: ChunkPreviewResponse
  currentFileName: string
  runHistory: RunHistoryItem[]
  getCachedPreview: (cacheKey: string) => ChunkPreviewResponse | null
}>) {
  const { open, onOpenChange, current, currentFileName, runHistory, getCachedPreview } = props

  const candidates = useMemo(() => {
    const list = (runHistory || [])
      .filter((item) => item.fileName === currentFileName && typeof item.cacheKey === 'string' && Boolean(item.cacheKey))
      .sort((a, b) => b.createdAt - a.createdAt)
    return list
  }, [runHistory, currentFileName])

  const [baselineKey, setBaselineKey] = useState<string>('')

  useEffect(() => {
    if (!open) return
    const next =
      (candidates.length > 1 ? candidates[1]?.cacheKey : candidates[0]?.cacheKey) ||
      ''
    setBaselineKey(next)
  }, [open, candidates])

  const baseline = useMemo(() => {
    const key = (baselineKey || '').trim()
    if (!key) return null
    return getCachedPreview(key)
  }, [baselineKey, getCachedPreview])

  const currentHierarchyBasis = useMemo(() => extractHierarchyBasis(current), [current])
  const baselineHierarchyBasis = useMemo(() => (baseline ? extractHierarchyBasis(baseline) : []), [baseline])

  const diff = useMemo(() => {
    if (!baseline) return null
    return computeChunkPreviewDiff(baseline, current)
  }, [baseline, current])
  const evidenceHighlights = useMemo(() => (diff ? buildSemanticEvidenceHighlights(diff) : null), [diff])

  const baselineMeta = useMemo(() => {
    if (!baselineKey) return null
    return candidates.find((c) => c.cacheKey === baselineKey) || null
  }, [baselineKey, candidates])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[92vw] max-w-[980px] p-0 overflow-hidden">
        <div className="p-6 border-b border-border/60 bg-card/80">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <GitCompareArrows className="w-5 h-5 text-primary" />
              预览对比（A/B）
            </DialogTitle>
            <DialogDescription className="text-xs">
              基于 chunk 内容的快速对比（哈希匹配，适合调参时判断“块有没有变好/变坏”）。
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="p-6 space-y-4">
          {candidates.length < 2 ? (
            <div className="flex items-start gap-2 text-sm text-muted-foreground bg-muted/40 border border-border/60 rounded-xl p-4">
              <Info className="w-4 h-4 mt-0.5" />
              <div>
                需要至少两次预览（同一个文件）才能对比。先修改参数并点击“预览”。
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-col md:flex-row md:items-center gap-3">
                <div className="text-xs text-muted-foreground min-w-[72px]">基线（A）</div>
                <Select value={baselineKey} onValueChange={(v) => setBaselineKey(v)}>
                  <SelectTrigger className="h-9 w-full md:w-[520px] text-xs bg-card/80">
                    <SelectValue placeholder="选择一个历史预览作为基线" />
                  </SelectTrigger>
                  <SelectContent>
                    {candidates.slice(1).map((item) => (
                      <SelectItem key={item.id} value={String(item.cacheKey || '')}>
                        {new Date(item.createdAt).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}{' '}
                        · {item.strategy} · {item.chunkSize}/{item.chunkOverlap} · {item.totalChunks} chunks
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="text-xs text-muted-foreground flex-1">
                  当前（B）：{current.chunk_strategy} · {current.params?.chunk_size}/{current.params?.chunk_overlap} · {current.total_chunks} chunks
                  {currentHierarchyBasis.length ? ` · hierarchy_basis=${currentHierarchyBasis.join(',')}` : ''}
                </div>
              </div>

              {baseline && diff ? (
                <div className="space-y-3">
                  <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
                    <div className="bg-card border border-border/60 rounded-xl p-4">
                    <div className="text-[10px] text-muted-foreground uppercase  font-medium">Chunks</div>
                    <div className="mt-2 flex items-end justify-between">
                      <div className="text-sm font-mono text-foreground/90">{diff.bCount}</div>
                      <div className={cn('text-xs font-mono', (() => {
    if (diff.deltaCount === 0) {
        return 'text-muted-foreground';
    }
    else if (diff.deltaCount > 0) {
            return 'text-info';
        }
        else {
            return 'text-warning';
        }
})())}>
                        {formatDelta(diff.deltaCount)}
                      </div>
                    </div>
                    <div className="mt-2 text-[11px] text-muted-foreground">
                      A: {diff.aCount} · B: {diff.bCount}
                    </div>
                    </div>

                    <div className="bg-card border border-border/60 rounded-xl p-4">
                    <div className="text-[10px] text-muted-foreground uppercase  font-medium">长度分布（{diff.unit}）</div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div className="text-muted-foreground">
                        P10<br />
                        <span className="font-mono text-foreground/90">{diff.bP10 ?? '-'}</span>
                        <span className="ml-1 text-muted-foreground">({formatDelta((diff.bP10 ?? 0) - (diff.aP10 ?? 0))})</span>
                      </div>
                      <div className="text-muted-foreground">
                        Avg<br />
                        <span className="font-mono text-foreground/90">{diff.bAvg ?? '-'}</span>
                        <span className="ml-1 text-muted-foreground">({formatDelta((diff.bAvg ?? 0) - (diff.aAvg ?? 0))})</span>
                      </div>
                      <div className="text-muted-foreground">
                        P95<br />
                        <span className="font-mono text-foreground/90">{diff.bP95 ?? '-'}</span>
                        <span className="ml-1 text-muted-foreground">({formatDelta((diff.bP95 ?? 0) - (diff.aP95 ?? 0))})</span>
                      </div>
                    </div>
                    </div>

                    <div className="bg-card border border-border/60 rounded-xl p-4">
                    <div className="text-[10px] text-muted-foreground uppercase  font-medium">内容重合度（估算）</div>
                    <div className="mt-2 flex items-end justify-between">
                      <div className="text-sm font-mono text-foreground/90">{Math.round((diff.overlap || 0) * 100)}%</div>
                      <div className="text-[11px] text-muted-foreground">
                        +{diff.added} / -{diff.removed}
                      </div>
                    </div>
                    <div className="mt-2 text-[11px] text-muted-foreground">
                      以 trimmed chunk 内容哈希做 multiset 匹配；不考虑顺序和微小改动。
                    </div>
                    </div>

                    <div className="bg-card border border-border/60 rounded-xl p-4">
                    <div className="text-[10px] text-muted-foreground uppercase  font-medium">覆盖/重叠/质量</div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div className="text-muted-foreground">
                        coverage<br />
                        <span className="font-mono text-foreground/90">{formatPct(diff.bCoverage)}</span>
                        <span className="ml-1 text-muted-foreground">({formatDeltaPct(diff.deltaCoverage)})</span>
                      </div>
                      <div className="text-muted-foreground">
                        waste<br />
                        <span className="font-mono text-foreground/90">{formatPct(diff.bWaste)}</span>
                        <span className="ml-1 text-muted-foreground">({formatDeltaPct(diff.deltaWaste)})</span>
                      </div>
                      <div className="text-muted-foreground">
                        gaps<br />
                        <span className="font-mono text-foreground/90">{diff.bGapCount ?? '-'}</span>
                        <span className="ml-1 text-muted-foreground">({formatDelta((diff.bGapCount ?? 0) - (diff.aGapCount ?? 0))})</span>
                      </div>
                    </div>
                    <div className="mt-2 text-[11px] text-muted-foreground">
                      quality A: {baseline.quality_gate?.grade ?? '-'} · B: {current.quality_gate?.grade ?? '-'}
                    </div>
                    </div>
                  </div>

                  {evidenceHighlights ? (
                    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
                      <EvidenceHighlightsPanel
                        title="新增证据"
                        emptyLabel="当前版本没有新增的关键证据。"
                        tone="added"
                        items={evidenceHighlights.added}
                      />
                      <EvidenceHighlightsPanel
                        title="丢失证据"
                        emptyLabel="当前版本没有丢失的关键证据。"
                        tone="removed"
                        items={evidenceHighlights.removed}
                      />
                    </div>
                  ) : null}
                </div>
              ) : null}

              {baselineMeta ? (
                <div className="text-[11px] text-muted-foreground">
                  基线（A）来源：{baselineMeta.strategy} · {baselineMeta.chunkSize}/{baselineMeta.chunkOverlap} · {baselineMeta.durationMs}ms
                  {baselineMeta.cacheHit ? ' · Hit Cache' : ''}
                  {baselineHierarchyBasis.length ? ` · hierarchy_basis=${baselineHierarchyBasis.join(',')}` : ''}
                </div>
              ) : null}

              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={!baseline}
                  onClick={() => {
                    if (!baseline) return
                    const payload = chunkPreviewDiffToExport(baseline, current, {
                      baseline_cache_key: baselineKey || undefined,
                    })
                    const filename = `${sanitizeFilename(currentFileName)}.chunk-preview.diff.json`
                    downloadTextFile(filename, JSON.stringify(payload, null, 2), 'application/json;charset=utf-8')
                  }}
                >
                  <Download className="mr-2 h-4 w-4" />
                  导出 diff.json
                </Button>
                <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
                  关闭
                </Button>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
