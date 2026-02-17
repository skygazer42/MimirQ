import { WorkbenchPane } from '@/components/workbench'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { Dataset } from '@/types'

type KnowledgeScopePanelProps = {
  className?: string
  datasets: Dataset[]
  datasetsLoading?: boolean

  datasetScope: string
  setDatasetScope: (value: string) => void
  datasetAllValue?: string
}

export function KnowledgeScopePanel({
  className,
  datasets,
  datasetsLoading = false,
  datasetScope,
  setDatasetScope,
  datasetAllValue,
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

        <div className="text-sm text-muted-foreground">
          将文件夹、生命周期与状态筛选移动到这里。
        </div>
      </div>
    </WorkbenchPane>
  )
}
