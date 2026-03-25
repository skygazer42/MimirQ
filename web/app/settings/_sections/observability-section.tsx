'use client'

import { Input } from '@/components/ui/input'
import type { ObservabilityConfig } from '@/lib/api'
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

  return (
    <section>
      <div className="mb-6 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Eye className="h-5 w-5 text-primary" />
          观测与调试
        </h2>
        <div className="flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
          <span>保存后通常可立即生效</span>
        </div>
      </div>

      <div className="space-y-8 rounded-2xl border border-border bg-card p-6 shadow-sm">
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <FileSearch className="h-4 w-4 text-muted-foreground" />
                Tool Call 日志
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                记录工具调用耗时、成功/失败与参数键名（preview 可选，建议配合 PII 脱敏）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateObservability({ tool_call_log_enabled: !isToolCallLogEnabled })}
              className="shrink-0"
            >
              {isToolCallLogEnabled ? (
                <ToggleRight className="h-10 w-10 text-primary" />
              ) : (
                <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
              )}
            </button>
          </div>

          {isToolCallLogEnabled ? (
            <div className="grid grid-cols-1 gap-4 pt-2 md:grid-cols-3">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={observability.tool_call_log_include_preview ?? false}
                  onChange={(event) => updateObservability({ tool_call_log_include_preview: event.target.checked })}
                  className="h-4 w-4 accent-primary"
                />
                <span className="text-sm text-foreground/80">包含结果 preview</span>
              </div>
              <div>
                <div className="mb-1 text-xs text-muted-foreground">preview 最大字符数</div>
                <Input
                  type="number"
                  min={0}
                  max={5000}
                  value={observability.tool_call_log_max_preview_chars ?? 500}
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

        <div className="space-y-3 border-t pt-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Settings2 className="h-4 w-4 text-muted-foreground" />
                Workflow 生命周期日志
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                记录工作流总耗时、steps、success/fail（可选携带 execution path）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateObservability({ agent_log_enabled: !isAgentLogEnabled })}
              className="shrink-0"
            >
              {isAgentLogEnabled ? (
                <ToggleRight className="h-10 w-10 text-primary" />
              ) : (
                <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
              )}
            </button>
          </div>

          {isAgentLogEnabled ? (
            <div className="grid grid-cols-1 gap-4 pt-2 md:grid-cols-3">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={observability.agent_log_include_execution_path ?? false}
                  onChange={(event) =>
                    updateObservability({ agent_log_include_execution_path: event.target.checked })
                  }
                  className="h-4 w-4 accent-primary"
                />
                <span className="text-sm text-foreground/80">包含 execution path</span>
              </div>
              <div>
                <div className="mb-1 text-xs text-muted-foreground">错误 preview 最大字符数</div>
                <Input
                  type="number"
                  min={0}
                  max={5000}
                  value={observability.agent_log_max_preview_chars ?? 500}
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

        <div className="space-y-3 border-t pt-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <Eye className="h-4 w-4 text-muted-foreground" />
                RAG Metrics 日志（JSONL）
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                写入 RAG 过程指标到 logs/rag_metrics.jsonl（建议线上关闭 “包含原始文本”）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateObservability({ metrics_log_enabled: !isMetricsLogEnabled })}
              className="shrink-0"
            >
              {isMetricsLogEnabled ? (
                <ToggleRight className="h-10 w-10 text-primary" />
              ) : (
                <ToggleLeft className="h-10 w-10 text-muted-foreground hover:text-muted-foreground" />
              )}
            </button>
          </div>

          {isMetricsLogEnabled ? (
            <div className="grid grid-cols-1 gap-4 pt-2 md:grid-cols-3">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={observability.metrics_log_include_text ?? false}
                  onChange={(event) => updateObservability({ metrics_log_include_text: event.target.checked })}
                  className="h-4 w-4 accent-primary"
                />
                <span className="text-sm text-foreground/80">包含原始文本</span>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  )
}
