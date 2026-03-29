/**
 * PdfPreview - PDF panel for chunk preview (best-effort).
 *
 * Highlights selected/hovered chunks by mapping chunk char ranges to parsing position-tag blocks.
 */
'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Remote } from 'comlink'
import { AlertCircle } from 'lucide-react'
import dynamic from 'next/dynamic'

import { useChunkPreview } from '@/components/chunk-preview/context'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/ui/page-loading'
import { Skeleton } from '@/components/ui/skeleton'
import {
  computePdfPreviewData,
  findBlockIdsForChunkIndex,
  type PdfPreviewComputationResult,
} from '@/lib/pdf-preview-computation'
import { detachPromise } from '@/lib/utils'
import type { PdfPreviewWorkerApi } from '@/workers/pdf-preview.worker'

const PdfViewer = dynamic(() => import('@/components/parsing/pdf-viewer').then((mod) => mod.PdfViewer), {
  ssr: false,
  loading: () => <Skeleton className="h-[400px] w-full" />,
})

function PdfPreviewLoadingSkeleton() {
  return (
    <div className="flex h-full items-center justify-center px-6">
      <div className="w-full max-w-2xl rounded-2xl border border-border/60 bg-card/90 p-6 shadow-soft">
        <PageLoading
          className="min-h-0 flex-none justify-start"
          message="正在预计算 PDF 高亮..."
          srMessage="Preparing PDF highlight overlays"
        />
        <div className="mt-5 space-y-3">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-32 w-full rounded-xl" />
          <Skeleton className="h-32 w-full rounded-xl" />
        </div>
      </div>
    </div>
  )
}

