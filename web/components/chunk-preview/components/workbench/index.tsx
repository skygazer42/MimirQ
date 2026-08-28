/**
 * Workbench - 主工作台（包含 TopBar、Sidebar 和 Preview）
 */
'use client'

import { useState } from 'react'
import {
  BookOpen,
  Check,
  Cpu,
  FileUp,
  HelpCircle,
  Layers,
  ScanLine,
} from 'lucide-react'
import { useTranslations } from 'next-intl'

import { TopBar } from './top-bar'
import { Sidebar } from './sidebar'
import { OriginalPreview } from './preview/original-preview'
import { ChunkList } from './preview/chunk-list'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkingHelpDialog } from '@/components/chunk-preview/components/chunking-help-dialog'
import { Button } from '@/components/ui/button'
import {
  KnowledgeOpsFlowCard,
  KnowledgeOpsHero,
  KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS,
} from '@/components/ui/knowledge-ops-hero'
import {
  WorkbenchPane,
  WorkbenchPanelDialog,
  WorkbenchScaffold,
} from '@/components/workbench'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { cn } from '@/lib/utils'

function ChunkPreviewWorkbenchHeader() {
  const t = useTranslations('ChunkPreview')
  const { currentFileItem, datasetId, fileList } = useChunkPreview()

  return (
    <header>
      <KnowledgeOpsHero
        iconImage="chunk-preview"
        eyebrow="Knowledge Ops"
        badge="文档资产治理中枢"
        title={t('workbench.title')}
        description={t('workbench.description')}
        summary={
          <div className="grid gap-2 sm:grid-cols-2">
            <div className={KNOWLEDGE_OPS_SUMMARY_PANEL_CLASS}>
              <span className="inline-flex items-center gap-1.5">
                <span className="size-1 rounded-full bg-info/70" aria-hidden />
                范围
              </span>
              <span className="min-w-0 truncate font-medium text-foreground">
                {datasetId || '解析工作区'}
              </span>
              <span className="h-3.5 w-px bg-border/70" />
              <span>文件</span>
              <span className="font-mono tabular-nums text-foreground">
                {fileList.length}
              </span>
            </div>
            <KnowledgeOpsFlowCard
              steps={[
                { icon: BookOpen, label: '解析' },
                { icon: ScanLine, label: '切块' },
                { icon: Layers, label: currentFileItem ? '复核' : '预览' },
              ]}
            />
          </div>
        }
      />
    </header>
  )
}

