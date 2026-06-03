/**
 * Workbench - 主工作台（包含 TopBar、Sidebar 和 Preview）
 */
'use client'

import { useState } from 'react'
import { BookOpen, Check, Cpu, FileUp, HelpCircle, Layers, ScanLine } from 'lucide-react'
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

  return (
    <main
      data-chunk-preview-empty-canvas="true"
      className={cn(
        'relative flex h-full min-h-0 flex-1 overflow-hidden transition-colors duration-500',
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

      <div className="relative z-10 mx-auto flex w-full max-w-5xl flex-col justify-center px-8 py-12">
        <div className="mb-10 flex flex-wrap items-end justify-between gap-6">
          <div className="space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/8 px-4 py-1.5 text-[10px] font-black uppercase tracking-[0.2em] text-primary antialiased shadow-[0_2px_8px_-4px_rgba(var(--primary-rgb),0.2)]">
              <Layers className="size-3.5" strokeWidth={2.5} />
              {t('emptyState.badge')}
            </div>
            <h2 className="max-w-2xl text-4xl font-black tracking-tight text-foreground md:text-5xl antialiased">
              {t('emptyState.title')}
            </h2>
            <p className="max-w-2xl text-base font-medium leading-relaxed text-muted-foreground/80 antialiased">
              {t('emptyState.description')}
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            className="rounded-full border-border/80 bg-background/80 px-6 py-5 text-[13px] font-bold shadow-sm transition-all hover:bg-background hover:scale-105 active:scale-95 antialiased"
            onClick={() => setHelpOpen(true)}
          >
            <HelpCircle className="mr-2 size-4 text-primary" strokeWidth={2.5} />
            {t('emptyState.help')}
          </Button>
        </div>

        <div
          className={cn(
            'relative overflow-hidden rounded-[2.5rem] border-2 border-dashed border-primary/20 bg-background/40 p-1 transition-all duration-500 backdrop-blur-sm',
            isDragging ? 'border-primary scale-[1.02] bg-primary/5 shadow-2xl' : 'hover:border-primary/40 hover:bg-background/60 shadow-xl shadow-black/5'
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
            className="group flex min-h-[20rem] cursor-pointer flex-col items-center justify-center rounded-[2.4rem] text-center focus-ring transition-all"
          >
            <div className="relative mb-8 grid size-28 place-items-center">
              <div
                className={cn(
                  "absolute inset-0 rounded-full bg-primary/10 blur-2xl transition-opacity duration-500",
                  isDragging ? "opacity-100" : "opacity-0"
                )}
              />
              <span
                aria-hidden
                className="absolute inset-0 rounded-full border border-primary/20 bg-primary/5 shadow-[inset_0_0_40px_hsl(var(--primary)/0.1)] transition-transform duration-500 group-hover:scale-110"
              />
              <span
                aria-hidden
                className={cn(
                  'absolute inset-4 rounded-full border-2 border-dashed border-info/30',
                  isDragging && 'animate-spin motion-reduce:animate-none'
                )}
              />
              <span className="relative grid size-16 place-items-center rounded-2xl border border-white/20 bg-background/90 text-primary shadow-[0_20px_48px_-24px_hsl(var(--primary)/0.8)] transition-all duration-300 group-hover:-translate-y-1 group-hover:shadow-[0_24px_56px_-20px_hsl(var(--primary)/1)]">
                <FileUp className="size-7" strokeWidth={2.5} />
              </span>
            </div>
            <span className="text-2xl font-black tracking-tight text-foreground antialiased">
              {isDragging ? t('emptyState.draggingTitle') : t('emptyState.idleTitle')}
            </span>
            <span className="mt-3 text-sm font-bold text-muted-foreground/60 antialiased">
              {t('emptyState.uploadHint')}
            </span>
          </label>
        </div>

        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {processCards.map((item) => {
            const Icon = item.icon
            const content = (
              <div className="group/card relative h-full space-y-4 rounded-2xl border border-border/40 bg-background/20 p-5 transition-all hover:bg-background/60 hover:shadow-lg hover:shadow-black/5 antialiased">
                <div className={cn(
                  "flex size-10 items-center justify-center rounded-xl border transition-all duration-300 group-hover/card:scale-110 shadow-sm",
                  item.accent === 'primary' && "border-primary/20 bg-primary/10 text-primary",
                  item.accent === 'info' && "border-info/20 bg-info/10 text-info",
                  item.accent === 'amber' && "border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-400"
                )}>
                  <Icon className="size-5" strokeWidth={2.5} />
                </div>
                <div>
                  <div className="text-sm font-black uppercase tracking-wider text-foreground">
                    {item.title}
                  </div>
                  <div className="mt-1.5 text-xs font-bold leading-relaxed text-muted-foreground/75">
                    {item.description}
                  </div>
                </div>
                {item.action && (
                  <div className="absolute bottom-4 right-4 opacity-0 transition-opacity group-hover/card:opacity-100">
                    <div className="size-5 rounded-full bg-primary/10 text-primary grid place-items-center">
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
                className="text-left focus-ring"
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
