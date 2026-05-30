export type ChunkLengthHistogramBin = {
  from: number
  to: number
  count: number
}

export type ChunkLengthStats = {
  count: number
  total: number
  min: number
  max: number
  avg: number
  median: number
  p10: number
  p90: number
  p95: number
  shortCount: number
  duplicateCount: number
  histogram: ChunkLengthHistogramBin[]
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

// Fast, non-cryptographic hash for duplicate estimation.
function fnv1a32(text: string) {
  let hash = 0x811c9dc5
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.codePointAt(i) ?? 0
    // hash *= 16777619 (keep 32-bit)
    hash = (hash + (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24)) >>> 0
  }
  return hash >>> 0
}

function normalizeLength(value: unknown) {
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.trunc(n))
}

export function computeChunkLengthStats(
  chunks: Array<{ content?: string | null; length?: number | null }>,
  options?: { shortThreshold?: number; histogramBins?: number; hashMaxChars?: number }
): ChunkLengthStats | null {
  const shortThreshold = normalizeLength(options?.shortThreshold ?? 120)
  const histogramBins = clampInt(options?.histogramBins ?? 8, 3, 12)
  const hashMaxChars = clampInt(options?.hashMaxChars ?? 2048, 64, 10_000)

  const lengths: number[] = []
  const seen = new Set<string>()
  let duplicateCount = 0
  let shortCount = 0

  for (const c of chunks) {
    const content = String(c.content ?? '')
    const length = normalizeLength(typeof c.length === 'number' ? c.length : content.length)
    lengths.push(length)

    if (length > 0 && length < shortThreshold) shortCount += 1

    const trimmed = content.trim()
    if (!trimmed) continue

    const sample = trimmed.length > hashMaxChars ? trimmed.slice(0, hashMaxChars) : trimmed
    const key = `${length}:${fnv1a32(sample).toString(16)}`
    if (seen.has(key)) duplicateCount += 1
    else seen.add(key)
  }

  if (lengths.length === 0) return null

  const total = lengths.reduce((sum, n) => sum + n, 0)
  const min = Math.min(...lengths)
  const max = Math.max(...lengths)
  const avg = Math.round(total / lengths.length)
  const sorted = [...lengths].sort((a, b) => a - b)
  const median = percentile(sorted, 50)
  const p10 = percentile(sorted, 10)
  const p90 = percentile(sorted, 90)
  const p95 = percentile(sorted, 95)

  // Histogram bins based on [0, max]
  const stepBase = Math.max(50, Math.ceil(max / histogramBins / 50) * 50)
  const binCount = Math.max(1, Math.ceil((max + 1) / stepBase))
  const bins: ChunkLengthHistogramBin[] = Array.from({ length: binCount }, (_, i) => ({
    from: i * stepBase,
    to: (i + 1) * stepBase,
    count: 0,
  }))

  for (const len of lengths) {
    const idx = clampInt(Math.floor(len / stepBase), 0, bins.length - 1)
    bins[idx].count += 1
  }

  return {
    count: lengths.length,
    total,
    min,
    max,
    avg,
    median,
    p10,
    p90,
    p95,
    shortCount,
    duplicateCount,
    histogram: bins,
  }
}
