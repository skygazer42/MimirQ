import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('pdf viewer source', () => {
  it('passes explicit OffscreenCanvas and hardware-acceleration hints into pdf.js loading', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('FeatureTest.isOffscreenCanvasSupported')
    expect(src).toContain('isOffscreenCanvasSupported: offscreenCanvasSupported')
    expect(src).toContain('enableHWA: offscreenCanvasSupported')
    expect(src).toContain('pdfjsLib.getDocument({')
    expect(src).not.toContain('const doc = await pdfjsLib.getDocument({ data }).promise')
  })

  it('accepts optional precomputed page box groups instead of always recomputing them from blocks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('boxesByPage?: Map<number, Box[]> | null')
    expect(src).toContain('const resolvedBoxesByPage = useMemo(() =>')
    expect(src).toContain('if (boxesByPage) return boxesByPage')
    expect(src).toContain('const pageBoxes = resolvedBoxesByPage.get(index) || []')
  })

  it('accepts optional precomputed block-to-page lookups for active scroll positioning', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('blockIdToPageIndex?: Map<string, number> | null')
    expect(src).toContain('const resolvedBlockIdToPageIndex = useMemo(() =>')
    expect(src).toContain('if (blockIdToPageIndex) return blockIdToPageIndex')
    expect(src).toContain('const pageIndex = resolvedBlockIdToPageIndex.get(firstActive)')
  })

  it('cancels stale render tasks and cleans up page resources after rendering', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('type { PDFDocumentProxy, RenderTask }')
    expect(src).toContain('const renderTasksRef = useRef<Map<number, RenderTask>>(new Map())')
    expect(src).toContain('renderTasksRef.current.forEach((task) => task.cancel())')
    expect(src).toContain('renderTasksRef.current.clear()')
    expect(src).toContain('const renderTask = page.render({ canvas, viewport })')
    expect(src).toContain('renderTasksRef.current.set(pageIndex, renderTask)')
    expect(src).toContain('await renderTask.promise')
    expect(src).toContain('page.cleanup()')
  })

  it('tracks rendered pages in a ref so viewport observers do not churn on every render', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('const renderedPagesRef = useRef<Set<number>>(new Set())')
    expect(src).toContain('if (renderedPagesRef.current.has(pageIndex)) return')
    expect(src).toContain('renderedPagesRef.current = new Set()')
    expect(src).toContain('renderedPagesRef.current = next')
    expect(src).toContain('[pdfDoc, pageCount, scale]')
    expect(src).not.toContain('[pdfDoc, pageCount, renderedPages, scale]')
  })
})
