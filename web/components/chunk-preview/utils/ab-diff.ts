import type { ChunkPreviewResponse } from '@/types'

import { fnv1a32 } from './review-signals'
import { toChunkPreviewExport } from './export'

function safeNum(value: unknown): number | null {
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

export type SemanticEvidenceHighlightSegment = {
  text: string
  emphasis: boolean
}

export type SemanticEvidenceHighlightItem = {
  example: string
  count: number
  index: number
  referenceExample: string | null
  similarity: number
  segments: SemanticEvidenceHighlightSegment[]
}

export type SemanticEvidenceHighlights = {
  added: SemanticEvidenceHighlightItem[]
  removed: SemanticEvidenceHighlightItem[]
}

function normalizeEvidenceText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value).trim().replace(/\s+/g, ' ')
  }
  return ''
}

function buildBigramSet(value: string): Set<string> {
  const normalized = normalizeEvidenceText(value).toLowerCase()
  if (!normalized) return new Set()
  if (normalized.length < 2) return new Set([normalized])

  const grams = new Set<string>()
  for (let i = 0; i < normalized.length - 1; i += 1) {
    grams.add(normalized.slice(i, i + 2))
  }
  return grams
}

function scoreEvidenceSimilarity(a: string, b: string): number {
  const aGrams = buildBigramSet(a)
  const bGrams = buildBigramSet(b)
  if (!aGrams.size || !bGrams.size) return 0

  let overlap = 0
  for (const gram of aGrams) {
    if (bGrams.has(gram)) overlap += 1
  }
  return (2 * overlap) / (aGrams.size + bGrams.size)
}

function buildEvidenceSegments(sourceExample: string, referenceExample: string | null): SemanticEvidenceHighlightSegment[] {
  const source = normalizeEvidenceText(sourceExample)
  const reference = normalizeEvidenceText(referenceExample)

  if (!source) return []
  if (!reference) return [{ text: source, emphasis: true }]

  let prefix = 0
  while (
    prefix < source.length &&
    prefix < reference.length &&
    source[prefix]?.toLowerCase() === reference[prefix]?.toLowerCase()
  ) {
    prefix += 1
  }

  let suffix = 0
  while (
    suffix < source.length - prefix &&
    suffix < reference.length - prefix &&
    source[source.length - 1 - suffix]?.toLowerCase() === reference[reference.length - 1 - suffix]?.toLowerCase()
  ) {
    suffix += 1
  }

  const emphasisStart = prefix
  const emphasisEnd = Math.max(prefix, source.length - suffix)
  if (emphasisEnd <= emphasisStart) {
    return [{ text: source, emphasis: true }]
  }

  const segments: SemanticEvidenceHighlightSegment[] = []
  if (emphasisStart > 0) {
    segments.push({ text: source.slice(0, emphasisStart), emphasis: false })
  }
  segments.push({ text: source.slice(emphasisStart, emphasisEnd), emphasis: true })
  if (emphasisEnd < source.length) {
    segments.push({ text: source.slice(emphasisEnd), emphasis: false })
  }
  return segments.filter((segment) => segment.text.length > 0)
}

function buildSemanticEvidenceItems(
  source: ChunkPreviewDiffSummary['examplesAdded'],
  opposite: ChunkPreviewDiffSummary['examplesRemoved']
): SemanticEvidenceHighlightItem[] {
  return source.map((item) => {
    let bestReference: string | null = null
    let bestSimilarity = 0

    for (const candidate of opposite) {
      const similarity = scoreEvidenceSimilarity(item.example, candidate.example)
      if (similarity > bestSimilarity) {
        bestSimilarity = similarity
        bestReference = candidate.example
      }
    }

    const referenceExample = bestSimilarity >= 0.12 ? bestReference : null

    return {
      example: item.example,
      count: item.count,
      index: item.index,
      referenceExample,
      similarity: bestSimilarity,
      segments: buildEvidenceSegments(item.example, referenceExample),
    }
  })
}

export function computeChunkPreviewDiff(a: ChunkPreviewResponse, b: ChunkPreviewResponse): ChunkPreviewDiffSummary {
  const aStats = a.stats
  const bStats = b.stats

  const unit = (b.params?.unit || a.params?.unit || 'chars') as string

  const aAvg = safeNum(aStats?.avg)
  const bAvg = safeNum(bStats?.avg)
  const aP10 = safeNum(aStats?.p10)
  const bP10 = safeNum(bStats?.p10)
  const aP90 = safeNum(aStats?.p90)
  const bP90 = safeNum(bStats?.p90)

  const aCoverage = safeNum(aStats?.coverage_ratio)
  const bCoverage = safeNum(bStats?.coverage_ratio)
  const aWaste = safeNum(aStats?.overlap_waste_ratio)
  const bWaste = safeNum(bStats?.overlap_waste_ratio)
  const aGapCount = safeNum(aStats?.gap_count)
  const bGapCount = safeNum(bStats?.gap_count)

  const computePctl = (preview: ChunkPreviewResponse, pct: number) => {
    const lengths = (preview.chunks || []).map((c) => {
      const len = Number(c.length || 0) || 0
      const tokensFallback = Math.max(0, Math.trunc(len / 4))
      if (unit === 'tokens') {
        return typeof c.tokens_est === 'number' ? Math.max(0, Math.trunc(c.tokens_est)) : tokensFallback
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

export function buildSemanticEvidenceHighlights(
  summary: Pick<ChunkPreviewDiffSummary, 'examplesAdded' | 'examplesRemoved'>
): SemanticEvidenceHighlights {
  return {
    added: buildSemanticEvidenceItems(summary.examplesAdded || [], summary.examplesRemoved || []),
    removed: buildSemanticEvidenceItems(summary.examplesRemoved || [], summary.examplesAdded || []),
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
