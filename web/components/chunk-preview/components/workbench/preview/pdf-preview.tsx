/**
 * PDF pages remain readable independently of the optional chunk overlay computation.
 */
'use client'

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { releaseProxy, wrap } from 'comlink'
import dynamic from 'next/dynamic'
import { useTranslations } from 'next-intl'

import { useChunkPreview } from '@/components/chunk-preview/context'
import { Button } from '@/components/ui/button'
import { PageLoading } from '@/components/ui/page-loading'
import { Skeleton } from '@/components/ui/skeleton'
import { computePdfPreviewData, type PdfPreviewComputationResult } from '@/lib/pdf-preview-computation'
import { reportClientWarning } from '@/lib/client-logging'
import type { ChunkPreviewResponse } from '@/types'
import type { PdfPreviewWorkerApi } from '@/workers/pdf-preview.worker'
import { isPdfOriginalFile } from './pdf-dock'

const PdfViewer = dynamic(() => import('@/components/parsing/pdf-viewer').then((mod) => mod.PdfViewer), {
  ssr: false,
  loading: () => <Skeleton className="h-[400px] w-full" />,
})

type PdfPreparation = Readonly<
  { preview: ChunkPreviewResponse; file: File } & (
    { status: 'ready'; result: PdfPreviewComputationResult } | { status: 'failed' }
  )
>

export function PdfPreview({ file, preview }: Readonly<{ file: File | null; preview: ChunkPreviewResponse }>) {
  const t = useTranslations('ChunkPreview')
  if (!isPdfOriginalFile(preview, file)) {
    return <p className="p-4 text-sm text-muted-foreground">{t('pdfPreview.states.notPdf')}</p>
  }
  if (file === null) {
    return <p className="p-4 text-sm text-muted-foreground">{t('pdfPreview.states.noFile')}</p>
  }
  return <PdfPreviewContent file={file} preview={preview} />
}

