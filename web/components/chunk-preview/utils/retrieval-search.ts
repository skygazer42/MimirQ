import MiniSearch, { type SearchResult } from 'minisearch'
import type { ChunkPreviewItem } from '@/types'
import { getChunkSectionPath } from '@/components/chunk-preview/utils/sections'
import { expandTextRangeToCharacters, findCaseInsensitiveTextRanges } from '@/lib/text-offsets'

type ChunkSearchDoc = {
  id: number
  index: number
  content: string
  page_number?: number | null
  section?: string | null
}

export type ChunkSearchResult = {
  index: number
  score: number
  page_number?: number | null
  section?: string | null
  snippet: string
}

type ChunkSearchHit = SearchResult & ChunkSearchDoc

function makeSnippet(content: string, query: string) {
  const match = findCaseInsensitiveTextRanges(content, query, 1)[0]
  const range = expandTextRangeToCharacters(
    content,
    match === undefined ? 0 : Math.max(0, match.start - 60),
    match === undefined ? Math.min(content.length, 140) : Math.min(content.length, match.end + 60),
  )
  const prefix = range.start > 0 ? '…' : ''
  const suffix = match !== undefined && range.end < content.length ? '…' : ''
  return `${prefix}${content.slice(range.start, range.end)}${suffix}`
}

export function buildChunkSearchIndex(chunks: readonly ChunkPreviewItem[]) {
  const miniSearch = new MiniSearch<ChunkSearchDoc>({
    fields: ['content', 'section'],
    storeFields: ['index', 'content', 'page_number', 'section'],
    searchOptions: {
      prefix: true,
      fuzzy: 0.2,
    },
  })

  const docs: ChunkSearchDoc[] = chunks.map((chunk) => ({
    id: chunk.index,
    index: chunk.index,
    content: chunk.content,
    page_number: chunk.page_number,
    section: getChunkSectionPath(chunk),
  }))

  miniSearch.addAll(docs)
  return miniSearch
}

export function searchChunkIndex(
  index: MiniSearch<ChunkSearchDoc>,
  query: string,
  options?: { limit?: number },
): ChunkSearchResult[] {
  const q = query.trim()
  if (!q) return []
  const limit = Math.max(1, Math.min(50, options?.limit ?? 10))

  const results = index.search(q)
  return results.slice(0, limit).map((result) => {
    // This index is built above from typed docs and stores these exact fields.
    const hit = result as ChunkSearchHit
    return {
      index: hit.index,
      score: hit.score,
      page_number: hit.page_number,
      section: hit.section,
      snippet: makeSnippet(hit.content, q),
    }
  })
}
