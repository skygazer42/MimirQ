import { describe, expect, it } from 'vitest'

import type { ChunkPreviewItem, ChunkPreviewResponse } from '@/types'
import { findChunkParent } from '@/components/chunk-preview/utils/metadata'
import {
  buildChunkListRows,
  getApplicableReviewSignals,
  getSectionFilterValue,
  parseLengthBounds,
} from './chunk-list-model'

const hierarchy = {
  view: 'hierarchy' as const,
  collapsedGroups: new Set<string>(),
  forceExpand: false,
  noSectionLabel: 'No section',
}

function entries(chunks: readonly ChunkPreviewItem[]) {
  return chunks.map((chunk, position) => ({ chunk, position }))
}

function parentAndChild(): ChunkPreviewItem[] {
  return [
    {
      index: 4,
      content: 'parent',
      length: 6,
      start_index: 0,
      end_index: 30,
      metadata: { chunk_role: 'parent', parent_id: 0 },
    },
    {
      index: 9,
      content: 'child',
      length: 5,
      start_index: 5,
      end_index: 10,
      metadata: { chunk_role: 'child', parent_id: 0 },
    },
  ]
}

describe('actual list grouping and measurement scope', () => {
  it('keeps numeric identities distinct from strings and preserves frozen source rows', () => {
    const chunks = parentAndChild()
    for (const chunk of chunks) {
      Object.freeze(chunk.metadata)
      Object.freeze(chunk)
    }
    Object.freeze(chunks)
    const rows = buildChunkListRows(chunks, entries(chunks), hierarchy)
    expect(rows.map((row) => row.key)).toEqual(['chunk:4', 'chunk:9'])
    expect(rows[0]).toMatchObject({ kind: 'parent', position: 0, childCountTotal: 1 })
    const distinct = [{ ...chunks[1], metadata: { chunk_role: 'child', parent_id: '0' } }]
    expect(findChunkParent(distinct[0], chunks)).toBeUndefined()
    expect(chunks[0].metadata?.parent_id).toBe(0)
  })

  it('does not choose one of two matching parents or duplicate their child', () => {
    const chunks = parentAndChild()
    chunks.splice(1, 0, { ...chunks[0], index: 7 })
    expect(findChunkParent(chunks[2], chunks)).toBeUndefined()
    const rows = buildChunkListRows(chunks, entries(chunks), hierarchy)
    expect(rows.map((row) => row.key)).toEqual(['chunk:4', 'chunk:7', 'chunk:9'])
    expect(rows.every((row) => row.kind === 'chunk')).toBe(true)
  })

  it('preserves collapse preference while forcing matching children visible during a filter', () => {
    const chunks = parentAndChild()
    const collapsedGroups = new Set(['parent:4'])
    expect(buildChunkListRows(chunks, entries(chunks), { ...hierarchy, collapsedGroups })).toHaveLength(1)
    const rows = buildChunkListRows(chunks, [entries(chunks)[1]], { ...hierarchy, collapsedGroups, forceExpand: true })
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ kind: 'parent', isContext: true, forceExpanded: true, collapsed: false })
    expect(rows[1]).toMatchObject({ kind: 'chunk', position: 1, indent: 1 })
    expect(collapsedGroups.has('parent:4')).toBe(true)
  })

  it('keeps actual sentinel-like and prototype names separate from missing section groups', () => {
    const chunks = parentAndChild().map((chunk, position) => ({
      ...chunk,
      metadata: position === 0 ? { header_path: '__mimirq_section_none__' } : undefined,
    }))
    const rows = buildChunkListRows(chunks, entries(chunks), { ...hierarchy, view: 'section' })
    expect(rows.filter((row) => row.kind === 'section').map((row) => row.label)).toEqual([
      '__mimirq_section_none__',
      'No section',
    ])
    expect(new Set(rows.map((row) => row.key)).size).toBe(4)
    expect(getSectionFilterValue('constructor')).toBe('section:constructor')
    expect(getSectionFilterValue(null)).toBe('__mimirq_section_none__')
  })

  it('parses true zero bounds without repairing fractions, nonfinite numbers or an inverted range', () => {
    expect(parseLengthBounds('', '0')).toEqual({ valid: true, minimum: undefined, maximum: 0 })
    expect(parseLengthBounds('1.5', '')).toMatchObject({ valid: false, minimumInvalid: true })
    expect(parseLengthBounds('Infinity', '')).toMatchObject({ valid: false, minimumInvalid: true })
    expect(parseLengthBounds('5', '2')).toEqual({ valid: false, minimumInvalid: true, maximumInvalid: true })
  })

  it('invalidates only measurements that depend on the changed producer fields', () => {
    const preview: ChunkPreviewResponse = {
      filename: 'source.md',
      file_type: 'md',
      file_size: 30,
      total_chunks: 2,
      total_characters: 30,
      params: { chunk_size: 1000, chunk_overlap: 0 },
      chunks: parentAndChild(),
      parser_backend: 'auto',
      chunk_strategy: 'parent_child',
      review_signals: {
        basis: 'child',
        short_indices: [9],
        duplicate_indices: [],
        gap_indices: [9],
        overlap_indices: [],
      },
    }
    expect(getApplicableReviewSignals(preview, { 9: { metadata: { chunk_role: 'child', reviewed: true } } })).toBe(
      preview.review_signals,
    )
    expect(getApplicableReviewSignals(preview, { 9: { content: 'edited' } })).toMatchObject({
      short_indices: undefined,
      duplicate_indices: undefined,
      gap_indices: [9],
    })
    expect(getApplicableReviewSignals(preview, { 9: { metadata: { chunk_role: 'parent' } } })).toMatchObject({
      short_indices: [9],
      gap_indices: undefined,
      overlap_indices: undefined,
    })
  })
})
