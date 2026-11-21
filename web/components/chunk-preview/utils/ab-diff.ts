import type { ChunkPreviewResponse } from '@/types'
import type { ChunkPreviewState } from '../types'

import { toChunkPreviewExport } from './export'

type ComparisonCandidate = ChunkPreviewState['runHistory'][number] & { cacheKey: string }

/** The cache owns the latest response per key; history options must describe that same snapshot. */
export function getComparisonCandidates(
  history: readonly ChunkPreviewState['runHistory'][number][],
  fileId: string,
): ComparisonCandidate[] {
  const candidates = new Map<string, ComparisonCandidate>()
  const ordered = [...history].sort((left, right) => right.createdAt - left.createdAt)
  for (const run of ordered) {
    const cacheKey = run.cacheKey
    if (run.fileId !== fileId || cacheKey === undefined || cacheKey.length === 0 || candidates.has(cacheKey)) continue
    candidates.set(cacheKey, { ...run, cacheKey })
  }
  return Array.from(candidates.values())
}

function buildMultiset(chunks: ReadonlyArray<{ index: number; content: string }>) {
  const map = new Map<string, { count: number; example: string; firstIndex: number }>()
  for (const chunk of chunks) {
    const trimmed = chunk.content.trim()
    if (!trimmed) continue
    const prev = map.get(trimmed)
    if (prev) {
      prev.count += 1
      continue
    }
    const example = trimmed.length <= 160 ? trimmed : Array.from(trimmed).slice(0, 160).join('')
    map.set(trimmed, { count: 1, example, firstIndex: chunk.index })
  }
  return map
}

