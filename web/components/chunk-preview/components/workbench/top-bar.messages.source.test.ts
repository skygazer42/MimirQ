import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk preview top bar messages source', () => {
  it('routes top-bar status, actions, and import/export copy through next-intl', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'top-bar.tsx'), 'utf8')

    expect(src).toContain("useTranslations('ChunkPreview')")
    expect(src).toContain("t('workbench.title')")
    expect(src).toContain("t('topBar.strategyLabel')")
    expect(src).toContain("t('topBar.paramsLabel')")
    expect(src).not.toContain("t('topBar.parserLabel')")
    expect(src).toContain("t('topBar.status.cacheHit')")
    expect(src).toContain("t('topBar.status.parseCache')")
    expect(src).toContain('topBar.status.quality')
    expect(src).toContain('topBar.status.warnings')
    expect(src).toContain("t('topBar.submitSuccess')")
    expect(src).toContain("t('topBar.dirtyWarning')")
    expect(src).toContain("t('topBar.actions.reset')")
    expect(src).toContain("t('topBar.actions.openSettingsPanel')")
    expect(src).toContain("t('topBar.actions.showOriginal')")
    expect(src).toContain("t('topBar.actions.hideOriginal')")
    expect(src).toContain("t('topBar.actions.moreActions')")
    expect(src).toContain("t('topBar.actions.copyConfig')")
    expect(src).toContain("t('topBar.actions.exportConfig')")
    expect(src).toContain("t('topBar.actions.importConfigFromFile')")
    expect(src).toContain("t('topBar.actions.importConfigFromClipboard')")
    expect(src).toContain("t('topBar.actions.comparePreview')")
    expect(src).toContain("t('topBar.actions.copyCurl')")
    expect(src).toContain("t('topBar.actions.copyDocumentId')")
    expect(src).toContain("t('topBar.actions.openCurrentChunkInChat')")
    expect(src).toContain("t('topBar.actions.openDocumentInChat')")
    expect(src).toContain("t('topBar.actions.close')")
    expect(src).toContain("t('topBar.actions.completed')")
    expect(src).toContain("t('topBar.actions.confirmIngest')")
  })
})
