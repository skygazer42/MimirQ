import { buildBlockIdToBestChunkIndex, type BlockRangeLike } from '@/components/chunk-preview/utils/pdf-box-mapping'
import {
  createPositionTagIndexMapper,
  extractBlocksFromMarkdownWithRanges,
  type ParsingPosition,
  type ParsingBlockWithRange,
} from '@/lib/parsing-positions'
import type { ChunkPreviewItem } from '@/types'

export type PdfPreviewChunkLike = Pick<ChunkPreviewItem, 'start_index' | 'end_index'>

export type PdfPreviewChunkRange = {
  index: number
  start: number
  end: number
}

export type PdfPreviewBox = {
  id: string
  position: ParsingPosition
}

export interface PdfPreviewComputationResult {
  blocksWithPositions: ParsingBlockWithRange[]
  blockRanges: BlockRangeLike[]
  chunkRanges: PdfPreviewChunkRange[]
  blockIdToChunkIndexEntries: Array<[string, number]>
  boxesByPageEntries: Array<[number, PdfPreviewBox[]]>
}

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
): BlockRangeLike[] {
  return blocks.map((block) => ({
    id: block.id,
    start: mapIndex(asInt(block.rawStart)),
    end: mapIndex(asInt(block.rawEnd)),
  }))
}

function computeChunkRanges(
  previewChunks: PdfPreviewChunkLike[],
  mapIndex: (rawIndex: number) => number
): PdfPreviewChunkRange[] {
  return previewChunks.map((chunk, index) => ({
    index,
    start: mapIndex(asInt(chunk.start_index)),
    end: mapIndex(asInt(chunk.end_index)),
  }))
}

function computeBoxesByPageEntries(blocks: ParsingBlockWithRange[]): Array<[number, PdfPreviewBox[]]> {
  const boxesByPage = new Map<number, PdfPreviewBox[]>()

  for (const block of blocks) {
    for (const position of block.positions || []) {
      const pages = position.pages?.length ? position.pages : [0]
      for (const pageIndex of pages) {
        const pageBoxes = boxesByPage.get(pageIndex) || []
        pageBoxes.push({ id: block.id, position })
        boxesByPage.set(pageIndex, pageBoxes)
      }
    }
  }

  return Array.from(boxesByPage.entries())
}

export function findBlockIdsForChunkIndex(params: {
  chunkIndex: number | null
  chunkRanges: PdfPreviewChunkRange[]
  blockRanges: BlockRangeLike[]
}): string[] {
  const { chunkIndex, chunkRanges, blockRanges } = params
  if (chunkIndex == null) return []

  const chunk = chunkRanges.find((candidate) => candidate.index === chunkIndex)
  if (!chunk || chunk.start === chunk.end) return []

  const ids: string[] = []
  for (const block of blockRanges) {
    if (!overlap(chunk.start, chunk.end, block.start, block.end)) continue
    ids.push(block.id)
    if (ids.length >= 600) break
  }

  return ids
}

export function computePdfPreviewData(params: {
  rawOriginal: string
  previewChunks: PdfPreviewChunkLike[]
}): PdfPreviewComputationResult {
  const { rawOriginal, previewChunks } = params
  const parsed = extractBlocksFromMarkdownWithRanges(rawOriginal)
  const blocksWithPositions = parsed.blocks.filter((block) => (block.positions || []).length > 0)
  const mapIndex = createPositionTagIndexMapper(rawOriginal, parsed.tagRanges)
  const blockRanges = computeBlockRanges(blocksWithPositions, mapIndex)
  const chunkRanges = computeChunkRanges(previewChunks, mapIndex)
  const blockIdToChunkIndexEntries = Array.from(
    buildBlockIdToBestChunkIndex(
      blockRanges,
      chunkRanges.map((chunk) => ({
        index: chunk.index,
        start_index: chunk.start,
        end_index: chunk.end,
      }))
    ).entries()
  )
  const boxesByPageEntries = computeBoxesByPageEntries(blocksWithPositions)

  return {
    blocksWithPositions,
    blockRanges,
    chunkRanges,
    blockIdToChunkIndexEntries,
    boxesByPageEntries,
  }
}
