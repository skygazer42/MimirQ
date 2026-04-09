'use client'

import { Input } from '@/components/ui/input'
import { systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'
import type { ObservabilityConfig } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Eye, FileSearch, Settings2, ToggleLeft, ToggleRight } from 'lucide-react'

type ObservabilitySectionProps = {
  observability: ObservabilityConfig
  updateObservability: (patch: Partial<ObservabilityConfig>) => void
}

export function ObservabilitySection({
  observability,
  updateObservability,
}: Readonly<ObservabilitySectionProps>) {
  const isToolCallLogEnabled = observability.tool_call_log_enabled ?? false
  const isAgentLogEnabled = observability.agent_log_enabled ?? false
  const isMetricsLogEnabled = observability.metrics_log_enabled ?? false
  const toggleIconClass = 'h-7 w-7'

  return (
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold tracking-[-0.01em] text-foreground">
          <Eye className="h-4 w-4 text-primary" />
          观测与调试
        </h2>
        <div className="inline-flex items-center gap-1 rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
          <span>保存后通常可立即生效</span>
        </div>
      </div>

      <div className={cn(systemWorkbenchTokens.panel, 'space-y-3 p-3.5')}>
        <div className="space-y-2.5 rounded-lg border border-border/70 bg-muted/10 p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className={cn(systemPageTokens.heading, 'flex items-center gap-1.5')}>
                <FileSearch className="h-4 w-4 text-muted-foreground" />
                工具调用日志（tool_call_log）
              </div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                记录工具调用耗时、成功/失败与参数键名（可选结果预览，建议配合 PII 脱敏）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateObservability({ tool_call_log_enabled: !isToolCallLogEnabled })}
              className="shrink-0"
              aria-label="切换工具调用日志（observability.tool_call_log_enabled）"
            >
              {isToolCallLogEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>

          {isToolCallLogEnabled ? (
            <div className="grid grid-cols-1 gap-3 pt-1 md:grid-cols-3">
              <label className="flex items-center gap-2 rounded-md border border-border/70 bg-background/70 px-2.5 py-2">
                <input
                  type="checkbox"
                  checked={observability.tool_call_log_include_preview ?? false}
                  onChange={(event) => updateObservability({ tool_call_log_include_preview: event.target.checked })}
                  className="h-3.5 w-3.5 accent-primary"
                />
                <span className="text-[11px] font-medium text-foreground/85">包含结果预览（include_preview）</span>
              </label>
              <div>
                <div className="mb-1 text-[11px] font-semibold text-foreground/80">预览最大字符数（max_preview_chars）</div>
                <Input
                  type="number"
                  min={0}
                  max={5000}
                  value={observability.tool_call_log_max_preview_chars ?? 500}
                  className="h-8 text-[12px]"
                  onChange={(event) =>
                    updateObservability({
                      tool_call_log_max_preview_chars: Number.parseInt(event.target.value || '0', 10),
                    })
                  }
                />
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-2.5 rounded-lg border border-border/70 bg-muted/10 p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className={cn(systemPageTokens.heading, 'flex items-center gap-1.5')}>
                <Settings2 className="h-4 w-4 text-muted-foreground" />
                工作流生命周期日志（agent_log）
              </div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                记录工作流总耗时、步骤、成功/失败（可选携带执行路径 execution_path）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateObservability({ agent_log_enabled: !isAgentLogEnabled })}
              className="shrink-0"
              aria-label="切换工作流生命周期日志（observability.agent_log_enabled）"
            >
              {isAgentLogEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>

          {isAgentLogEnabled ? (
            <div className="grid grid-cols-1 gap-3 pt-1 md:grid-cols-3">
              <label className="flex items-center gap-2 rounded-md border border-border/70 bg-background/70 px-2.5 py-2">
                <input
                  type="checkbox"
                  checked={observability.agent_log_include_execution_path ?? false}
                  onChange={(event) =>
                    updateObservability({ agent_log_include_execution_path: event.target.checked })
                  }
                  className="h-3.5 w-3.5 accent-primary"
                />
                <span className="text-[11px] font-medium text-foreground/85">包含执行路径（execution_path）</span>
              </label>
              <div>
                <div className="mb-1 text-[11px] font-semibold text-foreground/80">错误预览最大字符数（max_preview_chars）</div>
                <Input
                  type="number"
                  min={0}
                  max={5000}
                  value={observability.agent_log_max_preview_chars ?? 500}
                  className="h-8 text-[12px]"
                  onChange={(event) =>
                    updateObservability({
                      agent_log_max_preview_chars: Number.parseInt(event.target.value || '0', 10),
                    })
                  }
                />
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-2.5 rounded-lg border border-border/70 bg-muted/10 p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className={cn(systemPageTokens.heading, 'flex items-center gap-1.5')}>
                <Eye className="h-4 w-4 text-muted-foreground" />
                RAG 指标日志（metrics_log，JSONL）
              </div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                写入 RAG 过程指标到 logs/rag_metrics.jsonl（建议生产环境关闭“包含原始文本”）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateObservability({ metrics_log_enabled: !isMetricsLogEnabled })}
              className="shrink-0"
              aria-label="切换 RAG 指标日志（observability.metrics_log_enabled）"
            >
              {isMetricsLogEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>

          {isMetricsLogEnabled ? (
            <div className="grid grid-cols-1 gap-3 pt-1 md:grid-cols-3">
              <label className="flex items-center gap-2 rounded-md border border-border/70 bg-background/70 px-2.5 py-2">
                <input
                  type="checkbox"
                  checked={observability.metrics_log_include_text ?? false}
                  onChange={(event) => updateObservability({ metrics_log_include_text: event.target.checked })}
                  className="h-3.5 w-3.5 accent-primary"
                />
                <span className="text-[11px] font-medium text-foreground/85">包含原始文本</span>
              </label>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  )
}
