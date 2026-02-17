import { WorkbenchPane } from '@/components/workbench'
import { cn } from '@/lib/utils'

type KnowledgeScopePanelProps = {
  className?: string
}

export function KnowledgeScopePanel({ className }: KnowledgeScopePanelProps) {
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
      <div className="text-sm text-muted-foreground">
        将数据集、文件夹、生命周期与状态筛选移动到这里。
      </div>
    </WorkbenchPane>
  )
}

