/**
 * PdfPreview - PDF panel for chunk preview (best-effort).
 *
 * Highlights selected/hovered chunks by mapping chunk char ranges to parsing position-tag blocks.
 */
'use client'

import { useCallback, useMemo, useState } from 'react'
import { AlertCircle } from 'lucide-react'

import { useChunkPreview } from '@/components/chunk-preview/context'
import { buildBlockIdToBestChunkIndex } from '@/components/chunk-preview/utils/pdf-box-mapping'
import dynamic from 'next/dynamic'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { ChunkPreviewItem } from '@/types'

const PdfViewer = dynamic(() => import('@/components/parsing/pdf-viewer').then((mod) => mod.PdfViewer), {
  ssr: false,
  loading: () => <Skeleton className="h-[400px] w-full" />,
})
import {
  createPositionTagIndexMapper,
  extractBlocksFromMarkdownWithRanges,
  ParsingBlockWithRange,
} from '@/lib/parsing-positions'

function asInt(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? Math.trunc(n) : 0
}

function overlap(aStart: number, aEnd: number, bStart: number, bEnd: number): boolean {
  const a0 = Math.min(aStart, aEnd)
  const a1 = Math.max(aStart, aEnd)
  const b0 = Math.min(bStart, bEnd)
  const b1 = Math.max(bStart, bEnd)
  return a1 > b0 && b1 > a0
}

function computeBlockRanges(
  blocks: ParsingBlockWithRange[],
  mapIndex: (rawIndex: number) => number
): Array<{ id: string; start: number; end: number }> {
  return (blocks || []).map((b) => ({
    id: b.id,
    start: mapIndex(asInt(b.rawStart)),
    end: mapIndex(asInt(b.rawEnd)),
  }))
}

function blockIdsForChunk(params: {
  chunkIndex: number | null
  previewChunks: Array<Pick<ChunkPreviewItem, 'start_index' | 'end_index'>>
  blockRanges: Array<{ id: string; start: number; end: number }>
  mapIndex: (rawIndex: number) => number
}): string[] {
  const { chunkIndex, previewChunks, blockRanges, mapIndex } = params
  if (chunkIndex == null) return []
  const chunk = previewChunks?.[chunkIndex]
  if (!chunk) return []

  const start = mapIndex(asInt(chunk.start_index))
  const end = mapIndex(asInt(chunk.end_index))
  if (start === end) return []

  const ids: string[] = []
  for (const b of blockRanges) {
    if (!overlap(start, end, b.start, b.end)) continue
    ids.push(b.id)
    if (ids.length >= 600) break
  }
  return ids
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

  const isPdf = useMemo(() => {
    const ft = String(previewData?.file_type || '').toLowerCase()
    if (ft === 'pdf') return true
    const name = String(currentFile?.name || '').toLowerCase()
    return name.endsWith('.pdf')
  }, [currentFile?.name, previewData?.file_type])

  const rawOriginal = previewData?.original_text || ''

  const parsed = useMemo(() => {
    if (!rawOriginal) return null
    return extractBlocksFromMarkdownWithRanges(rawOriginal)
  }, [rawOriginal])

  const blocksWithPositions = useMemo(() => {
    const all = parsed?.blocks || []
    return all.filter((b) => (b.positions || []).length > 0)
  }, [parsed?.blocks])

  const mapIndex = useMemo(() => {
    if (!rawOriginal) return (idx: number) => Math.max(0, asInt(idx))
    return createPositionTagIndexMapper(rawOriginal, parsed?.tagRanges)
  }, [parsed?.tagRanges, rawOriginal])

  const blockRanges = useMemo(() => computeBlockRanges(blocksWithPositions, mapIndex), [blocksWithPositions, mapIndex])

  const previewChunks = useMemo(() => previewData?.chunks ?? [], [previewData?.chunks])
  const chunkRanges = useMemo(() => {
    return previewChunks.map((chunk, index) => ({
      index,
      start_index: mapIndex(asInt(chunk.start_index)),
      end_index: mapIndex(asInt(chunk.end_index)),
    }))
  }, [mapIndex, previewChunks])

  const blockIdToChunkIndex = useMemo(
    () => buildBlockIdToBestChunkIndex(blockRanges, chunkRanges),
    [blockRanges, chunkRanges]
  )

  const selectedBlockIds = useMemo(
    () =>
      blockIdsForChunk({
        chunkIndex: selectedChunkIndex,
        previewChunks,
        blockRanges,
        mapIndex,
      }),
    [blockRanges, mapIndex, previewChunks, selectedChunkIndex]
  )
  const hoveredBlockIds = useMemo(
    () =>
      blockIdsForChunk({
        chunkIndex: hoveredChunkIndex,
        previewChunks,
        blockRanges,
        mapIndex,
      }),
    [blockRanges, hoveredChunkIndex, mapIndex, previewChunks]
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
