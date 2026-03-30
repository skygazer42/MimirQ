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

  it('releases main-thread page resources after raster work completes even when worker rendering is available', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('let releasePageResources: (() => void) | null = null')

    const renderTaskIndex = src.indexOf('const renderTask = page.render({ canvas, viewport })')
    const renderPromiseIndex = src.indexOf('await renderTask.promise', renderTaskIndex)
    const releaseIndex = src.indexOf('releasePageResources?.()', renderPromiseIndex)

    expect(renderTaskIndex).toBeGreaterThan(-1)
    expect(renderPromiseIndex).toBeGreaterThan(renderTaskIndex)
    expect(releaseIndex).toBeGreaterThan(renderPromiseIndex)
  })

  it('tracks rendered pages in a ref so viewport observers do not churn on every render', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('const renderedPagesRef = useRef<Set<number>>(new Set())')
    expect(src).toContain('if (renderedPagesRef.current.has(pageIndex)) return')
    expect(src).toContain('renderedPagesRef.current = new Set()')
    expect(src).toContain('renderedPagesRef.current = next')
    expect(src).toContain('[attachOffscreenPageCanvas, offscreenRenderEnabled, pdfDoc, pageCount, rememberPageAspectRatio, scale]')
    expect(src).not.toContain('[pdfDoc, pageCount, renderedPages, scale]')
  })

  it('queues viewport-triggered page renders behind idle scheduling instead of rendering every page immediately', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('requestIdleCallback')
    expect(src).toContain('const queuedPagesRef = useRef<Set<number>>(new Set())')
    expect(src).toContain('const queuePageRender = useCallback(')
    expect(src).toContain('queuedPagesRef.current.add(pageIndex)')
    expect(src).toContain('flushQueuedPageRendersRef')
    expect(src).toContain('detachPromise(flushQueuedPageRendersRef.current())')
    expect(src).not.toContain('detachPromise(renderPage(idx))')
    expect(src).not.toContain('detachPromise(renderPage(0))')
  })

  it('releases far-off pages while preserving intrinsic page size hints for long PDFs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('const releasePage = useCallback(')
    expect(src).toContain('canvas.width = 0')
    expect(src).toContain('canvas.height = 0')
    expect(src).toContain("contentVisibility: 'auto'")
    expect(src).toContain('containIntrinsicSize')
    expect(src).toContain('releasePage(idx)')
  })

  it('can hand page raster work to a dedicated OffscreenCanvas render worker when the browser supports it', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain("new URL('../../workers/pdf-page-render.worker.ts', import.meta.url)")
    expect(src).toContain('transferControlToOffscreen')
    expect(src).toContain('setOffscreenRenderEnabled(true)')
    expect(src).toContain('await api.attachPageCanvas(')
    expect(src).toContain('await api.renderPage({')
    expect(src).toContain('offscreenApi.releasePage(pageIndex)')
  })
})
