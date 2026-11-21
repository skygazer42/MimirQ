/**
 * PdfViewer - render PDF pages with optional layout box overlays.
 */
'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, ChevronLeft, ChevronRight, FileText, RotateCcw } from '@/components/icons'
import type { PDFDocumentLoadingTask, PDFDocumentProxy, PDFPageProxy, RenderTask } from 'pdfjs-dist'
import type { ParsingEditFocusHint } from '@/lib/parsing-edit-focus'
import { computePdfOverlayRect, computePdfOverlayScrollTop, detectPdfBboxCoordinateSpace } from '@/lib/pdf-bbox'
import { toPrimitiveString } from '@/lib/primitive-text'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { ParsingPosition } from '@/lib/parsing-positions'
import { BboxOverlay, type BboxOverlayItem } from '@/components/parsing/bbox-overlay'
import { reportClientWarning } from '@/lib/client-logging'
import { selectPdfPagesToReleaseForPool, selectPdfPagesToRender } from './pdf-render-canvas-pool'
import { getPdfSource, loadPdfJsModule, readPdfSourceData, type PdfSource } from '@/lib/pdf-source'

type Box = BboxOverlayItem
type PageBaseSize = { width: number; height: number }

type PdfViewerProps = {
  showToolbar?: boolean
  file?: File | null
  fileUrl?: string | null
  scrollToPageIndex?: number | null
  boxesByPage?: ReadonlyMap<number, readonly Box[]> | null
  blockIdToPageIndex?: ReadonlyMap<string, number> | null
  activeBlockIds?: readonly string[] | null
  hoveredBlockIds?: readonly string[] | null
  showAllBoxes?: boolean
  onHoverBlockId?: (blockId: string | null) => void
  onClickBlockId?: (blockId: string, hint?: ParsingEditFocusHint) => void
}

type IdleGlobal = typeof globalThis & {
  requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => number
  cancelIdleCallback?: (id: number) => void
}

const IDLE_RENDER_TIMEOUT_MS = 400
const MAIN_THREAD_PAGE_RENDER_TIMEOUT_MS = 12_000
const DEFAULT_PAGE_PLACEHOLDER_HEIGHT = '520px'
const MAX_PAGE_RENDER_RETRIES = 3
const PAGE_RENDER_RETRY_DELAY_MS = 150
const PDFJS_CMAPS_URL = '/pdfjs/cmaps/'
const PDFJS_STANDARD_FONTS_URL = '/pdfjs/standard_fonts/'
const PDFJS_WASM_URL = '/pdfjs/wasm/'
const PDFJS_ICCS_URL = '/pdfjs/iccs/'

function findNearestScrollableAncestor(container: HTMLElement): HTMLElement | null {
  let node = container.parentElement
  while (node) {
    if (node === globalThis.document.body || node === globalThis.document.documentElement) return null

    const style = globalThis.window.getComputedStyle(node)
    const canScrollY =
      (style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflowY === 'overlay') &&
      node.scrollHeight > node.clientHeight + 1
    if (canScrollY) return node

    node = node.parentElement
  }

  return null
}

type ScrollPdfPageIntoElementOptions = {
  behavior: ScrollBehavior
  scrollElement: HTMLElement
  targetElement: HTMLElement
}

function scrollPdfPageIntoElement({ behavior, scrollElement, targetElement }: ScrollPdfPageIntoElementOptions) {
  const scrollRect = scrollElement.getBoundingClientRect()
  const targetRect = targetElement.getBoundingClientRect()
  const centeredTop =
    scrollElement.scrollTop +
    targetRect.top -
    scrollRect.top -
    Math.max(24, Math.floor((scrollElement.clientHeight - targetRect.height) / 2))

  scrollElement.scrollTo({
    behavior,
    top: Math.max(0, centeredTop),
  })
}

type ScrollPdfOverlayIntoElementOptions = {
  behavior: ScrollBehavior
  overlayHeight: number
  overlayTop: number
  pageElement: HTMLElement
  scrollElement: HTMLElement
}

