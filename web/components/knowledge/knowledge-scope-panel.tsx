import { useState } from 'react'
import { ChevronDown, Filter, FolderSearch } from 'lucide-react'
import { WorkbenchPane } from '@/components/workbench'
import { DatasetFolderTree } from '@/components/document-library/dataset-folder-tree'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { Dataset } from '@/types'
import { useTranslations } from 'next-intl'

type DocLifecycleFilter = 'active' | 'archived' | 'disabled' | 'all'
type DocStatusFilter = 'all' | 'completed' | 'processing' | 'failed' | 'quarantined'
type DocCountValue = string | number

type KnowledgeScopePanelProps = {
  className?: string
  surface?: 'pane' | 'embedded'
  mode?: 'documents' | 'retrieval' | 'settings'
  datasets: Dataset[]
  datasetsLoading?: boolean

  datasetScope: string
  setDatasetScope: (value: string) => void
  datasetAllValue?: string

  selectedDatasetId?: string
  lifecycleFilter: DocLifecycleFilter
  setLifecycleFilter: (value: DocLifecycleFilter) => void
  folderPath: string | null
  setFolderPath: (value: string | null) => void

  statusFilter: DocStatusFilter
  setStatusFilter: (value: DocStatusFilter) => void
  totalDocs: DocCountValue
  completedDocsValue: DocCountValue
  processingDocsValue: DocCountValue
  failedDocsValue: DocCountValue
  quarantinedDocsValue: DocCountValue
}