export function PdfPreview() {
  const {
    currentFile,
    previewData,
    hoveredChunkIndex,
    selectedChunkIndex,
    includeOriginalText,
    setHoveredChunkIndex,
    setSelectedChunkIndex,
  } = useChunkPreview()

  const [showAllBoxes, setShowAllBoxes] = useState(false)
  const [pdfComputation, setPdfComputation] = useState<PdfPreviewComputationResult | null>(null)
  const [isPreparingPdfPreview, setIsPreparingPdfPreview] = useState(false)
  const [pdfPreparationError, setPdfPreparationError] = useState<string | null>(null)
  const pdfPreviewSeqRef = useRef(0)
  const pdfPreviewWorkerRef = useRef<Worker | null>(null)
  const pdfPreviewApiRef = useRef<Remote<PdfPreviewWorkerApi> | null>(null)
  const pdfPreviewWorkerDisabledRef = useRef(false)

  const isPdf = useMemo(() => {
    const ft = String(previewData?.file_type || '').toLowerCase()
    if (ft === 'pdf') return true
    const name = String(currentFile?.name || '').toLowerCase()
    return name.endsWith('.pdf')
  }, [currentFile?.name, previewData?.file_type])

  const rawOriginal = previewData?.original_text || ''
  const previewChunks = useMemo(() => previewData?.chunks ?? [], [previewData?.chunks])

  useEffect(() => {
    const seq = ++pdfPreviewSeqRef.current
    let cancelled = false

    if (!rawOriginal) {
      setPdfComputation(null)
      setPdfPreparationError(null)
      setIsPreparingPdfPreview(false)
      return
    }

    setPdfComputation(null)
    setPdfPreparationError(null)
    setIsPreparingPdfPreview(true)

    const applyResult = (result: PdfPreviewComputationResult) => {
      if (cancelled || pdfPreviewSeqRef.current !== seq) return
      setPdfComputation(result)
      setIsPreparingPdfPreview(false)
    }

    const handleMainThreadFailure = (error: unknown) => {
      console.warn('PDF preview preprocessing failed', error)
      if (cancelled || pdfPreviewSeqRef.current !== seq) return
      setPdfPreparationError('PDF 高亮预处理失败，请刷新后重试。')
      setPdfComputation(null)
      setIsPreparingPdfPreview(false)
    }

    const computeOnMainThread = () => {
      try {
        applyResult(computePdfPreviewData({ rawOriginal, previewChunks }))
      } catch (error) {
        handleMainThreadFailure(error)
      }
    }

    if (pdfPreviewWorkerDisabledRef.current || typeof Worker === 'undefined') {
      computeOnMainThread()
      return () => {
        cancelled = true
      }
    }

    detachPromise((async () => {
      try {
        let api = pdfPreviewApiRef.current
        if (!pdfPreviewWorkerRef.current || !api) {
          const { wrap } = await import('comlink')
          if (cancelled) return
          pdfPreviewWorkerRef.current = new Worker(
            new URL('../../../../../workers/pdf-preview.worker.ts', import.meta.url),
            { type: 'module' }
          )
          api = wrap<PdfPreviewWorkerApi>(pdfPreviewWorkerRef.current)
          pdfPreviewApiRef.current = api
        }

        const result = await api.computePdfPreviewData({ rawOriginal, previewChunks })
        applyResult(result)
      } catch (error) {
        console.warn('PDF preview worker failed; falling back to main thread', error)
        pdfPreviewWorkerDisabledRef.current = true
        computeOnMainThread()
      }
    })())

    return () => {
      cancelled = true
    }
  }, [previewChunks, rawOriginal])

  useEffect(() => {
    return () => {
      pdfPreviewApiRef.current = null
      pdfPreviewWorkerRef.current?.terminate()
      pdfPreviewWorkerRef.current = null
    }
  }, [])

  const blocksWithPositions = useMemo(
    () => pdfComputation?.blocksWithPositions || [],
    [pdfComputation?.blocksWithPositions]
  )
  const blockRanges = useMemo(
    () => pdfComputation?.blockRanges || [],
    [pdfComputation?.blockRanges]
  )
  const chunkRanges = useMemo(
    () => pdfComputation?.chunkRanges || [],
    [pdfComputation?.chunkRanges]
  )
  const blockIdToChunkIndex = useMemo(
    () => new Map(pdfComputation?.blockIdToChunkIndexEntries || []),
    [pdfComputation?.blockIdToChunkIndexEntries]
  )

  const selectedBlockIds = useMemo(
    () =>
      findBlockIdsForChunkIndex({
        chunkIndex: selectedChunkIndex,
        blockRanges,
        chunkRanges,
      }),
    [blockRanges, chunkRanges, selectedChunkIndex]
  )
  const hoveredBlockIds = useMemo(
    () =>
      findBlockIdsForChunkIndex({
        chunkIndex: hoveredChunkIndex,
        blockRanges,
        chunkRanges,
      }),
    [blockRanges, chunkRanges, hoveredChunkIndex]
  )

  const activeBlockIds = selectedBlockIds.length ? selectedBlockIds : hoveredBlockIds

  const handleHoverBlockId = useCallback(
    (blockId: string | null) => {
      if (!blockId) {
        setHoveredChunkIndex(null)
        return
      }
      const idx = blockIdToChunkIndex.get(blockId)
      if (typeof idx !== 'number' || !Number.isFinite(idx)) return
      setHoveredChunkIndex(idx)
    },
    [blockIdToChunkIndex, setHoveredChunkIndex]
  )

  const handleClickBlockId = useCallback(
    (blockId: string | null) => {
      if (!blockId) return
      const idx = blockIdToChunkIndex.get(blockId)
      if (typeof idx !== 'number' || !Number.isFinite(idx)) return
      setSelectedChunkIndex(idx)
    },
    [blockIdToChunkIndex, setSelectedChunkIndex]
  )

  if (!isPdf) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        当前文件不是 PDF
      </div>
    )
  }

  if (!currentFile) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        未选择文件
      </div>
    )
  }

  if (!rawOriginal) {
    return (
      <div className="flex h-full items-center justify-center px-6">
        <div className="max-w-md rounded-2xl border border-border/60 bg-card p-5 text-center shadow-sm">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-warning/10 text-warning">
            <AlertCircle className="h-5 w-5" />
          </div>
          <div className="text-sm font-semibold text-foreground">无法显示 PDF 高亮</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {includeOriginalText
              ? '后端未返回 original_text（可能被 original_text_max_chars 限制）。'
              : '当前关闭了 include_original_text（预览性能设置）。'}
          </div>
        </div>
      </div>
    )
  }

  if (isPreparingPdfPreview && !pdfComputation) {
    return <PdfPreviewLoadingSkeleton />
  }

  if (pdfPreparationError) {
    return (
      <div className="flex h-full items-center justify-center px-6">
        <div className="max-w-md rounded-2xl border border-border/60 bg-card p-5 text-center shadow-sm">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
            <AlertCircle className="h-5 w-5" />
          </div>
          <div className="text-sm font-semibold text-foreground">PDF 高亮预处理失败</div>
          <div className="mt-1 text-xs text-muted-foreground">{pdfPreparationError}</div>
        </div>
      </div>
    )
  }

  if (blocksWithPositions.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-6">
        <div className="max-w-md rounded-2xl border border-border/60 bg-card p-5 text-center shadow-sm">
          <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-warning/10 text-warning">
            <AlertCircle className="h-5 w-5" />
          </div>
          <div className="text-sm font-semibold text-foreground">未检测到 PDF 位置标签</div>
          <div className="mt-1 text-xs text-muted-foreground">
            该解析结果不包含 @@page\tl\tr\tt\tb## 标签，无法做 PDF 框选高亮。你仍可使用“源码”面板做 offset 高亮。
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="relative h-full">
      <div className="absolute right-3 top-3 z-10 flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 rounded-full bg-background/70 px-3 backdrop-blur"
          onClick={() => setShowAllBoxes((prev) => !prev)}
        >
          {showAllBoxes ? '仅高亮' : '显示全部框'}
        </Button>
      </div>
      <PdfViewer
        file={currentFile}
        blocks={blocksWithPositions}
        activeBlockIds={activeBlockIds}
        hoveredBlockIds={hoveredBlockIds}
        showAllBoxes={showAllBoxes}
        onHoverBlockId={handleHoverBlockId}
        onClickBlockId={handleClickBlockId}
      />
    </div>
  )
}