function scrollPdfOverlayIntoElement({
  behavior,
  overlayHeight,
  overlayTop,
  pageElement,
  scrollElement,
}: ScrollPdfOverlayIntoElementOptions) {
  const scrollRect = scrollElement.getBoundingClientRect()
  const pageRect = pageElement.getBoundingClientRect()
  scrollElement.scrollTo({
    behavior,
    top: computePdfOverlayScrollTop({
      containerHeight: scrollElement.clientHeight,
      containerScrollTop: scrollElement.scrollTop,
      containerTop: scrollRect.top,
      overlayHeight,
      overlayTop,
      pageTop: pageRect.top,
    }),
  })
}

type PdfPagesProps = Omit<PdfViewerProps, 'file' | 'fileUrl'> & {
  pdfDoc: PDFDocumentProxy
}

type PdfLoadResult = Readonly<
  { source: PdfSource; requestRevision: number } & (
    { status: 'ready'; document: PDFDocumentProxy } | { status: 'error'; message: string }
  )
>

export function PdfViewer({ file, fileUrl, ...pageProps }: Readonly<PdfViewerProps>) {
  const source = getPdfSource(file, fileUrl)
  const [reloadRequest, setReloadRequest] = useState(0)
  const [loadResult, setLoadResult] = useState<PdfLoadResult | null>(null)
  const currentLoadResult =
    loadResult?.source === source && loadResult.requestRevision === reloadRequest ? loadResult : null

  useEffect(() => {
    setLoadResult(null)
    if (source === null) return
    const controller = new AbortController()
    let loadingTask: PDFDocumentLoadingTask | null = null

    function releaseLoadingTask() {
      const task = loadingTask
      loadingTask = null
      if (task !== null) {
        void task.destroy().catch((error: unknown) => reportClientWarning('PDF loading task cleanup failed', error))
      }
    }

    async function loadPdf(selectedSource: PdfSource) {
      try {
        const data = await readPdfSourceData(selectedSource, controller.signal)
        controller.signal.throwIfAborted()
        const pdfjsLib = await loadPdfJsModule()
        controller.signal.throwIfAborted()
        const offscreenCanvasSupported = pdfjsLib.FeatureTest.isOffscreenCanvasSupported
        loadingTask = pdfjsLib.getDocument({
          data,
          isOffscreenCanvasSupported: offscreenCanvasSupported,
          enableHWA: offscreenCanvasSupported,
          cMapUrl: PDFJS_CMAPS_URL,
          standardFontDataUrl: PDFJS_STANDARD_FONTS_URL,
          wasmUrl: PDFJS_WASM_URL,
          iccUrl: PDFJS_ICCS_URL,
        })
        const document = await loadingTask.promise
        if (!controller.signal.aborted) {
          setLoadResult({ source: selectedSource, requestRevision: reloadRequest, status: 'ready', document })
        }
      } catch (error: unknown) {
        if (!controller.signal.aborted) {
          const message = error instanceof Error ? error.message : toPrimitiveString(error)
          setLoadResult({ source: selectedSource, requestRevision: reloadRequest, status: 'error', message })
        }
        releaseLoadingTask()
      }
    }

    void loadPdf(source)
    return () => {
      controller.abort()
      releaseLoadingTask()
    }
  }, [source, reloadRequest])

  if (source === null) {
    return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">未选择 PDF</div>
  }
  if (currentLoadResult === null) return <PdfViewerLoading showToolbar={pageProps.showToolbar === true} />
  if (currentLoadResult.status === 'error') {
    return (
      <div className="flex h-full items-center justify-center px-6">
        <div className="max-w-md rounded-2xl border border-border/60 bg-card p-5 text-center shadow-sm">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
            <AlertCircle className="h-5 w-5" />
          </div>
          <div role="alert">
            <div className="text-sm font-semibold text-foreground">PDF 加载失败</div>
            <div className="mt-1 text-xs text-muted-foreground">{currentLoadResult.message}</div>
          </div>
          <div className="mt-4 flex justify-center">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setReloadRequest((request) => request + 1)}
            >
              <RotateCcw className="h-4 w-4" />
              重试
            </Button>
          </div>
        </div>
      </div>
    )
  }
  return <PdfPages {...pageProps} pdfDoc={currentLoadResult.document} />
}

