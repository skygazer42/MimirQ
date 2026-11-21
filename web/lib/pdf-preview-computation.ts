import { buildBlockIdToBestChunkIndex, type BlockTextRange } from './pdf-box-mapping'
import {
  createPositionTagIndexMapper,
  extractBlocksFromMarkdownWithRanges,
  type ParsingPosition,
  type ParsingBlockWithRange,
} from '@/lib/parsing-positions'
import type { ChunkPreviewItem } from '@/types'
import { createCodePointToUtf16Converter } from './text-offsets'

type PdfPreviewChunkLike = Pick<ChunkPreviewItem, 'start_index' | 'end_index'>

type PdfPreviewChunkRange = {
  /** Position in the source chunks array; independent of backend chunk.index. */
  index: number
  start: number
  end: number
}

type PdfPreviewBox = {
  id: string
  position: ParsingPosition
}

export type PdfPreviewComputationResult = {
  positionedBlockCount: number
  blockIdToChunkIndexEntries: Array<[string, number]>
  blockIdToPageIndexEntries: Array<[string, number]>
  chunkBlockIdsByIndexEntries: Array<[number, string[]]>
  boxesByPageEntries: Array<[number, PdfPreviewBox[]]>
}

function overlap(aStart: number, aEnd: number, bStart: number, bEnd: number): boolean {
  return aEnd > bStart && bEnd > aStart
}

function computeBlockRanges(blocks: ParsingBlockWithRange[], mapIndex: (rawIndex: number) => number): BlockTextRange[] {
  return blocks.map((block) => ({
    id: block.id,
    start: mapIndex(block.rawStart),
    end: mapIndex(block.rawEnd),
  }))
}

function computeChunkRanges(
  previewChunks: readonly PdfPreviewChunkLike[],
  toUtf16: (offset: number) => number | undefined,
  mapIndex: (rawIndex: number) => number,
): PdfPreviewChunkRange[] {
  return previewChunks.flatMap((chunk, index) => {
    const rawStart = toUtf16(chunk.start_index)
    const rawEnd = toUtf16(chunk.end_index)
    if (rawStart === undefined || rawEnd === undefined || rawEnd <= rawStart) return []
    const start = mapIndex(rawStart)
    const end = mapIndex(rawEnd)
    return end > start ? [{ index, start, end }] : []
  })
}

function computeBoxesByPageEntries(blocks: ParsingBlockWithRange[]): Array<[number, PdfPreviewBox[]]> {
  const boxesByPage = new Map<number, PdfPreviewBox[]>()

  for (const block of blocks) {
    for (const position of block.positions) {
      for (const pageIndex of position.pages) {
        const box = { id: block.id, position }
        const pageBoxes = boxesByPage.get(pageIndex)
        if (pageBoxes === undefined) boxesByPage.set(pageIndex, [box])
        else pageBoxes.push(box)
      }
    }
  }

  return Array.from(boxesByPage.entries())
}

function computeBlockIdToPageIndexEntries(blocks: ParsingBlockWithRange[]): Array<[string, number]> {
  const entries: Array<[string, number]> = []

  for (const block of blocks) {
    for (const position of block.positions) {
      if (position.pages.length === 0) continue
      entries.push([block.id, position.pages[0]])
      break
    }
  }

  return entries
}

function findBlockIdsForChunkRange(chunk: PdfPreviewChunkRange, blockRanges: readonly BlockTextRange[]): string[] {
  const ids: string[] = []
  for (const block of blockRanges) {
    if (!overlap(chunk.start, chunk.end, block.start, block.end)) continue
    ids.push(block.id)
  }

  return ids
}

function computeChunkBlockIdsByIndexEntries(params: {
  chunkRanges: PdfPreviewChunkRange[]
  blockRanges: BlockTextRange[]
}): Array<[number, string[]]> {
  const { chunkRanges, blockRanges } = params

  return chunkRanges.map((chunk) => [chunk.index, findBlockIdsForChunkRange(chunk, blockRanges)])
}

export function computePdfPreviewData(params: {
  rawOriginal: string
  previewChunks: readonly PdfPreviewChunkLike[]
}): PdfPreviewComputationResult {
  const { rawOriginal, previewChunks } = params
  const parsed = extractBlocksFromMarkdownWithRanges(rawOriginal)
  const blocksWithPositions = parsed.blocks.filter((block) =>
    block.positions.some((position) => position.pages.length > 0),
  )
  const converter = createCodePointToUtf16Converter(rawOriginal)
  const mapIndex = createPositionTagIndexMapper(rawOriginal, parsed.tagRanges)
  const blockRanges = computeBlockRanges(blocksWithPositions, mapIndex)
  const chunkRanges = computeChunkRanges(previewChunks, converter.toUtf16, mapIndex)
  const blockIdToChunkIndexEntries = Array.from(
    buildBlockIdToBestChunkIndex(
      blockRanges,
      chunkRanges.map((chunk) => ({
        index: chunk.index,
        start_index: chunk.start,
        end_index: chunk.end,
      })),
    ).entries(),
  )
  const blockIdToPageIndexEntries = computeBlockIdToPageIndexEntries(blocksWithPositions)
  const chunkBlockIdsByIndexEntries = computeChunkBlockIdsByIndexEntries({
    chunkRanges,
    blockRanges,
  })
  const boxesByPageEntries = computeBoxesByPageEntries(blocksWithPositions)

  return {
    positionedBlockCount: blocksWithPositions.length,
    blockIdToChunkIndexEntries,
    blockIdToPageIndexEntries,
    chunkBlockIdsByIndexEntries,
    boxesByPageEntries,
  }
}
