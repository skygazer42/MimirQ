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

  return (
    <WorkbenchPane
      className={cn(className)}
      header={
        <div className="flex items-baseline gap-2">
          <div className="text-sm font-semibold">{t('header.title')}</div>
          <div className="text-xs text-muted-foreground">{t('header.subtitle')}</div>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">{t("dataset.label")}</div>
          <Select value={datasetScope} onValueChange={setDatasetScope}>
            <SelectTrigger
              className="h-9 w-full"
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

        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">{t('status.label')}</div>
          <div className="flex flex-wrap items-center gap-2">
            {statusItems.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setStatusFilter(item.key as DocStatusFilter)}
                className={cn(
                  'h-9 px-3 rounded-full border text-xs font-semibold transition-colors focus-ring',
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

        {selectedDatasetId ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <div className="text-xs font-medium text-muted-foreground">{t('folder.label')}</div>
              {folderPath ? (
                <button
                  type="button"
                  onClick={() => setFolderPath(null)}
                  className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-4"
                >
                  {t('folder.clear')}
                </button>
              ) : null}
            </div>
            <DatasetFolderTree
              datasetId={selectedDatasetId}
              lifecycle={lifecycleFilter}
              selectedPath={folderPath}
              onSelect={setFolderPath}
            />
          </div>
        ) : (
          <div className="rounded-lg border border-border/60 bg-muted/20 p-3 text-xs text-muted-foreground">
            {t('folder.empty')}
          </div>
        )}

        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">{t('lifecycle.label')}</div>
          <Select value={lifecycleFilter} onValueChange={(v) => setLifecycleFilter(v as DocLifecycleFilter)}>
            <SelectTrigger className="h-9 w-full" aria-label={t("lifecycle.ariaLabel")}>
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
    </WorkbenchPane>
  )
}