function PdfViewerLoading({ showToolbar }: Readonly<{ showToolbar: boolean }>) {
  return (
    <div role="status" aria-label="正在加载 PDF" className="flex h-full min-h-0 flex-col">
      {showToolbar ? (
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background/60 px-5 text-[13px]">
          <FileText className="size-3.5 text-muted-foreground" />
          <span>原文 PDF</span>
          <span className="ml-auto text-xs text-muted-foreground">正在读取…</span>
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-hidden px-5 py-7">
        <Skeleton className="mx-auto h-64 max-h-full w-full max-w-4xl" />
      </div>
    </div>
  )
}

type PdfZoom = 'fit' | '100' | '150' | '200'
type PdfPageState = Readonly<{ status: 'queued' | 'processing' | 'ready' } | { status: 'error'; message: string }>
type PdfRenderJob = { readonly pageIndex: number; task: RenderTask | null }
type PdfScheduledWork = Readonly<{ cancel: () => void }>
type PdfNavigationTarget =
  | Readonly<{ kind: 'page'; key: string; pageIndex: number }>
  | Readonly<{ kind: 'block-page'; key: string; pageIndex: number; blockId: string }>
  | Readonly<{
      kind: 'box'
      key: string
      pageIndex: number
      blockId: string
      position: ParsingPosition
      pageBoxes: readonly Box[]
    }>

function isPdfPageIndex(index: number | null | undefined, pageCount: number): index is number {
  return index !== null && index !== undefined && Number.isInteger(index) && index >= 0 && index < pageCount
}

function getPdfNavigationTarget({
  activeBlockIds,
  blockIdToPageIndex,
  boxesByPage,
  scrollToPageIndex,
  pageCount,
}: Pick<PdfViewerProps, 'activeBlockIds' | 'blockIdToPageIndex' | 'boxesByPage' | 'scrollToPageIndex'> & {
  pageCount: number
}): PdfNavigationTarget | null {
  const blockId = activeBlockIds?.[0]
  if (blockId !== undefined) {
    const pageIndex = blockIdToPageIndex?.get(blockId)
    if (!isPdfPageIndex(pageIndex, pageCount)) return null
    const pageBoxes = boxesByPage?.get(pageIndex)
    if (pageBoxes !== undefined) {
      const box = pageBoxes.find((candidate) => candidate.id === blockId)
      if (box !== undefined) {
        const position = box.position
        return {
          kind: 'box',
          key: JSON.stringify([
            'box',
            blockId,
            pageIndex,
            position.left,
            position.right,
            position.top,
            position.bottom,
          ]),
          pageIndex,
          blockId,
          position,
          pageBoxes,
        }
      }
    }
    return { kind: 'block-page', key: JSON.stringify(['block-page', blockId, pageIndex]), pageIndex, blockId }
  }
  if (!isPdfPageIndex(scrollToPageIndex, pageCount)) return null
  return { kind: 'page', key: JSON.stringify(['page', scrollToPageIndex]), pageIndex: scrollToPageIndex }
}

function getPdfPageScale(size: PageBaseSize, zoom: PdfZoom, fitWidth: number): number {
  return zoom === 'fit' ? fitWidth / size.width : Number(zoom) / 100
}

async function waitForPdfPageRender(task: RenderTask, pageIndex: number): Promise<void> {
  let timeoutId!: ReturnType<typeof setTimeout>
  try {
    await new Promise<void>((resolve, reject) => {
      timeoutId = setTimeout(() => {
        reject(new Error(`PDF 第 ${pageIndex + 1} 页渲染超时`))
        task.cancel()
      }, MAIN_THREAD_PAGE_RENDER_TIMEOUT_MS)
      void task.promise.then(resolve, reject)
    })
  } finally {
    clearTimeout(timeoutId)
  }
}

function cancelScheduledWork(reference: { current: PdfScheduledWork | null }) {
  const work = reference.current
  reference.current = null
  work?.cancel()
}

function PdfPages({
  pdfDoc,
  showToolbar = false,
  scrollToPageIndex,
  boxesByPage,
  blockIdToPageIndex,
  activeBlockIds,
  hoveredBlockIds,
  showAllBoxes = true,
  onHoverBlockId,
  onClickBlockId,
}: Readonly<PdfPagesProps>) {
  const pageCount = pdfDoc.numPages
  const pageNumbers = useMemo(() => Array.from({ length: pageCount }, (_, index) => index + 1), [pageCount])
  const [currentPage, setCurrentPage] = useState(1)
  const [zoom, setZoom] = useState<PdfZoom>('fit')
  const [fitWidth, setFitWidth] = useState(0)
  const [pageSizes, setPageSizes] = useState<ReadonlyMap<number, PageBaseSize>>(new Map())
  const [pageStates, setPageStates] = useState<ReadonlyMap<number, PdfPageState>>(new Map())
  const pageStatesRef = useRef(pageStates)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const contentRef = useRef<HTMLDivElement | null>(null)
  const canvasRefs = useRef(new Map<number, HTMLCanvasElement>())
  const pageRefs = useRef(new Map<number, HTMLDivElement>())
  const renderQueueRef = useRef<number[]>([])
  const requiredPagesRef = useRef<ReadonlySet<number>>(new Set())
  const currentPageIndexRef = useRef(0)
  const activeJobRef = useRef<PdfRenderJob | null>(null)
  const renderScheduleRef = useRef<PdfScheduledWork | null>(null)
  const viewportScheduleRef = useRef<PdfScheduledWork | null>(null)
  const retryTimersRef = useRef(new Map<number, PdfScheduledWork>())
  const retryCountsRef = useRef(new Map<number, number>())
  const navigationStartedRef = useRef<string | null>(null)
  const navigationCompletedRef = useRef<string | null>(null)
  const internalSelectionRef = useRef<string | null>(null)
  const activeIds = useMemo(() => new Set(activeBlockIds), [activeBlockIds])
  const hoveredIds = useMemo(() => new Set(hoveredBlockIds), [hoveredBlockIds])
  const navigationTarget = useMemo(
    () => getPdfNavigationTarget({ activeBlockIds, blockIdToPageIndex, boxesByPage, scrollToPageIndex, pageCount }),
    [activeBlockIds, blockIdToPageIndex, boxesByPage, scrollToPageIndex, pageCount],
  )
  const navigationPageSize = navigationTarget?.kind === 'box' ? pageSizes.get(navigationTarget.pageIndex) : undefined

  function publishPageStates(next: ReadonlyMap<number, PdfPageState>) {
    pageStatesRef.current = next
    setPageStates(next)
  }

  function setReadingPage(pageIndex: number) {
    currentPageIndexRef.current = pageIndex
    setCurrentPage(pageIndex + 1)
  }

  function goToPage(pageIndex: number) {
    if (!isPdfPageIndex(pageIndex, pageCount)) return
    const element = pageRefs.current.get(pageIndex)
    const container = containerRef.current
    if (element === undefined || container === null) return
    setReadingPage(pageIndex)
    scrollPdfPageIntoElement({ behavior: 'auto', scrollElement: container, targetElement: element })
    requestViewportUpdate()
  }

  function setPageState(pageIndex: number, state: PdfPageState | undefined) {
    const previous = pageStatesRef.current
    if (state === undefined && !previous.has(pageIndex)) return
    const next = new Map(previous)
    if (state === undefined) next.delete(pageIndex)
    else next.set(pageIndex, state)
    publishPageStates(next)
  }

  function clearPageRetry(pageIndex: number) {
    retryTimersRef.current.get(pageIndex)?.cancel()
    retryTimersRef.current.delete(pageIndex)
    retryCountsRef.current.delete(pageIndex)
  }

  function clearPageCanvas(pageIndex: number) {
    const canvas = canvasRefs.current.get(pageIndex)
    if (canvas !== undefined) {
      canvas.width = 0
      canvas.height = 0
    }
  }

  function retireActiveJob() {
    const job = activeJobRef.current
    activeJobRef.current = null
    if (job === null) return
    job.task?.cancel()
    clearPageCanvas(job.pageIndex)
    setPageState(job.pageIndex, undefined)
  }

  function scheduleRenderFlush() {
    if (activeJobRef.current !== null || renderQueueRef.current.length === 0 || renderScheduleRef.current !== null)
      return
    const idleGlobal: IdleGlobal = globalThis
    const requestIdle = idleGlobal.requestIdleCallback
    const cancelIdle = idleGlobal.cancelIdleCallback
    let scheduled: PdfScheduledWork
    const flush = () => {
      if (renderScheduleRef.current !== scheduled) return
      renderScheduleRef.current = null
      callbacksRef.current.flush()
    }
    if (typeof requestIdle === 'function' && typeof cancelIdle === 'function') {
      const handle = requestIdle(flush, { timeout: IDLE_RENDER_TIMEOUT_MS })
      scheduled = { cancel: () => cancelIdle(handle) }
    } else {
      const handle = setTimeout(flush, 0)
      scheduled = { cancel: () => clearTimeout(handle) }
    }
    renderScheduleRef.current = scheduled
  }

  function requestViewportUpdate() {
    if (viewportScheduleRef.current !== null) return
    let scheduled: PdfScheduledWork
    const handle = requestAnimationFrame(() => {
      if (viewportScheduleRef.current !== scheduled) return
      viewportScheduleRef.current = null
      callbacksRef.current.measure()
    })
    scheduled = { cancel: () => cancelAnimationFrame(handle) }
    viewportScheduleRef.current = scheduled
  }

  function trimCanvasPool() {
    const renderedPages = new Set<number>()
    for (const [pageIndex, state] of pageStatesRef.current) {
      if (state.status === 'ready') renderedPages.add(pageIndex)
    }
    const released = selectPdfPagesToReleaseForPool({
      renderedPages,
      keepPage: currentPageIndexRef.current,
      retainedPages: requiredPagesRef.current,
    })
    for (const pageIndex of released) {
      clearPageCanvas(pageIndex)
      setPageState(pageIndex, undefined)
    }
  }

  function queuePage(pageIndex: number) {
    const state = pageStatesRef.current.get(pageIndex)
    if (
      !requiredPagesRef.current.has(pageIndex) ||
      state?.status === 'ready' ||
      state?.status === 'error' ||
      state?.status === 'processing' ||
      retryTimersRef.current.has(pageIndex) ||
      renderQueueRef.current.includes(pageIndex)
    )
      return
    renderQueueRef.current.push(pageIndex)
    if (state?.status !== 'queued') setPageState(pageIndex, { status: 'queued' })
    scheduleRenderFlush()
  }

  function retryOrFail(pageIndex: number, error: unknown) {
    const attempts = retryCountsRef.current.get(pageIndex)
    if (attempts !== undefined && attempts >= MAX_PAGE_RENDER_RETRIES) {
      const message = error instanceof Error ? error.message : toPrimitiveString(error)
      setPageState(pageIndex, { status: 'error', message })
      reportClientWarning(`PDF page ${pageIndex + 1} render failed`, error)
      return
    }
    retryCountsRef.current.set(pageIndex, attempts === undefined ? 1 : attempts + 1)
    setPageState(pageIndex, { status: 'queued' })
    const handle = setTimeout(() => {
      if (retryTimersRef.current.get(pageIndex) !== retry) return
      retryTimersRef.current.delete(pageIndex)
      callbacksRef.current.queue(pageIndex)
    }, PAGE_RENDER_RETRY_DELAY_MS)
    const retry = { cancel: () => clearTimeout(handle) }
    retryTimersRef.current.set(pageIndex, retry)
  }

  function rememberPageSize(pageIndex: number, width: number, height: number) {
    setPageSizes((previous) => {
      const current = previous.get(pageIndex)
      if (current?.width === width && current.height === height) return previous
      const next = new Map(previous)
      next.set(pageIndex, { width, height })
      return next
    })
  }

  async function renderPage(job: PdfRenderJob) {
    const pageIndex = job.pageIndex
    let page: PDFPageProxy | undefined
    try {
      page = await pdfDoc.getPage(pageIndex + 1)
      if (activeJobRef.current !== job) return
      const base = page.getViewport({ scale: 1 })
      if (!Number.isFinite(base.width) || !Number.isFinite(base.height) || base.width <= 0 || base.height <= 0) {
        throw new Error('PDF 页面尺寸无效')
      }
      rememberPageSize(pageIndex, base.width, base.height)
      const viewport = page.getViewport({ scale: getPdfPageScale(base, zoom, fitWidth) })
      const canvas = canvasRefs.current.get(pageIndex)
      if (canvas === undefined) throw new Error('PDF 页面画布不可用')
      canvas.width = Math.ceil(viewport.width)
      canvas.height = Math.ceil(viewport.height)
      const context = canvas.getContext('2d', { alpha: false })
      if (context === null) throw new Error('无法创建 PDF 页面绘图上下文')
      context.clearRect(0, 0, canvas.width, canvas.height)
      const task = page.render({ canvas: null, canvasContext: context, viewport, background: '#ffffff' })
      job.task = task
      await waitForPdfPageRender(task, pageIndex)
      if (activeJobRef.current !== job) return
      clearPageRetry(pageIndex)
      setPageState(pageIndex, { status: 'ready' })
      trimCanvasPool()
    } catch (error: unknown) {
      if (activeJobRef.current !== job) return
      clearPageCanvas(pageIndex)
      retryOrFail(pageIndex, error)
    } finally {
      try {
        page?.cleanup()
      } finally {
        if (activeJobRef.current === job) {
          activeJobRef.current = null
          scheduleRenderFlush()
        }
      }
    }
  }

  function flushRenderQueue() {
    if (activeJobRef.current !== null) return
    while (renderQueueRef.current.length > 0) {
      const pageIndex = renderQueueRef.current.shift()!
      const state = pageStatesRef.current.get(pageIndex)
      if (!requiredPagesRef.current.has(pageIndex) || state?.status !== 'queued') continue
      const job: PdfRenderJob = { pageIndex, task: null }
      activeJobRef.current = job
      setPageState(pageIndex, { status: 'processing' })
      void renderPage(job).catch((error: unknown) => reportClientWarning('PDF page cleanup failed', error))
      return
    }
  }

  function navigateToRequestedTarget() {
    const selectedInside = internalSelectionRef.current
    internalSelectionRef.current = null
    if (navigationTarget === null) {
      navigationStartedRef.current = null
      navigationCompletedRef.current = null
      return
    }
    if (selectedInside !== null && navigationTarget.kind !== 'page' && navigationTarget.blockId === selectedInside) {
      navigationCompletedRef.current = navigationTarget.key
      return
    }
    if (navigationCompletedRef.current === navigationTarget.key) return
    const container = containerRef.current
    const element = pageRefs.current.get(navigationTarget.pageIndex)
    if (container === null || element === undefined || container.clientWidth === 0 || container.clientHeight === 0)
      return
    setReadingPage(navigationTarget.pageIndex)
    const scrollElement =
      container.scrollHeight > container.clientHeight + 1 ? container : findNearestScrollableAncestor(container)
    if (scrollElement === null) {
      navigationCompletedRef.current = navigationTarget.key
      return
    }
    const behavior = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
    if (navigationTarget.kind === 'box' && navigationPageSize !== undefined) {
      const coordinateSpace = detectPdfBboxCoordinateSpace({
        items: navigationTarget.pageBoxes,
        pageBaseWidth: navigationPageSize.width,
        pageBaseHeight: navigationPageSize.height,
      })
      const rect = computePdfOverlayRect({
        position: navigationTarget.position,
        scale: getPdfPageScale(navigationPageSize, zoom, fitWidth),
        pageBaseWidth: navigationPageSize.width,
        pageBaseHeight: navigationPageSize.height,
        coordinateSpace,
      })
      scrollPdfOverlayIntoElement({
        behavior,
        overlayHeight: rect.height,
        overlayTop: rect.top,
        pageElement: element,
        scrollElement,
      })
      navigationCompletedRef.current = navigationTarget.key
      return
    }
    if (navigationStartedRef.current !== navigationTarget.key) {
      scrollPdfPageIntoElement({ behavior, scrollElement, targetElement: element })
      navigationStartedRef.current = navigationTarget.key
    }
    if (navigationTarget.kind !== 'box') navigationCompletedRef.current = navigationTarget.key
  }

  function updateViewportWindow() {
    const container = containerRef.current
    if (container === null) return
    if (container.clientWidth === 0 || container.clientHeight === 0) {
      requiredPagesRef.current = new Set()
    } else {
      if (zoom === 'fit') {
        const firstPage = pageRefs.current.get(0)
        if (firstPage === undefined || firstPage.clientWidth === 0) return
        if (firstPage.clientWidth !== fitWidth) {
          setFitWidth(firstPage.clientWidth)
          return
        }
      }
      const viewport = container.getBoundingClientRect()
      const pages = [...pageRefs.current].map(([index, element]) => {
        const rect = element.getBoundingClientRect()
        return { index, top: rect.top, bottom: rect.bottom }
      })
      const window = selectPdfPagesToRender({
        pages,
        viewportTop: viewport.top,
        viewportBottom: viewport.top + container.clientHeight,
        currentPageIndex: currentPageIndexRef.current,
      })
      requiredPagesRef.current = new Set(window.pageIndices)
      if (window.currentPageIndex !== null) setReadingPage(window.currentPageIndex)
    }
    const required = requiredPagesRef.current
    if (activeJobRef.current !== null && !required.has(activeJobRef.current.pageIndex)) retireActiveJob()
    for (const [pageIndex, state] of pageStatesRef.current) {
      if (!required.has(pageIndex) && state.status === 'queued') {
        clearPageRetry(pageIndex)
        setPageState(pageIndex, undefined)
      }
    }
    renderQueueRef.current = []
    for (const pageIndex of required) queuePage(pageIndex)
    trimCanvasPool()
    navigateToRequestedTarget()
  }

  function resetRendering() {
    cancelScheduledWork(renderScheduleRef)
    retireActiveJob()
    for (const retry of retryTimersRef.current.values()) retry.cancel()
    retryTimersRef.current.clear()
    retryCountsRef.current.clear()
    renderQueueRef.current = []
    publishPageStates(new Map())
    for (const canvas of canvasRefs.current.values()) {
      canvas.width = 0
      canvas.height = 0
    }
    requestViewportUpdate()
  }

  function retryPage(pageIndex: number) {
    if (pageStatesRef.current.get(pageIndex)?.status !== 'error') return
    clearPageRetry(pageIndex)
    clearPageCanvas(pageIndex)
    setPageState(pageIndex, undefined)
    queuePage(pageIndex)
  }

  function handleOverlayClick(pageIndex: number, blockId: string, hint?: ParsingEditFocusHint) {
    setReadingPage(pageIndex)
    internalSelectionRef.current = blockId
    onClickBlockId?.(blockId, hint)
    requestViewportUpdate()
  }

  const callbacksRef = useRef({
    flush: flushRenderQueue,
    measure: updateViewportWindow,
    requestViewport: requestViewportUpdate,
    reset: resetRendering,
    queue: queuePage,
  })
  useLayoutEffect(() => {
    callbacksRef.current = {
      flush: flushRenderQueue,
      measure: updateViewportWindow,
      requestViewport: requestViewportUpdate,
      reset: resetRendering,
      queue: queuePage,
    }
  })
  useLayoutEffect(() => {
    callbacksRef.current.reset()
  }, [fitWidth, zoom])
  useLayoutEffect(() => {
    callbacksRef.current.requestViewport()
  }, [navigationTarget?.key, navigationPageSize])
  useLayoutEffect(() => {
    const container = containerRef.current
    const content = contentRef.current
    if (container === null || content === null) return
    const canvases = [...canvasRefs.current.values()]
    const retryTimers = retryTimersRef.current
    const update = () => callbacksRef.current.requestViewport()
    const observer = new ResizeObserver(update)
    observer.observe(container)
    observer.observe(content)
    container.addEventListener('scroll', update, { passive: true })
    callbacksRef.current.requestViewport()
    return () => {
      observer.disconnect()
      container.removeEventListener('scroll', update)
      cancelScheduledWork(viewportScheduleRef)
      cancelScheduledWork(renderScheduleRef)
      const job = activeJobRef.current
      activeJobRef.current = null
      job?.task?.cancel()
      for (const retry of retryTimers.values()) retry.cancel()
      retryTimers.clear()
      renderQueueRef.current = []
      for (const canvas of canvases) {
        canvas.width = 0
        canvas.height = 0
      }
    }
  }, [])

  if (pageCount === 0)
    return (
      <p role="status" className="p-4 text-sm text-muted-foreground">
        该 PDF 没有可显示的页面
      </p>
    )

  return (
    <div className="flex h-full min-h-0 flex-col">
      {showToolbar ? (
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-background/60 px-5 text-[13px]">
          <FileText className="size-3.5 text-muted-foreground" />
          <span>原文 PDF</span>
          <div className="ml-auto flex items-center gap-2 text-xs tabular-nums text-muted-foreground">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="上一页原文"
              disabled={currentPage <= 1}
              onClick={() => goToPage(currentPageIndexRef.current - 1)}
            >
              <ChevronLeft className="size-3.5" />
            </Button>
            <span>
              <span className="text-foreground">{currentPage}</span> / {pageCount} 页
            </span>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="下一页原文"
              disabled={currentPage >= pageCount}
              onClick={() => goToPage(currentPageIndexRef.current + 1)}
            >
              <ChevronRight className="size-3.5" />
            </Button>
            <select
              aria-label="原文缩放"
              value={zoom}
              onChange={(event) => {
                const value = event.currentTarget.value
                if (value === 'fit' || value === '100' || value === '150' || value === '200') setZoom(value)
              }}
              className="ml-1 max-w-24 rounded border-0 border-l border-border bg-transparent py-1 pl-2 text-xs text-muted-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
            >
              <option value="fit">适合宽度</option>
              <option value="100">100%</option>
              <option value="150">150%</option>
              <option value="200">200%</option>
            </select>
          </div>
        </div>
      ) : null}
      <div
        ref={containerRef}
        role="region"
        aria-label="PDF 页面"
        tabIndex={0}
        className="min-h-0 flex-1 overflow-auto overscroll-contain no-scrollbar px-5 py-7"
      >
        <div ref={contentRef} className="flex min-w-full flex-col gap-6">
          {pageNumbers.map((pageNumber) => {
            const index = pageNumber - 1
            const size = pageSizes.get(index)
            const state = pageStates.get(index)
            const pageBoxes = boxesByPage?.get(index)
            const pending = state?.status === 'queued' || state?.status === 'processing'
            let placeholder = '页面尚未渲染'
            if (state?.status === 'queued') placeholder = '等待渲染页面…'
            else if (state?.status === 'processing') placeholder = '正在渲染页面…'
            return (
              <div
                key={pageNumber}
                ref={(element) => {
                  if (element === null) pageRefs.current.delete(index)
                  else pageRefs.current.set(index, element)
                }}
                data-page-index={index}
                data-page-rendered={state?.status === 'ready' ? 'true' : 'false'}
                className={cn(
                  'relative mx-auto bg-card shadow-sm ring-1 ring-border/60',
                  !showToolbar && 'rounded-xl',
                  zoom === 'fit' && 'w-full',
                  zoom === 'fit' && (showToolbar ? 'max-w-[480px]' : 'max-w-4xl'),
                )}
                style={{
                  minHeight: size === undefined ? DEFAULT_PAGE_PLACEHOLDER_HEIGHT : undefined,
                  aspectRatio: size === undefined ? undefined : size.width / size.height,
                  width: zoom === 'fit' || size === undefined ? undefined : (size.width * Number(zoom)) / 100,
                }}
              >
                <canvas
                  ref={(element) => {
                    if (element === null) canvasRefs.current.delete(index)
                    else canvasRefs.current.set(index, element)
                  }}
                  role="img"
                  aria-label={`PDF 第 ${pageNumber} 页`}
                  className={cn('block h-auto w-full', !showToolbar && 'rounded-xl')}
                />
                {state?.status === 'error' ? (
                  <button
                    type="button"
                    aria-label={`重试第 ${pageNumber} 页`}
                    className="absolute inset-0 flex flex-col items-center justify-center gap-2 rounded-xl bg-card px-4 text-xs text-foreground"
                    onClick={() => retryPage(index)}
                  >
                    <span className="flex items-center font-medium">
                      <RotateCcw className="mr-2 size-4" />
                      渲染失败，点击重试
                    </span>
                    <span role="alert" className="max-w-full break-words text-muted-foreground">
                      {state.message}
                    </span>
                  </button>
                ) : state?.status !== 'ready' ? (
                  <div
                    className="pointer-events-none absolute inset-0 overflow-hidden rounded-xl"
                    aria-label={placeholder}
                  >
                    <Skeleton className="h-full w-full rounded-none" />
                    {pending ? (
                      <span role="status" className="sr-only">
                        {placeholder}
                      </span>
                    ) : null}
                  </div>
                ) : null}
                {state?.status === 'ready' && size !== undefined && pageBoxes !== undefined ? (
                  <BboxOverlay
                    items={pageBoxes}
                    scale={getPdfPageScale(size, zoom, fitWidth)}
                    pageBaseWidth={size.width}
                    pageBaseHeight={size.height}
                    showAll={showAllBoxes}
                    activeIds={activeIds}
                    hoveredIds={hoveredIds}
                    onHoverId={onHoverBlockId}
                    onClickId={
                      onClickBlockId === undefined
                        ? undefined
                        : (blockId, hint) => handleOverlayClick(index, blockId, hint)
                    }
                  />
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