type ChunkPreviewDiffSummary = {
  // Existing serialized field: the current run's unit, not a shared A/B unit.
  unit: string
  aUnit: 'chars' | 'tokens'
  bUnit: 'chars' | 'tokens'
  aCount: number
  bCount: number
  deltaCount: number
  aAvg: number | null
  bAvg: number | null
  aP10: number | null
  bP10: number | null
  aP90: number | null
  bP90: number | null
  aP95: number | null
  bP95: number | null
  deltaAvg: number | null
  deltaP10: number | null
  deltaP95: number | null
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

type SemanticEvidenceHighlightSegment = {
  text: string
  emphasis: boolean
}

type SemanticEvidenceHighlightItem = {
  example: string
  count: number
  index: number
  referenceExample: string | null
  similarity: number
  segments: SemanticEvidenceHighlightSegment[]
}

type SemanticEvidenceHighlights = {
  added: SemanticEvidenceHighlightItem[]
  removed: SemanticEvidenceHighlightItem[]
}

function normalizeEvidenceText(value: string): string {
  return value.trim().replace(/\s+/g, ' ')
}

function buildBigramSet(value: string): Set<string> {
  const normalized = normalizeEvidenceText(value).toLowerCase()
  if (!normalized) return new Set()
  const characters = Array.from(normalized)
  if (characters.length < 2) return new Set([normalized])

  const grams = new Set<string>()
  for (let index = 0; index < characters.length - 1; index += 1) {
    grams.add(characters[index] + characters[index + 1])
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

function buildEvidenceSegments(
  sourceExample: string,
  referenceExample: string | null,
): SemanticEvidenceHighlightSegment[] {
  const source = normalizeEvidenceText(sourceExample)
  const reference = referenceExample === null ? null : normalizeEvidenceText(referenceExample)

  if (!source) return []
  if (!reference) return [{ text: source, emphasis: true }]
  const sourceCharacters = Array.from(source)
  const referenceCharacters = Array.from(reference)

  let prefix = 0
  while (
    prefix < sourceCharacters.length &&
    prefix < referenceCharacters.length &&
    sourceCharacters[prefix].toLowerCase() === referenceCharacters[prefix].toLowerCase()
  ) {
    prefix += 1
  }

  let suffix = 0
  while (
    suffix < sourceCharacters.length - prefix &&
    suffix < referenceCharacters.length - prefix &&
    sourceCharacters[sourceCharacters.length - 1 - suffix].toLowerCase() ===
      referenceCharacters[referenceCharacters.length - 1 - suffix].toLowerCase()
  ) {
    suffix += 1
  }

  const emphasisStart = prefix
  const emphasisEnd = sourceCharacters.length - suffix
  if (emphasisEnd <= emphasisStart) {
    return [{ text: source, emphasis: true }]
  }

  const segments: SemanticEvidenceHighlightSegment[] = []
  if (emphasisStart > 0) {
    segments.push({ text: sourceCharacters.slice(0, emphasisStart).join(''), emphasis: false })
  }
  segments.push({ text: sourceCharacters.slice(emphasisStart, emphasisEnd).join(''), emphasis: true })
  if (emphasisEnd < sourceCharacters.length) {
    segments.push({ text: sourceCharacters.slice(emphasisEnd).join(''), emphasis: false })
  }
  return segments
}

function buildSemanticEvidenceItems(
  source: ChunkPreviewDiffSummary['examplesAdded'],
  opposite: ChunkPreviewDiffSummary['examplesRemoved'],
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

function getMetricDelta(before: number | null, after: number | null): number | null {
  return before === null || after === null ? null : after - before
}

export function computeChunkPreviewDiff(a: ChunkPreviewResponse, b: ChunkPreviewResponse): ChunkPreviewDiffSummary {
  const aStats = a.stats
  const bStats = b.stats

  const aUnit = aStats?.unit ?? a.params.unit ?? 'chars'
  const bUnit = bStats?.unit ?? b.params.unit ?? 'chars'
  const sameLengthUnit = aUnit === bUnit
  const aAvg = aStats?.avg ?? null
  const bAvg = bStats?.avg ?? null
  const aP10 = aStats?.p10 ?? null
  const bP10 = bStats?.p10 ?? null
  const aP90 = aStats?.p90 ?? null
  const bP90 = bStats?.p90 ?? null
  const aP95 = aStats?.p95 ?? null
  const bP95 = bStats?.p95 ?? null
  const aCoverage = aStats?.coverage_ratio ?? null
  const bCoverage = bStats?.coverage_ratio ?? null
  const aWaste = aStats?.overlap_waste_ratio ?? null
  const bWaste = bStats?.overlap_waste_ratio ?? null
  const aGapCount = aStats?.gap_count ?? null
  const bGapCount = bStats?.gap_count ?? null
  const aSet = buildMultiset(a.chunks)
  const bSet = buildMultiset(b.chunks)

  let common = 0
  let total = 0
  let added = 0
  let removed = 0
  const examplesAdded: Array<{ example: string; count: number; index: number }> = []
  const examplesRemoved: Array<{ example: string; count: number; index: number }> = []

  const keys = new Set<string>([...aSet.keys(), ...bSet.keys()])
  for (const key of keys) {
    const av = aSet.get(key)?.count ?? 0
    const bv = bSet.get(key)?.count ?? 0
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
    unit: bUnit,
    aUnit,
    bUnit,
    aCount: a.total_chunks,
    bCount: b.total_chunks,
    deltaCount: b.total_chunks - a.total_chunks,
    aAvg,
    bAvg,
    aP10,
    bP10,
    aP90,
    bP90,
    aP95,
    bP95,
    deltaAvg: sameLengthUnit ? getMetricDelta(aAvg, bAvg) : null,
    deltaP10: sameLengthUnit ? getMetricDelta(aP10, bP10) : null,
    deltaP95: sameLengthUnit ? getMetricDelta(aP95, bP95) : null,
    aCoverage,
    bCoverage,
    deltaCoverage: getMetricDelta(aCoverage, bCoverage),
    aWaste,
    bWaste,
    deltaWaste: getMetricDelta(aWaste, bWaste),
    aGapCount,
    bGapCount,
    deltaGapCount: getMetricDelta(aGapCount, bGapCount),
    added,
    removed,
    overlap,
    examplesAdded: examplesAdded.slice(0, 3),
    examplesRemoved: examplesRemoved.slice(0, 3),
  }
}

export function buildSemanticEvidenceHighlights(
  summary: Pick<ChunkPreviewDiffSummary, 'examplesAdded' | 'examplesRemoved'>,
): SemanticEvidenceHighlights {
  return {
    added: buildSemanticEvidenceItems(summary.examplesAdded, summary.examplesRemoved),
    removed: buildSemanticEvidenceItems(summary.examplesRemoved, summary.examplesAdded),
  }
}

export function chunkPreviewDiffToExport(
  baseline: ChunkPreviewResponse,
  current: ChunkPreviewResponse,
  options?: { baseline_cache_key?: string; current_cache_key?: string },
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
