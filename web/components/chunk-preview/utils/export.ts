import type {
  ChunkPreviewItem,
  ChunkPreviewQualityGate,
  ChunkPreviewResponse,
  ChunkPreviewReviewSignals,
  ChunkPreviewStats,
  JsonObject,
} from '@/types'
import { toPrimitiveString, toSingleLinePrimitiveString } from '@/lib/primitive-text'
import { sanitizeFilename } from '@/lib/sanitize'
import type { ChunkOverrides } from '../types'

export { sanitizeFilename } from '@/lib/sanitize'

interface ChunkPreviewReviewReportChunk {
  index: number
  page_number: number | null
  start_index: number
  end_index: number
  length: number
  tokens_est: number | null
  role: string | null
  parent_id: string | null
  disabled: boolean
  edited: boolean
  flags: {
    short: boolean
    duplicate: boolean
    gap: boolean
    overlap: boolean
  }
  gap_before: number
  overlap_prev: number
  content_hash: string | null
  content_preview: string
}

interface ChunkPreviewReviewReport {
  schema: 'mimirq.chunk_review.v1'
  generated_at: string
  file: {
    filename: string
    file_type: string
    file_size: number
    file_sha256: string | null
    total_characters: number
  }
  config: {
    parser_backend: string
    chunk_strategy: string
    chunk_size: number | undefined
    chunk_overlap: number | undefined
    unit: 'chars' | 'tokens'
    strategy_params: JsonObject
  }
  stats: ChunkPreviewStats | null
  review_signals: ChunkPreviewReviewSignals
  quality_gate: ChunkPreviewQualityGate | null
  recommendations: string[]
  warnings: string[]
  summary: {
    total_chunks: number
    total_chunks_in_report: number
    include_disabled: boolean
    disabled_count: number
    edited_count: number
    issue_counts: {
      short: number
      duplicate: number
      gap: number
      overlap: number
    }
    coverage_basis: 'all' | 'child'
  }
  chunks: ChunkPreviewReviewReportChunk[]
}

function getChunkMetadata(chunk: ChunkPreviewItem): JsonObject {
  return chunk.metadata ?? {}
}

function getChunkRole(metadata: JsonObject): string | null {
  const role = metadata.chunk_role
  return typeof role === 'string' ? role : null
}

function getChunkParentId(metadata: JsonObject): string | null {
  const parentId = metadata.parent_id
  if (typeof parentId === 'string') return parentId
  const parentNodeId = metadata.parent_node_id
  return typeof parentNodeId === 'string' ? parentNodeId : null
}

