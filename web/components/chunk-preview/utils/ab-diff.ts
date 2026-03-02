import type { ChunkPreviewResponse } from '@/types'

import { fnv1a32 } from './review-signals'
import { toChunkPreviewExport } from './export'

function safeNum(value: any): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function clampInt(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.trunc(value)))
}

function percentile(sorted: number[], p: number) {
  if (sorted.length === 0) return 0
  const pp = Math.min(100, Math.max(0, p))
  const idx = Math.floor((pp / 100) * (sorted.length - 1))
  return sorted[clampInt(idx, 0, sorted.length - 1)] ?? 0
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

export type ChunkPreviewDiffSummary = {
  unit: string
  aCount: number
  bCount: number
  deltaCount: number
  aAvg: number | null
  bAvg: number | null
  aP10: number | null
  bP10: number | null
  aP90: number | null
  bP90: number | null
  aP95: number
  bP95: number
  aCoverage: number | null
  bCoverage: number | null
  deltaCoverage: number | null
  aWaste: number | null
  bWaste: number | null
  deltaWaste: number | null
  aGapCount: number | null
  bGapCount: number | null
  deltaGapCount: number | null
  added: number
  removed: number
  overlap: number
  examplesAdded: Array<{ example: string; count: number; index: number }>
  examplesRemoved: Array<{ example: string; count: number; index: number }>
}

export function computeChunkPreviewDiff(a: ChunkPreviewResponse, b: ChunkPreviewResponse): ChunkPreviewDiffSummary {
  const aStats = a.stats || {}
  const bStats = b.stats || {}

  const unit = (b.params?.unit || a.params?.unit || 'chars') as string

  const aAvg = safeNum((aStats as any).avg)
  const bAvg = safeNum((bStats as any).avg)
  const aP10 = safeNum((aStats as any).p10)
  const bP10 = safeNum((bStats as any).p10)
  const aP90 = safeNum((aStats as any).p90)
  const bP90 = safeNum((bStats as any).p90)

  const aCoverage = safeNum((aStats as any).coverage_ratio)
  const bCoverage = safeNum((bStats as any).coverage_ratio)
  const aWaste = safeNum((aStats as any).overlap_waste_ratio)
  const bWaste = safeNum((bStats as any).overlap_waste_ratio)
  const aGapCount = safeNum((aStats as any).gap_count)
  const bGapCount = safeNum((bStats as any).gap_count)

  const computePctl = (preview: ChunkPreviewResponse, pct: number) => {
    const lengths = (preview.chunks || []).map((c) => {
      const len = Number((c as any)?.length || 0) || 0
      const tokensFallback = Math.max(0, Math.trunc(len / 4))
      if (unit === 'tokens') {
        return typeof (c as any)?.tokens_est === 'number' ? Math.max(0, Math.trunc((c as any).tokens_est)) : tokensFallback
      }
      return Math.max(0, Math.trunc(len))
    })
    const sorted = [...lengths].sort((x, y) => x - y)
    return percentile(sorted, pct)
  }

  const aP95 = computePctl(a, 95)
  const bP95 = computePctl(b, 95)

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
    unit,
    aCount: Number(a.total_chunks || 0),
    bCount: Number(b.total_chunks || 0),
    deltaCount: Number(b.total_chunks || 0) - Number(a.total_chunks || 0),
    aAvg,
    bAvg,
    aP10,
    bP10,
    aP90,
    bP90,
    aP95,
    bP95,
    aCoverage,
    bCoverage,
    deltaCoverage: aCoverage == null || bCoverage == null ? null : bCoverage - aCoverage,
    aWaste,
    bWaste,
    deltaWaste: aWaste == null || bWaste == null ? null : bWaste - aWaste,
    aGapCount,
    bGapCount,
    deltaGapCount: aGapCount == null || bGapCount == null ? null : bGapCount - aGapCount,
    added,
    removed,
    overlap,
    examplesAdded: examplesAdded.slice(0, 3),
    examplesRemoved: examplesRemoved.slice(0, 3),
  }
}

export function chunkPreviewDiffToExport(
  baseline: ChunkPreviewResponse,
  current: ChunkPreviewResponse,
  options?: { baseline_cache_key?: string; current_cache_key?: string }
) {
  return {
    schema: 'mimirq.chunk_preview_diff.v1',
    generated_at: new Date().toISOString(),
    meta: {
      baseline_cache_key: options?.baseline_cache_key ?? null,
      current_cache_key: options?.current_cache_key ?? null,
    },
    baseline: toChunkPreviewExport(baseline),
    current: toChunkPreviewExport(current),
    diff: computeChunkPreviewDiff(baseline, current),
  }
}

