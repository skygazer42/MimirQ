/**
 * PdfViewer - render PDF pages with optional layout box overlays.
 */
'use client'

import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { AlertCircle, Loader2, RotateCcw } from 'lucide-react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import { ParsingBlock } from '@/lib/parsing-positions'
import { toPrimitiveString } from '@/lib/primitive-text'
import { Button } from '@/components/ui/button'
import { BboxOverlay, type BboxOverlayItem } from '@/components/parsing/bbox-overlay'
import { detachPromise } from '@/lib/utils'


type Box = BboxOverlayItem

interface PdfViewerProps {
  file?: File | null
  blocks?: ParsingBlock[]
  boxesByPage?: Map<number, Box[]> | null
  activeBlockIds?: string[] | null
  hoveredBlockIds?: string[] | null
  showAllBoxes?: boolean
  onHoverBlockId?: (blockId: string | null) => void
  onClickBlockId?: (blockId: string) => void
}

export function PdfViewer({
  file,
  blocks = [],
  boxesByPage,
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
  const [renderedPages, setRenderedPages] = useState<Set<number>>(new Set())
  const renderingPagesRef = useRef<Set<number>>(new Set())
  const renderGenRef = useRef(0)
  const pageNumbers = useMemo(() => Array.from({ length: pageCount }, (_, pageNumber) => pageNumber + 1), [pageCount])

  const retryLoad = useCallback(() => {
    setReloadTick((prev) => prev + 1)
  }, [])

  useEffect(() => {
    let cancelled = false

    async function loadPdf() {
      if (!file) {
        setPdfDoc(null)
        setPageCount(0)
        setRenderedPages(new Set())
        setLoadError(null)
        return
      }

      setIsLoading(true)
      setLoadError(null)
      try {
        const data = new Uint8Array(await file.arrayBuffer())
        const pdfjsLib = await import('pdfjs-dist/webpack.mjs')
        const offscreenCanvasSupported = Boolean(pdfjsLib.FeatureTest.isOffscreenCanvasSupported)
        const doc = await pdfjsLib.getDocument({
          data,
          isOffscreenCanvasSupported: offscreenCanvasSupported,
          enableHWA: offscreenCanvasSupported,
        }).promise
        if (cancelled) return
        setPdfDoc(doc)
        setPageCount(doc.numPages)
        setRenderedPages(new Set())
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : toPrimitiveString(err)
          setLoadError(message || 'PDF 加载失败')
          setPdfDoc(null)
          setPageCount(0)
          setRenderedPages(new Set())
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    loadPdf()
    return () => {
      cancelled = true
    }
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
	        setScale((prev) => (Math.abs(prev - nextScale) > 0.01 ? nextScale : prev))
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

  // Invalidate any in-flight renders when doc/scale changes.
  useEffect(() => {
    renderGenRef.current += 1
    renderingPagesRef.current.clear()
    setRenderedPages(new Set())
  }, [pdfDoc, scale])

  const renderPage = useCallback(
    async (pageIndex: number) => {
      const doc = pdfDoc
      const totalPages = pageCount
      if (!doc || !totalPages) return
      if (pageIndex < 0 || pageIndex >= totalPages) return

      // Prevent duplicate renders for the same page.
      if (renderedPages.has(pageIndex)) return
      if (renderingPagesRef.current.has(pageIndex)) return

      const gen = renderGenRef.current
      renderingPagesRef.current.add(pageIndex)
      try {
        const page = await doc.getPage(pageIndex + 1)
        if (renderGenRef.current !== gen) return
        const viewport = page.getViewport({ scale })
        const canvas = canvasRefs.current.get(pageIndex)
        if (!canvas) return

        canvas.width = Math.ceil(viewport.width)
        canvas.height = Math.ceil(viewport.height)
        await page.render({ canvas, viewport }).promise
        if (renderGenRef.current !== gen) return

        setRenderedPages((prev) => {
          if (prev.has(pageIndex)) return prev
          const next = new Set(prev)
          next.add(pageIndex)
          return next
        })
      } catch {
        // Best-effort: leave it as not rendered; user can scroll away/back to retry.
      } finally {
        renderingPagesRef.current.delete(pageIndex)
      }
    },
    [pdfDoc, pageCount, renderedPages, scale]
  )

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
          detachPromise(renderPage(idx))
        }
      },
      {
        root: container,
        // Pre-render a bit ahead/behind for smoother scrolling.
        rootMargin: '800px 0px 800px 0px',
        threshold: 0.01,
      }
    )

    // Observe all page containers.
    for (let i = 0; i < totalPages; i += 1) {
      const el = pageRefs.current.get(i)
      if (el) observer.observe(el)
    }

    // Kickstart: render first page ASAP.
    detachPromise(renderPage(0))

    return () => {
      cancelled = true
      observer.disconnect()
    }
  }, [pdfDoc, pageCount, renderPage])

  const resolvedBoxesByPage = useMemo(() => {
    if (boxesByPage) return boxesByPage

    const map = new Map<number, Box[]>()
    for (const block of blocks) {
      for (const position of block.positions || []) {
        const pages = position.pages?.length ? position.pages : [0]
        for (const pageIndex of pages) {
          const list = map.get(pageIndex) || []
          list.push({ id: block.id, position })
          map.set(pageIndex, list)
        }
      }
    }
    return map
  }, [blocks, boxesByPage])

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
    (blockId: string) => {
      if (!onClickBlockId) return
      onClickBlockId(blockId)
    },
    [onClickBlockId]
  )

  useEffect(() => {
    const firstActive = (activeBlockIds || [])[0]
    if (!firstActive) return
    const block = blocks.find((item) => item.id === firstActive)
    const pageIndex = block?.positions?.[0]?.pages?.[0]
    if (pageIndex == null) return
    const el = pageRefs.current.get(pageIndex)
    const reduceMotion =
      globalThis.window !== undefined &&
      typeof globalThis.window.matchMedia === 'function' &&
      globalThis.window.matchMedia('(prefers-reduced-motion: reduce)').matches
    el?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' })
  }, [activeBlockIds, blocks])

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
          const isRendered = renderedPages.has(index)
	          return (
	            <div
	              key={`page-${pageNumber}`}
              ref={(el) => {
                if (el) pageRefs.current.set(index, el)
              }}
              data-page-index={index}
	              className="relative rounded-xl bg-card shadow-sm ring-1 ring-border/60"
	            >
              <canvas
                ref={(el) => {
                  if (el) canvasRefs.current.set(index, el)
                }}
                className="block h-auto w-full rounded-xl"
              />
		              {isRendered ? null : (
		                <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground bg-background/60 rounded-xl">
		                  <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
		                  渲染中...
		                </div>
              )}
              <BboxOverlay
                items={pageBoxes}
                scale={scale}
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