export function KnowledgeScopePanel({
  className,
  surface = 'pane',
  mode = 'documents',
  datasets,
  datasetsLoading = false,
  datasetScope,
  setDatasetScope,
  datasetAllValue,
  selectedDatasetId,
  lifecycleFilter,
  setLifecycleFilter,
  folderPath,
  setFolderPath,
  statusFilter,
  setStatusFilter,
  totalDocs,
  completedDocsValue,
  processingDocsValue,
  failedDocsValue,
  quarantinedDocsValue,
}: Readonly<KnowledgeScopePanelProps>) {
  const t = useTranslations('KnowledgeScopePanel')
  const DATASET_ALL = datasetAllValue ?? '__all__'
  const embedded = surface === 'embedded'
  const showDocumentFilters = mode === 'documents'
  const statusItems = [
    { key: 'all', count: totalDocs },
    { key: 'completed', count: completedDocsValue },
    { key: 'processing', count: processingDocsValue },
    { key: 'failed', count: failedDocsValue },
    { key: 'quarantined', count: quarantinedDocsValue },
  ].map((item) => {
    const count = Number(item.count || 0)
    const ratio = item.key === 'all'
      ? 1
      : Math.max(0, Math.min(1, Number(totalDocs || 0) > 0 ? count / Number(totalDocs || 0) : 0))

    return {
      ...item,
      label: t(`status.${item.key}.label`),
      ratio,
      showRatioBar: item.key !== 'all' && count > 0 && Number(totalDocs || 0) > 0,
      ratioClassName:
        item.key === 'completed'
          ? 'bg-success/70'
          : item.key === 'processing'
            ? 'bg-info/70'
            : item.key === 'failed'
              ? 'bg-destructive/75'
              : item.key === 'quarantined'
                ? 'bg-warning/75'
                : 'bg-primary/55',
      countElement: (
        <span className={cn(
          "font-mono text-[11px] transition-all tabular-nums",
          count === 0 
            ? "opacity-20 font-medium" 
            : "font-bold text-foreground bg-muted/40 px-1.5 py-0.5 rounded-md shadow-inner-soft"
        )}>
          {count}
        </span>
      )
    }
  })

  const header = (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2">
        <div className="flex size-6 items-center justify-center rounded-lg border border-border/50 bg-background/60 text-primary/70 shadow-sm backdrop-blur-sm">
          <Filter className="h-3.5 w-3.5" />
        </div>
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-foreground/72">
            {t('header.subtitle')}
          </div>
          <div className="text-[11px] font-medium tracking-[0.08em] text-muted-foreground/72">
            {t('header.title')}
          </div>
        </div>
      </div>
      <div className="h-px w-full bg-gradient-to-r from-primary/35 via-border/60 to-transparent" />
    </div>
  )

  const sectionClassName = embedded ? 'space-y-3' : 'space-y-2'
  const sectionShellClassName = embedded
    ? 'rounded-2xl border border-border/40 bg-muted/10 px-3 py-3 backdrop-blur-sm shadow-[inset_0_1px_0_hsl(var(--background)/0.28)]'
    : undefined
  const embeddedSelectTriggerClassName = embedded
    ? 'h-10 rounded-xl border-border/50 bg-background/70 pl-3.5 pr-2.5 shadow-none backdrop-blur-sm transition-[border-color,background-color,box-shadow] duration-200 ease-out hover:border-border/70 hover:bg-background/88 hover:shadow-[0_10px_24px_-24px_hsl(var(--foreground)/0.45)] focus:border-primary/35 focus:ring-primary/15 data-[state=open]:border-primary/35 data-[state=open]:bg-background/95 data-[state=open]:shadow-[0_16px_34px_-24px_hsl(var(--primary)/0.28)] [&>span]:font-medium [&>span]:text-foreground/90 [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:text-muted-foreground/65'
    : 'h-9'
  const embeddedSelectContentClassName = embedded
    ? 'rounded-xl border-border/55 bg-popover/96 p-1 shadow-[0_18px_42px_-28px_hsl(var(--foreground)/0.36)] backdrop-blur-md'
    : undefined
  const datasetItems = [
    { id: DATASET_ALL, name: t('dataset.all') },
    ...datasets.map((ds) => ({ id: ds.id, name: ds.name })),
  ]
  const [datasetListExpanded, setDatasetListExpanded] = useState(false)
  const selectedDatasetItem = datasetItems.find((item) => item.id === datasetScope) ?? datasetItems[0]

  const statusThemes: Record<DocStatusFilter, string> = {
    all: 'bg-primary/10 border-primary/40 text-primary shadow-[0_0_12px_-4px_rgba(var(--primary),0.3)]',
    completed: 'bg-emerald-500/10 border-emerald-500/40 text-emerald-600 dark:text-emerald-400 shadow-[0_0_12px_-4px_rgba(16,185,129,0.3)]',
    processing: 'bg-sky-500/10 border-sky-500/40 text-sky-600 dark:text-sky-400 shadow-[0_0_12px_-4px_rgba(14,165,233,0.3)]',
    failed: 'bg-red-500/10 border-red-500/40 text-red-600 dark:text-red-400 shadow-[0_0_12px_-4px_rgba(239,68,68,0.3)]',
    quarantined: 'bg-amber-500/10 border-amber-500/40 text-amber-600 dark:text-amber-400 shadow-[0_0_12px_-4px_rgba(245,158,11,0.3)]',
  }

  const body = (
    <div className={cn('space-y-4', embedded && 'space-y-3 p-3.5 lg:p-4')}>
      <div className={cn(sectionClassName, sectionShellClassName)}>
        <div className="text-xs font-medium text-muted-foreground">{t("dataset.label")}</div>
        <div className="space-y-2">
          <button
            type="button"
            aria-label={t("dataset.ariaLabel")}
            aria-expanded={datasetListExpanded}
            onClick={() => setDatasetListExpanded((prev) => !prev)}
            className={cn(
              'flex w-full items-center justify-between gap-3 rounded-xl border border-border/55 bg-background/60 px-3 py-2.5 text-left transition-colors focus-ring',
              embedded && 'backdrop-blur-sm',
              datasetListExpanded
                ? 'border-primary/25 bg-background/85'
                : 'hover:border-border/75 hover:bg-background/78'
            )}
          >
            <div className="min-w-0">
              <div className="truncate text-[12px] font-medium text-foreground">
                {datasetsLoading ? t('dataset.loading') : selectedDatasetItem.name}
              </div>
            </div>
            <ChevronDown
              className={cn(
                'h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-200',
                datasetListExpanded && 'rotate-180'
              )}
            />
          </button>

          {datasetListExpanded ? (
            <div
              role="group"
              aria-label={t("dataset.ariaLabel")}
              className={cn(
                'space-y-1 rounded-xl border border-border/55 bg-background/55 p-1.5',
                embedded && 'backdrop-blur-sm'
              )}
            >
              {datasetsLoading ? (
                <div className="rounded-lg px-2.5 py-2 text-[11px] text-muted-foreground">{t('dataset.loading')}</div>
              ) : (
                <div className="max-h-56 space-y-1 overflow-y-auto pr-0.5">
                  {datasetItems.map((item) => {
                    const isActive = datasetScope === item.id
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => {
                          setDatasetScope(item.id)
                          setDatasetListExpanded(false)
                        }}
                        className={cn(
                          'flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[12px] transition-colors focus-ring',
                          isActive
                            ? 'bg-primary/10 text-primary shadow-inner-soft'
                            : 'text-muted-foreground hover:bg-muted/35 hover:text-foreground'
                        )}
                        aria-pressed={isActive}
                      >
                        <span
                          className={cn(
                            'h-1.5 w-1.5 shrink-0 rounded-full transition-colors',
                            isActive ? 'bg-primary' : 'bg-muted-foreground/35'
                          )}
                        />
                        <span className="min-w-0 truncate font-medium">{item.name}</span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>

      {showDocumentFilters ? (
        <div className={cn(sectionClassName, sectionShellClassName)}>
          <div className="text-xs font-medium text-muted-foreground">{t('status.label')}</div>
          <div className="flex flex-wrap items-center gap-2">
            {statusItems.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setStatusFilter(item.key as DocStatusFilter)}
                className={cn(
                  'relative overflow-hidden',
                  embedded
                    ? 'min-h-9 rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition-all duration-300 focus-ring'
                    : 'h-9 rounded-full border px-3 text-xs font-semibold transition-all duration-300 focus-ring',
                  statusFilter === item.key
                    ? (statusThemes[item.key as DocStatusFilter] || statusThemes.all)
                    : 'bg-background/60 border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/30 hover:border-border/80'
                )}
                aria-pressed={statusFilter === item.key}
              >
                {item.showRatioBar ? (
                  <span
                    aria-hidden="true"
                    className={cn('pointer-events-none absolute inset-x-2 bottom-1 h-[2px] rounded-full opacity-90 transition-all duration-500', item.ratioClassName)}
                    style={{ width: statusFilter === item.key ? '0%' : `calc(${Math.max(item.ratio * 100, 8)}% - 1rem)` }}
                  />
                ) : null}
                <span className="relative z-10">
                  {item.label}
                  <span className={cn(
                    "ml-1.5 font-mono tabular-nums text-[10px] transition-all",
                    statusFilter === item.key ? "opacity-100 font-black" : "opacity-50"
                  )}>{item.count}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {showDocumentFilters ? (
        <div className={cn(sectionClassName, sectionShellClassName)}>
          {selectedDatasetId ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-xs font-medium text-muted-foreground">{t('folder.label')}</div>
                {folderPath ? (
                  <button
                    type="button"
                    onClick={() => setFolderPath(null)}
                    className="text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground"
                  >
                    {t('folder.clear')}
                  </button>
                ) : null}
              </div>
              <DatasetFolderTree
                className={embedded ? 'rounded-xl border border-border/50 bg-muted/10 p-2.5' : undefined}
                datasetId={selectedDatasetId}
                lifecycle={lifecycleFilter}
                selectedPath={folderPath}
                onSelect={setFolderPath}
              />
            </div>
          ) : (
            <div
              aria-disabled="true"
              title={t('folder.empty')}
              className="group/empty rounded-2xl border border-dashed border-border/60 bg-transparent p-3 text-[11px] text-muted-foreground transition-[transform,border-color,background-color] duration-200 ease-out hover:scale-[1.015] hover:border-primary/35 hover:bg-primary/[0.03]"
            >
              <div className="flex items-start gap-2.5">
                <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-xl border border-border/50 bg-background/60 text-muted-foreground/60 transition-colors group-hover/empty:border-primary/25 group-hover/empty:bg-primary/5 group-hover/empty:text-primary/70">
                  <FolderSearch className="h-3.5 w-3.5" />
                </div>
                <div className="space-y-1">
                  <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-muted-foreground/45 group-hover/empty:text-primary/55">
                    {t('folder.pendingTitle')}
                  </div>
                  <div>{t('folder.empty')}</div>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : null}

      {showDocumentFilters ? (
        <div className={cn(sectionClassName, sectionShellClassName)}>
          <div className="text-xs font-medium text-muted-foreground">{t('lifecycle.label')}</div>
          <Select value={lifecycleFilter} onValueChange={(v) => setLifecycleFilter(v as DocLifecycleFilter)}>
            <SelectTrigger
              className={cn('w-full', embeddedSelectTriggerClassName)}
              aria-label={t("lifecycle.ariaLabel")}
            >
              <SelectValue placeholder={t("lifecycle.placeholder")} />
            </SelectTrigger>
            <SelectContent className={embeddedSelectContentClassName}>
              <SelectItem value="active">{t("lifecycle.active")}</SelectItem>
              <SelectItem value="disabled">{t('lifecycle.disabled')}</SelectItem>
              <SelectItem value="archived">{t("lifecycle.archived")}</SelectItem>
              <SelectItem value="all">{t('lifecycle.all')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      ) : null}
    </div>
  )

  if (embedded) {
    return (
      <div className={cn('flex flex-col border-0 bg-transparent', className)}>
        <div className="border-b border-border/60 bg-background/40 px-4 py-3 backdrop-blur-sm">{header}</div>
        {body}
      </div>
    )
  }

  return (
    <WorkbenchPane className={cn(className)} header={header}>
      {body}
    </WorkbenchPane>
  )
}
