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
