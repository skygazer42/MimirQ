import type { ChunkPreviewResponse } from '@/types'
import { computeCoverageSignals, computeDuplicateIndices, computeShortIndices, fnv1a32, roughEstimateTokens } from './review-signals'

export function sanitizeFilename(name: string) {
  const trimmed = (name || '').trim()
  const base = trimmed || 'chunks'
  return base.replace(/[\\/:*?"<>|]+/g, '_')
}

export function downloadTextFile(filename: string, content: string, mime = 'text/plain;charset=utf-8') {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function toChunkPreviewExport(preview: ChunkPreviewResponse) {
  // Keep exports stable + lightweight: omit original_text (can be huge).
  const { original_text: _omit, ...rest } = preview as any
  return {
    ...rest,
    original_text_included: Boolean(preview.original_text),
  }
}

export function applyChunkOverridesToPreview(
  preview: ChunkPreviewResponse,
  overrides: Record<number, { content?: string; metadata?: Record<string, any>; disabled?: boolean; updatedAt?: number }> | undefined,
  options?: { include_disabled?: boolean }
) {
  const keys = overrides ? Object.keys(overrides) : []
  const includeDisabled = Boolean(options?.include_disabled)
  if (!keys.length) return preview

  const chunks = (preview.chunks || []).reduce((acc, chunk) => {
    const idx = typeof chunk.index === 'number' ? chunk.index : (preview.chunks || []).indexOf(chunk)
    const override = overrides?.[idx]

    const isDisabled = Boolean(override?.disabled)
    if (isDisabled && !includeDisabled) return acc
    if (!override) {
      acc.push(chunk)
      return acc
    }

    const content = String(override.content ?? chunk.content ?? '')
    const metadata = (override.metadata ?? chunk.metadata ?? {}) as Record<string, any>
    const exportMetadata = isDisabled && includeDisabled ? { ...metadata, __mimirq_skip: true } : metadata
    acc.push({
      ...chunk,
      content,
      metadata: exportMetadata,
      length: content.length,
      tokens_est: roughEstimateTokens(content),
    })
    return acc
  }, [] as any[])

  return {
    ...preview,
    chunks,
    total_chunks: chunks.length,
  }
}

function csvEscape(value: unknown) {
  const raw = String(value ?? '')
  const needsQuote = /[",\n\r]/.test(raw)
  const escaped = raw.replace(/"/g, '""')
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

  lines.push(`# ${safeName}`)
  lines.push('')
  lines.push(`- parser_backend: ${preview.parser_backend}`)
  lines.push(`- chunk_strategy: ${preview.chunk_strategy}`)
  lines.push(`- chunk_size: ${preview.params?.chunk_size} (${unit})`)
  lines.push(`- chunk_overlap: ${preview.params?.chunk_overlap} (${unit})`)
  lines.push(`- total_chunks: ${preview.total_chunks}`)
  lines.push('')

  // Use 4 backticks to reduce accidental fence collisions with chunk contents.
  const fence = '````'

  for (const c of preview.chunks || []) {
    const pageLabel = typeof c.page_number === 'number' ? ` (P.${c.page_number})` : ''
    const tok = typeof c.tokens_est === 'number' ? c.tokens_est : undefined
    const lenLine = tok != null ? `${c.length} chars · ${tok} tok` : `${c.length} chars`

    lines.push(`## Chunk ${Number(c.index) + 1}${pageLabel}`)
    lines.push('')
    lines.push(`- range: ${c.start_index}-${c.end_index}`)
    lines.push(`- length: ${lenLine}`)
    lines.push('')
    lines.push(`${fence}text`)
    lines.push(String(c.content ?? ''))
    lines.push(fence)
    lines.push('')
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
  overrides: Record<number, { content?: string; metadata?: Record<string, any>; disabled?: boolean; updatedAt?: number }> | undefined,
  options?: { include_disabled?: boolean }
) {
  const includeDisabled = Boolean(options?.include_disabled)

  const mergedAll = applyChunkOverridesToPreview(preview, overrides, { include_disabled: true })
  const merged = includeDisabled ? mergedAll : applyChunkOverridesToPreview(preview, overrides, { include_disabled: false })

  const unit: 'chars' | 'tokens' = mergedAll.params?.unit === 'tokens' ? 'tokens' : 'chars'

  const editedIndices = new Set<number>()
  const disabledIndices = new Set<number>()
  for (const [k, v] of Object.entries(overrides || {})) {
    const idx = Number(k)
    if (!Number.isFinite(idx)) continue
    if ((v as any)?.disabled) disabledIndices.add(idx)
    if ((v as any)?.content !== undefined || (v as any)?.metadata !== undefined) editedIndices.add(idx)
  }

  const duplicateIndices = computeDuplicateIndices(mergedAll.chunks || [])
  const shortIndices = computeShortIndices(mergedAll.chunks || [], unit)
  const coverage = computeCoverageSignals(mergedAll.chunks || [], { strategy: mergedAll.chunk_strategy })

  const reviewSignals =
    (mergedAll as any).review_signals ??
    ({
      basis: coverage.basis,
      short_indices: Array.from(shortIndices).sort((a, b) => a - b),
      duplicate_indices: Array.from(duplicateIndices).sort((a, b) => a - b),
      gap_indices: Array.from(coverage.gapIndices).sort((a, b) => a - b),
      overlap_indices: Array.from(coverage.overlapIndices).sort((a, b) => a - b),
      gap_before_by_index: Object.fromEntries(Array.from(coverage.gapBeforeByIndex.entries()).map(([k, v]) => [String(k), v])),
      overlap_prev_by_index: Object.fromEntries(Array.from(coverage.overlapPrevByIndex.entries()).map(([k, v]) => [String(k), v])),
    } as any)

  const chunks = (merged.chunks || []).map((c) => {
    const idx = Number(c.index)
    const meta = (c.metadata || {}) as Record<string, any>
    const raw = String(c.content || '')
    const trimmed = raw.trim()

    const gapBefore = coverage.gapBeforeByIndex.get(idx) || 0
    const overlapPrev = coverage.overlapPrevByIndex.get(idx) || 0

    const isDisabled = Boolean((overrides as any)?.[idx]?.disabled) || Boolean(meta.__mimirq_skip)
    const isEdited = editedIndices.has(idx)

    return {
      index: idx,
      page_number: typeof c.page_number === 'number' ? c.page_number : null,
      start_index: Number(c.start_index) || 0,
      end_index: Number(c.end_index) || 0,
      length: Number(c.length) || 0,
      tokens_est: typeof c.tokens_est === 'number' ? c.tokens_est : null,
      role: typeof meta.chunk_role === 'string' ? meta.chunk_role : null,
      parent_id: typeof meta.parent_id === 'string' ? meta.parent_id : typeof meta.parent_node_id === 'string' ? meta.parent_node_id : null,
      disabled: isDisabled,
      edited: isEdited,
      flags: {
        short: shortIndices.has(idx),
        duplicate: duplicateIndices.has(idx),
        gap: coverage.gapIndices.has(idx),
        overlap: coverage.overlapIndices.has(idx),
      },
      gap_before: gapBefore,
      overlap_prev: overlapPrev,
      content_hash: trimmed ? fnv1a32(trimmed) : null,
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
      file_sha256: (mergedAll as any).file_sha256 ?? null,
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
    quality_gate: (mergedAll as any).quality_gate ?? null,
    recommendations: (mergedAll as any).recommendations ?? [],
    warnings: (mergedAll as any).warnings ?? [],
    summary: {
      total_chunks: mergedAll.total_chunks,
      total_chunks_in_report: chunks.length,
      include_disabled: includeDisabled,
      disabled_count: disabledIndices.size,
      edited_count: editedIndices.size,
      issue_counts: {
        short: shortIndices.size,
        duplicate: duplicateIndices.size,
        gap: coverage.gapIndices.size,
        overlap: coverage.overlapIndices.size,
      },
      coverage_basis: coverage.basis,
    },
    chunks,
  }
}

function oneLine(value: unknown) {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
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
  overrides: Record<number, { content?: string; metadata?: Record<string, any>; disabled?: boolean; updatedAt?: number }> | undefined,
  options?: { include_disabled?: boolean }
) {
  const report = chunkPreviewToReviewReport(preview, overrides, options) as any

  const lines: string[] = []

  const filename = String(report?.file?.filename || preview.filename || 'document')
  lines.push(`# ${filename} — Chunk Review`)
  lines.push('')
  lines.push(`- schema: ${String(report?.schema || 'mimirq.chunk_review.v1')}`)
  if (report?.generated_at) lines.push(`- generated_at: ${String(report.generated_at)}`)
  lines.push('')

  const cfg = (report?.config || {}) as any
  lines.push('## Config')
  lines.push(`- parser_backend: ${String(cfg.parser_backend || '')}`)
  lines.push(`- chunk_strategy: ${String(cfg.chunk_strategy || '')}`)
  lines.push(`- chunk_size: ${String(cfg.chunk_size ?? '')} (${String(cfg.unit || 'chars')})`)
  lines.push(`- chunk_overlap: ${String(cfg.chunk_overlap ?? '')} (${String(cfg.unit || 'chars')})`)
  lines.push('')

  const stats = (report?.stats || {}) as any
  lines.push('## Stats')
  lines.push(`- count: ${String(stats.count ?? '')}`)
  if (stats.coverage_ratio != null) lines.push(`- coverage_ratio: ${fmtPctRatio(stats.coverage_ratio) ?? String(stats.coverage_ratio)}`)
  if (stats.overlap_waste_ratio != null) {
    lines.push(`- overlap_waste_ratio: ${fmtPctRatio(stats.overlap_waste_ratio) ?? String(stats.overlap_waste_ratio)}`)
  }
  if (stats.gap_count != null) lines.push(`- gap_count: ${String(stats.gap_count)}`)
  if (stats.largest_gap != null) lines.push(`- largest_gap: ${String(stats.largest_gap)}`)
  lines.push('')

  const summary = (report?.summary || {}) as any
  const issueCounts = (summary.issue_counts || {}) as any
  lines.push('## Summary')
  lines.push(`- total_chunks: ${String(summary.total_chunks ?? '')}`)
  lines.push(`- total_chunks_in_report: ${String(summary.total_chunks_in_report ?? '')}`)
  lines.push(`- include_disabled: ${String(summary.include_disabled ?? false)}`)
  lines.push(`- disabled_count: ${String(summary.disabled_count ?? 0)} · edited_count: ${String(summary.edited_count ?? 0)}`)
  lines.push(
    `- issue_counts: short=${String(issueCounts.short ?? 0)} duplicate=${String(issueCounts.duplicate ?? 0)} gap=${String(issueCounts.gap ?? 0)} overlap=${String(issueCounts.overlap ?? 0)}`
  )
  lines.push('')

  const signals = (report?.review_signals || {}) as any
  lines.push('## Issue Indices')
  lines.push(`- short_indices: ${listChunkNumbers(signals.short_indices)}`)
  lines.push(`- duplicate_indices: ${listChunkNumbers(signals.duplicate_indices)}`)
  lines.push(`- gap_indices: ${listChunkNumbers(signals.gap_indices)}`)
  lines.push(`- overlap_indices: ${listChunkNumbers(signals.overlap_indices)}`)
  lines.push('')

  const recs = Array.isArray(report?.recommendations) ? report.recommendations : []
  if (recs.length) {
    lines.push('## Recommendations')
    for (const r of recs.slice(0, 20)) lines.push(`- ${oneLine(r)}`)
    if (recs.length > 20) lines.push(`- …(+${recs.length - 20})`)
    lines.push('')
  }

  // Keep it compact: include only a small sample of problematic chunks.
  const chunks = Array.isArray(report?.chunks) ? report.chunks : []
  const flagged = chunks.filter((c: any) => c?.flags?.short || c?.flags?.duplicate || c?.flags?.gap || c?.flags?.overlap)
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
