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
        'flex w-full max-w-full overflow-hidden rounded-full border border-border/70 bg-card/95 p-1 shadow-[0_16px_44px_-34px_rgba(15,23,42,0.38)]',
        className
      )}
    >
      {/* 入库流程: Parse -> Governance -> Chunk -> Chat */}
      <IngestionWorkflowStepper
        compact={compact}
        className={compact ? 'min-w-max' : 'w-full min-w-[640px]'}
      />
    </div>
  )
}
