import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('similarity diagnostics graph source', () => {
  it('imports next-intl translations for the UX copy', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-diagnostics-graph.tsx'), 'utf8')

    expect(src).toContain("import { useTranslations } from 'next-intl'")
    expect(src).toContain("useTranslations('SimilarityDiagnosticsGraph')")
    expect(src).toContain("t('graphTooLargeTitle')")
  })

  it('uses a branded loading shell around the lazy 3D graph bundle', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-diagnostics-graph.tsx'), 'utf8')

    expect(src).toContain('react-force-graph-3d')
    expect(src).toContain('PageLoading')
    expect(src).toContain("t('loadingMessage')")
    expect(src).toContain("t('loadingSrMessage')")
    expect(src).not.toContain('animate-pulse')
  })

  it('guards oversized diagnostics graphs instead of forcing every 3D render through the main flow', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-diagnostics-graph.tsx'), 'utf8')

    expect(src).toContain('MAX_DIAGNOSTICS_GRAPH_NODES')
    expect(src).toContain('MAX_DIAGNOSTICS_GRAPH_LINKS')
    expect(src).toContain('const exceedsGraphComplexityBudget =')
    expect(src).toContain("t('graphTooLargeTitle')")
    expect(src).toContain("t('graphTooLargeHint')")
  })
})
