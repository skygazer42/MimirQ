import { describe, expect, it } from 'vitest'

import {
  buildGraphViewportLod,
  createGraphSpatialIndex,
  getGraphViewportTier,
  type GraphViewportRect,
} from './graph-viewport-lod'

const VIEWPORT: GraphViewportRect = {
  minX: -10,
  minY: -10,
  maxX: 10,
  maxY: 10,
}

describe('graph viewport LOD', () => {
  it('queries positioned nodes through a bounded spatial index', () => {
    const index = createGraphSpatialIndex([
      { id: 'inside-a', x: -2, y: 3 },
      { id: 'inside-b', x: 8, y: -4 },
      { id: 'outside', x: 32, y: 32 },
      { id: 'missing-position' },
    ])

    expect(index.query(VIEWPORT).map((node) => String(node.id)).sort((a, b) => a.localeCompare(b))).toEqual(['inside-a', 'inside-b'])
    expect(index.nearest({ x: 9, y: -5 })?.id).toBe('inside-b')
  })

  it('keeps only visible nodes and their links in large graph overview mode', () => {
    const nodes = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 8, y: 0 },
      { id: 'c', x: 40, y: 0 },
      { id: 'd', x: 80, y: 0 },
    ]
    const links = [
      { id: 'ab', source: 'a', target: 'b' },
      { id: 'bc', source: 'b', target: 'c' },
      { id: 'cd', source: 'c', target: 'd' },
    ]

    const lod = buildGraphViewportLod({
      nodes,
      links,
      viewport: VIEWPORT,
      globalScale: 0.25,
      totalNodeCount: 5000,
      maxOverviewNodes: 2,
    })

    expect(lod.tier).toBe('overview')
    expect(Array.from(lod.visibleNodeIds).sort((a, b) => a.localeCompare(b))).toEqual(['a', 'b'])
    expect(Array.from(lod.visibleLinkIds)).toEqual(['ab'])
    expect(lod.hiddenNodeCount).toBe(2)
    expect(lod.hiddenLinkCount).toBe(2)
  })

  it('switches from overview to detail when zoomed in or graph is small', () => {
    expect(getGraphViewportTier({ globalScale: 0.25, totalNodeCount: 5000 })).toBe('overview')
    expect(getGraphViewportTier({ globalScale: 0.8, totalNodeCount: 5000 })).toBe('balanced')
    expect(getGraphViewportTier({ globalScale: 2, totalNodeCount: 5000 })).toBe('detail')
    expect(getGraphViewportTier({ globalScale: 0.25, totalNodeCount: 50 })).toBe('detail')
  })
})