function ChunkPreviewEmptyCanvas() {
  const t = useTranslations('ChunkPreview')
  const {
    isDragging,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    addFiles,
    loadExample,
  } = useChunkPreview()
  const [helpOpen, setHelpOpen] = useState(false)

  const processCards: Array<{
    icon: typeof BookOpen
    title: string
    description: string
    action: (() => void) | null
    accent: string
  }> = [
    {
      icon: BookOpen,
      title: t('emptyState.exampleTitle'),
      description: t('emptyState.exampleDescription'),
      action: loadExample,
      accent: 'text-info',
    },
    {
      icon: ScanLine,
      title: t('emptyState.previewTitle'),
      description: t('emptyState.previewDescription'),
      action: null,
      accent: 'text-info',
    },
    {
      icon: Cpu,
      title: t('emptyState.tipsTitle'),
      description: t('emptyState.tipsDescription'),
      action: null,
      accent: 'text-info/70',
    },
  ]
  const visualSteps: Array<{
    icon: typeof BookOpen
    label: string
    tone: string
  }> = [
    {
      icon: BookOpen,
      label: t('emptyState.visual.steps.parse'),
      tone: 'text-info',
    },
    {
      icon: ScanLine,
      label: t('emptyState.visual.steps.chunk'),
      tone: 'text-info',
    },
    {
      icon: Layers,
      label: t('emptyState.visual.steps.review'),
      tone: 'text-info/70',
    },
  ]

  return (
    <main
      data-chunk-preview-empty-canvas="true"
      className={cn(
        'relative flex h-full min-h-0 flex-1 items-start overflow-y-auto overscroll-contain bg-info/[0.035] transition-colors duration-500',
        isDragging && 'bg-info/[0.08]'
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="relative z-10 mx-auto flex w-full max-w-6xl flex-col px-6 py-6">
        <div
          data-chunk-empty-intake-panel
          className="border-b border-foreground/10 pb-5"
        >
          <div className="flex flex-col gap-4 xl:flex-row xl:items-stretch xl:justify-between">
            <div className="flex min-w-0 flex-1 flex-col justify-between gap-3">
              <div className="inline-flex w-fit items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-info">
                <Layers className="size-3.5" strokeWidth={2.2} />
                {t('emptyState.badge')}
              </div>
              <div>
                <h2 className="max-w-2xl text-xl font-medium tracking-[-0.02em] text-foreground md:text-[22px]">
                  {t('emptyState.title')}
                </h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
                  {t('emptyState.description')}
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 w-fit rounded-lg border-foreground/10 bg-background/70 px-3 text-[11px] font-medium shadow-none hover:bg-background"
                onClick={() => setHelpOpen(true)}
              >
                <HelpCircle className="mr-1.5 size-3.5 text-info" strokeWidth={2.2} />
                {t('emptyState.help')}
              </Button>
            </div>

            <div
              className={cn(
                'relative w-full overflow-hidden rounded-xl border border-dashed border-info/30 bg-background/60 transition-colors duration-200 xl:w-[24rem]',
                isDragging ? 'border-info bg-info/[0.06]' : 'hover:border-info/50 hover:bg-background/80'
              )}
            >
              <input
                id="chunk-empty-file-input"
                type="file"
                accept={UPLOAD_ACCEPT}
                multiple
                className="hidden"
                onChange={(event) => {
                  const files = event.target.files ? Array.from(event.target.files) : []
                  if (files.length > 0) addFiles(files)
                  event.target.value = ''
                }}
              />
              <label
                htmlFor="chunk-empty-file-input"
                className={cn(
                  'group flex min-h-[9rem] cursor-pointer items-center gap-4 px-4 py-4 text-left focus-ring',
                  isDragging && 'bg-info/[0.04]'
                )}
              >
                <FileUp className="size-5 shrink-0 text-info" strokeWidth={2.2} />
                <span className="min-w-0">
                  <span className="block text-sm font-semibold tracking-[-0.01em] text-foreground">
                    {isDragging ? t('emptyState.draggingTitle') : t('emptyState.idleTitle')}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                    {t('emptyState.uploadHint')}
                  </span>
                </span>
              </label>
            </div>
          </div>
        </div>

        <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,0.82fr)_minmax(24rem,1fr)]">
          <div className="divide-y divide-foreground/10 border-y border-foreground/10">
            {processCards.map((item) => {
              const Icon = item.icon
              const content = (
                <div className="relative flex items-start gap-3 py-3 pr-6">
                  <Icon className={cn('mt-0.5 size-4 shrink-0', item.accent)} strokeWidth={2.2} />
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-foreground">
                      {item.title}
                    </div>
                    <div className="mt-1 text-[11px] leading-5 text-muted-foreground">
                      {item.description}
                    </div>
                  </div>
                  {item.action && (
                    <Check className="absolute right-0 top-3.5 size-3.5 text-info" strokeWidth={2.4} />
                  )}
                </div>
              )

              return item.action ? (
                <button
                  key={item.title}
                  type="button"
                  onClick={item.action}
                  className="block w-full text-left focus-ring"
                >
                  {content}
                </button>
              ) : (
                <div key={item.title}>
                  {content}
                </div>
              )
            })}
          </div>

          <section
            data-chunk-empty-visual-map
            className="relative border-t border-foreground/10 pt-5 xl:border-l xl:border-t-0 xl:pl-5 xl:pt-0"
          >
            <div className="flex h-full flex-col gap-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold tracking-[-0.01em] text-foreground">
                    {t('emptyState.visual.title')}
                  </h3>
                  <p className="mt-1 max-w-md text-[11px] leading-5 text-muted-foreground">
                    {t('emptyState.visual.description')}
                  </p>
                </div>
              </div>

              <div className="grid flex-1 gap-4 xl:grid-cols-[0.9fr_1.1fr] xl:items-stretch">
                <div className="relative xl:border-r xl:border-foreground/10 xl:pr-4">
                  <div className="mb-4 flex items-center justify-between">
                    <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/80">
                      Source
                    </span>
                    <span className="text-[10px] font-medium text-info">
                      TXT / PDF
                    </span>
                  </div>
                  <div className="space-y-2.5">
                    <div className="h-3 w-3/4 rounded-full bg-foreground/18" />
                    <div className="h-2.5 w-full rounded-full bg-muted-foreground/16" />
                    <div className="h-2.5 w-5/6 rounded-full bg-muted-foreground/16" />
                    <div className="h-2.5 w-2/3 rounded-full bg-muted-foreground/14" />
                  </div>
                  <div className="mt-6 rounded-lg border border-dashed border-info/25 bg-info/[0.04] p-3">
                    <div className="h-2 w-2/5 rounded-full bg-info/24" />
                    <div className="mt-2 h-2 w-11/12 rounded-full bg-info/16" />
                  </div>
                </div>

                <div className="relative xl:pl-1">
                  <div>
                    {visualSteps.map((step, index) => {
                      const StepIcon = step.icon
                      return (
                        <div
                          key={step.label}
                          className="relative flex items-center gap-3 border-b border-foreground/10 py-3 last:border-b-0"
                        >
                          <StepIcon className={cn('size-4 shrink-0', step.tone)} strokeWidth={2.2} />
                          <div className="min-w-0 flex-1">
                            <div className="text-xs font-semibold tracking-[-0.01em] text-foreground">
                              {step.label}
                            </div>
                            <div className="mt-1 flex gap-1.5">
                              <span className="h-1.5 w-14 rounded-full bg-muted-foreground/18" />
                              <span className="h-1.5 w-8 rounded-full bg-muted-foreground/12" />
                            </div>
                          </div>
                          <span className="text-[10px] font-medium tabular-nums text-muted-foreground/80">
                            0{index + 1}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>

              <div className="grid gap-4 border-t border-foreground/10 pt-3 sm:grid-cols-2">
                <div className="px-1">
                  <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/80">
                    {t('emptyState.visual.metrics.chunks')}
                  </div>
                  <div className="mt-1 flex items-end gap-2">
                    <span className="text-xl font-semibold text-foreground">12</span>
                    <span className="pb-1 text-[10px] text-muted-foreground/80">
                      preview
                    </span>
                  </div>
                </div>
                <div className="border-l border-foreground/10 pl-4">
                  <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/80">
                    {t('emptyState.visual.metrics.coverage')}
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full w-3/4 rounded-full bg-info" />
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>

      <ChunkingHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </main>
  )
}

export function Workbench() {
  const t = useTranslations('ChunkPreview')
  const {
    currentFile,
    currentFileItem,
    showOriginalPanel,
    showSettingsPanel,
    toggleSettingsPanel,
  } = useChunkPreview()
  const toolbar = currentFile && currentFileItem ? <TopBar /> : null

  return (
    <>
      <WorkbenchScaffold
        title={t('workbench.title')}
        description={t('workbench.description')}
        iconImage="chunk-preview"
        icon={Layers}
        iconColor="text-primary"
        header={<ChunkPreviewWorkbenchHeader />}
        size="full"
        toolbar={toolbar}
        paneGroupClassName="gap-5 xl:gap-6"
        leftPanel={
          <WorkbenchPane bodyClassName="p-0">
            <Sidebar variant="pane" />
          </WorkbenchPane>
        }
        mainPanel={
          <WorkbenchPane
            className="flex-1 min-w-0"
            bodyClassName="p-0 overflow-hidden"
          >
            {currentFile && currentFileItem ? (
              <main className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-background lg:flex-row">
                {showOriginalPanel ? <OriginalPreview /> : null}
                <ChunkList />
              </main>
            ) : (
              <ChunkPreviewEmptyCanvas />
            )}
          </WorkbenchPane>
        }
      />

      {/* Mobile: settings panel as a modal (sheet-like) */}
      <WorkbenchPanelDialog
        open={showSettingsPanel}
        onOpenChange={(open) => {
          if (open !== showSettingsPanel) toggleSettingsPanel()
        }}
        title={t('workbench.settingsPanelTitle')}
      >
        <Sidebar variant="dialog" />
      </WorkbenchPanelDialog>
    </>
  )
}
