import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk compare dialog source', () => {
  it('renders highlighted added and removed evidence sections for semantic diff review', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-compare-dialog.tsx'), 'utf8')

    expect(src).toContain("useTranslations('ChunkPreview')")
    expect(src).toContain("t('compareDialog.title')")
    expect(src).toContain("t('compareDialog.description')")
    expect(src).toContain("t('compareDialog.needTwoRuns')")
    expect(src).toContain("t('compareDialog.baselineLabel')")
    expect(src).toContain("t('compareDialog.baselinePlaceholder')")
    expect(src).toContain("t('compareDialog.evidence.addedTitle')")
    expect(src).toContain("t('compareDialog.evidence.removedTitle')")
    expect(src).toContain("t('compareDialog.evidence.addedEmpty')")
    expect(src).toContain("t('compareDialog.evidence.removedEmpty')")
    expect(src).toContain("t('compareDialog.actions.exportDiff')")
    expect(src).toContain("t('compareDialog.actions.close')")
    expect(src).toContain('buildSemanticEvidenceHighlights')
    expect(src).toContain('referenceExample')
    expect(src).toContain('segment.emphasis')
  })
})
