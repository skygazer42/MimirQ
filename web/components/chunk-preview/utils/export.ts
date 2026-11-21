import type { ChunkPreviewItem, ChunkPreviewResponse } from '@/types'
import { sanitizeFilename } from '@/lib/sanitize'
import { downloadBlob } from '@/lib/download'
import type { ChunkOverrides } from '../types'
import { applyChunkEdits } from './chunk-edits'

export { sanitizeFilename } from '@/lib/sanitize'

export function downloadTextFile(filename: string, content: string, mime = 'text/plain;charset=utf-8') {
  downloadBlob(filename, new Blob([content], { type: mime }))
}

export function toChunkPreviewExport(preview: ChunkPreviewResponse) {
  // Both source representations can be large; the flag describes this exported payload.
  const { original_text: _originalText, original_text_cleaned: _cleanedText, ...rest } = preview
  return {
    ...rest,
    original_text_included: false,
  }
}

export function applyChunkOverridesToPreview(
  preview: ChunkPreviewResponse,
  overrides: ChunkOverrides,
  options?: { include_disabled?: boolean },
): ChunkPreviewResponse {
  const includeDisabled = options?.include_disabled === true
  const chunks: ChunkPreviewItem[] = []
  let changed = false
  for (const chunk of preview.chunks) {
    const override = overrides[chunk.index]
    const isDisabled = override?.disabled === true
    if (isDisabled && !includeDisabled) {
      changed = true
      continue
    }
    const edited = applyChunkEdits(chunk, override)
    if (edited !== chunk || isDisabled) changed = true
    chunks.push(isDisabled ? { ...edited, metadata: { ...edited.metadata, __mimirq_skip: true } } : edited)
  }
  if (!changed) return preview

  // These measurements describe the server response, not this local projection.
  const result: ChunkPreviewResponse = {
    ...preview,
    chunks,
    total_chunks: chunks.length,
    stats: null,
  }
  delete result.chunking_stats_tokens
  delete result.review_signals
  delete result.quality_gate
  delete result.recommendations
  delete result.recommendation_patches
  delete result.total_chunks_full
  delete result.chunks_truncated
  delete result.chunks_max_count
  return result
}

function csvEscape(value: string | number | null | undefined) {
  // CSV has no absent-value token; an unavailable optional field is an empty cell.
  if (value === null || value === undefined) {
    return ''
  }
  const raw = String(value)
  const needsQuote = /[",\n\r]/.test(raw)
  const escaped = raw.replaceAll('"', '""')
  return needsQuote ? `"${escaped}"` : escaped
}

export function chunkPreviewToCsv(preview: ChunkPreviewResponse) {
  const headers = ['index', 'page_number', 'start_index', 'end_index', 'length', 'content']
  const rows = preview.chunks.map((chunk) => [
    chunk.index,
    chunk.page_number,
    chunk.start_index,
    chunk.end_index,
    chunk.length,
    chunk.content,
  ])
  return [headers, ...rows].map((row) => row.map(csvEscape).join(',')).join('\n')
}

export function getMarkdownCodeFence(content: string): string {
  let fence = '````'
  for (const match of content.matchAll(/`+/g)) {
    if (match[0].length >= fence.length) fence = '`'.repeat(match[0].length + 1)
  }
  return fence
}

export function chunkPreviewToMarkdown(preview: ChunkPreviewResponse) {
  const lines: string[] = []
  const unit = preview.params.unit ?? 'chars'
  const safeName = sanitizeFilename(preview.filename)

  lines.push(
    `# ${safeName}`,
    '',
    `- parser_backend: ${preview.parser_backend}`,
    `- chunk_strategy: ${preview.chunk_strategy}`,
    `- chunk_size: ${preview.params.chunk_size} (${unit})`,
    `- chunk_overlap: ${preview.params.chunk_overlap} (${unit})`,
    `- total_chunks: ${preview.total_chunks}`,
    '',
  )

  for (const chunk of preview.chunks) {
    const fence = getMarkdownCodeFence(chunk.content)
    const pageLabel = typeof chunk.page_number === 'number' ? ` (P.${chunk.page_number})` : ''
    const lengthLabel =
      typeof chunk.tokens_est === 'number' ? `${chunk.length} chars · ${chunk.tokens_est} tok` : `${chunk.length} chars`

    lines.push(
      `## Chunk ${chunk.index + 1}${pageLabel}`,
      '',
      `- range: ${chunk.start_index}-${chunk.end_index}`,
      `- length: ${lengthLabel}`,
      '',
      `${fence}text`,
      chunk.content,
      fence,
      '',
    )
  }

  return lines.join('\n')
}

export function chunkPreviewToJsonl(preview: ChunkPreviewResponse) {
  const rows = preview.chunks.map((chunk) =>
    JSON.stringify({
      index: chunk.index,
      page_number: chunk.page_number,
      start_index: chunk.start_index,
      end_index: chunk.end_index,
      length: chunk.length,
      tokens_est: chunk.tokens_est,
      metadata: chunk.metadata,
      content: chunk.content,
    }),
  )
  return rows.join('\n')
}