export function downloadTextFile(filename: string, content: string, mime = 'text/plain;charset=utf-8') {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function toChunkPreviewExport(preview: ChunkPreviewResponse) {
  // Keep exports stable + lightweight: omit original_text (can be huge).
  const { original_text: _omit, ...rest } = preview
  return {
    ...rest,
    original_text_included: Boolean(preview.original_text),
  }
}

export function applyChunkOverridesToPreview(
  preview: ChunkPreviewResponse,
  overrides: ChunkOverrides | undefined,
  options?: { include_disabled?: boolean }
) {
  const keys = overrides ? Object.keys(overrides) : []
  const includeDisabled = Boolean(options?.include_disabled)
  if (!keys.length) return preview

  const chunks = (preview.chunks || []).reduce<ChunkPreviewItem[]>((acc, chunk, fallbackIndex) => {
    const idx = typeof chunk.index === 'number' ? chunk.index : fallbackIndex
    const override = overrides?.[idx]

    const isDisabled = Boolean(override?.disabled)
    if (isDisabled && !includeDisabled) return acc
    if (!override) {
      acc.push(chunk)
      return acc
    }

    const content = String(override.content ?? chunk.content ?? '')
    const metadata = override.metadata ?? chunk.metadata ?? {}
    const exportMetadata = isDisabled && includeDisabled ? { ...metadata, __mimirq_skip: true } : metadata
    acc.push({
      ...chunk,
      content,
      metadata: exportMetadata,
      length: content.length,
      tokens_est: override.content !== undefined ? undefined : chunk.tokens_est,
    })
    return acc
  }, [])

  return {
    ...preview,
    chunks,
    total_chunks: chunks.length,
  }
}

function emptyReviewSignals(): ChunkPreviewReviewSignals {
  return {
    basis: 'all',
    short_indices: [],
    duplicate_indices: [],
    gap_indices: [],
    overlap_indices: [],
    gap_before_by_index: {},
    overlap_prev_by_index: {},
  }
}

function toIndexSet(indices: number[] | undefined): Set<number> {
  const out = new Set<number>()
  for (const value of indices || []) {
    const n = Number(value)
    if (Number.isFinite(n)) out.add(Math.trunc(n))
  }
  return out
}

function toSignalValueMap(values: Record<string, number> | Record<number, number> | undefined): Map<number, number> {
  const out = new Map<number, number>()
  for (const [key, value] of Object.entries(values || {})) {
    const index = Number(key)
    const signalValue = Number(value)
    if (Number.isFinite(index) && Number.isFinite(signalValue)) out.set(Math.trunc(index), Math.trunc(signalValue))
  }
  return out
}

function csvEscape(value: unknown) {
  let raw = ''
  if (value == null) {
    raw = ''
  } else if (
    typeof value === 'string'
    || typeof value === 'number'
    || typeof value === 'boolean'
    || typeof value === 'bigint'
  ) {
    raw = toPrimitiveString(value)
  } else {
    raw = JSON.stringify(value)
  }
  const needsQuote = /[",\n\r]/.test(raw)
  const escaped = raw.replaceAll("\"", '""')
  return needsQuote ? `"${escaped}"` : escaped
}

export function chunkPreviewToCsv(preview: ChunkPreviewResponse) {
  const headers = ['index', 'page_number', 'start_index', 'end_index', 'length', 'content']
  const rows = preview.chunks.map((c) => [
    c.index,
    c.page_number ?? '',
    c.start_index,
    c.end_index,
    c.length,
    c.content ?? '',
  ])
  return [headers, ...rows].map((row) => row.map(csvEscape).join(',')).join('\n')
}

export function chunkPreviewToMarkdown(preview: ChunkPreviewResponse) {
  const lines: string[] = []
  const unit = preview.params?.unit || 'chars'
  const safeName = sanitizeFilename(preview.filename || 'document')

    lines.push(`# ${safeName}`, '', `- parser_backend: ${preview.parser_backend}`, `- chunk_strategy: ${preview.chunk_strategy}`, `- chunk_size: ${preview.params?.chunk_size} (${unit})`, `- chunk_overlap: ${preview.params?.chunk_overlap} (${unit})`, `- total_chunks: ${preview.total_chunks}`, '')

  // Use 4 backticks to reduce accidental fence collisions with chunk contents.
  const fence = '````'

  for (const c of preview.chunks || []) {
    const pageLabel = typeof c.page_number === 'number' ? ` (P.${c.page_number})` : ''
    const tok = typeof c.tokens_est === 'number' ? c.tokens_est : undefined
    const lenLine = tok == null ? `${c.length} chars` : `${c.length} chars · ${tok} tok`

        lines.push(`## Chunk ${Number(c.index) + 1}${pageLabel}`, '', `- range: ${c.start_index}-${c.end_index}`, `- length: ${lenLine}`, '', `${fence}text`, String(c.content ?? ''), fence, '')
  }

  return lines.join('\n')
}

export function chunkPreviewToJsonl(preview: ChunkPreviewResponse) {
  const rows = (preview.chunks || []).map((c) =>
    JSON.stringify({
      index: c.index,
      page_number: c.page_number ?? null,
      start_index: c.start_index,
      end_index: c.end_index,
      length: c.length,
      tokens_est: typeof c.tokens_est === 'number' ? c.tokens_est : null,
      metadata: c.metadata ?? {},
      content: c.content ?? '',
    })
  )
  return rows.join('\n')
}

export function chunkPreviewToReviewReport(
  preview: ChunkPreviewResponse,
  overrides: ChunkOverrides | undefined,
  options?: { include_disabled?: boolean }
): ChunkPreviewReviewReport {
  const includeDisabled = Boolean(options?.include_disabled)

  const mergedAll = applyChunkOverridesToPreview(preview, overrides, { include_disabled: true })
  const merged = includeDisabled ? mergedAll : applyChunkOverridesToPreview(preview, overrides, { include_disabled: false })

  const unit: 'chars' | 'tokens' = mergedAll.params?.unit === 'tokens' ? 'tokens' : 'chars'

  const editedIndices = new Set<number>()
  const disabledIndices = new Set<number>()
  for (const [k, v] of Object.entries(overrides || {})) {
    const idx = Number(k)
    if (!Number.isFinite(idx)) continue
    if (v?.disabled) disabledIndices.add(idx)
    if (v?.content !== undefined || v?.metadata !== undefined) editedIndices.add(idx)
  }

  const reviewSignals: ChunkPreviewReviewSignals = mergedAll.review_signals ?? emptyReviewSignals()
  const shortIndices = toIndexSet(reviewSignals.short_indices)
  const duplicateIndices = toIndexSet(reviewSignals.duplicate_indices)
  const gapIndices = toIndexSet(reviewSignals.gap_indices)
  const overlapIndices = toIndexSet(reviewSignals.overlap_indices)
  const gapBeforeByIndex = toSignalValueMap(reviewSignals.gap_before_by_index)
  const overlapPrevByIndex = toSignalValueMap(reviewSignals.overlap_prev_by_index)

  const chunks: ChunkPreviewReviewReportChunk[] = (merged.chunks || []).map((c) => {
    const idx = Number(c.index)
    const meta = getChunkMetadata(c)
    const raw = String(c.content || '')

    const gapBefore = gapBeforeByIndex.get(idx) || 0
    const overlapPrev = overlapPrevByIndex.get(idx) || 0

    const override = overrides?.[idx]
    const isDisabled = Boolean(override?.disabled) || Boolean(meta.__mimirq_skip)
    const isEdited = editedIndices.has(idx)

    return {
      index: idx,
      page_number: typeof c.page_number === 'number' ? c.page_number : null,
      start_index: Number(c.start_index) || 0,
      end_index: Number(c.end_index) || 0,
      length: Number(c.length) || 0,
      tokens_est: typeof c.tokens_est === 'number' ? c.tokens_est : null,
      role: getChunkRole(meta),
      parent_id: getChunkParentId(meta),
      disabled: isDisabled,
      edited: isEdited,
      flags: {
        short: shortIndices.has(idx),
        duplicate: duplicateIndices.has(idx),
        gap: gapIndices.has(idx),
        overlap: overlapIndices.has(idx),
      },
      gap_before: gapBefore,
      overlap_prev: overlapPrev,
      content_hash: null,
      content_preview: raw.length > 220 ? `${raw.slice(0, 220)}...` : raw,
    }
  })

  return {
    schema: 'mimirq.chunk_review.v1',
    generated_at: new Date().toISOString(),
    file: {
      filename: mergedAll.filename,
      file_type: mergedAll.file_type,
      file_size: mergedAll.file_size,
      file_sha256: mergedAll.file_sha256 ?? null,
      total_characters: mergedAll.total_characters,
    },
    config: {
      parser_backend: mergedAll.parser_backend,
      chunk_strategy: mergedAll.chunk_strategy,
      chunk_size: mergedAll.params?.chunk_size,
      chunk_overlap: mergedAll.params?.chunk_overlap,
      unit,
      strategy_params: mergedAll.params?.strategy_params || {},
    },
    stats: mergedAll.stats || null,
    review_signals: reviewSignals,
    quality_gate: mergedAll.quality_gate ?? null,
    recommendations: mergedAll.recommendations ?? [],
    warnings: mergedAll.warnings ?? [],
    summary: {
      total_chunks: mergedAll.total_chunks,
      total_chunks_in_report: chunks.length,
      include_disabled: includeDisabled,
      disabled_count: disabledIndices.size,
      edited_count: editedIndices.size,
      issue_counts: {
        short: shortIndices.size,
        duplicate: duplicateIndices.size,
        gap: gapIndices.size,
        overlap: overlapIndices.size,
      },
      coverage_basis: reviewSignals.basis ?? 'all',
    },
    chunks,
  }
}

function oneLine(value: unknown) {
  return toSingleLinePrimitiveString(value)
}

function fmtPctRatio(value: unknown): string | null {
  const v = Number(value)
  if (!Number.isFinite(v)) return null
  return `${Math.max(0, Math.min(100, Math.round(v * 100)))}%`
}

function listChunkNumbers(indices: number[] | undefined, options?: { limit?: number }) {
  const limit = options?.limit ?? 80
  const list = Array.isArray(indices) ? indices.filter((n) => typeof n === 'number' && Number.isFinite(n)).sort((a, b) => a - b) : []
  if (!list.length) return '-'
  const shown = list.slice(0, Math.max(1, limit)).map((n) => `#${Math.trunc(n) + 1}`)
  const extra = list.length > shown.length ? ` …(+${list.length - shown.length})` : ''
  return `${shown.join(', ')}${extra}`
}

export function chunkPreviewToReviewMarkdown(
  preview: ChunkPreviewResponse,
  overrides: ChunkOverrides | undefined,
  options?: { include_disabled?: boolean }
) {
  const report = chunkPreviewToReviewReport(preview, overrides, options)

  const lines: string[] = []

  const filename = String(report.file.filename || preview.filename || 'document')
  lines.push(`# ${filename} — Chunk Review`, '', `- schema: ${String(report.schema || 'mimirq.chunk_review.v1')}`)
  if (report.generated_at) lines.push(`- generated_at: ${String(report.generated_at)}`)
  lines.push('')

  const cfg = report.config
  lines.push('## Config', `- parser_backend: ${String(cfg.parser_backend || '')}`, `- chunk_strategy: ${String(cfg.chunk_strategy || '')}`, `- chunk_size: ${String(cfg.chunk_size ?? '')} (${String(cfg.unit || 'chars')})`, `- chunk_overlap: ${String(cfg.chunk_overlap ?? '')} (${String(cfg.unit || 'chars')})`, '')

  const stats = report.stats
  lines.push('## Stats', `- count: ${String(stats?.count ?? '')}`)
  if (stats?.coverage_ratio != null) lines.push(`- coverage_ratio: ${fmtPctRatio(stats.coverage_ratio) ?? String(stats.coverage_ratio)}`)
  if (stats?.overlap_waste_ratio != null) {
    lines.push(`- overlap_waste_ratio: ${fmtPctRatio(stats.overlap_waste_ratio) ?? String(stats.overlap_waste_ratio)}`)
  }
  if (stats?.gap_count != null) lines.push(`- gap_count: ${String(stats.gap_count)}`)
  if (stats?.largest_gap != null) lines.push(`- largest_gap: ${String(stats.largest_gap)}`)
  lines.push('')

  const summary = report.summary
  const issueCounts = summary.issue_counts
  lines.push('## Summary', `- total_chunks: ${String(summary.total_chunks ?? '')}`, `- total_chunks_in_report: ${String(summary.total_chunks_in_report ?? '')}`, `- include_disabled: ${String(summary.include_disabled ?? false)}`, `- disabled_count: ${String(summary.disabled_count ?? 0)} · edited_count: ${String(summary.edited_count ?? 0)}`, `- issue_counts: short=${String(issueCounts.short ?? 0)} duplicate=${String(issueCounts.duplicate ?? 0)} gap=${String(issueCounts.gap ?? 0)} overlap=${String(issueCounts.overlap ?? 0)}`, '')

  const signals = report.review_signals
  lines.push('## Issue Indices', `- short_indices: ${listChunkNumbers(signals.short_indices)}`, `- duplicate_indices: ${listChunkNumbers(signals.duplicate_indices)}`, `- gap_indices: ${listChunkNumbers(signals.gap_indices)}`, `- overlap_indices: ${listChunkNumbers(signals.overlap_indices)}`, '')

  const recs = report.recommendations
  if (recs.length) {
    lines.push('## Recommendations')
    for (const r of recs.slice(0, 20)) lines.push(`- ${oneLine(r)}`)
    if (recs.length > 20) lines.push(`- …(+${recs.length - 20})`)
    lines.push('')
  }

  // Keep it compact: include only a small sample of problematic chunks.
  const chunks = report.chunks
  const flagged = chunks.filter((c) => c.flags.short || c.flags.duplicate || c.flags.gap || c.flags.overlap)
  if (flagged.length) {
    lines.push('## Samples (first 30 flagged chunks)')
    for (const c of flagged.slice(0, 30)) {
      const idx = Number(c.index)
      const range = `${String(c.start_index ?? '')}-${String(c.end_index ?? '')}`
      const flags = Object.entries(c.flags || {})
        .filter(([, v]) => Boolean(v))
        .map(([k]) => k)
        .join(',')
      lines.push(`- #${Number.isFinite(idx) ? idx + 1 : '?'} · range ${range} · flags: ${flags || '-'}`)
      const previewText = oneLine(c.content_preview || '')
      if (previewText) lines.push(`  - preview: ${previewText}`)
    }
    if (flagged.length > 30) lines.push(`- …(+${flagged.length - 30})`)
    lines.push('')
  }

  return lines.join('\n')
}
