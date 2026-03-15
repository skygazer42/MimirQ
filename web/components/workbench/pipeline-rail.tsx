import { cn } from '@/lib/utils'

import { IngestionWorkflowStepper } from '@/components/ui/ingestion-workflow-stepper'
import { Panel } from '@/components/ui/panel'

export function PipelineRail({
  className,
  compact = true,
}: Readonly<{
  className?: string
  compact?: boolean
}>) {
  return (
    <Panel variant="muted" padding="sm" className={cn('border-border/60', className)}>
      {/* 入库流程: Parse -> Governance -> Chunk -> Chat */}
      <IngestionWorkflowStepper compact={compact} />
    </Panel>
  )
}
