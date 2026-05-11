import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { readMessageCatalogSource } from '@/lib/source-test-utils'

function read(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

function expectTranslationNamespace(src: string, namespace: string) {
  expect(
    src.includes(`useTranslations('${namespace}')`) || src.includes(`useTranslations("${namespace}")`)
  ).toBe(true)
}

function expectTranslationCall(src: string, key: string) {
  expect(src.includes(`t('${key}'`) || src.includes(`t("${key}"`)).toBe(true)
}

function expectNoTranslationCall(src: string, key: string) {
  expect(src.includes(`t('${key}'`) || src.includes(`t("${key}"`)).toBe(false)
}

describe('document detail message sources', () => {
  it('moves document detail dialog copy into next-intl catalogs', () => {
    const mainSrc = read('document-detail-dialog.tsx')
    const detailSrc = [
      mainSrc,
      read('document-detail-dialog/document-detail-summary-cards.tsx'),
      read('document-detail-dialog/document-detail-tags-panel.tsx'),
      read('document-detail-dialog/document-detail-lifecycle-panel.tsx'),
      read('document-detail-dialog/document-detail-activity-panel.tsx'),
    ].join('\n')
    const accessSrc = read('document-detail-dialog/document-access-dialog.tsx')
    const versionsSrc = read('document-detail-dialog/document-versions-dialog.tsx')
    const messagesSrc = readMessageCatalogSource(path.resolve(__dirname, '..'))

    expectTranslationNamespace(detailSrc, 'DocumentDetailDialog')
    ;[
      'toasts.tagsUpdated',
      'toasts.copySuccess',
      'toasts.chunkSaved',
      'toasts.chunkEnabled',
      'toasts.chunkDisabled',
      'toasts.chunkReembedded',
      'toasts.lifecycleUpdated',
      'toasts.versionActivated',
      'toasts.versionDeleted',
      'toasts.kgExtractStarted',
      'toasts.kgDeleted',
      'toasts.accessUpdated',
      'accessModes.inherit',
      'trigger.preview',
      'header.chunkCount',
      'header.parserChip',
      'header.chunkingChip',
      'cards.parse.title',
      'cards.governance.title',
      'cards.chunking.title',
      'tags.title',
      'tags.description',
      'tags.empty',
      'alerts.saveFailedTitle',
      'alerts.loadFailedTitle',
      'alerts.permissionCheckFailedTitle',
      'alerts.validationFailedTitle',
      'actions.edit',
      'lifecycle.readOnly',
      'lifecycle.title',
      'lifecycle.description',
      'lifecycle.fields.publicationStatus.label',
      'lifecycle.empty',
      'errors.saveChunkFailed',
      'errors.chunkOperationFailed',
      'errors.reembedFailed',
      'errors.lifecyclePermissionCheckUnknown',
      'errors.loadDetailFailed',
      'errors.saveLifecycleFailed',
      'errors.loadVersionsFailed',
      'errors.loadTimelineFailed',
      'errors.loadChunksFailed',
      'errors.loadMoreChunksFailed',
      'errors.activateVersionFailed',
      'errors.deleteVersionFailed',
      'errors.kgExtractFailed',
      'errors.kgDeleteFailed',
      'errors.updateAccessFailed',
      'chunks.emptyDescription',
      'chunks.searchEmptyTitle',
      'chunks.clearFilter',
      'chunks.listAriaLabel',
      'chunks.charCount',
      'chunks.disabledBadge',
      'chunks.actions.edit',
      'chunks.actions.editDisabled',
      'chunks.actions.enable',
      'chunks.actions.disable',
      'chunks.actions.reembed',
      'chunks.actions.reembedDisabled',
      'chunks.actions.copy',
      'chunks.loadMore',
      'timeline.emptyDescription',
      'timeline.listAriaLabel',
      'timeline.synthetic',
      'timeline.meta.stage',
      'timeline.meta.status',
      'timeline.meta.progress',
      'timeline.meta.requestId',
      'timeline.meta.actorId',
      'timeline.actions.copyEvent',
      'kg.extract',
      'kg.deleteDialog.title',
      'search.placeholder',
      'views.ariaLabel',
    ].forEach((key) => {
      expectTranslationCall(detailSrc, key)
    })
    ;['alerts.permissionFailedTitle', 'alerts.inputInvalidTitle'].forEach((key) => {
      expectNoTranslationCall(detailSrc, key)
    })

    expectTranslationNamespace(accessSrc, 'DocumentAccessDialog')
    ;['trigger', 'mode.placeholder'].forEach((key) => {
      expectTranslationCall(accessSrc, key)
    })

    expectTranslationNamespace(versionsSrc, 'DocumentVersionsDialog')
    ;['trigger', 'dialogs.activate.title', 'empty.title'].forEach((key) => {
      expectTranslationCall(versionsSrc, key)
    })

    expect(messagesSrc).toContain("synthetic: '系统生成'")
    expect(messagesSrc).toContain("stage: '阶段'")
    expect(messagesSrc).toContain("status: '状态'")
    expect(messagesSrc).toContain("progress: '进度'")
    expect(messagesSrc).toContain("requestId: '请求 ID'")
    expect(messagesSrc).toContain("actorId: '操作人'")
  })
})
