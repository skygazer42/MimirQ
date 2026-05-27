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

  it('loads pdf.js from public runtime assets instead of bundling pdfjs-dist into the Next.js client build', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain("'/pdfjs/build/pdf.mjs'")
    expect(src).toContain("'/pdfjs-compat/pdf.worker.mjs'")
    expect(src).toContain('webpackIgnore: true')
    expect(src).toContain('GlobalWorkerOptions.workerSrc')
    expect(src).not.toContain("import('pdfjs-dist/webpack.mjs')")
  })

  it('installs runtime polyfills before loading the pdf.js ESM bundle and worker', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')
    const workerSrc = fs.readFileSync(path.resolve(__dirname, '../../public/pdfjs-compat/pdf.worker.mjs'), 'utf8')

    expect(src).toContain('function installPdfJsCompatPolyfills()')
    expect(src).toContain("typeof promiseCtor.withResolvers !== 'function'")
    expect(src).toContain("typeof mapPrototype.getOrInsertComputed !== 'function'")
    expect(src).toContain('installPdfJsCompatPolyfills()')
    expect(workerSrc).toContain('function installPdfJsCompatPolyfills()')
    expect(workerSrc).toContain("typeof Promise.withResolvers !== 'function'")
    expect(workerSrc).toContain("typeof Map.prototype.getOrInsertComputed !== 'function'")
    expect(workerSrc).toContain("await import('../pdfjs/build/pdf.worker.mjs')")
  })

  it('disables OffscreenCanvas worker page rasterization and keeps rendering on the main thread', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('const ENABLE_PDF_OFFSCREEN_RENDER = false')
    expect(src).toContain('return ENABLE_PDF_OFFSCREEN_RENDER && (')
    expect(src).not.toContain('setOffscreenRenderEnabled(true)')
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

  it('centers the active layout box instead of only scrolling to the PDF page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('computePdfOverlayScrollTop')
    expect(src).toContain('const targetBox = pageBoxes.find((box) => box.id === firstActive)')
    expect(src).toContain('container.scrollTo({')
    expect(src).toContain('top: computePdfOverlayScrollTop({')
    expect(src).toContain('overlayTop: rect.top')
    expect(src).toContain('overlayHeight: rect.height')
  })

  it('cancels stale render tasks and cleans up page resources after rendering', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('type { PDFDocumentProxy, RenderTask }')
    expect(src).toContain('const renderTasksRef = useRef<Map<number, RenderTask>>(new Map())')
    expect(src).toContain('renderTasksRef.current.forEach((task) => task.cancel())')
    expect(src).toContain('renderTasksRef.current.clear()')
    expect(src).toContain("const canvasContext = canvas.getContext('2d', { alpha: false })")
    expect(src).toContain("const renderTask = page.render({ canvas: null, canvasContext, viewport, background: '#ffffff' })")
    expect(src).toContain('renderTasksRef.current.set(pageIndex, renderTask)')
    expect(src).toContain('await renderTask.promise')
    expect(src).toContain('page.cleanup()')
  })

  it('releases main-thread page resources after raster work completes even when worker rendering is available', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('let releasePageResources: (() => void) | null = null')

    const renderTaskIndex = src.indexOf("const renderTask = page.render({ canvas: null, canvasContext, viewport, background: '#ffffff' })")
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
    expect(src).toContain('markPageRendered')
    expect(src).toContain('trimRenderedPagePool')
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
    expect(src).toContain('const INITIAL_PDF_PAGE_PRERENDER_COUNT = 3')
    expect(src).toContain('for (let pageIndex = 0; pageIndex < Math.min(totalPages, INITIAL_PDF_PAGE_PRERENDER_COUNT); pageIndex += 1)')
    expect(src).toContain('}, [pageCount, pdfDoc, queuePageRender, scale])')
    expect(src).not.toContain('detachPromise(renderPage(idx))')
    expect(src).not.toContain('detachPromise(renderPage(0))')

    const prerenderLoopIndex = src.indexOf(
      'for (let pageIndex = 0; pageIndex < Math.min(totalPages, INITIAL_PDF_PAGE_PRERENDER_COUNT); pageIndex += 1)'
    )
    const immediateFlushIndex = src.indexOf('detachPromise(flushQueuedPageRendersRef.current())', prerenderLoopIndex)
    const effectReturnIndex = src.indexOf('return () => {', prerenderLoopIndex)

    expect(prerenderLoopIndex).toBeGreaterThan(-1)
    expect(immediateFlushIndex).toBeGreaterThan(prerenderLoopIndex)
    expect(effectReturnIndex).toBeGreaterThan(immediateFlushIndex)
  })

  it('distinguishes actively rendering pages from offscreen pages that are merely waiting to lazy-load', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('const [loadingPages, setLoadingPages] = useState<Set<number>>(new Set())')
    expect(src).toContain('const isPageLoading = loadingPages.has(index)')
    expect(src).toContain("isPageLoading ? '渲染中...' : '滚动后加载...'")
  })

  it('uses responsive page placeholders instead of fixed-width intrinsic-size hints that can hide the first visible PDF page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('const pageStyle = pageAspectRatio')
    expect(src).toContain("minHeight: DEFAULT_PAGE_PLACEHOLDER_HEIGHT")
    expect(src).toContain("aspectRatio: String(pageAspectRatio)")
    expect(src).not.toContain('const DEFAULT_PAGE_CSS_WIDTH = 896')
    expect(src).not.toContain('getPagePlaceholderHeight(')
    expect(src).not.toContain("contentVisibility: 'auto'")
    expect(src).not.toContain('containIntrinsicSize')
  })

  it('does not let the retention observer cancel pages that have not rendered yet', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('if (!renderedPagesRef.current.has(idx)) continue')
    expect(src).toContain('releasePage(idx)')
  })

  it('resets the PDF scroll container to the first page when the active file changes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('containerRef.current?.scrollTo({ top: 0 })')
    expect(src).toContain('}, [file, fileUrl, reloadTick])')
  })

  it('bounds retained rasterized pages behind an explicit canvas pool budget', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain("from '@/components/parsing/pdf-render-canvas-pool'")
    expect(src).toContain('const retainedPageIndicesRef = useRef<Set<number>>(new Set())')
    expect(src).toContain('const trimRenderedPagePool = useCallback(')
    expect(src).toContain('selectPdfPagesToReleaseForPool({')
    expect(src).toContain('maxRetainedPages: MAX_RETAINED_PAGE_CANVASES')
    expect(src).toContain('retainedPages: retainedPageIndicesRef.current')
    expect(src).toContain('queuedPages: queuedPagesRef.current')
    expect(src).toContain('renderingPages: renderingPagesRef.current')
    expect(src).toContain('releasePage(stalePageIndex)')
    expect(src).toContain('trimRenderedPagePool(pageIndex)')
  })

  it('retries initial page renders when the canvas is not ready or a first-pass raster attempt fails', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('const MAIN_THREAD_PAGE_RENDER_TIMEOUT_MS = 12_000')
    expect(src).toContain('const MAX_PAGE_RENDER_RETRIES = 3')
    expect(src).toContain('const PAGE_RENDER_RETRY_DELAY_MS = 150')
    expect(src).toContain('const pageRenderRetryCountsRef = useRef<Map<number, number>>(new Map())')
    expect(src).toContain('const pageRenderRetryTimeoutsRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())')
    expect(src).toContain('const schedulePageRenderRetry = useCallback(')
    expect(src).toContain('if (!canvas) {')
    expect(src).toContain("if (!canvasContext) {")
    expect(src).toContain('schedulePageRenderRetry(pageIndex)')
    expect(src).toContain('queuePageRender(pageIndex)')
    expect(src).toContain('detachPromise(flushQueuedPageRendersRef.current())')
    expect(src).toContain('await Promise.race([')
    expect(src).toContain('await renderTask.promise')
    expect(src).toContain('reject(new Error(`Main-thread render timed out for page ${pageIndex + 1}`))')
    expect(src).toContain('renderTask.cancel()')
    expect(src).toContain('pageRenderRetryCountsRef.current.delete(pageIndex)')
    expect(src).toContain('pageRenderRetryTimeoutsRef.current.forEach((timeoutId) => clearTimeout(timeoutId))')
  })

  it('keeps probing stalled first-page renders and surfaces an explicit retry action instead of leaving the placeholder stuck forever', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('const FIRST_PAGE_RENDER_WATCHDOG_INTERVAL_MS = 1_500')
    expect(src).toContain('const [failedPages, setFailedPages] = useState<Set<number>>(new Set())')
    expect(src).toContain('const markPageFailed = useCallback(')
    expect(src).toContain('const clearPageFailure = useCallback(')
    expect(src).toContain('const retryPageRender = useCallback(')
    expect(src).toContain('setInterval(() => {')
    expect(src).toContain('retryPageRender(pageIndex)')
    expect(src).toContain('const isPageFailed = failedPages.has(index)')
    expect(src).toContain("'渲染失败，点击重试'")
    expect(src).not.toContain("{isPageLoading ? '渲染中...' : '滚动后加载...'}")
  })

  it('publishes a development-only PDF viewer debug snapshot so stuck page state can be inspected from the browser console', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain("process.env.NODE_ENV !== 'development'")
    expect(src).toContain('__mimirqPdfViewerDebug')
    expect(src).toContain('activeRenderCount: activeRenderCountRef.current')
    expect(src).toContain('pageErrors: Object.fromEntries(pageRenderErrorsRef.current.entries())')
    expect(src).toContain('queuedPages: Array.from(queuedPagesRef.current)')
    expect(src).toContain('renderingPages: Array.from(renderingPagesRef.current)')
    expect(src).toContain('retryCounts: Object.fromEntries(pageRenderRetryCountsRef.current.entries())')
    expect(src).toContain('delete win.__mimirqPdfViewerDebug')
  })

  it('can load a remote/blob URL source for document-viewer citation overlays', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('fileUrl?: string | null')
    expect(src).toContain('const hasSource = Boolean(file || fileUrl)')
    expect(src).toContain('fetch(fileUrl')
    expect(src).toContain('}, [cancelRenderTasks, file, fileUrl, hasSource, reloadTick])')
  })

  it('can scroll to a citation page without relying on browser PDF iframe fragments', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-viewer.tsx'), 'utf8')

    expect(src).toContain('scrollToPageIndex?: number | null')
    expect(src).toContain('typeof scrollToPageIndex ===')
    expect(src).toContain('Math.trunc(scrollToPageIndex)')
    expect(src).toContain('el.offsetTop - 24')
    expect(src).toContain('}, [pageCount, scrollToPageIndex])')
  })
})
