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
  PipelineRail,
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
      accent: 'primary',
    },
    {
      icon: ScanLine,
      title: t('emptyState.previewTitle'),
      description: t('emptyState.previewDescription'),
      action: null,
      accent: 'info',
    },
    {
      icon: Cpu,
      title: t('emptyState.tipsTitle'),
      description: t('emptyState.tipsDescription'),
      action: null,
      accent: 'amber',
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
      tone: 'border-primary/20 bg-primary/10 text-primary',
    },
    {
      icon: ScanLine,
      label: t('emptyState.visual.steps.chunk'),
      tone: 'border-info/20 bg-info/10 text-info',
    },
    {
      icon: Layers,
      label: t('emptyState.visual.steps.review'),
      tone: 'border-success/20 bg-success/10 text-success',
    },
  ]

  return (
    <main
      data-chunk-preview-empty-canvas="true"
      className={cn(
        'relative flex h-full min-h-0 flex-1 items-start overflow-hidden transition-colors duration-500',
        'bg-[radial-gradient(circle_at_18%_12%,hsl(var(--primary)/0.12),transparent_35%),radial-gradient(circle_at_84%_18%,hsl(var(--info)/0.12),transparent_30%),linear-gradient(135deg,hsl(var(--background)),hsl(var(--muted)/0.3))]',
        isDragging && 'bg-primary/10'
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-10 top-10 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--primary)/0.4),transparent)]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[url('/grid.svg')] opacity-[0.045] [mask-image:radial-gradient(ellipse_at_center,black,transparent_80%)]"
      />

      <div className="relative z-10 mx-auto flex w-full max-w-6xl flex-col px-6 py-6">
        <div
          data-chunk-empty-intake-panel
          className="rounded-3xl border border-border/45 bg-background/72 p-4 shadow-[0_10px_30px_-24px_rgba(15,23,42,0.35)] backdrop-blur-sm"
        >
          <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch lg:justify-between">
            <div className="flex min-w-0 flex-1 flex-col justify-between gap-3">
              <div className="inline-flex w-fit items-center gap-2 rounded-full border border-primary/20 bg-primary/8 px-3 py-1 text-[9px] font-black uppercase tracking-[0.16em] text-primary antialiased">
                <Layers className="size-3.5" strokeWidth={2.5} />
                {t('emptyState.badge')}
              </div>
              <div>
                <h2 className="max-w-2xl text-2xl font-black tracking-[-0.01em] text-foreground md:text-3xl antialiased">
                  {t('emptyState.title')}
                </h2>
                <p className="mt-2 max-w-3xl text-sm font-medium leading-6 text-muted-foreground/78 antialiased">
                  {t('emptyState.description')}
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 w-fit rounded-full border-border/70 bg-background/70 px-3 text-[11px] font-bold shadow-none antialiased hover:bg-background"
                onClick={() => setHelpOpen(true)}
              >
                <HelpCircle className="mr-1.5 size-3.5 text-primary" strokeWidth={2.5} />
                {t('emptyState.help')}
              </Button>
            </div>

            <div
              className={cn(
                'relative w-full overflow-hidden rounded-2xl border border-dashed border-primary/25 bg-muted/10 p-1 transition-all duration-300 lg:w-[24rem]',
                isDragging ? 'border-primary bg-primary/6' : 'hover:border-primary/40 hover:bg-muted/16'
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
                  'group flex min-h-[9rem] cursor-pointer items-center gap-4 rounded-[1rem] px-4 py-4 text-left focus-ring transition-all',
                  isDragging ? 'bg-primary/6' : 'bg-background/50 hover:bg-background/70'
                )}
              >
                <span className="grid size-12 shrink-0 place-items-center rounded-xl border border-primary/18 bg-primary/8 text-primary">
                  <FileUp className="size-5" strokeWidth={2.5} />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-black tracking-[-0.01em] text-foreground antialiased">
                    {isDragging ? t('emptyState.draggingTitle') : t('emptyState.idleTitle')}
                  </span>
                  <span className="mt-1 block text-xs font-semibold leading-5 text-muted-foreground/70 antialiased">
                    {t('emptyState.uploadHint')}
                  </span>
                </span>
              </label>
            </div>
          </div>
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,0.82fr)_minmax(24rem,1fr)]">
          <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-1">
            {processCards.map((item) => {
              const Icon = item.icon
              const content = (
                <div className="group/card relative h-full space-y-3 rounded-2xl border border-border/35 bg-background/45 p-4 transition-all hover:bg-background/65 antialiased">
                  <div
                    className={cn(
                      'flex size-9 items-center justify-center rounded-xl border transition-all duration-300 group-hover/card:scale-105 shadow-none',
                      item.accent === 'primary' && 'border-primary/20 bg-primary/10 text-primary',
                      item.accent === 'info' && 'border-info/20 bg-info/10 text-info',
                      item.accent === 'amber' &&
                        'border-warning/20 bg-warning/10 text-warning'
                    )}
                  >
                    <Icon className="size-4.5" strokeWidth={2.5} />
                  </div>
                  <div>
                    <div className="text-xs font-black uppercase tracking-[0.12em] text-foreground">
                      {item.title}
                    </div>
                    <div className="mt-1 text-[11px] font-bold leading-5 text-muted-foreground/75">
                      {item.description}
                    </div>
                  </div>
                  {item.action && (
                    <div className="absolute bottom-4 right-4 opacity-0 transition-opacity group-hover/card:opacity-100">
                      <div className="grid size-5 place-items-center rounded-full bg-primary/10 text-primary">
                        <Check className="size-3" strokeWidth={3} />
                      </div>
                    </div>
                  )}
                </div>
              )

              return item.action ? (
                <button
                  key={item.title}
                  type="button"
                  onClick={item.action}
                  className="h-full text-left focus-ring"
                >
                  {content}
                </button>
              ) : (
                <div key={item.title} className="h-full">
                  {content}
                </div>
              )
            })}
          </div>

          <section
            data-chunk-empty-visual-map
            className="relative min-h-[18rem] overflow-hidden rounded-3xl border border-border/35 bg-background/50 p-4 shadow-[0_16px_44px_-34px_rgba(15,23,42,0.45)] antialiased"
          >
            <div
              aria-hidden
              className="absolute -right-16 -top-20 size-56 rounded-full bg-info/12 blur-3xl"
            />
            <div
              aria-hidden
              className="absolute -bottom-20 left-1/4 size-48 rounded-full bg-primary/10 blur-3xl"
            />

            <div className="relative z-10 flex h-full flex-col gap-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-sm font-black tracking-[-0.01em] text-foreground">
                    {t('emptyState.visual.title')}
                  </h3>
                  <p className="mt-1 max-w-md text-[11px] font-semibold leading-5 text-muted-foreground/72">
                    {t('emptyState.visual.description')}
                  </p>
                </div>
                <div className="hidden rounded-full border border-border/45 bg-background/60 px-3 py-1 text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground/65 sm:block">
                  Preview
                </div>
              </div>

              <div className="grid flex-1 gap-4 md:grid-cols-[0.9fr_1.1fr] md:items-stretch">
                <div className="relative overflow-hidden rounded-2xl border border-border/35 bg-background/58 p-4">
                  <div className="mb-4 flex items-center justify-between">
                    <span className="text-[10px] font-black uppercase tracking-[0.14em] text-muted-foreground/65">
                      Source
                    </span>
                    <span className="rounded-full bg-primary/8 px-2 py-0.5 text-[9px] font-black text-primary">
                      TXT / PDF
                    </span>
                  </div>
                  <div className="space-y-2.5">
                    <div className="h-3 w-3/4 rounded-full bg-foreground/18" />
                    <div className="h-2.5 w-full rounded-full bg-muted-foreground/16" />
                    <div className="h-2.5 w-5/6 rounded-full bg-muted-foreground/16" />
                    <div className="h-2.5 w-2/3 rounded-full bg-muted-foreground/14" />
                  </div>
                  <div className="mt-6 rounded-xl border border-dashed border-primary/22 bg-primary/6 p-3">
                    <div className="h-2 w-2/5 rounded-full bg-primary/24" />
                    <div className="mt-2 h-2 w-11/12 rounded-full bg-primary/16" />
                  </div>
                </div>

                <div className="relative rounded-2xl border border-border/35 bg-background/48 p-4">
                  <div className="absolute left-5 top-1/2 hidden h-px w-[calc(100%-2.5rem)] -translate-y-1/2 bg-[linear-gradient(90deg,hsl(var(--primary)/0.35),hsl(var(--info)/0.35),hsl(142_70%_45%/0.35))] md:block" />
                  <div className="relative grid gap-3">
                    {visualSteps.map((step, index) => {
                      const StepIcon = step.icon
                      return (
                        <div
                          key={step.label}
                          className="relative flex items-center gap-3 rounded-2xl border border-border/40 bg-background/72 p-3 shadow-[0_8px_24px_-22px_rgba(15,23,42,0.45)]"
                        >
                          <div
                            className={cn(
                              'grid size-9 shrink-0 place-items-center rounded-xl border',
                              step.tone
                            )}
                          >
                            <StepIcon className="size-4" strokeWidth={2.5} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="text-xs font-black tracking-[-0.01em] text-foreground">
                              {step.label}
                            </div>
                            <div className="mt-1 flex gap-1.5">
                              <span className="h-1.5 w-14 rounded-full bg-muted-foreground/18" />
                              <span className="h-1.5 w-8 rounded-full bg-muted-foreground/12" />
                            </div>
                          </div>
                          <span className="rounded-full bg-muted/60 px-2 py-0.5 text-[10px] font-black text-muted-foreground/70">
                            0{index + 1}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                <div className="rounded-2xl border border-border/30 bg-background/45 px-3 py-2">
                  <div className="text-[10px] font-black uppercase tracking-[0.14em] text-muted-foreground/60">
                    {t('emptyState.visual.metrics.chunks')}
                  </div>
                  <div className="mt-1 flex items-end gap-2">
                    <span className="text-xl font-black text-foreground">12</span>
                    <span className="pb-1 text-[10px] font-bold text-muted-foreground/62">
                      preview
                    </span>
                  </div>
                </div>
                <div className="rounded-2xl border border-border/30 bg-background/45 px-3 py-2">
                  <div className="text-[10px] font-black uppercase tracking-[0.14em] text-muted-foreground/60">
                    {t('emptyState.visual.metrics.coverage')}
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full w-3/4 rounded-full bg-[linear-gradient(90deg,hsl(var(--primary)),hsl(var(--info)))]" />
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
        pipelineRail={<PipelineRail />}
        toolbar={toolbar}
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
