/**
 * PdfViewer - render PDF pages with optional layout box overlays.
 */
'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import * as pdfjsLib from 'pdfjs-dist'
import { ParsingBlock, ParsingPosition } from '@/lib/parsing-positions'

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url
).toString()

type Box = {
  blockId: string
  position: ParsingPosition
}

interface PdfViewerProps {
  file?: File | null
  blocks?: ParsingBlock[]
  activeBlockId?: string | null
  hoveredBlockId?: string | null
  showAllBoxes?: boolean
}

export function PdfViewer({
  file,
  blocks = [],
  activeBlockId,
  hoveredBlockId,
  showAllBoxes = true,
}: PdfViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRefs = useRef<Map<number, HTMLCanvasElement>>(new Map())
  const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null)
  const [pageCount, setPageCount] = useState(0)
  const [scale, setScale] = useState(1)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function loadPdf() {
      if (!file) {
        setPdfDoc(null)
        setPageCount(0)
        return
      }

      setIsLoading(true)
      try {
        const data = await file.arrayBuffer()
        const doc = await pdfjsLib.getDocument({ data }).promise
        if (cancelled) return
        setPdfDoc(doc)
        setPageCount(doc.numPages)
      } catch {
        if (!cancelled) {
          setPdfDoc(null)
          setPageCount(0)
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    loadPdf()
    return () => {
      cancelled = true
    }
  }, [file])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !pdfDoc) return

    let raf = 0
    const updateScale = () => {
      if (!container || !pdfDoc) return
      const width = container.clientWidth
      if (!width) return
      pdfDoc.getPage(1).then((page) => {
        const viewport = page.getViewport({ scale: 1 })
        const nextScale = width / viewport.width
        setScale((prev) => (Math.abs(prev - nextScale) > 0.01 ? nextScale : prev))
      })
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
    if (!pdfDoc || !pageCount) return

    async function renderPages() {
      for (let i = 1; i <= pageCount; i += 1) {
        const page = await pdfDoc.getPage(i)
        if (cancelled) return
        const viewport = page.getViewport({ scale })
        const canvas = canvasRefs.current.get(i - 1)
        if (!canvas) continue
        const context = canvas.getContext('2d')
        if (!context) continue
        canvas.width = viewport.width
        canvas.height = viewport.height
        await page.render({ canvasContext: context, viewport }).promise
      }
    }

    renderPages()
    return () => {
      cancelled = true
    }
  }, [pdfDoc, pageCount, scale])

  const boxesByPage = useMemo(() => {
    const map = new Map<number, Box[]>()
    for (const block of blocks) {
      for (const position of block.positions || []) {
        const pages = position.pages?.length ? position.pages : [0]
        for (const pageIndex of pages) {
          const list = map.get(pageIndex) || []
          list.push({ blockId: block.id, position })
          map.set(pageIndex, list)
        }
      }
    }
    return map
  }, [blocks])

  useEffect(() => {
    if (!activeBlockId) return
    const block = blocks.find((item) => item.id === activeBlockId)
    const pageIndex = block?.positions?.[0]?.pages?.[0]
    if (pageIndex == null) return
    const el = pageRefs.current.get(pageIndex)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [activeBlockId, blocks])

  if (!file) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400">
        未选择 PDF
      </div>
    )
  }

  if (isLoading || !pdfDoc) {
    return (
      <div className="flex h-full items-center justify-center text-gray-400">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        正在加载 PDF...
      </div>
    )
  }

  return (
    <div ref={containerRef} className="h-full overflow-y-auto px-4 py-6">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
        {Array.from({ length: pageCount }).map((_, index) => {
          const pageBoxes = boxesByPage.get(index) || []
          return (
            <div
              key={`page-${index}`}
              ref={(el) => {
                if (el) pageRefs.current.set(index, el)
              }}
              className="relative rounded-xl border border-gray-200 bg-white shadow-sm"
            >
              <canvas
                ref={(el) => {
                  if (el) canvasRefs.current.set(index, el)
                }}
                className="block h-auto w-full rounded-xl"
              />
              <div className="pointer-events-none absolute inset-0">
                {pageBoxes.map((box, boxIndex) => {
                  if (!showAllBoxes && box.blockId !== activeBlockId && box.blockId !== hoveredBlockId) {
                    return null
                  }
                  const { left, right, top, bottom } = box.position
                  const x = Math.min(left, right) * scale
                  const y = Math.min(top, bottom) * scale
                  const width = Math.abs(right - left) * scale
                  const height = Math.abs(bottom - top) * scale
                  const isActive = box.blockId === activeBlockId
                  const isHovered = box.blockId === hoveredBlockId
                  const baseColor = isActive ? 'border-amber-500 bg-amber-200/20' : 'border-sky-400/60'
                  const hoverColor = isHovered ? 'border-sky-500 bg-sky-200/20' : ''
                  return (
                    <div
                      key={`box-${index}-${boxIndex}`}
                      className={`absolute rounded border ${baseColor} ${hoverColor}`}
                      style={{ left: x, top: y, width, height }}
                    />
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

