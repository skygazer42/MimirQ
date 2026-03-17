import { describe, expect, it } from 'vitest'

import { decorateLinksForDisplay } from './graph-edge-display'

describe('decorateLinksForDisplay', () => {
  it('spreads parallel edges deterministically via curvature', () => {
    const links = [
      { source: 'A', target: 'B', label: 'owns' },
      { source: 'A', target: 'B', label: 'mentions' },
      { source: 'B', target: 'A', label: 'related_to' },
    ]

    const out = decorateLinksForDisplay(structuredClone(links))
    const curvatures = out.map((l: any) => l.curvature)

    expect(curvatures.every((v) => typeof v === 'number')).toBe(true)
    expect(new Set(curvatures).size).toBe(3)

    // Calling twice should be stable.
    const out2 = decorateLinksForDisplay(structuredClone(links))
    expect(out2.map((l: any) => l.curvature)).toEqual(curvatures)
  })

  it('renders self-loops as loops with distinct rotations when there are multiple', () => {
    const links = [
      { source: 'A', target: 'A', label: 'self_1' },
      { source: 'A', target: 'A', label: 'self_2' },
      { source: 'A', target: 'A', label: 'self_3' },
    ]

    const out = decorateLinksForDisplay(structuredClone(links))
    const curvatures = out.map((l: any) => l.curvature)
    const rotations = out.map((l: any) => l.curveRotation)

    expect(curvatures.every((v) => typeof v === 'number' && v > 0)).toBe(true)
    expect(rotations.every((v) => typeof v === 'number')).toBe(true)
    expect(new Set(rotations).size).toBe(3)
  })

  it('handles empty or missing endpoint ids without throwing', () => {
    const links = [
      { source: null, target: null, label: 'x' },
      { source: { id: 'A' }, target: { id: 'B' }, label: 'y' },
    ]

    const out = decorateLinksForDisplay(structuredClone(links))
    expect(out).toHaveLength(2)
    expect(typeof (out[0] as any).curvature).toBe('number')
    expect(typeof (out[1] as any).curvature).toBe('number')
  })
})

