import type { RagasRegressionRunDiffResponse } from '@/types'
import { cn } from '@/lib/utils'

export function AblationComparisonSummary({ diff }: Readonly<{ diff: RagasRegressionRunDiffResponse }>) {
  const score = diff.diff_score
  const delta = score?.delta ?? null

  return (
    <dl aria-label="运行对比结论" className="grid grid-cols-3 gap-3 border-b border-border px-4 py-3 sm:gap-8 sm:px-5">
      <div className="min-w-0">
        <dt className="text-xs text-muted-foreground">基线得分</dt>
        <dd className="mt-1 text-2xl tabular-nums sm:text-3xl">{score?.base_score?.toFixed(4) ?? '—'}</dd>
        <dd className="mt-1 truncate text-xs text-muted-foreground" title={diff.base_run_id}>
          {diff.base_run_id}
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="text-xs text-muted-foreground">候选得分</dt>
        <dd className="mt-1 text-2xl tabular-nums sm:text-3xl">{score?.target_score?.toFixed(4) ?? '—'}</dd>
        <dd className="mt-1 truncate text-xs text-muted-foreground" title={diff.target_run_id}>
          {diff.target_run_id}
        </dd>
      </div>
      <div className="min-w-0">
        <dt className="text-xs text-muted-foreground">指标变化</dt>
        <dd
          className={cn(
            'mt-1 text-2xl tabular-nums sm:text-3xl',
            delta !== null && delta > 0 && 'text-success',
            delta !== null && delta < 0 && 'text-destructive',
          )}
        >
          {delta === null ? '—' : `${delta > 0 ? '+' : ''}${delta.toFixed(4)}`}
        </dd>
      </div>
    </dl>
  )
}
