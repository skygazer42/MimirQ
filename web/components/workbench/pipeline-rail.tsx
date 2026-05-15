import { cn } from '@/lib/utils'

import { IngestionWorkflowStepper } from '@/components/ui/ingestion-workflow-stepper'

export function PipelineRail({
  className,
  compact = false,
}: Readonly<{
  className?: string
  compact?: boolean
}>) {
  return (
    <div
      data-testid="pipeline-rail"
      className={cn(
        'flex w-fit max-w-full overflow-x-auto rounded-full border border-border/70 bg-card/95 p-1 shadow-[0_16px_44px_-34px_rgba(15,23,42,0.38)]',
        className
      )}
    >
      {/* 入库流程: Parse -> Governance -> Chunk -> Chat */}
      <IngestionWorkflowStepper compact={compact} className="min-w-max" />
    </div>
  )
}
