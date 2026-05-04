/**
 * PdfViewer - render PDF pages with optional layout box overlays.
 */
'use client'

import type { Remote } from 'comlink'
import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { AlertCircle, Loader2, RotateCcw } from 'lucide-react'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import { ParsingBlock } from '@/lib/parsing-positions'
import type { ParsingEditFocusHint } from '@/lib/parsing-edit-focus'
import { classifyParsingBlock } from '@/lib/parsing-layout'
import { toPrimitiveString } from '@/lib/primitive-text'
import { Button } from '@/components/ui/button'
import { BboxOverlay, type BboxOverlayItem } from '@/components/parsing/bbox-overlay'
import {
 MAX_RETAINED_PAGE_CANVASES,
 selectPdfPagesToReleaseForPool,
} from '@/components/parsing/pdf-render-canvas-pool'
import { detachPromise } from '@/lib/utils'
import type { PdfPageRenderWorkerApi } from '@/workers/pdf-page-render.worker'


type Box = BboxOverlayItem
type PdfJsModule = typeof import('pdfjs-dist/build/pdf.mjs')
type PageBaseSize = { width: number; height: number }

interface PdfViewerProps {
 file?: File | null
 blocks?: ParsingBlock[]
 boxesByPage?: Map<number, Box[]> | null
 blockIdToPageIndex?: Map<string, number> | null
 activeBlockIds?: string[] | null
 hoveredBlockIds?: string[] | null
 showAllBoxes?: boolean
 onHoverBlockId?: (blockId: string | null) => void
 onClickBlockId?: (blockId: string, hint?: ParsingEditFocusHint) => void
}

type IdleCallbackHandle = number
type IdleGlobal = typeof globalThis & {
 requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => IdleCallbackHandle
 cancelIdleCallback?: (id: IdleCallbackHandle) => void
}

const MAX_CONCURRENT_RENDERS = 1
const RENDER_ROOT_MARGIN = '800px 0px 800px 0px'
const RETAIN_ROOT_MARGIN = '2400px 0px 2400px 0px'
const IDLE_RENDER_TIMEOUT_MS = 400
const MAIN_THREAD_PAGE_RENDER_TIMEOUT_MS = 12_000
const OFFSCREEN_PAGE_RENDER_TIMEOUT_MS = 12_000
const DEFAULT_PAGE_PLACEHOLDER_HEIGHT = '520px'
const INITIAL_PDF_PAGE_PRERENDER_COUNT = 3
const FIRST_PAGE_RENDER_WATCHDOG_INTERVAL_MS = 1_500
const MAX_PAGE_RENDER_RETRIES = 3
const PAGE_RENDER_RETRY_DELAY_MS = 150
// Next dev still wraps the dedicated render worker in eval-based chunks, which can leave
// page rasterization stuck indefinitely. Keep rendering on the main thread for now.
const ENABLE_PDF_OFFSCREEN_RENDER = false
const PDFJS_MODULE_URL = '/pdfjs/build/pdf.mjs'
const PDFJS_WORKER_URL = '/pdfjs-compat/pdf.worker.mjs'
const PDFJS_CMAPS_URL = '/pdfjs/cmaps/'
const PDFJS_STANDARD_FONTS_URL = '/pdfjs/standard_fonts/'
const PDFJS_WASM_URL = '/pdfjs/wasm/'
const PDFJS_ICCS_URL = '/pdfjs/iccs/'

let pdfJsModulePromise: Promise<PdfJsModule> | null = null

function installPdfJsCompatPolyfills() {
 const promiseCtor = Promise as typeof Promise & {
 withResolvers?: () => {
 promise: Promise<unknown>
 resolve: (value: unknown) => void
 reject: (reason?: unknown) => void
 }
 }

 if (typeof promiseCtor.withResolvers !== 'function') {
 Object.defineProperty(promiseCtor, 'withResolvers', {
 configurable: true,
 writable: true,
 value() {
 let resolve: (value: unknown) => void = () => {}
 let reject: (reason?: unknown) => void = () => {}
 const promise = new Promise((innerResolve, innerReject) => {
 resolve = innerResolve
 reject = innerReject
 })

 return { promise, resolve, reject }
 },
 })
 }

 const mapPrototype = Map.prototype as typeof Map.prototype & {
 getOrInsertComputed?: (key: unknown, compute: (key: unknown) => unknown) => unknown
 }

 if (typeof mapPrototype.getOrInsertComputed !== 'function') {
 Object.defineProperty(mapPrototype, 'getOrInsertComputed', {
 configurable: true,
 writable: true,
 value(key: unknown, compute: (key: unknown) => unknown) {
 if (this.has(key)) {
 return this.get(key)
 }

 const value = compute(key)
 this.set(key, value)
 return value
 },
 })
 }
}

async function loadPdfJsModule(): Promise<PdfJsModule> {
 try {
 if (!pdfJsModulePromise) {
 installPdfJsCompatPolyfills()
 // Bypass Next's dev-time webpack wrapping for pdf.js. The wrapped chunk crashes
 // on Mozilla's ESM bundle with "Object.defineProperty called on non-object".
 pdfJsModulePromise = import(/* webpackIgnore: true */ PDFJS_MODULE_URL) as Promise<PdfJsModule>
 }

 const pdfjsLib = await pdfJsModulePromise
 pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL
 return pdfjsLib
 } catch (error) {
 pdfJsModulePromise = null
 throw error
 }
}

function canUseOffscreenCanvasRender(): boolean {
 return ENABLE_PDF_OFFSCREEN_RENDER && (
 typeof Worker !== 'undefined' &&
 typeof OffscreenCanvas !== 'undefined' &&
 typeof HTMLCanvasElement !== 'undefined' &&
 typeof HTMLCanvasElement.prototype.transferControlToOffscreen === 'function'
 )
}

