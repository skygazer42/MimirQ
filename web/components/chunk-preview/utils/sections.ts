import type { ChunkPreviewItem } from '@/types'

function normalizePath(raw: string) {
  const s = String(raw || '').trim()
  if (!s) return ''

  // markdown_header uses " > " separators; outline uses " / ".
  // Keep a single visual separator for UI grouping.
  return s
    .split('>')
    .flatMap((part) => part.split('/'))
    .map((part) => part.trim().split(/\s+/).filter(Boolean).join(' '))
    .filter(Boolean)
    .join(' / ')
}

export function getChunkSectionPath(chunk: ChunkPreviewItem): string | null {
  const meta = (chunk?.metadata || {})

  const outlineStr = meta.outline_path_str
  if (typeof outlineStr === 'string') {
    const v = normalizePath(outlineStr)
    if (v) return v
  }

  const outlineArr = meta.outline_path
  if (Array.isArray(outlineArr) && outlineArr.length > 0) {
    const v = normalizePath(outlineArr.map(String).filter(Boolean).join(' / '))
    if (v) return v
  }

  const headerPath = meta.header_path
  if (typeof headerPath === 'string') {
    const v = normalizePath(headerPath)
    if (v) return v
  }

  return null
}

export function getChunkSectionLabel(chunk: ChunkPreviewItem): { full: string; short: string } | null {
  const full = getChunkSectionPath(chunk)
  if (!full) return null

  // Use last segment as short label for cards; keep the full path in a tooltip.
  const parts = full.split(' / ').map((p) => p.trim()).filter(Boolean)
  const last = parts.at(-1) || full
  const short = last.length > 40 ? last.slice(0, 39) + '…' : last
  return { full, short }
}
