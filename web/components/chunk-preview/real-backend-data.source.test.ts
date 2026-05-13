import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..', '..')
const repoRoot = path.resolve(webRoot, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('chunk preview real backend data contract', () => {
  it('requests backend review signals and exposes server p95 stats', () => {
    const helpers = read('lib/api/document-helpers.ts')
    const context = read('components/chunk-preview/context.tsx')
    const types = read('types/processing.ts')

    expect(helpers).toContain('include_review_signals?: boolean')
    expect(helpers).toContain('include_review_signals:')
    expect(context).toContain('include_review_signals: true')
    expect(types).toContain('p95?: number')
  })

  it('keeps visible sidebar and quality filter facts sourced from backend payloads', () => {
    const sidebar = read('components/chunk-preview/components/workbench/sidebar-client.tsx')
    const chunkList = read('components/chunk-preview/components/workbench/preview/chunk-list.tsx')
    const coverageMini = read('components/chunk-preview/components/workbench/preview/coverage-heatmap-mini.tsx')
    const exportUtil = read('components/chunk-preview/utils/export.ts')

    expect(sidebar).not.toContain("computeChunkLengthStats")
    expect(sidebar).toContain('const serverStats = previewData?.stats ?? null')
    expect(sidebar).toContain('serverStats?.p95')
    expect(chunkList).not.toContain('fnv1a32')
    expect(chunkList).not.toContain('computeCoverageSignals')
    expect(chunkList).toContain('previewData?.review_signals')
    expect(coverageMini).not.toContain('computeCoverageHeatmapBins')
    expect(coverageMini).toContain('stats?.coverage_ratio')
    expect(exportUtil).not.toContain('computeCoverageSignals')
    expect(exportUtil).not.toContain('computeDuplicateIndices')
    expect(exportUtil).not.toContain('computeShortIndices')
    expect(exportUtil).not.toContain('fnv1a32')
    expect(exportUtil).toContain('mergedAll.review_signals ?? emptyReviewSignals()')
  })

  it('keeps backend chunk-preview schemas and handlers returning p95', () => {
    const schema = fs.readFileSync(path.resolve(repoRoot, 'app/api/schemas/document.py'), 'utf8')
    const handler = fs.readFileSync(path.resolve(repoRoot, 'app/api/v1/document_chunk_preview.py'), 'utf8')

    expect(schema).toContain('p95: int = 0')
    expect(handler.match(/p95=_pct\(95\)/g)?.length ?? 0).toBeGreaterThanOrEqual(2)
  })

  it('does not flood the backend by loading every saved document body on page entry', () => {
    const context = read('components/chunk-preview/context.tsx')

    expect(context).toContain('const CHUNK_PREVIEW_SCOPE_DOCUMENT_LIMIT = 12')
    expect(context).toContain('for (const doc of docs)')
    expect(context).not.toContain('limit: 100')
    expect(context).not.toContain('Promise.all(')
  })
})
