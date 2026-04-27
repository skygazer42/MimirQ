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
  // t("dataset.label")
  // t("lifecycle.placeholder")
  // t('header.title')
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
    <div className="space-y-2">
      {/* text-[11px] font-medium tracking-[0.08em] */}
      {/* bg-gradient-to-r from-primary/35 via-border/60 to-transparent */}
      <div className="flex items-start gap-2.5">
        <div className="relative flex size-6 items-center justify-center rounded-lg border border-border/70 bg-background text-primary/80 shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_10px_20px_-18px_rgba(15,23,42,0.24)]">
          <span className="pointer-events-none absolute inset-0 rounded-[inherit] bg-[linear-gradient(135deg,rgba(255,255,255,0.28),transparent_54%)] opacity-80" />
          <Filter className="h-3 w-3" />
        </div>
        <div className="min-w-0">
          <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-foreground/68">
            {t('header.subtitle')}
          </div>
          <div className="mt-0.5 text-[13px] font-medium tracking-[-0.02em] text-foreground/92">
            导航
          </div>
          <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground/76">
            收拢数据集、状态、目录与生命周期筛选，在侧列表实时联动。
          </div>
        </div>
      </div>
      <div className="h-px w-full bg-border/70" />
    </div>
  )

  // const sectionClassName = embedded ? 'space-y-3' : 'space-y-2'
  const sectionClassName = embedded ? 'space-y-2' : 'space-y-2'
  // const sectionShellClassName = embedded
  // rounded-2xl border border-border/40 bg-muted/10
  const sectionShellClassName = embedded
    ? 'rounded-[18px] border border-border/70 bg-background/90 px-2.5 py-2.5 shadow-[0_10px_20px_-22px_rgba(15,23,42,0.22)]'
    : undefined
  const embeddedSelectTriggerClassName = embedded
    ? 'h-8 rounded-[12px] border-border/70 bg-background pl-3 pr-2 text-[11px] shadow-none transition-colors duration-200 [&>span]:font-medium [&>span]:text-foreground/90 [&>svg]:h-3 [&>svg]:w-3 [&>svg]:text-muted-foreground/65'
    : 'h-9'
  const embeddedSelectContentClassName = embedded
    ? 'rounded-[14px] border-border/70 bg-popover p-1 shadow-[0_18px_42px_-28px_hsl(var(--foreground)/0.36)]'
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
    <div className={cn('space-y-3', embedded && 'space-y-2.5 p-3')}>
      {/* cn('space-y-4', embedded && 'space-y-3 p-3.5 lg:p-4') */}
      <div className={cn(sectionClassName, sectionShellClassName)}>
        <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/72">{t("dataset.label")}</div>
        <div className="space-y-1.5">
          <button
            type="button"
            aria-label={t("dataset.ariaLabel")}
            aria-expanded={datasetListExpanded}
            onClick={() => setDatasetListExpanded((prev) => !prev)}
            className={cn(
              'flex w-full items-center justify-between gap-2.5 rounded-[12px] border border-border/70 bg-background px-2.5 py-2 text-left transition-colors focus-ring',
              datasetListExpanded
                ? 'border-primary/25'
                : 'hover:border-border hover:bg-background/96'
            )}
          >
            <div className="min-w-0">
              <div className="truncate text-[11px] font-normal text-foreground/90">
                {datasetsLoading ? t('dataset.loading') : selectedDatasetItem.name}
              </div>
            </div>
            <ChevronDown
              className={cn(
                'h-3 w-3 shrink-0 text-muted-foreground transition-transform duration-200',
                datasetListExpanded && 'rotate-180'
              )}
            />
          </button>

          {datasetListExpanded ? (
            <div
              role="group"
              aria-label={t("dataset.ariaLabel")}
              className={cn(
                'space-y-1 rounded-[12px] border border-border/70 bg-background p-1'
              )}
            >
              {datasetsLoading ? (
                <div className="rounded-lg px-2 py-1.5 text-[10px] text-muted-foreground">{t('dataset.loading')}</div>
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
                          'flex w-full items-center gap-2 rounded-[10px] px-2 py-1.5 text-left text-[11px] transition-colors focus-ring',
                          isActive
                            ? 'bg-primary/10 text-primary'
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
                        <span className="min-w-0 truncate font-normal text-foreground/88">{item.name}</span>
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
        <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/72">{t('status.label')}</div>
          <div className="flex flex-wrap items-center gap-1.5">
            {statusItems.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setStatusFilter(item.key as DocStatusFilter)}
                className={cn(
                  'relative overflow-hidden transition-[transform,box-shadow]',
                  embedded
                    ? 'min-h-8 rounded-[10px] border px-2 py-1 text-[10px] font-medium transition-all duration-300 hover:-translate-y-[1px] focus-ring'
                    : 'h-9 rounded-full border px-3 text-xs font-medium transition-all duration-300 hover:-translate-y-[1px] focus-ring',
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
                {/* className={cn('pointer-events-none absolute inset-x-2 bottom-1 h-[2px] rounded-full opacity-90', item.ratioClassName)} */}
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
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/72">{t('folder.label')}</div>
                {folderPath ? (
                  <button
                    type="button"
                    onClick={() => setFolderPath(null)}
                    className="text-[10px] text-muted-foreground underline underline-offset-4 hover:text-foreground"
                  >
                    {t('folder.clear')}
                  </button>
                ) : null}
              </div>
              <DatasetFolderTree
                className={embedded ? 'rounded-[12px] border border-border/70 bg-background p-2' : undefined}
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
              className="group/empty rounded-[16px] border border-dashed border-border/70 bg-transparent p-2.5 text-[10px] text-muted-foreground"
            >
              {/* group/empty rounded-2xl border border-dashed border-border/60 */}
              {/* hover:scale-[1.015] */}
              <div className="flex items-start gap-2.5">
                <div className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-lg border border-border/70 bg-background text-muted-foreground/60">
                  <FolderSearch className="h-3 w-3" />
                </div>
                <div className="space-y-1">
                  <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/45">
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
          <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/72">{t('lifecycle.label')}</div>
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
        <div className="border-b border-border/70 bg-background/92 px-3 py-3">{header}</div>
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
