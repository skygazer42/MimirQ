/**
 * Workbench - 主工作台（包含 TopBar、Sidebar 和 Preview）
 */
'use client'

import { useState } from 'react'
import { BookOpen, Cpu, FileUp, HelpCircle, Layers, ScanLine } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { TopBar } from './top-bar'
import { Sidebar } from './sidebar'
import { OriginalPreview } from './preview/original-preview'
import { ChunkList } from './preview/chunk-list'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkingHelpDialog } from '@/components/chunk-preview/components/chunking-help-dialog'
import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/ui/page-header'
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

  return (
    <header>
      <PageHeader
        title={t('workbench.title')}
        description={t('workbench.description')}
        iconImage="chunk-preview"
        icon={Layers}
        iconColor="text-primary"
        badge={String(t('workbench.header.eyebrow'))}
        compact
        className="p-0"
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
  }> = [
    {
      icon: BookOpen,
      title: t('emptyState.exampleTitle'),
      description: t('emptyState.exampleDescription'),
      action: loadExample,
    },
    {
      icon: ScanLine,
      title: t('emptyState.previewTitle'),
      description: t('emptyState.previewDescription'),
      action: null,
    },
    {
      icon: Cpu,
      title: t('emptyState.tipsTitle'),
      description: t('emptyState.tipsDescription'),
      action: null,
    },
  ]

  return (
    <main
      data-chunk-preview-empty-canvas="true"
      className={cn(
        'relative flex h-full min-h-0 flex-1 overflow-hidden bg-[radial-gradient(circle_at_18%_12%,hsl(var(--primary)/0.10),transparent_30%),radial-gradient(circle_at_84%_18%,hsl(var(--info)/0.10),transparent_28%),linear-gradient(135deg,hsl(var(--background)),hsl(var(--surface-2)/0.62))]',
        isDragging && 'bg-primary/8'
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-10 top-10 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--primary)/0.32),transparent)]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[url('/grid.svg')] opacity-[0.035]"
      />

      <div className="relative z-10 mx-auto flex w-full max-w-5xl flex-col justify-center px-6 py-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-primary/16 bg-primary/8 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">
              <Layers className="size-3.5" />
              {t('emptyState.badge')}
            </div>
            <h2 className="mt-4 max-w-2xl text-3xl font-semibold tracking-[-0.04em] text-foreground md:text-4xl">
              {t('emptyState.title')}
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
              {t('emptyState.description')}
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            className="rounded-full border-border/60 bg-background/76 text-[12px]"
            onClick={() => setHelpOpen(true)}
          >
            <HelpCircle className="mr-1.5 size-3.5" />
            {t('emptyState.help')}
          </Button>
        </div>

        <div
          className={cn(
            'relative overflow-hidden border-y border-dashed border-primary/24 px-4 py-7 transition-colors duration-150 md:px-6 md:py-9 motion-reduce:transition-none',
            isDragging && 'border-primary/50 bg-primary/8'
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
            className="group flex min-h-[17rem] cursor-pointer flex-col items-center justify-center rounded-[1.4rem] text-center focus-ring"
          >
            <span className="relative mb-5 grid size-24 place-items-center">
              <span
                aria-hidden
                className="absolute inset-0 rounded-full border border-primary/18 bg-primary/8 shadow-[inset_0_0_34px_hsl(var(--primary)/0.08)]"
              />
              <span
                aria-hidden
                className={cn(
                  'absolute inset-3 rounded-full border border-dashed border-info/28',
                  isDragging && 'animate-spin motion-reduce:animate-none'
                )}
              />
              <span className="relative grid size-14 place-items-center rounded-2xl bg-background/86 text-primary shadow-[0_18px_42px_-30px_hsl(var(--primary)/0.85)]">
                <FileUp className="size-6" />
              </span>
            </span>
            <span className="text-lg font-semibold text-foreground">
              {isDragging ? t('emptyState.draggingTitle') : t('emptyState.idleTitle')}
            </span>
            <span className="mt-2 text-xs text-muted-foreground">
              {t('emptyState.uploadHint')}
            </span>
          </label>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {processCards.map((item) => {
            const Icon = item.icon
            const content = (
              <>
                <div className="mb-3 flex size-9 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Icon className="size-4" />
                </div>
                <div className="text-sm font-semibold text-foreground">
                  {item.title}
                </div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  {item.description}
                </div>
              </>
            )

            return item.action ? (
              <button
                key={item.title}
                type="button"
                onClick={item.action}
                className="border-l border-border/70 pl-4 text-left transition-colors hover:border-primary/45 focus-ring"
              >
                {content}
              </button>
            ) : (
              <div key={item.title} className="border-l border-border/70 pl-4">
                {content}
              </div>
            )
          })}
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
