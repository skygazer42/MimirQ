import type { ChunkPreviewItem } from '@/types'

function normalizePath(raw: string) {
  const text = raw.trim()
  if (!text) return ''

  // markdown_header uses " > " separators; outline uses " / ".
  // Keep a single visual separator for UI grouping.
  return text
    .split('>')
    .flatMap((part) => part.split('/'))
    .map((part) => part.trim().split(/\s+/).filter(Boolean).join(' '))
    .filter(Boolean)
    .join(' / ')
}

export function getChunkSectionPath(chunk: Pick<ChunkPreviewItem, 'metadata'>): string | null {
  const metadata = chunk.metadata

  const outlineStr = metadata?.outline_path_str
  if (typeof outlineStr === 'string') {
    const v = normalizePath(outlineStr)
    if (v) return v
  }

  const outlineArr = metadata?.outline_path
  if (Array.isArray(outlineArr) && outlineArr.length > 0) {
    const v = normalizePath(outlineArr.filter((part): part is string => typeof part === 'string').join(' / '))
    if (v) return v
  }

  const headerPath = metadata?.header_path
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
  const parts = full.split(' / ')
  const last = parts.at(-1)!
  const characters = Array.from(last)
  const short = characters.length > 40 ? `${characters.slice(0, 39).join('')}…` : last
  return { full, short }
}
