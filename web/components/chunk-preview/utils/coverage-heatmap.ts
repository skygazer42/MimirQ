import type { ChunkPreviewItem } from '@/types'

function clampInt(value: number, min: number, max: number) {
  const n = Number(value)
  if (!Number.isFinite(n)) return min
  return Math.min(max, Math.max(min, Math.trunc(n)))
}

export function computeCoverageHeatmapBins(
  chunks: ChunkPreviewItem[],
  totalChars: number,
  options?: { bins?: number; strategy?: string }
): { bins: number; totalChars: number; counts: number[]; max: number } {
  const bins = clampInt(options?.bins ?? 80, 10, 400)
  const total = Math.max(0, Math.trunc(Number(totalChars) || 0))
  const empty = { bins, totalChars: total, counts: Array.from({ length: bins }, () => 0), max: 0 }
  if (!chunks?.length || total <= 0) return empty

  // Parent-child chunking: the heatmap should reflect the most granular chunks (children),
  // otherwise the parent range can dominate the entire document.
  let analysis = chunks
  if (String(options?.strategy || '').trim().toLowerCase() === 'parent_child') {
    const filtered = (chunks || []).filter((c) => c.metadata?.chunk_role !== 'parent')
    if (filtered.length > 0) analysis = filtered
  }

  const diff = Array.from({ length: bins + 1 }, () => 0)

  for (const c of analysis || []) {
    const start = Math.max(0, Math.trunc(Number(c.start_index ?? 0) || 0))
    const end = Math.max(start, Math.trunc(Number(c.end_index ?? start) || start))
    if (end <= start) continue

    let startBin = Math.floor((start / total) * bins)
    let endBin = Math.ceil((end / total) * bins)

    startBin = clampInt(startBin, 0, bins - 1)
    endBin = clampInt(endBin, startBin + 1, bins)

    diff[startBin] += 1
    diff[endBin] -= 1
  }

  const counts: number[] = []
  let running = 0
  let max = 0
  for (let i = 0; i < bins; i += 1) {
    running += diff[i] || 0
    const v = Math.max(0, Math.trunc(running))
    counts.push(v)
    if (v > max) max = v
  }

  return { bins, totalChars: total, counts, max }
}
