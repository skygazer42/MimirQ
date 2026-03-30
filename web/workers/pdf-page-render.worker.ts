import { expose } from 'comlink'
import 'pdfjs-dist/build/pdf.worker.mjs'
import { FeatureTest, getDocument } from 'pdfjs-dist/build/pdf.mjs'
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist/build/pdf.mjs'

type PageViewportSnapshot = {
  width: number
  height: number
}

type PageCanvasBinding = {
  pageIndex: number
  canvas: OffscreenCanvas
}

class WorkerCanvasFactory {
  constructor(_: { enableHWA?: boolean; ownerDocument?: Document | undefined } = {}) {}

  create(width: number, height: number) {
    const canvas = this._createCanvas(width, height)
    return {
      canvas,
      context: canvas.getContext('2d'),
    }
  }

  reset(canvasAndContext: { canvas: OffscreenCanvas | null; context: OffscreenCanvasRenderingContext2D | null }, width: number, height: number) {
    if (!canvasAndContext.canvas) {
      throw new Error('Canvas is not specified')
    }
    canvasAndContext.canvas.width = width
    canvasAndContext.canvas.height = height
  }

  destroy(canvasAndContext: { canvas: OffscreenCanvas | null; context: OffscreenCanvasRenderingContext2D | null }) {
    if (!canvasAndContext.canvas) {
      throw new Error('Canvas is not specified')
    }
    canvasAndContext.canvas.width = 0
    canvasAndContext.canvas.height = 0
    canvasAndContext.canvas = null
    canvasAndContext.context = null
  }

  _createCanvas(width: number, height: number) {
    return new OffscreenCanvas(width, height)
  }
}

class WorkerFilterFactory {
  constructor(_: { docId?: string; ownerDocument?: Document | undefined } = {}) {}

  addFilter() {
    return 'none'
  }

  addHCMFilter() {
    return 'none'
  }

  addAlphaFilter() {
    return 'none'
  }

  addLuminosityFilter() {
    return 'none'
  }

  addHighlightHCMFilter() {
    return 'none'
  }

  destroy() {}
}

let pdfLoadingTask: PDFDocumentLoadingTask | null = null
let pdfDoc: PDFDocumentProxy | null = null
const pageCanvases = new Map<number, OffscreenCanvas>()
const pageRenderTasks = new Map<number, RenderTask>()

function cancelPageRender(pageIndex: number) {
  pageRenderTasks.get(pageIndex)?.cancel()
  pageRenderTasks.delete(pageIndex)
}

async function cancelAllRenders() {
  for (const pageIndex of pageRenderTasks.keys()) {
    cancelPageRender(pageIndex)
  }
}

async function initializeDocument(data: Uint8Array): Promise<{ pageCount: number; firstPageViewport: PageViewportSnapshot | null }> {
  await destroy()

  const offscreenCanvasSupported = Boolean(FeatureTest.isOffscreenCanvasSupported)
  const loadingTask = getDocument({
    data,
    CanvasFactory: WorkerCanvasFactory,
    FilterFactory: WorkerFilterFactory,
    disableFontFace: true,
    useSystemFonts: false,
    isOffscreenCanvasSupported: offscreenCanvasSupported,
    enableHWA: offscreenCanvasSupported,
  })

  pdfLoadingTask = loadingTask
  const doc = await loadingTask.promise
  pdfDoc = doc

  if (doc.numPages < 1) {
    return {
      pageCount: 0,
      firstPageViewport: null,
    }
  }

  const firstPage = await doc.getPage(1)
  try {
    const viewport = firstPage.getViewport({ scale: 1 })
    return {
      pageCount: doc.numPages,
      firstPageViewport: {
        width: viewport.width,
        height: viewport.height,
      },
    }
  } finally {
    firstPage.cleanup()
  }
}

async function attachPageCanvas({ pageIndex, canvas }: PageCanvasBinding) {
  pageCanvases.set(pageIndex, canvas)
}

async function renderPage(params: { pageIndex: number; scale: number }): Promise<PageViewportSnapshot> {
  const { pageIndex, scale } = params
  const doc = pdfDoc
  if (!doc) {
    throw new Error('PDF document is not initialized')
  }

  const canvas = pageCanvases.get(pageIndex)
  if (!canvas) {
    throw new Error(`No OffscreenCanvas attached for page ${pageIndex}`)
  }

  cancelPageRender(pageIndex)

  const page = await doc.getPage(pageIndex + 1)
  let activeRenderTask: RenderTask | null = null
  try {
    const viewport = page.getViewport({ scale })
    canvas.width = Math.ceil(viewport.width)
    canvas.height = Math.ceil(viewport.height)

    const renderTask = page.render({
      canvas: canvas as unknown as HTMLCanvasElement,
      viewport,
    })
    activeRenderTask = renderTask
    pageRenderTasks.set(pageIndex, renderTask)
    await renderTask.promise

    return {
      width: viewport.width,
      height: viewport.height,
    }
  } finally {
    if (activeRenderTask && pageRenderTasks.get(pageIndex) === activeRenderTask) {
      pageRenderTasks.delete(pageIndex)
    }
    page.cleanup()
  }
}

async function releasePage(pageIndex: number) {
  cancelPageRender(pageIndex)
  const canvas = pageCanvases.get(pageIndex)
  if (!canvas) return
  canvas.width = 0
  canvas.height = 0
}

async function destroy() {
  await cancelAllRenders()

  for (const canvas of pageCanvases.values()) {
    canvas.width = 0
    canvas.height = 0
  }
  pageCanvases.clear()

  const loadingTask = pdfLoadingTask
  pdfLoadingTask = null
  pdfDoc = null

  if (!loadingTask) {
    return
  }

  try {
    await loadingTask.destroy()
  } catch {
    // Best-effort cleanup.
  }
}

const api = {
  initializeDocument,
  attachPageCanvas,
  renderPage,
  releasePage,
  cancelAllRenders,
  destroy,
}

export type PdfPageRenderWorkerApi = typeof api

expose(api)
