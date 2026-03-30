import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('sidebar client messages source', () => {
  it('routes preview action controls and analysis section labels through next-intl', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'sidebar-client.tsx'), 'utf8')

    expect(src).toContain("useTranslations('ChunkPreview')")
    expect(src).toContain("t('sidebar.ingestionPipeline')")
    expect(src).toContain("t('sidebar.previewActions.loading')")
    expect(src).toContain("t('sidebar.previewActions.run')")
    expect(src).toContain("t('sidebar.previewActions.cancel')")
    expect(src).toContain("t('sidebar.previewActions.ignoreCache')")
    expect(src).toContain("t('sidebar.previewActions.forceRefresh')")
    expect(src).toContain("t('sidebar.analysis.title')")
    expect(src).toContain("t('sidebar.analysis.collapse')")
    expect(src).toContain("t('sidebar.analysis.expand')")
  })
})
