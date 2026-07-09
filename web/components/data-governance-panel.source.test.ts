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
    expectSourceToContain(src, 'KnowledgeOpsHero')
    expectSourceToContain(src, 'KnowledgeOpsFlowCard')
    expectSourceToContain(
      src,
      'title={headerTitle}'
    )
    expectSourceToContain(
      src,
      "description={t('header.workspaceSubtitle')}"
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

  it('presents the empty governance workbench as a frameless intake surface', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'data-governance-panel.tsx'),
      'utf8'
    )
    const zhSrc = fs.readFileSync(
      path.resolve(__dirname, '../i18n/messages/zh-CN/governance.ts'),
      'utf8'
    )

    expectSourceToContain(src, 'data-governance-empty-workbench="true"')
    expectSourceToContain(src, 'const EMPTY_UPLOAD_FORMATS =')
    expectSourceToContain(src, 'const EMPTY_UPLOAD_STEPS =')
    expectSourceToContain(src, 'EmptyStructurePreview')
    expectSourceToContain(src, "t('emptyUpload.structureEmptyTitle')")
    expectSourceToContain(src, "t('emptyUpload.structureEmptyDescription')")
    expectSourceToContain(src, "t('emptyUpload.dropCta')")
    expectSourceNotToContain(src, 'w-full max-w-3xl overflow-hidden rounded-3xl border border-dashed p-16 text-center')
    expectSourceNotToContain(src, 'data-governance-empty-hologram="true"')
    expectSourceNotToContain(src, 'rounded-[2rem] border p-4')
    expectSourceNotToContain(src, 'rounded-[1.6rem] border border-dashed')
    expectSourceNotToContain(src, 'rounded-[1.35rem] border border-border/70')
    expectSourceToContain(src, 'border-y border-dashed border-primary/24')
    expectSourceToContain(src, 'data-governance-empty-structure-rail="true"')
    expectSourceToContain(zhSrc, "structureEmptyTitle: '等待生成目录'")
    expectSourceToContain(zhSrc, "dropCta: '拖入文件或点击选择，系统会自动解析目录、章节和清洗线索。'")
  })
})
