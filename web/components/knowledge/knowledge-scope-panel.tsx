import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
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
  ].map((item) => ({
    ...item,
    label: t(`status.${item.key}.label`),
  }))

  const header = (
    <div className="flex items-baseline gap-2">
      <div className="text-sm font-semibold">{t('header.title')}</div>
      <div className="text-xs text-muted-foreground">{t('header.subtitle')}</div>
    </div>
  )

  const sectionClassName = embedded ? 'space-y-3 border-b border-border/50 pb-4 last:border-b-0 last:pb-0' : 'space-y-2'
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

  const body = (
    <div className={cn('space-y-4', embedded && 'p-3.5 lg:p-4')}>
      <div className={sectionClassName}>
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
        <div className={sectionClassName}>
          <div className="text-xs font-medium text-muted-foreground">{t('status.label')}</div>
          <div className="flex flex-wrap items-center gap-2">
            {statusItems.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setStatusFilter(item.key as DocStatusFilter)}
                className={cn(
                  embedded
                    ? 'min-h-9 rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition-colors focus-ring'
                    : 'h-9 rounded-full border px-3 text-xs font-semibold transition-colors focus-ring',
                  statusFilter === item.key
                    ? 'bg-primary/10 border-primary/40 text-primary'
                    : 'bg-background/60 border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/30'
                )}
                aria-pressed={statusFilter === item.key}
              >
                {item.label}
                <span className="ml-1 tabular-nums text-[11px] opacity-80">{item.count}</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {showDocumentFilters ? (
        <div className={sectionClassName}>
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
            <div className="rounded-xl border border-dashed border-border/60 bg-transparent p-3 text-[11px] text-muted-foreground">
              {t('folder.empty')}
            </div>
          )}
        </div>
      ) : null}

      {showDocumentFilters ? (
        <div className={sectionClassName}>
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
