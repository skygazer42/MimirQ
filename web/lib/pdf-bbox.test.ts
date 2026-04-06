import { describe, expect, it } from 'vitest'

import { computePdfOverlayRect, detectPdfBboxCoordinateSpace } from './pdf-bbox'

describe('pdf-bbox', () => {
  it('keeps absolute PDF-point coordinates on the legacy scale path', () => {
    const space = detectPdfBboxCoordinateSpace({
      items: [{ position: { pages: [0], left: 151, right: 442, top: 103, bottom: 121, raw: '@@1' } }],
      pageBaseWidth: 612,
      pageBaseHeight: 792,
    })

    expect(space).toBe('absolute')
    const rect = computePdfOverlayRect({
      position: { pages: [0], left: 151, right: 442, top: 103, bottom: 121, raw: '@@1' },
      scale: 1.5,
      pageBaseWidth: 612,
      pageBaseHeight: 792,
      coordinateSpace: space,
    })

    expect(rect.left).toBeCloseTo(226.5)
    expect(rect.top).toBeCloseTo(154.5)
    expect(rect.width).toBeCloseTo(436.5)
    expect(rect.height).toBeCloseTo(27)
  })

  it('detects legacy 0..1000 MinerU coordinates and maps them into the rendered page box', () => {
    const space = detectPdfBboxCoordinateSpace({
      items: [{ position: { pages: [0], left: 246, right: 722, top: 130, bottom: 152, raw: '@@1' } }],
      pageBaseWidth: 612,
      pageBaseHeight: 792,
    })

    expect(space).toBe('normalized-1000')
    const rect = computePdfOverlayRect({
      position: { pages: [0], left: 246, right: 722, top: 130, bottom: 152, raw: '@@1' },
      scale: 1,
      pageBaseWidth: 612,
      pageBaseHeight: 792,
      coordinateSpace: space,
    })

    expect(rect.left).toBeCloseTo(150.552)
    expect(rect.top).toBeCloseTo(102.96)
    expect(rect.width).toBeCloseTo(291.312)
    expect(rect.height).toBeCloseTo(17.424)
  })
})
