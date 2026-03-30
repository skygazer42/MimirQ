import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk auto tune dialog source', () => {
  it('routes auto-tune actions, table labels, and status copy through next-intl', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-auto-tune-dialog.tsx'), 'utf8')

    expect(src).toContain("useTranslations('ChunkPreview')")
    expect(src).toContain("t('autoTune.unavailable.separatorStrategy')")
    expect(src).toContain("t('autoTune.unavailable.previewRequired')")
    expect(src).toContain("t('autoTune.toasts.requestFailed')")
    expect(src).toContain('autoTune.toasts.completed')
    expect(src).toContain("t('autoTune.trigger.readyTitle')")
    expect(src).toContain("t('autoTune.trigger.disabledTitle')")
    expect(src).toContain("t('autoTune.trigger.label')")
    expect(src).toContain("t('autoTune.dialog.title')")
    expect(src).toContain("t('autoTune.dialog.description')")
    expect(src).toContain("t('autoTune.currentFile.title')")
    expect(src).toContain("t('autoTune.currentFile.cancel')")
    expect(src).toContain("t('autoTune.labels.minCoverage')")
    expect(src).toContain("t('autoTune.labels.maxOverlapWaste')")
    expect(src).toContain("t('autoTune.labels.maxChunks')")
    expect(src).toContain("t('autoTune.labels.topN')")
    expect(src).toContain('autoTune.labels.searchSpace')
    expect(src).toContain("t('autoTune.actions.exportJson')")
    expect(src).toContain("t('autoTune.actions.start')")
    expect(src).toContain("t('autoTune.actions.applyAndPreview')")
    expect(src).toContain("t('autoTune.table.ariaLabel')")
    expect(src).toContain("t('autoTune.table.params')")
    expect(src).toContain("t('autoTune.table.coverage')")
    expect(src).toContain("t('autoTune.table.waste')")
    expect(src).toContain("t('autoTune.table.chunks')")
    expect(src).toContain("t('autoTune.table.avgP90')")
    expect(src).toContain("t('autoTune.table.grade')")
    expect(src).toContain("t('autoTune.table.action')")
    expect(src).toContain("t('autoTune.empty.noMatches')")
    expect(src).toContain("t('autoTune.empty.noResults')")
  })
})
