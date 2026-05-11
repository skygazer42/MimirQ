/**
 * Workbench - 主工作台（包含 TopBar、Sidebar 和 Preview）
 */
'use client'

import type { ReactNode } from 'react'
import { FileStack, Layers } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { TopBar } from './top-bar'
import { Sidebar } from './sidebar'
import { OriginalPreview } from './preview/original-preview'
import { ChunkList } from './preview/chunk-list'
import { useChunkPreview } from '@/components/chunk-preview/context'
import {
  PipelineRail,
  WorkbenchPane,
  WorkbenchPanelDialog,
  WorkbenchScaffold,
} from '@/components/workbench'
import { cn } from '@/lib/utils'

function ChunkPreviewHeaderChip({
  label,
  value,
  className,
  valueClassName,
}: Readonly<{
  label: ReactNode
  value: string
  className?: string
  valueClassName?: string
}>) {
  return (
    <span
      className={cn(
        'inline-flex min-w-0 items-center gap-1.5 rounded-lg border border-border/60 bg-muted/35 px-2.5 py-1 text-[11px] font-medium text-muted-foreground/80',
        className
      )}
    >
      <span className="shrink-0">{label}</span>
      <span
        className={cn(
          'min-w-0 truncate font-semibold text-foreground',
          valueClassName
        )}
      >
        {value}
      </span>
    </span>
  )
}

function ChunkPreviewHeaderStat({
  label,
  value,
  emphasis,
}: Readonly<{
  label: string
  value: string
  emphasis?: boolean
}>) {
  return (
    <div className="rounded-2xl border border-border/60 bg-card/82 px-3 py-2 shadow-subtle">
      <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/62">
        {label}
      </div>
      <div
        className={cn(
          'mt-1 truncate text-[13px] font-semibold ',
          emphasis ? 'text-primary' : 'text-foreground'
        )}
      >
        {value}
      </div>
    </div>
  )
}

function ChunkPreviewWorkbenchHeader() {
  const t = useTranslations('ChunkPreview')
  const {
    cacheHit,
    currentFileItem,
    datasetId,
    fileList,
    isLoading,
    isSubmitting,
    lastPreviewDurationMs,
    previewData,
    scopeSyncLoading,
  } = useChunkPreview()

  const scopeLabel = datasetId
    ? currentFileItem?.datasetName || t('workbench.header.datasetBound')
    : t('workbench.header.allSources')
  const currentFileLabel =
    currentFileItem?.displayName || t('workbench.header.noFile')
  const statusLabel = (() => {
    if (isSubmitting) return t('workbench.header.submitting')
    if (isLoading) return t('workbench.header.generating')
    if (scopeSyncLoading) return t('workbench.header.syncing')
    if (previewData)
      return t('workbench.header.ready', { count: previewData.total_chunks })
    return t('workbench.header.waiting')
  })()
  const durationMs =
    typeof previewData?.preview_duration_ms === 'number'
      ? previewData.preview_duration_ms
      : lastPreviewDurationMs
  const durationLabel =
    typeof durationMs === 'number' && Number.isFinite(durationMs)
      ? `${Math.max(0, Math.round(durationMs))} ms`
      : t('workbench.header.notRun')
  const sourceLabel = previewData
    ? previewData.parse_cache_hit || cacheHit
      ? t('workbench.header.cache')
      : t('workbench.header.backend')
    : t('workbench.header.backendMode')

  return (
    <header className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <div className="flex min-w-0 items-start gap-3">
        <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-2xl border border-primary/15 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--primary)/0.08))] shadow-[inset_0_1px_0_hsl(var(--background)),0_10px_24px_-18px_hsl(var(--primary)/0.7)]">
          <Layers className="size-5 text-primary" />
        </div>

        <div className="min-w-0 pt-0.5">
          <div className="text-[10px] font-semibold uppercase tracking-[0.24em] text-primary/70">
            {t('workbench.header.eyebrow')}
          </div>
          <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-[18px] font-semibold leading-6 text-foreground md:text-[21px]">
              {t('workbench.title')}
            </h1>
            <p className="max-w-[62ch] text-[12px] leading-[1.55] text-muted-foreground/76 md:text-[13px]">
              {t('workbench.description')}
            </p>
          </div>

          <div className="mt-2 flex max-w-full flex-wrap items-center gap-1.5">
            <ChunkPreviewHeaderChip
              label={t('workbench.header.scope')}
              value={scopeLabel}
            />
            <ChunkPreviewHeaderChip
              label={t('workbench.header.files')}
              value={t('workbench.header.fileCount', {
                count: fileList.length,
              })}
            />
            <ChunkPreviewHeaderChip
              label={t('workbench.header.status')}
              value={statusLabel}
              className={cn(
                previewData && !isLoading
                  ? 'border-primary/20 bg-primary/[0.07] text-primary/78'
                  : null,
                (isLoading || scopeSyncLoading) &&
                  'border-warning/20 bg-warning/[0.08] text-warning'
              )}
              valueClassName={
                previewData && !isLoading ? 'text-primary' : undefined
              }
            />
            <ChunkPreviewHeaderChip
              label={<FileStack className="size-3.5" aria-hidden />}
              value={currentFileLabel}
              className="max-w-[min(520px,100%)]"
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 lg:min-w-[250px] xl:min-w-[280px]">
        <ChunkPreviewHeaderStat
          label={t('workbench.header.duration')}
          value={durationLabel}
          emphasis={Boolean(previewData)}
        />
        <ChunkPreviewHeaderStat
          label={t('workbench.header.source')}
          value={sourceLabel}
          emphasis={Boolean(previewData)}
        />
      </div>
    </header>
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
            <main className="flex h-full min-h-0 min-w-0 flex-col lg:flex-row overflow-hidden bg-background">
              {showOriginalPanel ? <OriginalPreview /> : null}
              <ChunkList />
            </main>
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
