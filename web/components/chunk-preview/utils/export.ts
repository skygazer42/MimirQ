import type { ChunkPreviewResponse } from '@/types'

function roughEstimateTokens(text: string) {
  const raw = (text || '').trim()
  if (!raw) return 0
  return Math.max(1, Math.ceil(raw.length / 4))
}

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
