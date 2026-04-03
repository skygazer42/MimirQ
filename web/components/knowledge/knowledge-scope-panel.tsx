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

  const sectionClassName = embedded
    ? 'space-y-3 rounded-2xl border border-border/60 bg-background/80 p-4 shadow-soft/10'
    : 'space-y-2'

  const body = (
    <div className={cn('space-y-4', embedded && 'p-4 lg:p-5')}>
      <div className={sectionClassName}>
        <div className="text-xs font-medium text-muted-foreground">{t("dataset.label")}</div>
        <Select value={datasetScope} onValueChange={setDatasetScope}>
          <SelectTrigger
            className={cn('w-full', embedded ? 'h-10 rounded-xl border-border/70 bg-background/90' : 'h-9')}
            disabled={datasetsLoading}
            aria-label={t("dataset.ariaLabel")}
          >
            <SelectValue placeholder={datasetsLoading ? t('dataset.loading') : t('dataset.all')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={DATASET_ALL}>{t("dataset.all")}</SelectItem>
            {datasets.map((ds) => (
              <SelectItem key={ds.id} value={ds.id}>
                {ds.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

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
                  ? 'min-h-10 rounded-2xl border px-3 py-2 text-xs font-semibold transition-colors focus-ring'
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
              className={embedded ? 'rounded-2xl border border-border/60 bg-muted/20 p-3' : undefined}
              datasetId={selectedDatasetId}
              lifecycle={lifecycleFilter}
              selectedPath={folderPath}
              onSelect={setFolderPath}
            />
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-border/70 bg-muted/20 p-4 text-xs text-muted-foreground">
            {t('folder.empty')}
          </div>
        )}
      </div>

      <div className={sectionClassName}>
        <div className="text-xs font-medium text-muted-foreground">{t('lifecycle.label')}</div>
        <Select value={lifecycleFilter} onValueChange={(v) => setLifecycleFilter(v as DocLifecycleFilter)}>
          <SelectTrigger
            className={cn('w-full', embedded ? 'h-10 rounded-xl border-border/70 bg-background/90' : 'h-9')}
            aria-label={t("lifecycle.ariaLabel")}
          >
            <SelectValue placeholder={t("lifecycle.placeholder")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="active">{t("lifecycle.active")}</SelectItem>
            <SelectItem value="disabled">{t('lifecycle.disabled')}</SelectItem>
            <SelectItem value="archived">{t("lifecycle.archived")}</SelectItem>
            <SelectItem value="all">{t('lifecycle.all')}</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  )

  if (embedded) {
    return (
      <div className={cn('flex flex-col border-0 bg-transparent', className)}>
        <div className="border-b border-border/60 bg-background/60 px-5 py-4 backdrop-blur-sm">{header}</div>
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
