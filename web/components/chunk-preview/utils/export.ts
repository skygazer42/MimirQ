import type { ChunkPreviewResponse } from '@/types'

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
