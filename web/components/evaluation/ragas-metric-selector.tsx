'use client'

import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/utils'

export type RagasMetricOption = {
  key: string
  label: string
  hint: string
  category: string
  kind: 'RAGAS' | '程序化'
  cost: string
  scopes: Array<'conversation' | 'regression'>
}

export const RAGAS_METRIC_OPTIONS: RagasMetricOption[] = [
  { key: 'faithfulness', label: 'Faithfulness（忠实度）', hint: '看答案是否忠于检索上下文', category: '忠实度', kind: 'RAGAS', cost: 'LLM', scopes: ['conversation', 'regression'] },
  { key: 'response_relevancy', label: 'Response Relevancy（相关性）', hint: '看回答是否真正回应问题', category: '相关性', kind: 'RAGAS', cost: 'LLM', scopes: ['conversation', 'regression'] },
  { key: 'context_precision', label: 'Context Precision（无参考）', hint: '看引用上下文是否足够精准', category: '上下文', kind: 'RAGAS', cost: 'LLM', scopes: ['conversation', 'regression'] },
  { key: 'atomic_faithfulness', label: 'Atomic Faithfulness', hint: '按声明支持率估算局部幻觉风险，回归专用', category: '忠实度', kind: '程序化', cost: '低成本', scopes: ['regression'] },
  { key: 'hallucination_rate', label: 'Hallucination Rate', hint: '由 atomic faithfulness 反推的幻觉率，回归专用', category: '忠实度', kind: '程序化', cost: '低成本', scopes: ['regression'] },
  { key: 'citation_accuracy', label: 'Citation Accuracy', hint: '引用命中的证据是否属于人工标注来源，回归专用', category: '引用归因', kind: '程序化', cost: '低成本', scopes: ['regression'] },
  { key: 'citation_coverage', label: 'Citation Coverage', hint: '人工标注证据被引用或召回的覆盖率，回归专用', category: '引用归因', kind: '程序化', cost: '低成本', scopes: ['regression'] },
  { key: 'quote_verifiability', label: 'Quote Verifiability', hint: '回答中的引号片段能否回查到检索上下文，回归专用', category: '引用归因', kind: '程序化', cost: '低成本', scopes: ['regression'] },
  { key: 'chunk_attribution', label: 'Chunk Attribution', hint: '回答声明被检索证据支撑的比例，回归专用', category: '上下文', kind: '程序化', cost: '低成本', scopes: ['regression'] },
  { key: 'chunk_utilization', label: 'Chunk Utilization', hint: '被答案实际使用的 chunk 占比，回归专用', category: '上下文', kind: '程序化', cost: '低成本', scopes: ['regression'] },
  { key: 'noise_sensitivity', label: 'Noise Sensitivity', hint: '答案被无关上下文干扰的比例，回归专用', category: '鲁棒性', kind: '程序化', cost: '低成本', scopes: ['regression'] },
  { key: 'self_knowledge_ratio', label: 'Self Knowledge Ratio', hint: '正确但缺少引用支撑的声明比例，回归专用', category: '引用归因', kind: '程序化', cost: '低成本', scopes: ['regression'] },
  { key: 'refusal_correctness', label: 'Refusal Correctness', hint: '应拒答样例是否正确拒答，回归专用', category: '安全合规', kind: '程序化', cost: '低成本', scopes: ['regression'] },
]

export function getRagasMetricOptions(scope: 'conversation' | 'regression' = 'conversation'): RagasMetricOption[] {
  return RAGAS_METRIC_OPTIONS.filter((item) => item.scopes.includes(scope))
}

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
  scope = 'conversation',
}: Readonly<{
  metricKeys: string[]
  onMetricKeysChange: (nextKeys: string[]) => void
  disabled?: boolean
  className?: string
  itemClassName?: string
  textWrapClassName?: string
  labelClassName?: string
  hintClassName?: string
  scope?: 'conversation' | 'regression'
}>) {
  const options = getRagasMetricOptions(scope)

  return (
    <div className={cn('space-y-2', className)}>
      {options.map((metric) => (
        <label
          key={metric.key}
          className={cn(
            'flex items-start gap-2.5 rounded-lg border border-border/70 bg-card px-2.5 py-1.5',
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
            <span className={cn('flex flex-wrap items-center gap-1.5 text-[12px] font-medium text-foreground', labelClassName)}>
              <span>{metric.label}</span>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.12em] text-slate-500">{metric.kind}</span>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium text-slate-500">{metric.category}</span>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-medium text-slate-500">{metric.cost}</span>
            </span>
            <span className={cn('block text-[11px] leading-4 text-muted-foreground', hintClassName)}>{metric.hint}</span>
          </span>
        </label>
      ))}
    </div>
  )
}
