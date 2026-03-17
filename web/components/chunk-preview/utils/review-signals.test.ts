import { describe, expect, it } from 'vitest'
import type { ChunkPreviewItem } from '@/types'
import { computeCoverageSignals, computeDuplicateIndices, computeHierarchyReviewSignals, computeShortIndices } from './review-signals'

function chunk(
  index: number,
  start: number,
  end: number,
  content: string,
  meta?: Record<string, any>
): ChunkPreviewItem {
  return {
    index,
    content,
    length: content.length,
    tokens_est: Math.max(1, Math.ceil(content.length / 4)),
    start_index: start,
    end_index: end,
    page_number: 1,
    metadata: meta || {},
  }
}

describe('review-signals', () => {
  it('computeDuplicateIndices flags duplicates by trimmed content', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 0, 10, ' hello '),
      chunk(1, 10, 20, 'world'),
      chunk(2, 20, 30, 'hello'),
    ]
    const d = computeDuplicateIndices(chunks)
    expect(Array.from(d).sort((a, b) => a - b)).toEqual([0, 2])
  })

  it('computeShortIndices uses threshold per unit', () => {
    const a = chunk(0, 0, 10, 'x'.repeat(50))
    const b = chunk(1, 10, 20, 'y'.repeat(200))

    // chars: threshold=120 -> chunk 0 is short, chunk 1 is not.
    expect(Array.from(computeShortIndices([a, b], 'chars')).sort((x, y) => x - y)).toEqual([0])

    // tokens: threshold=40 -> use tokens_est.
    // 50 chars -> tokens_est ~ 13; 200 chars -> tokens_est ~ 50
    expect(Array.from(computeShortIndices([a, b], 'tokens')).sort((x, y) => x - y)).toEqual([0])
  })

  it('computeCoverageSignals detects gaps', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 0, 100, 'a'.repeat(200)),
      chunk(1, 150, 200, 'b'.repeat(200)),
    ]
    const s = computeCoverageSignals(chunks)
    expect(s.basis).toBe('all')
    expect(Array.from(s.gapIndices)).toEqual([1])
    expect(s.gapBeforeByIndex.get(1)).toBe(50)
  })

  it('computeCoverageSignals detects high overlaps (ratio >= 0.6)', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 0, 200, 'a'.repeat(200)),
      chunk(1, 50, 250, 'b'.repeat(200)),
    ]
    const s = computeCoverageSignals(chunks)
    expect(Array.from(s.overlapIndices)).toEqual([1])
    expect(s.overlapPrevByIndex.get(1)).toBe(150)
  })

  it('computeCoverageSignals flags any overlap for separator strategy (strict no-overlap)', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 0, 10, 'a'.repeat(200)),
      chunk(1, 9, 19, 'b'.repeat(200)),
    ]
    const s = computeCoverageSignals(chunks, { strategy: 'separator' })
    expect(Array.from(s.overlapIndices)).toEqual([1])
    expect(s.overlapPrevByIndex.get(1)).toBe(1)
  })

  it('computeCoverageSignals uses child-only basis for parent_child when children exist', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 0, 200, 'p'.repeat(200), { chunk_role: 'parent', parent_id: 'p1' }),
      chunk(1, 50, 150, 'c'.repeat(200), { chunk_role: 'child', parent_id: 'p1' }),
    ]
    const s = computeCoverageSignals(chunks, { strategy: 'parent_child' })
    expect(s.basis).toBe('child')
    // With only child coverage, there is a gap before the child.
    expect(Array.from(s.gapIndices)).toEqual([1])
    expect(s.gapBeforeByIndex.get(1)).toBe(50)
  })

  it('computeHierarchyReviewSignals stays inactive when no hierarchy metadata is present', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 0, 10, 'a'.repeat(50)),
      chunk(1, 10, 20, 'b'.repeat(50)),
    ]
    const s = computeHierarchyReviewSignals(chunks)
    expect(s.active).toBe(false)
    expect(Array.from(s.missingNodeKeyIndices)).toEqual([])
    expect(Array.from(s.missingFamilyKeyIndices)).toEqual([])
    expect(Array.from(s.missingPrevSiblingIndices)).toEqual([])
    expect(Array.from(s.missingNextSiblingIndices)).toEqual([])
  })

  it('computeHierarchyReviewSignals flags missing family keys when partially present', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 0, 10, 'a'.repeat(50), { hierarchy_node_key: 'n0', hierarchy_family_key: 'f' }),
      chunk(1, 10, 20, 'b'.repeat(50), { hierarchy_node_key: 'n1' }),
      chunk(2, 20, 30, 'c'.repeat(50), { hierarchy_node_key: 'n2', hierarchy_family_key: 'f' }),
    ]
    const s = computeHierarchyReviewSignals(chunks)
    expect(s.active).toBe(true)
    expect(Array.from(s.missingNodeKeyIndices)).toEqual([])
    expect(Array.from(s.missingFamilyKeyIndices).sort((a, b) => a - b)).toEqual([1])
  })

  it('computeHierarchyReviewSignals flags missing sibling links for middle chunks', () => {
    const chunks: ChunkPreviewItem[] = [
      chunk(0, 0, 10, 'a'.repeat(50), {
        hierarchy_node_key: 'n0',
        hierarchy_family_key: 'f',
        hierarchy_next_sibling_key: 'n1',
      }),
      chunk(1, 10, 20, 'b'.repeat(50), {
        hierarchy_node_key: 'n1',
        hierarchy_family_key: 'f',
        hierarchy_prev_sibling_key: 'n0',
        // missing next
      }),
      chunk(2, 20, 30, 'c'.repeat(50), {
        hierarchy_node_key: 'n2',
        hierarchy_family_key: 'f',
        hierarchy_prev_sibling_key: 'n1',
      }),
    ]
    const s = computeHierarchyReviewSignals(chunks)
    expect(s.active).toBe(true)
    expect(Array.from(s.missingPrevSiblingIndices)).toEqual([])
    expect(Array.from(s.missingNextSiblingIndices).sort((a, b) => a - b)).toEqual([1])
  })
})
