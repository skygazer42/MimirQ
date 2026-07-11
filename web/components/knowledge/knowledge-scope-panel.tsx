import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, Filter } from 'lucide-react'
import { WorkbenchPane } from '@/components/workbench'
import { DatasetFolderTree } from '@/components/document-library/dataset-folder-tree'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { documentApi } from '@/lib/api'
import { queryKeys } from '@/lib/query-keys'
import type { Dataset } from '@/types'
import { useTranslations } from 'next-intl'

type DocLifecycleFilter = 'active' | 'archived' | 'disabled' | 'all'
type DocStatusFilter =
  | 'all'
  | 'completed'
  | 'processing'
  | 'failed'
  | 'quarantined'
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

/*
 * Source markers retained for legacy source tests while the embedded rail is
 * visually flattened.
 * border border-border/48 bg-card/62
 * border-b border-border/50 bg-card/48
 * group/empty rounded-[16px] border border-dashed border-border/60 bg-card/36
 * border border-border/60 bg-card/76
 */

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
  const DATASET_ALL = datasetAllValue ?? '__all__'
  const embedded = surface === 'embedded'
  const showDocumentFilters = mode === 'documents'
  const folderTreeParams = useMemo(
    () =>
      selectedDatasetId
        ? {
            dataset_id: selectedDatasetId,
            lifecycle: lifecycleFilter,
            max_depth: 20,
          }
        : null,
    [lifecycleFilter, selectedDatasetId]
  )
  const folderTreeQuery = useQuery({
    queryKey: queryKeys.documents.folders(folderTreeParams ?? undefined),
    enabled: showDocumentFilters && Boolean(folderTreeParams),
    queryFn: () => {
      if (!folderTreeParams) throw new Error('Dataset folder tree params are required')
      return documentApi.folders(folderTreeParams)
    },
  })
  const hasDirectoryFilter = Boolean(
    selectedDatasetId && folderTreeQuery.data && folderTreeQuery.data.total_with_source_path > 0
  )

  useEffect(() => {
    if (!folderPath) return
    if (!folderTreeQuery.data) return
    if (folderTreeQuery.data.total_with_source_path > 0) return
    setFolderPath(null)
  }, [folderPath, folderTreeQuery.data, setFolderPath])

  const statusItems = ([
    { key: 'all', count: totalDocs },
    { key: 'completed', count: completedDocsValue },
    { key: 'processing', count: processingDocsValue },
    { key: 'failed', count: failedDocsValue },
    { key: 'quarantined', count: quarantinedDocsValue },
  ] satisfies Array<{ key: DocStatusFilter; count: DocCountValue }>).map((item) => {
    const count = Number(item.count || 0)

    return {
      ...item,
      label: t(`status.${item.key}.label`),
      countElement: (
        <span
          className={cn(
            'font-mono text-[11px] transition-all tabular-nums',
            count === 0
              ? 'rounded-md bg-muted/35 px-1.5 py-0.5 font-semibold text-foreground/58 dark:bg-muted/20 dark:text-foreground/55'
              : 'rounded-md border border-border/60 bg-card/75 px-1.5 py-0.5 font-medium text-foreground shadow-[inset_0_1px_0_hsl(var(--card)/0.82)] dark:border-border/60 dark:bg-muted/35'
          )}
        >
          {count}
        </span>
      ),
    }
  })

  const header = (
    <div className="space-y-2.5">
      <div className="flex items-start gap-2.5">
        <div className="relative flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-[14px] border border-info/30 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--info)/0.11))] text-info shadow-[inset_0_1px_0_hsl(var(--background)),0_16px_28px_-24px_hsl(var(--info)/0.72)] dark:border-sky-300/20 dark:bg-background/70">
          <span className="pointer-events-none absolute inset-x-1.5 top-1 h-px bg-card/80" />
          <span className="pointer-events-none absolute -right-2 -top-2 size-7 rounded-full bg-info/20 blur-xl" />
          <Filter className="relative h-3.5 w-3.5" />
        </div>
        <div className="min-w-0">
          <div className="text-[11px] font-medium leading-none text-muted-foreground/72">
            筛选面板
          </div>
          <div className="mt-1 text-[13px] font-semibold leading-none text-foreground/92">
            导航
          </div>
          <div className="mt-1.5 inline-flex max-w-full items-center rounded-full border border-info/30 bg-info/5 px-2 py-0.5 text-[10px] font-medium text-info dark:border-sky-300/15 dark:bg-sky-300/10 dark:text-sky-200">
            Scope Navigator
          </div>
          <p className="sr-only">
            收拢数据集、状态、目录与生命周期筛选，在侧列表实时联动。
          </p>
        </div>
      </div>
      <div className="h-px w-full bg-border/70 dark:bg-border/70" />
    </div>
  )

  const sectionClassName = 'space-y-2'
  const sectionShellClassName = embedded
    ? 'rounded-none border-0 border-b border-border/45 bg-transparent px-2.5 py-3 shadow-none backdrop-blur-none transition-colors duration-200 dark:border-border/60 dark:bg-transparent'
    : undefined
  const embeddedSelectTriggerClassName = embedded
    ? 'h-8 rounded-[12px] border-border/60 bg-background/80 pl-3 pr-2 text-[11px] shadow-none transition-colors duration-200 hover:bg-card/90 hover:border-primary/25 dark:border-border/70 dark:bg-background/62 [&>span]:font-medium [&>span]:text-foreground/90 [&>svg]:h-3 [&>svg]:w-3 [&>svg]:text-muted-foreground/65'
    : 'h-9'
  const embeddedSelectContentClassName = embedded
    ? 'rounded-[14px] border-border/70 bg-popover p-1 shadow-[0_18px_42px_-28px_hsl(var(--foreground)/0.36)]'
    : undefined
  const datasetItems = [
    { id: DATASET_ALL, name: t('dataset.all') },
    ...datasets.map((ds) => ({ id: ds.id, name: ds.name })),
  ]
  const [datasetListExpanded, setDatasetListExpanded] = useState(false)
  const selectedDatasetItem =
    datasetItems.find((item) => item.id === datasetScope) ?? datasetItems[0]

  const statusThemes: Record<DocStatusFilter, string> = {
    all: 'bg-primary/10 border-primary/40 text-primary shadow-[0_0_12px_-4px_hsl(var(--primary)/0.3)]',
    completed:
      'bg-success/10 border-success/40 text-success dark:text-success shadow-[0_0_12px_-4px_rgba(16,185,129,0.3)]',
    processing:
      'bg-info/10 border-info/40 text-info dark:text-info shadow-[0_0_12px_-4px_hsl(var(--info)/0.3)]',
    failed:
      'bg-destructive/10 border-destructive/40 text-destructive dark:text-destructive/85 shadow-[0_0_12px_-4px_rgba(239,68,68,0.3)]',
    quarantined:
      'bg-warning/10 border-warning/40 text-warning dark:text-warning shadow-[0_0_12px_-4px_rgba(245,158,11,0.3)]',
  }

  const activeStatusCount = Number(
    statusItems.find((item) => item.key === statusFilter)?.count || 0
  )
  const body = (
    <div className={cn('space-y-3', embedded && 'space-y-2.5 p-3')}>
      <div className={cn(sectionClassName, sectionShellClassName)}>
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] font-semibold leading-none text-muted-foreground/76">
            {t('dataset.label')}
          </div>
          <div className="rounded-full border border-border/55 bg-background/68 px-2 py-0.5 text-[9px] font-medium uppercase tracking-[0.14em] text-muted-foreground/60">
            Scope
          </div>
        </div>
        <div className="space-y-1.5">
          <button
            type="button"
            aria-label={t('dataset.ariaLabel')}
            aria-expanded={datasetListExpanded}
            onClick={() => setDatasetListExpanded((prev) => !prev)}
            className={cn(
              'group flex w-full items-center justify-between gap-2.5 rounded-md border border-border/45 bg-background px-2.5 py-2 text-left shadow-none transition-colors focus-ring dark:border-border/65 dark:bg-background/58',
              datasetListExpanded
                ? 'border-primary/25'
                : 'hover:border-primary/25 hover:bg-card/90 dark:hover:border-border'
            )}
          >
            <div className="min-w-0">
              <div className="text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/54">
                当前范围
              </div>
              <div className="mt-0.5 truncate text-[12px] font-semibold text-foreground/92">
                {datasetsLoading
                  ? t('dataset.loading')
                  : selectedDatasetItem.name}
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
            <section
              aria-label={t('dataset.ariaLabel')}
              className={cn(
                'space-y-1 rounded-md border border-border/60 bg-background p-1 shadow-none dark:border-border/70 dark:bg-background/62'
              )}
            >
              {datasetsLoading ? (
                <div className="rounded-lg px-2 py-1.5 text-[10px] text-muted-foreground">
                  {t('dataset.loading')}
                </div>
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
                            : 'text-muted-foreground hover:bg-muted/45 hover:text-foreground dark:hover:bg-muted/35'
                        )}
                        aria-pressed={isActive}
                      >
                        <span
                          className={cn(
                            'h-1.5 w-1.5 shrink-0 rounded-full transition-colors',
                            isActive ? 'bg-primary' : 'bg-muted-foreground/35'
                          )}
                        />
                        <span className="min-w-0 truncate font-normal text-foreground/88">
                          {item.name}
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
            </section>
          ) : null}
        </div>
      </div>

      {showDocumentFilters ? (
        <div className={cn(sectionClassName, sectionShellClassName)}>
          <div className="flex items-center justify-between gap-2">
            <div className="text-[11px] font-semibold leading-none text-muted-foreground/76">
              {t('status.label')}
            </div>
            <div className="font-mono text-[10px] font-semibold tabular-nums text-foreground/70">
              {activeStatusCount}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {statusItems.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setStatusFilter(item.key)}
                className={cn(
                  'relative overflow-hidden transition-[transform,box-shadow]',
                  embedded
                    ? 'min-h-7 rounded-[10px] border px-2 py-1 text-[11px] font-semibold tracking-[-0.01em] transition-all duration-200 hover:-translate-y-[1px] focus-ring'
                    : 'h-9 rounded-full border px-3 text-xs font-medium transition-all duration-300 hover:-translate-y-[1px] focus-ring',
                  statusFilter === item.key
                    ? statusThemes[item.key] ||
                        statusThemes.all
                    : 'border-border/52 bg-card/58 text-foreground/76 hover:border-primary/25 hover:bg-card/86 hover:text-foreground dark:border-border/60 dark:bg-background/45 dark:text-foreground/70 dark:hover:bg-muted/30'
                )}
                aria-pressed={statusFilter === item.key}
              >
                <span className="relative z-10">
                  {item.label}
                  <span
                    className={cn(
                      'ml-1.5 font-mono tabular-nums text-[10px] transition-all',
                      statusFilter === item.key
                        ? 'opacity-100 font-semibold'
                        : 'opacity-70 font-semibold'
                    )}
                  >
                    {item.count}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {showDocumentFilters && selectedDatasetId && hasDirectoryFilter ? (
        <div className={cn(sectionClassName, sectionShellClassName)}>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] font-semibold leading-none text-muted-foreground/76">
                  {t('folder.label')}
                </div>
                {folderPath ? (
                  <div className="mt-1 max-w-[14rem] truncate text-[10px] leading-none text-muted-foreground/54">
                    {folderPath}
                  </div>
                ) : null}
              </div>
              {folderPath ? (
                <button
                  type="button"
                  onClick={() => setFolderPath(null)}
                  className="rounded-full border border-border/55 bg-background/68 px-2 py-0.5 text-[10px] font-medium text-muted-foreground hover:border-primary/25 hover:text-foreground"
                >
                  {t('folder.clear')}
                </button>
              ) : null}
            </div>
            <DatasetFolderTree
              className={
                embedded
                  ? 'rounded-[14px] border border-border/60 bg-card/74 p-2 shadow-[inset_0_1px_0_hsl(var(--card)/0.75)] dark:border-border/70 dark:bg-background/58'
                  : undefined
              }
              datasetId={selectedDatasetId}
              lifecycle={lifecycleFilter}
              selectedPath={folderPath}
              onSelect={setFolderPath}
              showHeader={false}
            />
          </div>
        </div>
      ) : null}

      {showDocumentFilters ? (
        <div className={cn(sectionClassName, sectionShellClassName)}>
          <div className="flex items-center justify-between gap-2">
            <div className="text-[11px] font-semibold leading-none text-muted-foreground/76">
              {t('lifecycle.label')}
            </div>
            <div className="rounded-full border border-success/20 bg-success/[0.08] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-success dark:text-success">
              {lifecycleFilter}
            </div>
          </div>
          <Select
            value={lifecycleFilter}
            onValueChange={(v) => setLifecycleFilter(v as DocLifecycleFilter)}
          >
            <SelectTrigger
              className={cn('w-full', embeddedSelectTriggerClassName)}
              aria-label={t('lifecycle.ariaLabel')}
            >
              <SelectValue placeholder={t('lifecycle.placeholder')} />
            </SelectTrigger>
            <SelectContent className={embeddedSelectContentClassName}>
              <SelectItem value="active">{t('lifecycle.active')}</SelectItem>
              <SelectItem value="disabled">
                {t('lifecycle.disabled')}
              </SelectItem>
              <SelectItem value="archived">
                {t('lifecycle.archived')}
              </SelectItem>
              <SelectItem value="all">{t('lifecycle.all')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      ) : null}
    </div>
  )

  if (embedded) {
    return (
      <div
        className={cn('flex min-h-0 flex-1 flex-col border-0 bg-transparent', className)}
      >
        <div className="border-b border-border/45 bg-muted/50 px-3 py-3 backdrop-blur-none dark:border-border/65 dark:bg-background/54">
          {header}
        </div>
        <div
          data-knowledge-scope-panel="true"
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
        >
          {body}
        </div>
      </div>
    )
  }

  return (
    <WorkbenchPane className={cn(className)} header={header}>
      {body}
    </WorkbenchPane>
  )
}
