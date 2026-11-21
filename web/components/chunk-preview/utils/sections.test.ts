import { describe, expect, it } from 'vitest'

import type { ChunkPreviewItem, JsonObject } from '@/types'
import { getChunkSectionLabel, getChunkSectionPath } from './sections'

function chunk(metadata?: JsonObject): ChunkPreviewItem {
  return { index: 0, content: 'text', length: 4, start_index: 0, end_index: 4, metadata }
}

describe('actual chapter labels', () => {
  it('keeps only actual string path segments rather than manufacturing null or object labels', () => {
    const metadata = { outline_path: [null, { label: 'unknown' }, false, '  0 ', 'Heading'] }
    expect(getChunkSectionPath(chunk(metadata))).toBe('0 / Heading')
    expect(metadata.outline_path).toEqual([null, { label: 'unknown' }, false, '  0 ', 'Heading'])
  })

  it('uses the existing explicit source priority and retains unavailable chapters', () => {
    expect(getChunkSectionPath(chunk())).toBeNull()
    expect(getChunkSectionPath(chunk({ outline_path: [null], header_path: ' Root > Leaf ' }))).toBe('Root / Leaf')
    expect(getChunkSectionPath(chunk({ outline_path_str: 'Root > First', header_path: 'Other' }))).toBe('Root / First')
  })

  it('does not cut an emoji into an unmatched surrogate when shortening the last label', () => {
    const full = `${'a'.repeat(38)}😀tail`
    const label = getChunkSectionLabel(chunk({ header_path: full }))
    expect(label?.full).toBe(full)
    expect(label?.short).toBe(`${'a'.repeat(38)}😀…`)
    expect(Array.from(label!.short)).toHaveLength(40)
  })
})
