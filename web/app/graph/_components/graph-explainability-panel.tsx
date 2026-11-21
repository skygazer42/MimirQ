'use client'

import { Lightbulb } from '@/components/icons'

import { cn } from '@/lib/utils'

import type { GraphNodeLike } from '../graph-page-utils'

type GraphExplainabilityStep = {
  node: string
  reason: string
}

type GraphExplainabilityPanelProps = Readonly<{
  open: boolean
  explainSteps: readonly GraphExplainabilityStep[]
  currentStepIndex: number
  nodes: readonly GraphNodeLike[]
}>

export function GraphExplainabilityPanel({
  open,
  explainSteps,
  currentStepIndex,
  nodes,
}: GraphExplainabilityPanelProps) {
  if (!open) return null

  return (
    <section
      className="absolute bottom-8 left-8 z-20 w-80 rounded-2xl border border-border bg-card overflow-hidden shadow-none"
      aria-label="路径回放"
    >
      <div className="p-4 border-b border-border bg-muted/30 flex items-center gap-2">
        <Lightbulb className="w-4 h-4 text-primary" />
        <h3 className="font-bold text-foreground text-sm">路径回放</h3>
      </div>
      <ol className="list-none p-4 space-y-4 max-h-[300px] overflow-y-auto overscroll-contain no-scrollbar">
        {explainSteps.map((step, index) => {
          const nodeLabel = nodes.find((node) => node.id === step.node)?.label
          const label = nodeLabel === undefined || nodeLabel === '' ? step.node : nodeLabel
          const isActive = index === currentStepIndex
          const isDone = index < currentStepIndex
          let borderClass = 'border-border opacity-50'
          let dotClass = 'bg-muted'

          if (isActive) {
            borderClass = 'border-success'
            dotClass = 'bg-success'
          } else if (isDone) {
            borderClass = 'border-success/30'
            dotClass = 'bg-success/20'
          }

          return (
            <li
              key={JSON.stringify([step.node, index])}
              aria-current={isActive ? 'step' : undefined}
              className={cn(
                'relative pl-4 border-l-2 transition-colors duration-150 motion-reduce:transition-none',
                borderClass,
              )}
            >
              <div className={cn('absolute -left-[5px] top-0 w-2 h-2 rounded-full transition-colors', dotClass)} />
              <p className="text-xs font-semibold text-foreground mb-0.5">{label}</p>
              <p className="text-[11px] text-muted-foreground leading-snug">{step.reason}</p>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
