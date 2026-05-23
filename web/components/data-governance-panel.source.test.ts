import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('data governance panel source', () => {
  it('uses explicit spans, semantic buttons, and next-intl-backed labels', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'data-governance-panel.tsx'),
      'utf8'
    )

    expectSourceNotToContain(src, 'role="button"')
    expectSourceNotToContain(src, '{(() => {')
    expectSourceToContain(
      src,
      "const t = useTranslations('DataGovernancePanel')"
    )
    expectSourceToContain(src, 'const headerTitle = t("header.title")')
    expectSourceToContain(src, 'const headerSubtitle = t("header.subtitle")')
    expectSourceToContain(
      src,
      '<span className="h-1.5 w-1.5 rounded-full bg-primary/20" aria-hidden="true" />'
    )
    expectSourceToContain(
      src,
      '<span className="w-1.5 h-1.5 rounded-full bg-info/10 dark:bg-info/20" aria-hidden="true" />'
    )
    expectSourceToContain(src, "aria-label={t('emptyUpload.openUploadDialog')}")
    expectSourceToContain(
      src,
      "aria-label={t('a11y.openFile', { filename: file.filename })}"
    )
    expectSourceToContain(src, "aria-label={t('panel.collapse')}")
    expectSourceToContain(src, 'const contentBody =')
    expectSourceToContain(src, 'const activeFolderLabel = useMemo(() => {')
    expectSourceToContain(src, "t('sidebar.allFolders')")
  })

  it('does not render inbound routing hints as visible page chrome', () => {
    const panelSrc = fs.readFileSync(
      path.resolve(__dirname, 'data-governance-panel.tsx'),
      'utf8'
    )
    const zhSrc = fs.readFileSync(
      path.resolve(__dirname, '../i18n/messages/zh-CN/governance.ts'),
      'utf8'
    )

    expectSourceNotToContain(panelSrc, 'const InboundBanner = useMemo')
    expectSourceNotToContain(panelSrc, 'top={InboundBanner}')
    expectSourceNotToContain(panelSrc, "t('inbound.description')")
    expectSourceNotToContain(zhSrc, '该页当前仅做引导展示')
    expectSourceNotToContain(zhSrc, 'pipeline/governance')
  })

  it('adds a saved-document batch handoff queue for chunk preview submission', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'data-governance-panel.tsx'),
      'utf8'
    )
    const storeSrc = fs.readFileSync(
      path.resolve(__dirname, '../store/use-parsed-files-store.ts'),
      'utf8'
    )

    expectSourceToContain(src, 'selectedChunkFileIds')
    expectSourceToContain(src, 'toggleChunkFileSelection')
    expectSourceToContain(src, "file.chunkStatus === 'ready'")
    expectSourceToContain(src, 'markReadyFileIds')
    expectSourceToContain(src, 'markSubmittedFileIds')
    expectSourceToContain(src, 'handleSubmitSelectedToChunkPreview')
    expectSourceToContain(src, 'actions.submitSelectedToChunkPreview')
    expectSourceToContain(src, "t('sidebar.chunkReady')")
    expectSourceToContain(src, "t('sidebar.chunkSubmitted')")
    expectSourceToContain(src, "params.set('dataset_id', selectedDatasetId)")
    expectSourceToContain(
      src,
      "router.push(query ? `/chunk-preview?${query}` : '/chunk-preview')"
    )
    expectSourceToContain(
      storeSrc,
      "chunkStatus?: 'draft' | 'ready' | 'submitted'"
    )
  })
})
