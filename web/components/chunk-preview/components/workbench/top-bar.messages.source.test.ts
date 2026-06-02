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
    expect(src).toContain("t('topBar.status.qualityGrades.pass')")
    expect(src).toContain("t('topBar.status.qualityGrades.warn')")
    expect(src).toContain("t('topBar.status.qualityGrades.fail')")
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

  it('builds copied cURL auth headers from the current session instead of hard-coded demo IDs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'top-bar.tsx'), 'utf8')

    expect(src).toContain("import { getAuthHeaders } from '@/lib/auth-headers'")
    expect(src).toContain('const authHeaders = getAuthHeaders()')
    expect(src).toContain('Object.entries(authHeaders)')
    expect(src).not.toContain('X-User-ID: demo')
  })

  it('syncs visible preview timing to the active preview payload before falling back to local timing', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'top-bar.tsx'), 'utf8')

    expect(src).toContain('const visiblePreviewDurationMs =')
    expect(src).toContain("typeof previewData?.preview_duration_ms === 'number'")
    expect(src).toContain('Math.round(previewData.preview_duration_ms)')
    expect(src).toContain(': lastPreviewDurationMs')
    expect(src).not.toContain("{lastPreviewDurationMs}ms</span>")
  })

  it('binds visible top-bar facts to the active preview payload before local settings', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'top-bar.tsx'), 'utf8')

    expect(src).toContain('const visibleFileType =')
    expect(src).toContain('previewData?.file_type')
    expect(src).toContain('const visibleFileSize =')
    expect(src).toContain('previewData?.file_size')
    expect(src).toContain('const visibleChunkSize =')
    expect(src).toContain('previewData?.params?.chunk_size')
    expect(src).toContain('const visibleChunkOverlap =')
    expect(src).toContain('previewData?.params?.chunk_overlap')
    expect(src).toContain('{visibleChunkSize}/{visibleChunkOverlap}')
    expect(src).not.toContain('{chunkSize}/{chunkOverlap}')
  })

  it('presents the current file identity as dense labeled metadata instead of loose text', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'top-bar.tsx'), 'utf8')

    expect(src).toContain('data-current-file-summary')
    expect(src).toContain('const fileMetaChipClass =')
    expect(src).toContain("t('topBar.fileMeta.index')")
    expect(src).toContain("t('topBar.fileMeta.type')")
    expect(src).toContain("t('topBar.fileMeta.size')")
    expect(src).toContain("t('topBar.fileMeta.parser')")
    expect(src).not.toContain('<span>{formatFileSize(visibleFileSize)}</span>')
    expect(src).not.toContain('<span>{effectiveParserBackend}</span>')
  })

  it('renders the quality gate using localized grade labels instead of English PASS/WARN/FAIL', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'top-bar.tsx'), 'utf8')
    const messages = fs.readFileSync(
      path.resolve(__dirname, '../../../../i18n/messages/zh-CN/chunk-preview.ts'),
      'utf8'
    )

    expect(src).toContain('const visibleQualityLabel =')
    expect(src).toContain("t('topBar.status.qualityGrades.pass')")
    expect(src).not.toContain('String(previewData.quality_gate.grade).toUpperCase()')
    expect(messages).toContain("quality: '质量：{grade}'")
    expect(messages).toContain("pass: '通过'")
    expect(messages).not.toContain("quality: 'Quality: {grade}'")
  })

  it('uses localized chunk count copy in the Chinese top bar', () => {
    const messages = fs.readFileSync(
      path.resolve(__dirname, '../../../../i18n/messages/zh-CN/chunk-preview.ts'),
      'utf8'
    )

    expect(messages).toContain("chunks: '{count} 个切块'")
    expect(messages).not.toContain("chunks: '{count} Chunks'")
  })

  it('renders long operational errors as wrapped status copy instead of a truncated chip', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'top-bar.tsx'), 'utf8')

    expect(src).toContain('function formatTopBarError')
    expect(src).toContain('const topBarError = error ? formatTopBarError(error) : null')
    expect(src).toContain('break-words')
    expect(src).not.toContain('items-center gap-1.5 truncate rounded-lg border border-destructive')
  })
})
