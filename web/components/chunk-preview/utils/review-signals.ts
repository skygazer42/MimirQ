import type { ChunkPreviewItem, JsonObject } from '@/types'

function getChunkMetadata(chunk: ChunkPreviewItem): JsonObject {
  return chunk.metadata ?? {}
}

function getStringMeta(meta: JsonObject, key: string): string | undefined {
  const value = meta[key]
  return typeof value === 'string' ? value.trim() || undefined : undefined
}

export function roughEstimateTokens(text: string) {
  const raw = (text || '').trim()
  if (!raw) return 0
  // Fast + coarse: ~4 chars/token (works OK for Latin; underestimates for CJK).
  return Math.max(1, Math.ceil(raw.length / 4))
}

export function fnv1a32(input: string) {
  // Non-crypto, fast hash for UI duplicate detection.
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i += 1) {
    h ^= input.codePointAt(i) ?? 0
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

export function computeDuplicateIndices(chunks: ChunkPreviewItem[]) {
  const dups = new Set<number>()
  const seen = new Map<string, number>()
  for (const c of chunks || []) {
    const trimmed = String(c?.content ?? '').trim()
    if (!trimmed) continue
    const key = fnv1a32(trimmed)
    const prev = seen.get(key)
    if (prev == null) {
      seen.set(key, Number(c.index))
    } else {
      dups.add(prev)
      dups.add(Number(c.index))
    }
  }
  return dups
}

export function computeShortIndices(chunks: ChunkPreviewItem[], unit: 'chars' | 'tokens') {
  const threshold = unit === 'tokens' ? 40 : 120
  const out = new Set<number>()
  for (const c of chunks || []) {
    const tok = typeof c.tokens_est === 'number' ? c.tokens_est : roughEstimateTokens(String(c.content || ''))
    const len = unit === 'tokens' ? Number(tok || 0) : Number(c.length || 0)
    if (len > 0 && len < threshold) out.add(Number(c.index))
  }
  return out
}

export function computeRoleIndices(chunks: ChunkPreviewItem[]) {
  const parents = new Set<number>()
  const children = new Set<number>()
  for (const c of chunks || []) {
    const meta = getChunkMetadata(c)
    const role = getStringMeta(meta, 'chunk_role')
    const idx = Number(c.index)
    if (!Number.isFinite(idx)) continue
    if (role === 'parent') parents.add(idx)
    if (role === 'child') children.add(idx)
  }
  return { parents, children }
}

export function computeHierarchyReviewSignals(chunks: ChunkPreviewItem[]) {
  const missingNodeKeyIndices = new Set<number>()
  const missingFamilyKeyIndices = new Set<number>()
  const missingPrevSiblingIndices = new Set<number>()
  const missingNextSiblingIndices = new Set<number>()
  const basisValues = new Set<string>()

  const raw = chunks || []
  if (raw.length === 0) {
    return {
      active: false,
      missingNodeKeyIndices,
      missingFamilyKeyIndices,
      missingPrevSiblingIndices,
      missingNextSiblingIndices,
      basisValues,
    }
  }

  const sorted = [...raw].sort((a, b) => {
    const sa = Number(a.start_index) || 0
    const sb = Number(b.start_index) || 0
    if (sa !== sb) return sa - sb
    const ea = Number(a.end_index) || sa
    const eb = Number(b.end_index) || sb
    if (ea !== eb) return ea - eb
    return (Number(a.index) || 0) - (Number(b.index) || 0)
  })

  let anyNodeKey = false
  let anyFamilyKey = false
  let anySiblingLinks = false

  const nodeKeysByIndex = new Map<number, string>()
  const familyKeysByIndex = new Map<number, string>()
  const prevKeysByIndex = new Map<number, string>()
  const nextKeysByIndex = new Map<number, string>()

  for (const c of sorted) {
    const idx = Number(c.index)
    if (!Number.isFinite(idx)) continue
    const meta = getChunkMetadata(c)

    const basis = getStringMeta(meta, 'hierarchy_basis') ?? ''
    if (basis) basisValues.add(basis)

    const nodeKey = getStringMeta(meta, 'hierarchy_node_key') ?? ''
    if (nodeKey) {
      anyNodeKey = true
      nodeKeysByIndex.set(idx, nodeKey)
    }

    const familyKey = getStringMeta(meta, 'hierarchy_family_key') ?? ''
    if (familyKey) {
      anyFamilyKey = true
      familyKeysByIndex.set(idx, familyKey)
    }

    const prevKeyRaw = meta.hierarchy_prev_sibling_key ?? meta.prev_chunk_key
    const nextKeyRaw = meta.hierarchy_next_sibling_key ?? meta.next_chunk_key
    const prevKey = typeof prevKeyRaw === 'string' ? prevKeyRaw.trim() : ''
    const nextKey = typeof nextKeyRaw === 'string' ? nextKeyRaw.trim() : ''
    if (prevKey) {
      anySiblingLinks = true
      prevKeysByIndex.set(idx, prevKey)
    }
    if (nextKey) {
      anySiblingLinks = true
      nextKeysByIndex.set(idx, nextKey)
    }
  }

  // Only flag missing hierarchy fields if the document provides *any* hierarchy metadata.
  // This keeps the UI signal meaningful for legacy datasets / chunkers.
  if (anyNodeKey) {
    for (const c of sorted) {
      const idx = Number(c.index)
      if (!Number.isFinite(idx)) continue
      if (!nodeKeysByIndex.get(idx)) missingNodeKeyIndices.add(idx)
    }
  }

  if (anyFamilyKey) {
    for (const c of sorted) {
      const idx = Number(c.index)
      if (!Number.isFinite(idx)) continue
      if (!familyKeysByIndex.get(idx)) missingFamilyKeyIndices.add(idx)
    }
  }

  if (anySiblingLinks && sorted.length > 1) {
    for (let i = 0; i < sorted.length; i += 1) {
      const idx = Number(sorted[i]?.index)
      if (!Number.isFinite(idx)) continue
      const expectPrev = i > 0
      const expectNext = i < sorted.length - 1
      if (expectPrev && !prevKeysByIndex.get(idx)) missingPrevSiblingIndices.add(idx)
      if (expectNext && !nextKeysByIndex.get(idx)) missingNextSiblingIndices.add(idx)
    }
  }

  return {
    active: anyNodeKey || anyFamilyKey || anySiblingLinks,
    missingNodeKeyIndices,
    missingFamilyKeyIndices,
    missingPrevSiblingIndices,
    missingNextSiblingIndices,
    basisValues,
  }
}

export function computeCoverageSignals(
  chunks: ChunkPreviewItem[],
  options?: { strategy?: string }
): {
  basis: 'all' | 'child'
  gapIndices: Set<number>
  overlapIndices: Set<number>
  gapBeforeByIndex: Map<number, number>
  overlapPrevByIndex: Map<number, number>
} {
  const gapIndices = new Set<number>()
  const overlapIndices = new Set<number>()
  const gapBeforeByIndex = new Map<number, number>()
  const overlapPrevByIndex = new Map<number, number>()

  const raw = chunks || []
  if (raw.length === 0) {
    return { basis: 'all', gapIndices, overlapIndices, gapBeforeByIndex, overlapPrevByIndex }
  }

  let basis: 'all' | 'child' = 'all'
  let analysis = raw
  if (options?.strategy === 'parent_child') {
    const filtered = raw.filter((c) => getStringMeta(getChunkMetadata(c), 'chunk_role') !== 'parent')
    if (filtered.length > 0) {
      analysis = filtered
      basis = 'child'
    }
  }

  const strategy = options?.strategy || ''
  const strictNoOverlap = strategy === 'separator'

  const sorted = [...analysis].sort((a, b) => {
    const sa = Number(a.start_index) || 0
    const sb = Number(b.start_index) || 0
    if (sa !== sb) return sa - sb
    const ea = Number(a.end_index) || sa
    const eb = Number(b.end_index) || sb
    if (ea !== eb) return ea - eb
    return (Number(a.index) || 0) - (Number(b.index) || 0)
  })

  let coveredEnd = 0
  for (const c of sorted) {
    const idx = Number(c.index)
    if (!Number.isFinite(idx)) continue
    const start = Math.max(0, Number(c.start_index) || 0)
    const end = Math.max(start, Number(c.end_index) || start)

    if (start > coveredEnd) {
      const gap = start - coveredEnd
      if (gap > 0) {
        gapIndices.add(idx)
        gapBeforeByIndex.set(idx, gap)
      }
    } else if (start < coveredEnd) {
      const overlap = coveredEnd - start
      const chunkLen = Math.max(1, end - start)
      if (overlap > 0) overlapPrevByIndex.set(idx, overlap)

      // Flag only "meaningfully high" overlaps to avoid noisy overlap-by-design.
      // For separator (overlap=0), ANY overlap is unexpected -> flag.
      const isHigh = overlap > 0 && (strictNoOverlap || overlap / chunkLen >= 0.6 || overlap >= 800)
      if (isHigh) overlapIndices.add(idx)
    }

    if (end > coveredEnd) coveredEnd = end
  }

  return { basis, gapIndices, overlapIndices, gapBeforeByIndex, overlapPrevByIndex }
}
