import { describe, expect, it } from 'vitest'

import type { ChunkPreviewResponse } from '@/types'
import { buildSemanticEvidenceHighlights, computeChunkPreviewDiff, getComparisonCandidates } from './ab-diff'
import type { ChunkPreviewState } from '../types'

function preview(contents: string[]): ChunkPreviewResponse {
  return {
    filename: 'compare.md',
    file_type: 'md',
    file_size: 64,
    total_chunks: contents.length,
    total_characters: contents.reduce((total, content) => total + content.length, 0),
    params: { chunk_size: 500, chunk_overlap: 0, unit: 'chars' },
    chunks: contents.map((content, index) => ({
      index,
      content,
      length: content.length,
      start_index: index * 20,
      end_index: index * 20 + content.length,
    })),
    parser_backend: 'auto',
    chunk_strategy: 'recursive',
  }
}

describe('actual chunk content comparison', () => {
  it('uses the latest candidate for each actual cache result without sorting the caller history in place', () => {
    const base = {
      fileId: 'current-file',
      fileName: 'same.md',
      parserBackend: 'auto',
      strategy: 'recursive',
      chunkSize: 500,
      chunkOverlap: 0,
      totalChunks: 1,
      durationMs: 10,
      cacheHit: false,
    }
    const history: ChunkPreviewState['runHistory'] = [
      { ...base, id: 'old', cacheKey: 'same-result', createdAt: 1 },
      { ...base, id: 'latest', cacheKey: 'same-result', createdAt: 3 },
      { ...base, id: 'other-variant', cacheKey: 'other-result', createdAt: 2 },
      { ...base, id: 'foreign', fileId: 'foreign-file', cacheKey: 'foreign-result', createdAt: 4 },
    ]
    expect(getComparisonCandidates(history, 'current-file').map((run) => run.id)).toEqual(['latest', 'other-variant'])
    expect(history.map((run) => run.id)).toEqual(['old', 'latest', 'other-variant', 'foreign'])
  })

  it('uses actual backend P95 when the response omits chunk bodies', () => {
    const baseline = preview([])
    baseline.total_chunks = 50
    baseline.total_characters = 20000
    baseline.total_chunks_full = 50
    baseline.stats = { unit: 'chars', count: 50, avg: 400, p10: 100, p95: 900 }
    expect(computeChunkPreviewDiff(baseline, baseline)).toMatchObject({ aP95: 900, bP95: 900 })
  })

  it('keeps missing statistics and their changes unknown', () => {
    const baseline = preview(['first'])
    baseline.stats = null
    const current = preview(['next'])
    expect(computeChunkPreviewDiff(baseline, current)).toMatchObject({
      aAvg: null,
      bAvg: null,
      aP10: null,
      bP10: null,
      aP95: null,
      bP95: null,
      deltaAvg: null,
      deltaP10: null,
      deltaP95: null,
      deltaCoverage: null,
      deltaWaste: null,
      deltaGapCount: null,
    })
  })

  it('retains actual zero statistics and zero changes', () => {
    const baseline = preview([])
    baseline.stats = { unit: 'chars', avg: 0, p10: 0, p95: 0, coverage_ratio: 0, overlap_waste_ratio: 0, gap_count: 0 }
    expect(computeChunkPreviewDiff(baseline, baseline)).toMatchObject({
      aAvg: 0,
      bAvg: 0,
      aP10: 0,
      bP10: 0,
      aP95: 0,
      bP95: 0,
      deltaAvg: 0,
      deltaP10: 0,
      deltaP95: 0,
      deltaCoverage: 0,
      deltaWaste: 0,
      deltaGapCount: 0,
    })
  })

  it('keeps each run unit and does not subtract incompatible length statistics', () => {
    const baseline = preview(['first'])
    baseline.stats = { unit: 'chars', avg: 100, p10: 80, p95: 120, coverage_ratio: 0.5 }
    const current = preview(['next'])
    current.params.unit = 'tokens'
    current.stats = { unit: 'tokens', avg: 7, p10: 5, p95: 9, coverage_ratio: 0.75 }
    expect(computeChunkPreviewDiff(baseline, current)).toMatchObject({
      aUnit: 'chars',
      bUnit: 'tokens',
      aAvg: 100,
      bAvg: 7,
      aP95: 120,
      bP95: 9,
      deltaAvg: null,
      deltaP10: null,
      deltaP95: null,
      deltaCoverage: 0.25,
    })
  })

  it('keeps complete Unicode characters in comparison examples', () => {
    const content = `${'a'.repeat(159)}😀tail`
    const result = computeChunkPreviewDiff(preview([]), preview([content]))
    expect(result.examplesAdded[0].example).toBe(`${'a'.repeat(159)}😀`)
  })

  it('emphasizes the whole changed emoji instead of dividing its surrogate pair', () => {
    const result = buildSemanticEvidenceHighlights({
      examplesAdded: [{ example: 'A😀tail', count: 1, index: 0 }],
      examplesRemoved: [{ example: 'A😁tail', count: 1, index: 0 }],
    })
    expect(result.added[0].segments).toEqual([
      { text: 'A', emphasis: false },
      { text: '😀', emphasis: true },
      { text: 'tail', emphasis: false },
    ])
  })

  it('reports different content even when the old hash collides', () => {
    const result = computeChunkPreviewDiff(preview(['costarring']), preview(['liquid']))
    expect(result).toMatchObject({ added: 1, removed: 1, overlap: 0 })
    expect(result.examplesAdded).toEqual([{ example: 'liquid', count: 1, index: 0 }])
    expect(result.examplesRemoved).toEqual([{ example: 'costarring', count: 1, index: 0 }])
  })

  it('retains the current outer-whitespace comparison and actual multiplicities without changing input', () => {
    const baseline = preview(['  same\n', 'same'])
    const current = preview(['same', '  added\n'])
    expect(computeChunkPreviewDiff(baseline, current)).toMatchObject({ added: 1, removed: 1, overlap: 1 / 3 })
    expect(baseline.chunks.map((chunk) => chunk.content)).toEqual(['  same\n', 'same'])
    expect(current.chunks.map((chunk) => chunk.content)).toEqual(['same', '  added\n'])
  })
})