export function PdfViewer({
 file,
 blocks = [],
 boxesByPage,
 blockIdToPageIndex,
 activeBlockIds,
 hoveredBlockIds,
 showAllBoxes = true,
 onHoverBlockId,
 onClickBlockId,
}: Readonly<PdfViewerProps>) {
 const containerRef = useRef<HTMLDivElement | null>(null)
 const contentRef = useRef<HTMLDivElement | null>(null)
 const canvasRefs = useRef<Map<number, HTMLCanvasElement>>(new Map())
 const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map())
 const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null)
 const [pageCount, setPageCount] = useState(0)
 const [scale, setScale] = useState(1)
 const [isLoading, setIsLoading] = useState(false)
 const [loadError, setLoadError] = useState<string | null>(null)
 const [reloadTick, setReloadTick] = useState(0)
 const [defaultPageAspectRatio, setDefaultPageAspectRatio] = useState<number | null>(null)
 const [pageAspectRatios, setPageAspectRatios] = useState<Map<number, number>>(new Map())
 const [defaultPageBaseSize, setDefaultPageBaseSize] = useState<PageBaseSize | null>(null)
 const [pageBaseSizes, setPageBaseSizes] = useState<Map<number, PageBaseSize>>(new Map())
 const [renderedPages, setRenderedPages] = useState<Set<number>>(new Set())
 const [loadingPages, setLoadingPages] = useState<Set<number>>(new Set())
 const [failedPages, setFailedPages] = useState<Set<number>>(new Set())
 const [pageRenderErrors, setPageRenderErrors] = useState<Map<number, string>>(new Map())
 const [offscreenRenderEnabled, setOffscreenRenderEnabled] = useState(false)
 const renderedPagesRef = useRef<Set<number>>(new Set())
 const renderingPagesRef = useRef<Set<number>>(new Set())
 const renderTasksRef = useRef<Map<number, RenderTask>>(new Map())
 const pageRenderErrorsRef = useRef<Map<number, string>>(new Map())
 const offscreenRenderWorkerRef = useRef<Worker | null>(null)
 const offscreenRenderApiRef = useRef<Remote<PdfPageRenderWorkerApi> | null>(null)
 const transferredPageCanvasRef = useRef<Set<number>>(new Set())
 const offscreenRenderWorkerDisabledRef = useRef(false)
 const queuedPagesRef = useRef<Set<number>>(new Set())
 const retainedPageIndicesRef = useRef<Set<number>>(new Set())
 const renderQueueRef = useRef<number[]>([])
 const idleRenderHandleRef = useRef<IdleCallbackHandle | null>(null)
 const idleRenderTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
 const pageRenderRetryCountsRef = useRef<Map<number, number>>(new Map())
 const pageRenderRetryTimeoutsRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())
 const activeRenderCountRef = useRef(0)
 const flushQueuedPageRendersRef = useRef<() => Promise<void>>(async () => {})
 const renderGenRef = useRef(0)
 const pageNumbers = useMemo(() => Array.from({ length: pageCount }, (_, pageNumber) => pageNumber + 1), [pageCount])
 const renderModeKey = `${reloadTick}-${offscreenRenderEnabled ? 'offscreen' : 'main'}`

 const retryLoad = useCallback(() => {
 setReloadTick((prev) => prev + 1)
 }, [])

 const terminateOffscreenRenderWorker = useCallback(() => {
 const api = offscreenRenderApiRef.current
 offscreenRenderApiRef.current = null
 transferredPageCanvasRef.current.clear()
 if (api) {
 detachPromise(api.destroy().catch(() => {}))
 }
 offscreenRenderWorkerRef.current?.terminate()
 offscreenRenderWorkerRef.current = null
 }, [])

 const disableOffscreenRenderAndReload = useCallback(
 (reason: unknown) => {
 if (offscreenRenderWorkerDisabledRef.current) return
 offscreenRenderWorkerDisabledRef.current = true
 console.warn('PDF offscreen page render failed; falling back to main-thread raster', reason)
 terminateOffscreenRenderWorker()
 setOffscreenRenderEnabled(false)
 setReloadTick((prev) => prev + 1)
 },
 [terminateOffscreenRenderWorker]
 )

 const cancelRenderTasks = useCallback(() => {
 renderTasksRef.current.forEach((task) => task.cancel())
 renderTasksRef.current.clear()
 const offscreenApi = offscreenRenderApiRef.current
 if (offscreenApi) {
 detachPromise(offscreenApi.cancelAllRenders().catch(() => {}))
 }
 }, [])

 useEffect(() => {
 let cancelled = false

 async function loadPdf() {
 cancelRenderTasks()
 pageRenderRetryTimeoutsRef.current.forEach((timeoutId) => clearTimeout(timeoutId))
 pageRenderRetryTimeoutsRef.current.clear()
 pageRenderRetryCountsRef.current.clear()

 if (!file) {
 setPdfDoc(null)
 setPageCount(0)
 setDefaultPageAspectRatio(null)
 setPageAspectRatios(new Map())
 setDefaultPageBaseSize(null)
 setPageBaseSizes(new Map())
 retainedPageIndicesRef.current.clear()
 renderedPagesRef.current = new Set()
 setRenderedPages(new Set())
 setLoadingPages(new Set())
 setFailedPages(new Set())
 pageRenderErrorsRef.current = new Map()
 setPageRenderErrors(new Map())
 setLoadError(null)
 return
 }

 setIsLoading(true)
 setLoadError(null)
 try {
 const data = new Uint8Array(await file.arrayBuffer())
 const pdfjsLib = await loadPdfJsModule()
 const offscreenCanvasSupported = Boolean(pdfjsLib.FeatureTest.isOffscreenCanvasSupported)
 const doc = await pdfjsLib.getDocument({
 data,
 isOffscreenCanvasSupported: offscreenCanvasSupported,
 enableHWA: offscreenCanvasSupported,
 cMapUrl: PDFJS_CMAPS_URL,
 standardFontDataUrl: PDFJS_STANDARD_FONTS_URL,
 wasmUrl: PDFJS_WASM_URL,
 iccUrl: PDFJS_ICCS_URL,
 }).promise
 if (cancelled) return
 setPdfDoc(doc)
 setPageCount(doc.numPages)
 setDefaultPageAspectRatio(null)
 setPageAspectRatios(new Map())
 setDefaultPageBaseSize(null)
 setPageBaseSizes(new Map())
 retainedPageIndicesRef.current.clear()
 renderedPagesRef.current = new Set()
 setRenderedPages(new Set())
 setLoadingPages(new Set())
 setFailedPages(new Set())
 pageRenderErrorsRef.current = new Map()
 setPageRenderErrors(new Map())
 } catch (err) {
 if (!cancelled) {
 const message = err instanceof Error ? err.message : toPrimitiveString(err)
 setLoadError(message || 'PDF 加载失败')
 setPdfDoc(null)
 setPageCount(0)
 setDefaultPageAspectRatio(null)
 setPageAspectRatios(new Map())
 setDefaultPageBaseSize(null)
 setPageBaseSizes(new Map())
 retainedPageIndicesRef.current.clear()
 renderedPagesRef.current = new Set()
 setRenderedPages(new Set())
 setLoadingPages(new Set())
 setFailedPages(new Set())
 pageRenderErrorsRef.current = new Map()
 setPageRenderErrors(new Map())
 }
 } finally {
 if (!cancelled) setIsLoading(false)
 }
 }

 loadPdf()
 return () => {
 cancelled = true
 }
 }, [cancelRenderTasks, file, reloadTick])

 useEffect(() => {
 containerRef.current?.scrollTo({ top: 0 })
 }, [file, reloadTick])

 useEffect(() => {
 // Important: measure the actual content width (max-w-4xl) instead of the scroll container width,
 // otherwise the computed scale will not match the rendered canvas and overlays will drift.
 const container = contentRef.current
 if (!container || !pdfDoc) return

 let raf = 0
 const updateScale = async () => {
 if (!container || !pdfDoc) return
 // Prefer the first page container width (clientWidth excludes borders),
 // so the scale matches the canvas CSS size exactly.
 const firstPage = pageRefs.current.get(0)
 const width = (firstPage?.clientWidth || container.clientWidth) ?? 0
 if (!width) return
 try {
 const page = await pdfDoc.getPage(1)
 const viewport = page.getViewport({ scale: 1 })
 const nextScale = width / viewport.width
 const nextAspectRatio = viewport.width / viewport.height
 setDefaultPageBaseSize((prev) =>
 prev != null &&
 Math.abs(prev.width - viewport.width) < 0.001 &&
 Math.abs(prev.height - viewport.height) < 0.001
 ? prev
 : { width: viewport.width, height: viewport.height }
 )
 setScale((prev) => (Math.abs(prev - nextScale) > 0.01 ? nextScale : prev))
 setDefaultPageAspectRatio((prev) =>
 prev != null && Math.abs(prev - nextAspectRatio) < 0.001 ? prev : nextAspectRatio
 )
 } catch {
 // ignore
 }
 }

 const handleResize = () => {
 if (raf) cancelAnimationFrame(raf)
 raf = requestAnimationFrame(updateScale)
 }

 const observer = new ResizeObserver(handleResize)
 observer.observe(container)
 updateScale()

 return () => {
 if (raf) cancelAnimationFrame(raf)
 observer.disconnect()
 }
 }, [pdfDoc])

 useEffect(() => {
 let cancelled = false

 terminateOffscreenRenderWorker()
 setOffscreenRenderEnabled(false)

 if (!file || !pdfDoc) {
 return () => {
 cancelled = true
 }
 }

 if (offscreenRenderWorkerDisabledRef.current || !canUseOffscreenCanvasRender()) {
 return () => {
 cancelled = true
 }
 }

 detachPromise((async () => {
 try {
 const { transfer, wrap } = await import('comlink')
 if (cancelled) return

 const worker = new Worker(new URL('../../workers/pdf-page-render.worker.ts', import.meta.url), {
 type: 'module',
 })
 const api = wrap<PdfPageRenderWorkerApi>(worker)
 offscreenRenderWorkerRef.current = worker
 offscreenRenderApiRef.current = api

 const data = new Uint8Array(await file.arrayBuffer())
 await api.initializeDocument(transfer(data, [data.buffer]))

 if (cancelled) {
 await api.destroy().catch(() => {})
 worker.terminate()
 return
 }

 setOffscreenRenderEnabled(ENABLE_PDF_OFFSCREEN_RENDER)
 } catch (error) {
 console.warn('PDF offscreen render worker failed; falling back to main-thread raster', error)
 offscreenRenderWorkerDisabledRef.current = true
 terminateOffscreenRenderWorker()
 setOffscreenRenderEnabled(false)
 }
 })())

 return () => {
 cancelled = true
 terminateOffscreenRenderWorker()
 setOffscreenRenderEnabled(false)
 }
 }, [file, pdfDoc, terminateOffscreenRenderWorker])

 const clearQueuedRenderFlush = useCallback(() => {
 const idleGlobal: IdleGlobal = globalThis
 const cancelIdleCallback = idleGlobal.cancelIdleCallback

 if (idleRenderHandleRef.current != null && typeof cancelIdleCallback === 'function') {
 cancelIdleCallback(idleRenderHandleRef.current)
 }
 if (idleRenderTimeoutRef.current != null) {
 clearTimeout(idleRenderTimeoutRef.current)
 }

 idleRenderHandleRef.current = null
 idleRenderTimeoutRef.current = null
 }, [])

 const attachOffscreenPageCanvas = useCallback(
 async (pageIndex: number) => {
 if (!offscreenRenderEnabled) return false

 const api = offscreenRenderApiRef.current
 const canvas = canvasRefs.current.get(pageIndex)
 if (!api || !canvas) return false

 if (transferredPageCanvasRef.current.has(pageIndex)) {
 return true
 }

 const { transfer } = await import('comlink')
 const offscreenCanvas = canvas.transferControlToOffscreen()
 await api.attachPageCanvas(
 transfer(
 {
 pageIndex,
 canvas: offscreenCanvas,
 },
 [offscreenCanvas]
 )
 )

 transferredPageCanvasRef.current.add(pageIndex)
 return true
 },
 [offscreenRenderEnabled]
 )

 const rememberPageAspectRatio = useCallback((pageIndex: number, width: number, height: number) => {
 if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return

 const nextAspectRatio = width / height
 setPageAspectRatios((prev) => {
 const currentAspectRatio = prev.get(pageIndex)
 if (currentAspectRatio != null && Math.abs(currentAspectRatio - nextAspectRatio) < 0.001) {
 return prev
 }

 const next = new Map(prev)
 next.set(pageIndex, nextAspectRatio)
 return next
 })
 }, [])

 const rememberPageBaseSize = useCallback((pageIndex: number, width: number, height: number) => {
 if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return

 setPageBaseSizes((prev) => {
 const current = prev.get(pageIndex)
 if (
 current &&
 Math.abs(current.width - width) < 0.001 &&
 Math.abs(current.height - height) < 0.001
 ) {
 return prev
 }

 const next = new Map(prev)
 next.set(pageIndex, { width, height })
 return next
 })
 }, [])

 const clearPageRenderRetry = useCallback((pageIndex?: number) => {
 if (typeof pageIndex === 'number' && Number.isFinite(pageIndex)) {
 const timeoutId = pageRenderRetryTimeoutsRef.current.get(pageIndex)
 if (timeoutId) clearTimeout(timeoutId)
 pageRenderRetryTimeoutsRef.current.delete(pageIndex)
 pageRenderRetryCountsRef.current.delete(pageIndex)
 return
 }

 pageRenderRetryTimeoutsRef.current.forEach((timeoutId) => clearTimeout(timeoutId))
 pageRenderRetryTimeoutsRef.current.clear()
 pageRenderRetryCountsRef.current.clear()
 }, [])

 const setPageRenderError = useCallback((pageIndex: number, error: unknown) => {
 const message = error instanceof Error ? error.message : toPrimitiveString(error)
 const nextMessage = message || `Page ${pageIndex + 1} render failed`

 setPageRenderErrors((prev) => {
 if (prev.get(pageIndex) === nextMessage) return prev

 const next = new Map(prev)
 next.set(pageIndex, nextMessage)
 pageRenderErrorsRef.current = next
 return next
 })

 if (process.env.NODE_ENV === 'development') {
 console.warn(`PDF page ${pageIndex + 1} render failed`, error)
 }
 }, [])

 const clearPageRenderError = useCallback((pageIndex?: number) => {
 if (typeof pageIndex === 'number' && Number.isFinite(pageIndex)) {
 setPageRenderErrors((prev) => {
 if (!prev.has(pageIndex)) return prev

 const next = new Map(prev)
 next.delete(pageIndex)
 pageRenderErrorsRef.current = next
 return next
 })
 return
 }

 pageRenderErrorsRef.current = new Map()
 setPageRenderErrors(new Map())
 }, [])

 const markPageFailed = useCallback((pageIndex: number) => {
 setFailedPages((prev) => {
 if (prev.has(pageIndex)) return prev

 const next = new Set(prev)
 next.add(pageIndex)
 return next
 })
 }, [])

 const clearPageFailure = useCallback((pageIndex?: number) => {
 if (typeof pageIndex === 'number' && Number.isFinite(pageIndex)) {
 setFailedPages((prev) => {
 if (!prev.has(pageIndex)) return prev

 const next = new Set(prev)
 next.delete(pageIndex)
 return next
 })
 return
 }

 setFailedPages(new Set())
 }, [])

 const markPageRendered = useCallback((pageIndex: number) => {
 if (renderedPagesRef.current.has(pageIndex)) return false

 clearPageRenderRetry(pageIndex)
 clearPageFailure(pageIndex)
 clearPageRenderError(pageIndex)
 const next = new Set(renderedPagesRef.current)
 next.add(pageIndex)
 renderedPagesRef.current = next
 setRenderedPages(next)
 return true
 }, [clearPageFailure, clearPageRenderError, clearPageRenderRetry])

 const unmarkPageRendered = useCallback((pageIndex: number) => {
 if (!renderedPagesRef.current.has(pageIndex)) return false

 const next = new Set(renderedPagesRef.current)
 next.delete(pageIndex)
 renderedPagesRef.current = next
 setRenderedPages(next)
 return true
 }, [])

 const markPageLoading = useCallback((pageIndex: number) => {
 setLoadingPages((prev) => {
 if (prev.has(pageIndex)) return prev

 const next = new Set(prev)
 next.add(pageIndex)
 return next
 })
 }, [])

 const unmarkPageLoading = useCallback((pageIndex: number) => {
 setLoadingPages((prev) => {
 if (!prev.has(pageIndex)) return prev

 const next = new Set(prev)
 next.delete(pageIndex)
 return next
 })
 }, [])

 const scheduleQueuedRenderFlush = useCallback(() => {
 if (idleRenderHandleRef.current != null || idleRenderTimeoutRef.current != null) return

 const flush = () => {
 idleRenderHandleRef.current = null
 if (idleRenderTimeoutRef.current != null) {
 clearTimeout(idleRenderTimeoutRef.current)
 idleRenderTimeoutRef.current = null
 }
 detachPromise(flushQueuedPageRendersRef.current())
 }

 const idleGlobal: IdleGlobal = globalThis
 const requestIdleCallback = idleGlobal.requestIdleCallback
 if (typeof requestIdleCallback === 'function') {
 idleRenderHandleRef.current = requestIdleCallback(flush, { timeout: IDLE_RENDER_TIMEOUT_MS })
 return
 }

 idleRenderTimeoutRef.current = setTimeout(flush, 0)
 }, [])

 const queuePageRender = useCallback(
 (pageIndex: number) => {
 if (pageIndex < 0 || pageIndex >= pageCount) return
 if (renderedPagesRef.current.has(pageIndex)) return
 if (renderingPagesRef.current.has(pageIndex)) return
 if (queuedPagesRef.current.has(pageIndex)) return

 clearPageFailure(pageIndex)
 clearPageRenderError(pageIndex)
 queuedPagesRef.current.add(pageIndex)
 markPageLoading(pageIndex)
 renderQueueRef.current.push(pageIndex)
 scheduleQueuedRenderFlush()
 },
 [clearPageFailure, clearPageRenderError, markPageLoading, pageCount, scheduleQueuedRenderFlush]
 )

 const schedulePageRenderRetry = useCallback(
 (pageIndex: number) => {
 if (pageIndex < 0 || pageIndex >= pageCount) return
 if (renderedPagesRef.current.has(pageIndex)) {
 clearPageRenderRetry(pageIndex)
 return
 }
 // Important: schedule retries even if the page is currently marked as "rendering".
 // renderPage() calls us from its catch branch before clearing renderingPagesRef.
 if (queuedPagesRef.current.has(pageIndex)) return
 if (pageRenderRetryTimeoutsRef.current.has(pageIndex)) return

 const attempts = pageRenderRetryCountsRef.current.get(pageIndex) || 0
 if (attempts >= MAX_PAGE_RENDER_RETRIES) {
 markPageFailed(pageIndex)
 return
 }

 pageRenderRetryCountsRef.current.set(pageIndex, attempts + 1)
 markPageLoading(pageIndex)

 const timeoutId = setTimeout(() => {
 if (pageRenderRetryTimeoutsRef.current.get(pageIndex) === timeoutId) {
 pageRenderRetryTimeoutsRef.current.delete(pageIndex)
 }
 if (renderedPagesRef.current.has(pageIndex)) {
 clearPageRenderRetry(pageIndex)
 unmarkPageLoading(pageIndex)
 return
 }
 if (renderingPagesRef.current.has(pageIndex) || queuedPagesRef.current.has(pageIndex)) {
 return
 }

 queuePageRender(pageIndex)
 detachPromise(flushQueuedPageRendersRef.current())
 }, PAGE_RENDER_RETRY_DELAY_MS)

 pageRenderRetryTimeoutsRef.current.set(pageIndex, timeoutId)
 },
 [clearPageRenderRetry, markPageFailed, markPageLoading, pageCount, queuePageRender, unmarkPageLoading]
 )

 const releasePage = useCallback((pageIndex: number) => {
 const activeRenderTask = renderTasksRef.current.get(pageIndex)
 activeRenderTask?.cancel()
 renderTasksRef.current.delete(pageIndex)
 renderingPagesRef.current.delete(pageIndex)
 queuedPagesRef.current.delete(pageIndex)
 renderQueueRef.current = renderQueueRef.current.filter((candidate) => candidate !== pageIndex)
 clearPageRenderRetry(pageIndex)
 unmarkPageLoading(pageIndex)

 const canvas = canvasRefs.current.get(pageIndex)
 const offscreenApi = offscreenRenderApiRef.current
 if (transferredPageCanvasRef.current.has(pageIndex) && offscreenRenderEnabled && offscreenApi) {
 detachPromise(offscreenApi.releasePage(pageIndex).catch(() => {}))
 } else if (canvas) {
 canvas.width = 0
 canvas.height = 0
 }

 unmarkPageRendered(pageIndex)
 }, [clearPageRenderRetry, offscreenRenderEnabled, unmarkPageLoading, unmarkPageRendered])

 const retryPageRender = useCallback((pageIndex: number) => {
 if (pageIndex < 0 || pageIndex >= pageCount) return

 releasePage(pageIndex)
 clearPageFailure(pageIndex)
 queuePageRender(pageIndex)
 detachPromise(flushQueuedPageRendersRef.current())
 }, [clearPageFailure, pageCount, queuePageRender, releasePage])

 const trimRenderedPagePool = useCallback((pageIndex: number) => {
 const stalePageIndices = selectPdfPagesToReleaseForPool({
 renderedPages: renderedPagesRef.current,
 keepPage: pageIndex,
 maxRetainedPages: MAX_RETAINED_PAGE_CANVASES,
 retainedPages: retainedPageIndicesRef.current,
 queuedPages: queuedPagesRef.current,
 renderingPages: renderingPagesRef.current,
 })

 for (const stalePageIndex of stalePageIndices) {
 releasePage(stalePageIndex)
 }
 }, [releasePage])

 // Invalidate any in-flight renders when doc/scale changes.
 useEffect(() => {
 renderGenRef.current += 1
 clearQueuedRenderFlush()
 cancelRenderTasks()
 clearPageRenderRetry()
 clearPageRenderError()
 activeRenderCountRef.current = 0
 queuedPagesRef.current.clear()
 retainedPageIndicesRef.current.clear()
 renderQueueRef.current = []
 renderedPagesRef.current = new Set()
 renderingPagesRef.current.clear()
 setRenderedPages(new Set())
 setLoadingPages(new Set())
 setFailedPages(new Set())
 }, [cancelRenderTasks, clearPageRenderError, clearPageRenderRetry, clearQueuedRenderFlush, pdfDoc, scale])

 useEffect(() => {
 const doc = pdfDoc
 return () => {
 clearQueuedRenderFlush()
 cancelRenderTasks()
 clearPageRenderRetry()
 clearPageRenderError()
 if (!doc) return
 detachPromise(doc.cleanup())
 }
 }, [cancelRenderTasks, clearPageRenderError, clearPageRenderRetry, clearQueuedRenderFlush, pdfDoc])

 const renderPage = useCallback(
 async (pageIndex: number) => {
 const doc = pdfDoc
 const totalPages = pageCount
 if (!doc || !totalPages) return
 if (pageIndex < 0 || pageIndex >= totalPages) return

 // Prevent duplicate renders for the same page.
 if (renderedPagesRef.current.has(pageIndex)) return
 if (renderingPagesRef.current.has(pageIndex)) return

 const gen = renderGenRef.current
 renderingPagesRef.current.add(pageIndex)
 let activeRenderTask: RenderTask | null = null
 let releasePageResources: (() => void) | null = null
 let usedOffscreenWorker = false
 try {
 const page = await doc.getPage(pageIndex + 1)
 releasePageResources = () => {
 page.cleanup()
 releasePageResources = null
 }
 if (renderGenRef.current !== gen) return
 const baseViewport = page.getViewport({ scale: 1 })
 const viewport = page.getViewport({ scale })
 rememberPageAspectRatio(pageIndex, viewport.width, viewport.height)
 rememberPageBaseSize(pageIndex, baseViewport.width, baseViewport.height)

 const api = offscreenRenderEnabled ? offscreenRenderApiRef.current : null
 if (api) {
 usedOffscreenWorker = true
 releasePageResources?.()
 const attached = await attachOffscreenPageCanvas(pageIndex)
 if (!attached) {
 throw new Error(`Unable to attach OffscreenCanvas for page ${pageIndex}`)
 }

 let timeoutId: ReturnType<typeof setTimeout> | null = null
 try {
 await Promise.race([
 api.renderPage({ pageIndex, scale }),
 new Promise<never>((_, reject) => {
 timeoutId = setTimeout(() => {
 reject(new Error(`Offscreen render timed out for page ${pageIndex + 1}`))
 }, OFFSCREEN_PAGE_RENDER_TIMEOUT_MS)
 }),
 ])
 } finally {
 if (timeoutId) clearTimeout(timeoutId)
 }
 if (renderGenRef.current !== gen) return

 if (markPageRendered(pageIndex)) {
 trimRenderedPagePool(pageIndex)
 }
 return
 }

 const canvas = canvasRefs.current.get(pageIndex)
 if (!canvas) {
 if (renderGenRef.current !== gen) return
 setPageRenderError(pageIndex, `Canvas not mounted for page ${pageIndex + 1}`)
 schedulePageRenderRetry(pageIndex)
 return
 }

 canvas.width = Math.ceil(viewport.width)
 canvas.height = Math.ceil(viewport.height)
 const canvasContext = canvas.getContext('2d', { alpha: false })
 if (!canvasContext) {
 if (renderGenRef.current !== gen) return
 setPageRenderError(pageIndex, `Unable to acquire 2D canvas context for page ${pageIndex + 1}`)
 schedulePageRenderRetry(pageIndex)
 return
 }

 canvasContext.clearRect(0, 0, canvas.width, canvas.height)
 const renderTask = page.render({ canvas: null, canvasContext, viewport, background: '#ffffff' })
 activeRenderTask = renderTask
 renderTasksRef.current.set(pageIndex, renderTask)

 let renderTimeoutId: ReturnType<typeof setTimeout> | null = null

 try {
 await Promise.race([
 (async () => {
 await renderTask.promise
 })(),
 new Promise<never>((_, reject) => {
 renderTimeoutId = setTimeout(() => {
 try {
 renderTask.cancel()
 } catch {
 // ignore
 }
 reject(new Error(`Main-thread render timed out for page ${pageIndex + 1}`))
 }, MAIN_THREAD_PAGE_RENDER_TIMEOUT_MS)
 }),
 ])
 } finally {
 if (renderTimeoutId) clearTimeout(renderTimeoutId)
 renderTimeoutId = null
 }

 releasePageResources?.()
 if (renderGenRef.current !== gen) return
 if (markPageRendered(pageIndex)) {
 trimRenderedPagePool(pageIndex)
 }
 } catch (error) {
 // OffscreenCanvas transfer is one-way; if the worker can't render a page, fall back to main-thread
 // by disabling offscreen mode and forcing a reload to remount canvas nodes.
 if (usedOffscreenWorker) {
 setPageRenderError(pageIndex, error)
 disableOffscreenRenderAndReload(error)
 return
 }
 if (renderGenRef.current !== gen) return
 setPageRenderError(pageIndex, error)
 schedulePageRenderRetry(pageIndex)
 } finally {
 if (activeRenderTask && renderTasksRef.current.get(pageIndex) === activeRenderTask) {
 renderTasksRef.current.delete(pageIndex)
 }
 releasePageResources?.()
 renderingPagesRef.current.delete(pageIndex)
 if (!pageRenderRetryTimeoutsRef.current.has(pageIndex)) {
 unmarkPageLoading(pageIndex)
 }
 }
 },
 [
 attachOffscreenPageCanvas,
 disableOffscreenRenderAndReload,
 markPageRendered,
 offscreenRenderEnabled,
 pdfDoc,
 pageCount,
 rememberPageAspectRatio,
 rememberPageBaseSize,
 setPageRenderError,
 schedulePageRenderRetry,
 scale,
 trimRenderedPagePool,
 unmarkPageLoading,
 ]
 )

 const flushQueuedPageRenders = useCallback(async () => {
 while (activeRenderCountRef.current < MAX_CONCURRENT_RENDERS && renderQueueRef.current.length > 0) {
 const pageIndex = renderQueueRef.current.shift()
 if (typeof pageIndex !== 'number' || !Number.isFinite(pageIndex)) continue

 queuedPagesRef.current.delete(pageIndex)
 if (renderedPagesRef.current.has(pageIndex)) {
 unmarkPageLoading(pageIndex)
 continue
 }
 if (renderingPagesRef.current.has(pageIndex)) {
 unmarkPageLoading(pageIndex)
 continue
 }

 activeRenderCountRef.current += 1
 detachPromise(
 renderPage(pageIndex).finally(() => {
 activeRenderCountRef.current = Math.max(0, activeRenderCountRef.current - 1)
 if (renderQueueRef.current.length > 0) {
 scheduleQueuedRenderFlush()
 }
 })
 )
 }
 }, [renderPage, scheduleQueuedRenderFlush, unmarkPageLoading])

 flushQueuedPageRendersRef.current = flushQueuedPageRenders

 // Re-observe after scale changes so the first visible pages are re-queued when an
 // initial render was invalidated by the post-layout scale measurement.
 // Render pages on-demand as they enter the viewport.
 useEffect(() => {
 const container = containerRef.current
 const doc = pdfDoc
 const totalPages = pageCount
 if (!container || !doc || !totalPages) return

 let cancelled = false
 const observer = new IntersectionObserver(
 (entries) => {
 if (cancelled) return
 for (const entry of entries) {
 if (!entry.isIntersecting) continue
 const idxAttr = (entry.target as HTMLElement).dataset.pageIndex
 const idx = idxAttr ? Number(idxAttr) : Number.NaN
 if (!Number.isFinite(idx)) continue
 queuePageRender(idx)
 }
 },
 {
 root: container,
 // Pre-render a bit ahead/behind for smoother scrolling.
 rootMargin: RENDER_ROOT_MARGIN,
 threshold: 0.01,
 }
 )

 // Observe all page containers.
 for (let i = 0; i < totalPages; i += 1) {
 const el = pageRefs.current.get(i)
 if (el) observer.observe(el)
 }

 // Kickstart: render the first few pages ASAP so the initial preview is visible even
 // before the observer has fully settled after layout.
 for (let pageIndex = 0; pageIndex < Math.min(totalPages, INITIAL_PDF_PAGE_PRERENDER_COUNT); pageIndex += 1) {
 queuePageRender(pageIndex)
 }
 detachPromise(flushQueuedPageRendersRef.current())

 return () => {
 cancelled = true
 observer.disconnect()
 }
 }, [pageCount, pdfDoc, queuePageRender, scale])

 useEffect(() => {
 const doc = pdfDoc
 const totalPages = pageCount
 if (!doc || !totalPages) return

 const intervalId = setInterval(() => {
 for (let pageIndex = 0; pageIndex < Math.min(totalPages, INITIAL_PDF_PAGE_PRERENDER_COUNT); pageIndex += 1) {
 if (renderedPagesRef.current.has(pageIndex)) continue
 if (renderingPagesRef.current.has(pageIndex)) continue
 if (queuedPagesRef.current.has(pageIndex)) continue
 retryPageRender(pageIndex)
 }
 }, FIRST_PAGE_RENDER_WATCHDOG_INTERVAL_MS)

 return () => {
 clearInterval(intervalId)
 }
 }, [pageCount, pdfDoc, retryPageRender, scale])

 useEffect(() => {
 const container = containerRef.current
 const doc = pdfDoc
 const totalPages = pageCount
 if (!container || !doc || !totalPages) return

 let cancelled = false
 const retentionObserver = new IntersectionObserver(
 (entries) => {
 if (cancelled) return
 for (const entry of entries) {
 const idxAttr = (entry.target as HTMLElement).dataset.pageIndex
 const idx = idxAttr ? Number(idxAttr) : Number.NaN
 if (!Number.isFinite(idx)) continue
 if (entry.isIntersecting) {
 retainedPageIndicesRef.current.add(idx)
 continue
 }
 retainedPageIndicesRef.current.delete(idx)
 if (!renderedPagesRef.current.has(idx)) continue
 releasePage(idx)
 }
 },
 {
 root: container,
 rootMargin: RETAIN_ROOT_MARGIN,
 threshold: 0,
 }
 )

 for (let i = 0; i < totalPages; i += 1) {
 const el = pageRefs.current.get(i)
 if (el) retentionObserver.observe(el)
 }

 return () => {
 cancelled = true
 retentionObserver.disconnect()
 }
 }, [pageCount, pdfDoc, releasePage])

 const resolvedBoxesByPage = useMemo(() => {
 if (boxesByPage) return boxesByPage

 const map = new Map<number, Box[]>()
 for (const block of blocks) {
 const kind = classifyParsingBlock(block)
 for (const position of block.positions || []) {
 const pages = position.pages?.length ? position.pages : [0]
 for (const pageIndex of pages) {
 const list = map.get(pageIndex) || []
 list.push({ id: block.id, kind, position })
 map.set(pageIndex, list)
 }
 }
 }
 return map
 }, [blocks, boxesByPage])
 const resolvedBlockIdToPageIndex = useMemo(() => {
 if (blockIdToPageIndex) return blockIdToPageIndex

 const map = new Map<string, number>()
 for (const block of blocks) {
 const pageIndex = block.positions.find((position) => position.pages?.length)?.pages?.[0]
 if (typeof pageIndex !== 'number' || !Number.isFinite(pageIndex)) continue
 map.set(block.id, pageIndex)
 }
 return map
 }, [blockIdToPageIndex, blocks])

 const activeSet = useMemo(() => new Set(activeBlockIds || []), [activeBlockIds])
 const hoveredSet = useMemo(() => new Set(hoveredBlockIds || []), [hoveredBlockIds])

 const handleHoverBlock = useCallback(
 (blockId: string | null) => {
 if (!onHoverBlockId) return
 onHoverBlockId(blockId)
 },
 [onHoverBlockId]
 )

 const handleClickBlock = useCallback(
 (blockId: string, hint?: ParsingEditFocusHint) => {
 if (!onClickBlockId) return
 onClickBlockId(blockId, hint)
 },
 [onClickBlockId]
 )

 useEffect(() => {
 const firstActive = (activeBlockIds || [])[0]
 if (!firstActive) return
 const pageIndex = resolvedBlockIdToPageIndex.get(firstActive)
 if (pageIndex == null) return
 const el = pageRefs.current.get(pageIndex)
 const reduceMotion =
 globalThis.window !== undefined &&
 typeof globalThis.window.matchMedia === 'function' &&
 globalThis.window.matchMedia('(prefers-reduced-motion: reduce)').matches
 el?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' })
 }, [activeBlockIds, resolvedBlockIdToPageIndex])

 useEffect(() => {
 if (process.env.NODE_ENV !== 'development') return
 if (globalThis.window === undefined) return

 const win = globalThis.window as typeof globalThis.window & {
 __mimirqPdfViewerDebug?: Record<string, unknown>
 }

 win.__mimirqPdfViewerDebug = {
 activeRenderCount: activeRenderCountRef.current,
 failedPages: Array.from(failedPages),
 loadingPages: Array.from(loadingPages),
 pageCount,
 pageErrors: Object.fromEntries(pageRenderErrorsRef.current.entries()),
 queuedPages: Array.from(queuedPagesRef.current),
 renderedPages: Array.from(renderedPagesRef.current),
 renderingPages: Array.from(renderingPagesRef.current),
 retryCounts: Object.fromEntries(pageRenderRetryCountsRef.current.entries()),
 scale,
 }

 return () => {
 delete win.__mimirqPdfViewerDebug
 }
 }, [failedPages, loadingPages, pageCount, pageRenderErrors, renderedPages, scale])

 if (!file) {
 return (
 <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
 未选择 PDF
 </div>
 )
 }

 if (isLoading) {
 return (
 <div className="flex h-full items-center justify-center text-muted-foreground">
 <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
 正在加载 PDF...
 </div>
 )
 }

 if (loadError || !pdfDoc) {
 return (
 <div className="flex h-full items-center justify-center px-6">
 <div className="max-w-md rounded-2xl border border-border/60 bg-card p-5 text-center shadow-sm">
 <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
 <AlertCircle className="h-5 w-5" />
 </div>
 <div className="text-sm font-semibold text-foreground">PDF 加载失败</div>
 <div className="mt-1 text-xs text-muted-foreground">{loadError || '请重试，或重新上传该文件。'}</div>
 <div className="mt-4 flex justify-center gap-2">
 <Button variant="outline" size="sm" className="gap-1.5" onClick={retryLoad}>
 <RotateCcw className="h-4 w-4" />
 重试
 </Button>
 </div>
 </div>
 </div>
 )
 }

 return (
 <div ref={containerRef} className="h-full overflow-y-auto overscroll-contain no-scrollbar px-4 py-6">
 <div ref={contentRef} className="mx-auto flex w-full max-w-4xl flex-col gap-6">
 {pageNumbers.map((pageNumber) => {
 const index = pageNumber - 1
 const pageBoxes = resolvedBoxesByPage.get(index) || []
 const pageBaseSize = pageBaseSizes.get(index) ?? defaultPageBaseSize
 const isRendered = renderedPages.has(index)
 const isPageLoading = loadingPages.has(index)
 const isPageFailed = failedPages.has(index)
 const failedPlaceholderLabel = '渲染失败，点击重试'
 const pagePlaceholderLabel = isPageLoading ? '渲染中...' : '滚动后加载...'
 const pageAspectRatio = pageAspectRatios.get(index) ?? defaultPageAspectRatio
 const pageStyle = pageAspectRatio
 ? { aspectRatio: String(pageAspectRatio) }
 : { minHeight: DEFAULT_PAGE_PLACEHOLDER_HEIGHT }

 return (
 <div
 key={`page-${pageNumber}-${renderModeKey}`}
 ref={(el) => {
 if (el) {
 pageRefs.current.set(index, el)
 return
 }
 pageRefs.current.delete(index)
 }}
 data-page-index={index}
 className="relative rounded-xl bg-card shadow-sm ring-1 ring-border/60"
 style={pageStyle}
 >
 <canvas
 ref={(el) => {
 if (el) {
 canvasRefs.current.set(index, el)
 return
 }
 canvasRefs.current.delete(index)
 }}
 className="block h-auto w-full rounded-xl"
 style={pageAspectRatio ? { aspectRatio: String(pageAspectRatio) } : undefined}
 />
 {isRendered ? null : isPageFailed ? (
 <button
 type="button"
 className="absolute inset-0 flex items-center justify-center rounded-xl bg-card text-xs font-medium text-foreground transition hover:bg-card"
 onClick={() => retryPageRender(index)}
 >
 <RotateCcw className="mr-2 h-4 w-4" />
 {failedPlaceholderLabel}
 </button>
 ) : (
 <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-card text-xs text-muted-foreground">
 {isPageLoading ? (
 <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
 ) : null}
 {pagePlaceholderLabel}
 </div>
 )}
 <BboxOverlay
 items={pageBoxes}
 scale={scale}
 pageBaseWidth={pageBaseSize?.width ?? null}
 pageBaseHeight={pageBaseSize?.height ?? null}
 showAll={showAllBoxes}
 activeIds={activeSet}
 hoveredIds={hoveredSet}
 onHoverId={handleHoverBlock}
 onClickId={handleClickBlock}
 />
 </div>
 )
 })}
 </div>
 </div>
 )
}
