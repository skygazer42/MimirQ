import type { ChunkOverride } from '@/components/chunk-preview/types'
import type { ChunkPreviewItem, JsonObject } from '@/types'

export type SemanticQualityMetadata = {
  information_density?: number
  semantic_completeness?: number
  self_containedness?: number
  dedup_risk_prev_jaccard?: number | null
  needs_review?: boolean
  reasons?: string[]
}

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function getBooleanValue(record: JsonObject, key: string): boolean | undefined {
  const value = record[key]
  return typeof value === 'boolean' ? value : undefined
}

function getNumberValue(record: JsonObject, key: string): number | undefined {
  const value = record[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function getNullableNumberValue(record: JsonObject, key: string): number | null | undefined {
  const value = record[key]
  if (value === null) return null
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function getStringArrayValue(record: JsonObject, key: string): string[] | undefined {
  const value = record[key]
  if (!Array.isArray(value)) return undefined

  const strings = value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter(Boolean)

  return strings.length > 0 ? strings : undefined
}

function getMetadataObject(record: JsonObject, key: string): JsonObject | null {
  const value = record[key]
  return isJsonObject(value) ? value : null
}

export function getChunkMetadata(chunk: Pick<ChunkPreviewItem, 'metadata'>): JsonObject {
  return isJsonObject(chunk.metadata) ? chunk.metadata : {}
}

export function getStringValue(record: JsonObject, key: string): string | undefined {
  const value = record[key]
  return typeof value === 'string' ? value.trim() || undefined : undefined
}

export function getChunkRole(chunk: Pick<ChunkPreviewItem, 'metadata'>): string | undefined {
  return getStringValue(getChunkMetadata(chunk), 'chunk_role')
}

export function getSemanticQualityMetadata(chunk: Pick<ChunkPreviewItem, 'metadata'>): SemanticQualityMetadata | null {
  const semanticQuality = getMetadataObject(getChunkMetadata(chunk), 'semantic_quality')
  if (!semanticQuality) return null

  return {
    information_density: getNumberValue(semanticQuality, 'information_density'),
    semantic_completeness: getNumberValue(semanticQuality, 'semantic_completeness'),
    self_containedness: getNumberValue(semanticQuality, 'self_containedness'),
    dedup_risk_prev_jaccard: getNullableNumberValue(semanticQuality, 'dedup_risk_prev_jaccard'),
    needs_review: getBooleanValue(semanticQuality, 'needs_review'),
    reasons: getStringArrayValue(semanticQuality, 'reasons'),
  }
}

export function chunkNeedsReview(chunk: Pick<ChunkPreviewItem, 'metadata'>): boolean {
  const metadata = getChunkMetadata(chunk)
  if (chunkIsReviewed(chunk)) return false
  if (getBooleanValue(metadata, 'needs_review') === true) return true
  return getSemanticQualityMetadata(chunk)?.needs_review === true
}

export function chunkIsReviewed(chunk: Pick<ChunkPreviewItem, 'metadata'>): boolean {
  const metadata = getChunkMetadata(chunk)
  const status = getStringValue(metadata, 'review_status')?.toLowerCase()
  if (status === 'approved' || status === 'reviewed') return true
  return getBooleanValue(metadata, 'reviewed') === true
}

export function isChunkOverrideEdited(override: ChunkOverride | undefined): boolean {
  return override?.content !== undefined || override?.metadata !== undefined
}

export function isChunkOverrideDisabled(override: ChunkOverride | undefined): boolean {
  return override?.disabled === true
}