function PdfPreviewContent({ file, preview }: Readonly<{ file: File; preview: ChunkPreviewResponse }>) {
  const t = useTranslations('ChunkPreview')
  const { hoveredChunkIndex, selectedChunkIndex, setHoveredChunkIndex, setSelectedChunkIndex } = useChunkPreview()
  const [showAllBoxes, setShowAllBoxes] = useState(false)
  const [preparation, setPreparation] = useState<PdfPreparation | null>(null)
  const currentPreparation = preparation?.preview === preview && preparation.file === file ? preparation : null
  const sourceText = preview.original_text
  const rawOriginal = typeof sourceText === 'string' && sourceText !== '' ? sourceText : null

  useEffect(() => {
    if (rawOriginal === null) return
    let isCurrent = true
    let workerCleanup: (() => void) | null = null
    const input = { rawOriginal, previewChunks: preview.chunks }

    function releaseWorker() {
      const cleanup = workerCleanup
      workerCleanup = null
      cleanup?.()
    }

    async function prepare() {
      let result: PdfPreviewComputationResult | null
      if (typeof Worker === 'undefined') {
        result = computePdfPreviewData(input)
      } else {
        try {
          const worker = new Worker(new URL('../../../../../workers/pdf-preview.worker.ts', import.meta.url), {
            type: 'module',
            name: 'pdf-preview',
          })
          workerCleanup = () => worker.terminate()
          try {
            const api = wrap<PdfPreviewWorkerApi>(worker)
            result = await new Promise<PdfPreviewComputationResult | null>((resolve, reject) => {
              const onError = (event: ErrorEvent) => reject(new Error(event.message))
              const onMessageError = () => reject(new Error('PDF preview worker returned an unreadable message'))
              workerCleanup = () => {
                // Comlink drops pending calls when the proxy is released.
                resolve(null)
                worker.removeEventListener('error', onError)
                worker.removeEventListener('messageerror', onMessageError)
                try {
                  api[releaseProxy]()
                } finally {
                  worker.terminate()
                }
              }
              worker.addEventListener('error', onError)
              worker.addEventListener('messageerror', onMessageError)
              void api.computePdfPreviewData(input).then(resolve, reject)
            })
          } finally {
            releaseWorker()
          }
        } catch (error: unknown) {
          if (!isCurrent) return
          reportClientWarning('PDF preview worker failed; using local overlay computation', error)
          result = computePdfPreviewData(input)
        }
      }
      if (isCurrent && result !== null) setPreparation({ preview, file, status: 'ready', result })
    }

    void prepare().catch((error: unknown) => {
      if (!isCurrent) return
      reportClientWarning('PDF preview preprocessing failed', error)
      setPreparation({ preview, file, status: 'failed' })
    })
    return () => {
      isCurrent = false
      releaseWorker()
    }
  }, [file, preview, rawOriginal])

  const result = currentPreparation?.status === 'ready' ? currentPreparation.result : null
  const geometry = useMemo(
    () =>
      result === null
        ? null
        : {
            blockIdToChunkIndex: new Map(result.blockIdToChunkIndexEntries),
            blockIdToPageIndex: new Map(result.blockIdToPageIndexEntries),
            blockIdsByChunkIndex: new Map(result.chunkBlockIdsByIndexEntries),
            boxesByPage: new Map(result.boxesByPageEntries),
          },
    [result],
  )
  // A completed map can have no matching block for an actual source-array position.
  const selectedBlockIds = useMemo(
    () => (selectedChunkIndex === null ? [] : (geometry?.blockIdsByChunkIndex.get(selectedChunkIndex) ?? [])),
    [geometry, selectedChunkIndex],
  )
  const hoveredBlockIds = useMemo(
    () => (hoveredChunkIndex === null ? [] : (geometry?.blockIdsByChunkIndex.get(hoveredChunkIndex) ?? [])),
    [geometry, hoveredChunkIndex],
  )
  const activeBlockIds = selectedChunkIndex === null ? hoveredBlockIds : selectedBlockIds

  const handleHoverBlockId = useCallback(
    (blockId: string | null) => {
      const chunkIndex = blockId === null ? undefined : geometry?.blockIdToChunkIndex.get(blockId)
      setHoveredChunkIndex(chunkIndex === undefined ? null : chunkIndex)
    },
    [geometry, setHoveredChunkIndex],
  )
  const handleClickBlockId = useCallback(
    (blockId: string) => {
      const index = geometry?.blockIdToChunkIndex.get(blockId)
      if (index !== undefined) setSelectedChunkIndex(index)
    },
    [geometry, setSelectedChunkIndex],
  )

  let feedback: ReactNode = null
  if (rawOriginal === null) {
    feedback = (
      <p role="status" className="px-3 py-2 text-xs text-muted-foreground">
        {t('pdfPreview.states.originalTextMissing')}
      </p>
    )
  } else if (currentPreparation === null) {
    feedback = (
      <PageLoading
        className="min-h-0 flex-none py-2"
        message={t('pdfPreview.loading.message')}
        srMessage={t('pdfPreview.loading.srMessage')}
      />
    )
  } else if (currentPreparation.status === 'failed') {
    feedback = (
      <p role="alert" className="px-3 py-2 text-xs text-destructive">
        {t('pdfPreview.errors.preparationFailedTitle')}。{t('pdfPreview.errors.preparationFailedDescription')}
      </p>
    )
  } else if (currentPreparation.result.positionedBlockCount === 0) {
    feedback = (
      <p role="status" className="px-3 py-2 text-xs text-muted-foreground">
        {t('pdfPreview.states.noPositionTagsDescription')}
      </p>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {feedback}
      <div className="relative min-h-0 flex-1">
        {result !== null && result.positionedBlockCount > 0 ? (
          <div className="absolute right-3 top-3 z-10">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-8 rounded-full bg-background/70 px-3 backdrop-blur"
              aria-pressed={showAllBoxes}
              onClick={() => setShowAllBoxes((previous) => !previous)}
            >
              {showAllBoxes ? t('pdfPreview.actions.highlightOnly') : t('pdfPreview.actions.showAllBoxes')}
            </Button>
          </div>
        ) : null}
        <PdfViewer
          file={file}
          boxesByPage={geometry?.boxesByPage}
          blockIdToPageIndex={geometry?.blockIdToPageIndex}
          activeBlockIds={activeBlockIds}
          hoveredBlockIds={hoveredBlockIds}
          showAllBoxes={showAllBoxes}
          onHoverBlockId={handleHoverBlockId}
          onClickBlockId={handleClickBlockId}
        />
      </div>
    </div>
  )
}
