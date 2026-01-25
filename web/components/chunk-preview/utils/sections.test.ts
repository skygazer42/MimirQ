import { describe, expect, it } from 'vitest'
import type { ChunkPreviewItem } from '@/types'
import { getChunkSectionLabel, getChunkSectionPath } from './sections'

function chunk(meta: Record<string, any>): ChunkPreviewItem {
  return {
    index: 0,
    content: 'x',
    length: 1,
    tokens_est: 1,
    start_index: 0,
    end_index: 1,
    page_number: 1,
    metadata: meta,
  }
}

describe('sections', () => {
  it('getChunkSectionPath prefers outline_path_str', () => {
    const c = chunk({ outline_path_str: 'A / B / C' })
    expect(getChunkSectionPath(c)).toBe('A / B / C')
  })

  it('getChunkSectionPath falls back to outline_path array', () => {
    const c = chunk({ outline_path: ['A', 'B', 'C'] })
    expect(getChunkSectionPath(c)).toBe('A / B / C')
  })

  it('getChunkSectionPath normalizes markdown header_path separators', () => {
    const c = chunk({ header_path: 'H1  >   H2>H3' })
    expect(getChunkSectionPath(c)).toBe('H1 / H2 / H3')
  })

  it('getChunkSectionLabel returns last segment as short label', () => {
    const c = chunk({ header_path: 'A > B > C' })
    const label = getChunkSectionLabel(c)
    expect(label).not.toBeNull()
    expect(label?.full).toBe('A / B / C')
    expect(label?.short).toBe('C')
  })
})

