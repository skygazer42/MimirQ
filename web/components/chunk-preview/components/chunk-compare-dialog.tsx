/**
 * ChunkCompareDialog - Compare two preview runs (A/B)
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
import { GitCompareArrows, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { ChunkPreviewResponse } from '@/types'

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

function fnv1a32(input: string) {
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

function formatDelta(n: number) {
  if (!Number.isFinite(n) || n === 0) return '0'
  return n > 0 ? `+${n}` : String(n)
}

function safeNum(value: any): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function buildMultiset(chunks: Array<{ index: number; content?: string }>) {
  const map = new Map<string, { count: number; example: string; firstIndex: number }>()
  for (const c of chunks || []) {
    const trimmed = String(c?.content ?? '').trim()
    if (!trimmed) continue
    const key = fnv1a32(trimmed)
    const prev = map.get(key)
    if (prev) {
      prev.count += 1
      continue
    }
    map.set(key, { count: 1, example: trimmed.slice(0, 160), firstIndex: Number(c.index) })
  }
  return map
}

export function ChunkCompareDialog(props: {
  open: boolean
  onOpenChange: (open: boolean) => void
  current: ChunkPreviewResponse
  currentFileName: string
  runHistory: RunHistoryItem[]
  getCachedPreview: (cacheKey: string) => ChunkPreviewResponse | null
}) {
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

  const diff = useMemo(() => {
    if (!baseline) return null
    const a = baseline
    const b = current

    const aStats = a.stats || {}
    const bStats = b.stats || {}

    const aAvg = safeNum(aStats.avg)
    const bAvg = safeNum(bStats.avg)
    const aP10 = safeNum(aStats.p10)
    const bP10 = safeNum(bStats.p10)
    const aP90 = safeNum(aStats.p90)
    const bP90 = safeNum(bStats.p90)

    const aSet = buildMultiset(a.chunks || [])
    const bSet = buildMultiset(b.chunks || [])

    let common = 0
    let total = 0
    let added = 0
    let removed = 0
    const examplesAdded: Array<{ example: string; count: number; index: number }> = []
    const examplesRemoved: Array<{ example: string; count: number; index: number }> = []

    const keys = new Set<string>([...aSet.keys(), ...bSet.keys()])
    for (const key of keys) {
      const av = aSet.get(key)?.count || 0
      const bv = bSet.get(key)?.count || 0
      common += Math.min(av, bv)
      total += Math.max(av, bv)
      if (bv > av) {
        const delta = bv - av
        added += delta
        const meta = bSet.get(key)
        if (meta) examplesAdded.push({ example: meta.example, count: delta, index: meta.firstIndex })
      } else if (av > bv) {
        const delta = av - bv
        removed += delta
        const meta = aSet.get(key)
        if (meta) examplesRemoved.push({ example: meta.example, count: delta, index: meta.firstIndex })
      }
    }

    examplesAdded.sort((x, y) => y.count - x.count)
    examplesRemoved.sort((x, y) => y.count - x.count)

    const overlap = total > 0 ? common / total : 0

    return {
      unit: (b.params?.unit || a.params?.unit || 'chars') as string,
      aCount: Number(a.total_chunks || 0),
      bCount: Number(b.total_chunks || 0),
      deltaCount: Number(b.total_chunks || 0) - Number(a.total_chunks || 0),
      aAvg,
      bAvg,
      aP10,
      bP10,
      aP90,
      bP90,
      added,
      removed,
      overlap,
      examplesAdded: examplesAdded.slice(0, 3),
      examplesRemoved: examplesRemoved.slice(0, 3),
    }
  }, [baseline, current])

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
                </div>
              </div>

              {baseline && diff ? (
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                  <div className="bg-card border border-border/60 rounded-xl p-4">
                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">Chunks</div>
                    <div className="mt-2 flex items-end justify-between">
                      <div className="text-sm font-mono text-foreground/90">{diff.bCount}</div>
                      <div className={cn('text-xs font-mono', diff.deltaCount === 0 ? 'text-muted-foreground' : diff.deltaCount > 0 ? 'text-info' : 'text-warning')}>
                        {formatDelta(diff.deltaCount)}
                      </div>
                    </div>
                    <div className="mt-2 text-[11px] text-muted-foreground">
                      A: {diff.aCount} · B: {diff.bCount}
                    </div>
                  </div>

                  <div className="bg-card border border-border/60 rounded-xl p-4">
                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">长度分布（{diff.unit}）</div>
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
                        P90<br />
                        <span className="font-mono text-foreground/90">{diff.bP90 ?? '-'}</span>
                        <span className="ml-1 text-muted-foreground">({formatDelta((diff.bP90 ?? 0) - (diff.aP90 ?? 0))})</span>
                      </div>
                    </div>
                  </div>

                  <div className="bg-card border border-border/60 rounded-xl p-4">
                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">内容重合度（估算）</div>
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
                </div>
              ) : null}

              {baselineMeta ? (
                <div className="text-[11px] text-muted-foreground">
                  基线（A）来源：{baselineMeta.strategy} · {baselineMeta.chunkSize}/{baselineMeta.chunkOverlap} · {baselineMeta.durationMs}ms
                  {baselineMeta.cacheHit ? ' · Hit Cache' : ''}
                </div>
              ) : null}

              <div className="flex items-center justify-end gap-2">
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

