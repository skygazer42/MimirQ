import type { ChunkOverride } from '@/components/chunk-preview/types'
import type { ChunkPreviewItem, JsonObject } from '@/types'

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Read a nonempty metadata label or identity; document content is not normalized here. */
export function readMetadataString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const text = value.trim()
  return text.length === 0 ? undefined : text
}

export function getChunkRole(chunk: Pick<ChunkPreviewItem, 'metadata'>): string | undefined {
  return readMetadataString(chunk.metadata?.chunk_role)
}

export type ChunkIdentity = string | number

function isChunkIdentity(value: unknown): value is ChunkIdentity {
  return (typeof value === 'string' && value.length > 0) || (typeof value === 'number' && Number.isFinite(value))
}

export function getChunkParentIdentity(chunk: Pick<ChunkPreviewItem, 'metadata'>): ChunkIdentity | undefined {
  const identity = chunk.metadata?.parent_id ?? chunk.metadata?.parent_node_id
  return isChunkIdentity(identity) ? identity : undefined
}

/** Read aliases from a row already identified as a parent; IDs are opaque and zero is valid. */
export function getParentIdentities(parent: Pick<ChunkPreviewItem, 'metadata'>): ReadonlySet<ChunkIdentity> {
  return new Set([parent.metadata?.parent_id, parent.metadata?.node_id, parent.metadata?.id].filter(isChunkIdentity))
}

/** An ambiguous relation does not identify a parent entity. */
export function findChunkParent(chunk: ChunkPreviewItem, candidates: readonly ChunkPreviewItem[]) {
  if (getChunkRole(chunk) !== 'child') return undefined
  const identity = getChunkParentIdentity(chunk)
  if (identity === undefined) return undefined
  const matches = candidates.filter(
    (parent) =>
      getChunkRole(parent) === 'parent' &&
      getParentIdentities(parent).has(identity) &&
      parent.start_index <= chunk.start_index &&
      parent.end_index >= chunk.end_index &&
      parent.end_index > parent.start_index,
  )
  return matches.length === 1 ? matches[0] : undefined
}

/** Read a containing parent range from chunks already projected into the displayed text. */
export function getChunkParentRange(chunk: ChunkPreviewItem, chunks: readonly ChunkPreviewItem[]) {
  if (getChunkRole(chunk) !== 'child') return null
  const metadata = chunk.metadata
  const start = metadata?.parent_start_char
  const end = metadata?.parent_end_char
  if (
    typeof start === 'number' &&
    typeof end === 'number' &&
    end > start &&
    start <= chunk.start_index &&
    end >= chunk.end_index
  ) {
    return { start, end }
  }

  const parent = findChunkParent(chunk, chunks)
  return parent === undefined ? null : { start: parent.start_index, end: parent.end_index }
}

function getSemanticQualityMetadata(chunk: Pick<ChunkPreviewItem, 'metadata'>): JsonObject | undefined {
  const value = chunk.metadata?.semantic_quality
  return isJsonObject(value) ? value : undefined
}

export function getChunkReviewReasons(chunk: Pick<ChunkPreviewItem, 'metadata'>): readonly string[] | undefined {
  const reasons = getSemanticQualityMetadata(chunk)?.reasons
  return Array.isArray(reasons) ? reasons.filter((reason): reason is string => typeof reason === 'string') : undefined
}

export function chunkNeedsReview(chunk: Pick<ChunkPreviewItem, 'metadata'>): boolean {
  if (chunkIsReviewed(chunk)) return false
  return chunk.metadata?.needs_review === true || getSemanticQualityMetadata(chunk)?.needs_review === true
}

export function chunkIsReviewed(chunk: Pick<ChunkPreviewItem, 'metadata'>): boolean {
  const status = readMetadataString(chunk.metadata?.review_status)?.toLowerCase()
  return status === 'approved' || status === 'reviewed' || chunk.metadata?.reviewed === true
}

export function isChunkOverrideEdited(override: ChunkOverride | undefined): boolean {
  return override?.content !== undefined || override?.metadata !== undefined
}

export function isChunkOverrideDisabled(override: ChunkOverride | undefined): boolean {
  return override?.disabled === true
}
