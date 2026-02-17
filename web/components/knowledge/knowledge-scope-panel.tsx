import { WorkbenchPane } from '@/components/workbench'
import { DatasetFolderTree } from '@/components/document-library/dataset-folder-tree'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { Dataset } from '@/types'

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
}: KnowledgeScopePanelProps) {
  const DATASET_ALL = datasetAllValue ?? '__all__'

  return (
    <WorkbenchPane
      className={cn(className)}
      header={
        <div className="flex items-baseline gap-2">
          <div className="text-sm font-semibold">范围</div>
          <div className="text-xs text-muted-foreground">Scope</div>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">数据集</div>
          <Select value={datasetScope} onValueChange={setDatasetScope}>
            <SelectTrigger
              className="h-9 w-full"
              disabled={datasetsLoading}
              aria-label="筛选数据集"
            >
              <SelectValue placeholder={datasetsLoading ? '加载数据集…' : '全部数据集'} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={DATASET_ALL}>全部数据集</SelectItem>
              {datasets.map((ds) => (
                <SelectItem key={ds.id} value={ds.id}>
                  {ds.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">状态</div>
          <div className="flex flex-wrap items-center gap-2">
            {(
              [
                { key: 'all', label: '全部', count: totalDocs },
                { key: 'completed', label: '已就绪', count: completedDocsValue },
                { key: 'processing', label: '处理中', count: processingDocsValue },
                { key: 'failed', label: '失败', count: failedDocsValue },
                { key: 'quarantined', label: '隔离', count: quarantinedDocsValue },
              ] as const
            ).map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setStatusFilter(item.key)}
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
              <div className="text-xs font-medium text-muted-foreground">目录</div>
              {folderPath ? (
                <button
                  type="button"
                  onClick={() => setFolderPath(null)}
                  className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-4"
                >
                  清除
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
            选择一个数据集以浏览目录范围。
          </div>
        )}

        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">生命周期</div>
          <Select value={lifecycleFilter} onValueChange={(v) => setLifecycleFilter(v as DocLifecycleFilter)}>
            <SelectTrigger className="h-9 w-full" aria-label="筛选生命周期">
              <SelectValue placeholder="生命周期" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="active">启用中</SelectItem>
              <SelectItem value="disabled">已禁用</SelectItem>
              <SelectItem value="archived">已归档</SelectItem>
              <SelectItem value="all">全部</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </WorkbenchPane>
  )
}
