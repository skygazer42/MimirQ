import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('common UI copy source', () => {
  it('moves mode toggle copy into next-intl lookups', () => {
    const src = read('./mode-toggle.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain('t("modeToggle.ariaLabel")')
    expect(src).toContain('t("modeToggle.light")')
    expect(src).toContain('t("modeToggle.dark")')
    expect(src).toContain('t("modeToggle.system")')
    expect(src).toContain('hover:bg-[#CAF0F8]/55')
    expect(src).toContain('data-[highlighted]:bg-[#CAF0F8]/55')
  })

  it('moves breadcrumb route labels and aria copy into next-intl lookups', () => {
    const src = read('./ui/breadcrumb.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain('t("breadcrumb.navLabel")')
    expect(src).toContain('const ROUTE_LABEL_KEYS')
    expect(src).toContain("datasets: 'datasets'")
    expect(src).toContain("knowledge: 'knowledge'")
    expect(src).toContain("settings: 'settings'")
    expect(src).toContain("graph: 'graph'")
    expect(src).toContain("workflow: 'workflow'")
    expect(src).toContain('t(`breadcrumb.routes.${routeKey}`)')
  })

  it('moves ingestion workflow stepper copy into next-intl lookups', () => {
    const src = read('./ui/ingestion-workflow-stepper.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain('t("ingestionWorkflow.navLabel")')
    expect(src).toContain('t("ingestionWorkflow.parsing")')
    expect(src).toContain('t("ingestionWorkflow.governance")')
    expect(src).toContain('t("ingestionWorkflow.chunk")')
    expect(src).toContain('t("ingestionWorkflow.chat")')
  })

  it('moves file queue item copy into next-intl lookups', () => {
    const src = read('./ui/file-queue-item.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain('t("fileQueueItem.pending")')
    expect(src).toContain('t("fileQueueItem.parsing")')
    expect(src).toContain('t("fileQueueItem.parsed")')
    expect(src).toContain('t("fileQueueItem.error")')
    expect(src).toContain('t("fileQueueItem.folderLabel")')
    expect(src).toContain('t("fileQueueItem.sourcePathLabel")')
    expect(src).toContain('t("fileQueueItem.pages"')
    expect(src).toContain('t("fileQueueItem.retry")')
    expect(src).toContain('t("fileQueueItem.removeLabel")')
    expect(src).toContain('t("fileQueueItem.removeTitle")')
  })

  it('moves search input copy into next-intl lookups', () => {
    const src = read('./ui/search-input.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain("placeholder ?? t('searchInput.placeholder')")
    expect(src).toContain("label={t('searchInput.clearLabel')}")
  })

  it('moves tag input copy into next-intl lookups', () => {
    const src = read('./ui/tag-input.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain("placeholder ?? t('tagInput.placeholder')")
    expect(src).toContain("aria-label={t('tagInput.removeLabel'")
    expect(src).toContain("t('tagInput.add')")
  })

  it('moves confirm dialog default copy into next-intl lookups', () => {
    const src = read('./ui/confirm-dialog.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain("confirmLabel ?? t('confirmDialog.confirm')")
    expect(src).toContain("cancelLabel ?? t('confirmDialog.cancel')")
  })

  it('moves status badge default labels into next-intl lookups', () => {
    const src = read('./ui/status-badge.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain("t('statusBadge.pending')")
    expect(src).toContain("t('statusBadge.processing')")
    expect(src).toContain("t('statusBadge.completed')")
    expect(src).toContain("t('statusBadge.failed')")
    expect(src).toContain("t('statusBadge.quarantined')")
    expect(src).toContain("t('statusBadge.cancelled')")
  })

  it('moves page loading default copy into next-intl lookups', () => {
    const src = read('./ui/page-loading.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain("message ?? t('pageLoading.message')")
    expect(src).toContain("srMessage ?? t('pageLoading.srMessage')")
  })

  it('moves command dialog default copy into next-intl lookups', () => {
    const src = read('./ui/command.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain("t('command.title')")
    expect(src).toContain("t('command.description')")
  })

  it('moves pipeline visualizer stage labels into next-intl lookups', () => {
    const src = read('./ui/pipeline-visualizer.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain("t('pipelineVisualizer.upload')")
    expect(src).toContain("t('pipelineVisualizer.parse')")
    expect(src).toContain("t('pipelineVisualizer.chunk')")
    expect(src).toContain("t('pipelineVisualizer.index')")
  })

  it('moves theme customizer copy into next-intl lookups', () => {
    const src = read('../components/theme-customizer.tsx')

    expect(src).toContain("useTranslations('CommonUi')")
    expect(src).toContain("t('themeCustomizer.openLabel')")
    expect(src).toContain("t('themeCustomizer.title')")
    expect(src).toContain("t('themeCustomizer.description')")
    expect(src).toContain("t('themeCustomizer.resetAppearance')")
    expect(src).toContain("t('themeCustomizer.surfaceLabel')")
    expect(src).toContain("t('themeCustomizer.surfacePresetLabel'")
    expect(src).toContain("t(`themeCustomizer.surfacePresets.${preset.key}.title`)")
    expect(src).toContain("t('themeCustomizer.colorLabel')")
    expect(src).toContain("t('themeCustomizer.modeLabel')")
    expect(src).toContain("t('themeCustomizer.presetLabel'")
    expect(src).toContain("t('themeCustomizer.selected')")
    expect(src).toContain("t('modeToggle.light')")
    expect(src).toContain("t('modeToggle.dark')")
  })
})
