import MiniSearch from 'minisearch'
import type { ChunkPreviewItem } from '@/types'
import { getChunkSectionPath } from '@/components/chunk-preview/utils/sections'

type ChunkSearchDoc = {
  id: string
  index: number
  content: string
  page_number?: number
  section?: string
}

export type ChunkSearchResult = {
  index: number
  score: number
  page_number?: number
  section?: string
  snippet: string
}

type ChunkSearchHit = ChunkSearchDoc & {
  score?: number
}

function makeSnippet(content: string, query: string) {
  const text = String(content || '')
  const q = (query || '').trim()
  if (!q) return text.slice(0, 140)

  const lower = text.toLowerCase()
  const qLower = q.toLowerCase()
  const idx = lower.indexOf(qLower)
  if (idx < 0) return text.slice(0, 140)

  const start = Math.max(0, idx - 60)
  const end = Math.min(text.length, idx + q.length + 60)
  const prefix = start > 0 ? '…' : ''
  const suffix = end < text.length ? '…' : ''
  return `${prefix}${text.slice(start, end)}${suffix}`
}

export function buildChunkSearchIndex(chunks: ChunkPreviewItem[]) {
  const miniSearch = new MiniSearch<ChunkSearchDoc>({
    fields: ['content', 'section'],
    storeFields: ['index', 'content', 'page_number', 'section'],
    searchOptions: {
      prefix: true,
      fuzzy: 0.2,
    },
  })

  const docs: ChunkSearchDoc[] = (chunks || []).map((c) => {
    const idx = Number(c.index)
    return {
      id: String(idx),
      index: idx,
      content: String(c.content ?? ''),
      page_number: typeof c.page_number === 'number' ? Number(c.page_number) : undefined,
      section: getChunkSectionPath(c) || undefined,
    }
  })

  miniSearch.addAll(docs)
  return miniSearch
}

export function searchChunkIndex(
  index: MiniSearch<ChunkSearchDoc>,
  query: string,
  options?: { limit?: number }
): ChunkSearchResult[] {
  const q = (query || '').trim()
  if (!q) return []
  const limit = Math.max(1, Math.min(50, Number(options?.limit ?? 10)))

  const results = index.search(q)
  return results.slice(0, limit).map((result) => {
    const hit = result as unknown as ChunkSearchHit
    const content = String(hit.content ?? '')
    return {
      index: Number(hit.index),
      score: Number(hit.score || 0),
      page_number: typeof hit.page_number === 'number' ? Number(hit.page_number) : undefined,
      section: typeof hit.section === 'string' && hit.section.trim() ? String(hit.section) : undefined,
      snippet: makeSnippet(content, q),
    }
  })
}
