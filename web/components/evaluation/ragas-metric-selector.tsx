'use client'

import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/utils'

export type RagasMetricOption = {
  key: string
  label: string
  hint: string
}

export const RAGAS_METRIC_OPTIONS: RagasMetricOption[] = [
  { key: 'faithfulness', label: 'Faithfulness（忠实度）', hint: '看答案是否忠于检索上下文' },
  { key: 'response_relevancy', label: 'Response Relevancy（相关性）', hint: '看回答是否真正回应问题' },
  { key: 'context_precision', label: 'Context Precision（无参考）', hint: '看引用上下文是否足够精准' },
]

export function ragasMetricLabel(key: string): string {
  return RAGAS_METRIC_OPTIONS.find((item) => item.key === key)?.label || key
}

export function RagasMetricSelector({
  metricKeys,
  onMetricKeysChange,
  disabled = false,
  className,
  itemClassName,
  textWrapClassName,
  labelClassName,
  hintClassName,
}: Readonly<{
  metricKeys: string[]
  onMetricKeysChange: (nextKeys: string[]) => void
  disabled?: boolean
  className?: string
  itemClassName?: string
  textWrapClassName?: string
  labelClassName?: string
  hintClassName?: string
}>) {
  return (
    <div className={cn('space-y-2', className)}>
      {RAGAS_METRIC_OPTIONS.map((metric) => (
        <label
          key={metric.key}
          className={cn(
            'flex items-start gap-2.5 rounded-lg border border-border/70 bg-white px-2.5 py-1.5',
            disabled && 'opacity-60',
            itemClassName
          )}
        >
          <Checkbox
            checked={metricKeys.includes(metric.key)}
            disabled={disabled}
            onCheckedChange={(checked) => {
              if (checked === true) {
                if (metricKeys.includes(metric.key)) return
                onMetricKeysChange([...metricKeys, metric.key])
                return
              }
              onMetricKeysChange(metricKeys.filter((item) => item !== metric.key))
            }}
          />
          <span className={cn('space-y-0.5', textWrapClassName)}>
            <span className={cn('block text-[12px] font-medium text-foreground', labelClassName)}>{metric.label}</span>
            <span className={cn('block text-[11px] leading-4 text-muted-foreground', hintClassName)}>{metric.hint}</span>
          </span>
        </label>
      ))}
    </div>
  )
}
