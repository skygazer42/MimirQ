import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('pdf preview source', () => {
  it('moves PDF highlight preprocessing into a worker-backed computation pipeline', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pdf-preview.tsx'), 'utf8')

    expect(src).toContain('PdfPreviewLoadingSkeleton')
    expect(src).toContain('PageLoading')
    expect(src).toContain("new URL('../../../../../workers/pdf-preview.worker.ts', import.meta.url)")
    expect(src).toContain('wrap<PdfPreviewWorkerApi>')
    expect(src).toContain('computePdfPreviewData')
    expect(src).toContain('pdfPreviewWorkerRef.current?.terminate()')
    expect(src).not.toContain('const parsed = useMemo(() =>')
    expect(src).not.toContain('extractBlocksFromMarkdownWithRanges(rawOriginal)')
    expect(src).not.toContain('createPositionTagIndexMapper(rawOriginal')
    expect(src).not.toContain('buildBlockIdToBestChunkIndex(blockRanges, chunkRanges)')
  })
})
