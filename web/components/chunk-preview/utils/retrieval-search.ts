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
    const idx = Number((c as any)?.index)
    return {
      id: String(idx),
      index: idx,
      content: String((c as any)?.content ?? ''),
      page_number: typeof (c as any)?.page_number === 'number' ? Number((c as any).page_number) : undefined,
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

  const results = index.search(q) as any[]
  return results.slice(0, limit).map((r) => {
    const content = String(r.content ?? '')
    return {
      index: Number(r.index),
      score: Number(r.score || 0),
      page_number: typeof r.page_number === 'number' ? Number(r.page_number) : undefined,
      section: typeof r.section === 'string' && r.section.trim() ? String(r.section) : undefined,
      snippet: makeSnippet(content, q),
    }
  })
}
