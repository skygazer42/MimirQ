'use client'

import { SettingsSwitch } from '@/components/settings/settings-switch'
import { Input } from '@/components/ui/input'
import { settingsTextTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'
import type { ObservabilityConfig } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Eye, FileSearch, Settings2 } from 'lucide-react'

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
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <h2 className={cn(settingsTextTokens.sectionTitle, 'flex items-center gap-1.5')}>
          <Eye className={settingsTextTokens.sectionIcon} />
          观测与调试
        </h2>
        <div className={settingsTextTokens.sectionBadge}>
          <span>保存后对新请求生效</span>
        </div>
      </div>

      <div className={cn(systemWorkbenchTokens.panel, 'space-y-3 p-3.5')}>
        <div className="space-y-2.5 rounded-lg border border-border/70 bg-muted/10 p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className={cn(settingsTextTokens.panelTitle, 'flex items-center gap-1.5')}>
                <FileSearch className={settingsTextTokens.panelTitleIcon} />
                工具调用记录
              </div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                用于排查“某个工具为什么慢、为什么失败”。会记录调用耗时、是否成功，以及常用入参字段名；需要时可附带截断后的结果摘要。
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                <span className="rounded-md border border-slate-200 bg-background/85 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                  配置键：tool_call_log
                </span>
                <span className="rounded-md border border-slate-200 bg-background/85 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                  适合排查工具失败
                </span>
              </div>
            </div>
            <SettingsSwitch
              checked={isToolCallLogEnabled}
              onCheckedChange={(checked) => updateObservability({ tool_call_log_enabled: checked })}
              className="shrink-0"
              aria-label="切换工具调用日志（observability.tool_call_log_enabled）"
            />
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
                <span className="text-[11px] font-semibold text-slate-700">记录结果摘要</span>
              </label>
              <div>
                <div className={cn(settingsTextTokens.fieldLabel, 'mb-1')}>结果摘要最大字符数</div>
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
              <div className={cn(settingsTextTokens.panelTitle, 'flex items-center gap-1.5')}>
                <Settings2 className={settingsTextTokens.panelTitleIcon} />
                工作流运行记录
              </div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                用于排查“一次任务卡在哪一步”。会记录总耗时、步骤节点和成功/失败，必要时可把运行路径一起带上。
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                <span className="rounded-md border border-slate-200 bg-background/85 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                  配置键：agent_log
                </span>
                <span className="rounded-md border border-slate-200 bg-background/85 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                  适合排查流程卡点
                </span>
              </div>
            </div>
            <SettingsSwitch
              checked={isAgentLogEnabled}
              onCheckedChange={(checked) => updateObservability({ agent_log_enabled: checked })}
              className="shrink-0"
              aria-label="切换工作流生命周期日志（observability.agent_log_enabled）"
            />
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
                <span className="text-[11px] font-semibold text-slate-700">记录步骤路径</span>
              </label>
              <div>
                <div className={cn(settingsTextTokens.fieldLabel, 'mb-1')}>错误摘要最大字符数</div>
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
              <div className={cn(settingsTextTokens.panelTitle, 'flex items-center gap-1.5')}>
                <Eye className={settingsTextTokens.panelTitleIcon} />
                RAG 过程指标
              </div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                用于观察检索和生成是否稳定。会把每次问答的关键指标写入日志文件，适合做趋势分析、问题复盘和离线审计。
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                <span className="rounded-md border border-slate-200 bg-background/85 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                  配置键：metrics_log
                </span>
                <span className="rounded-md border border-slate-200 bg-background/85 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                  日志文件：logs/rag_metrics.jsonl
                </span>
              </div>
            </div>
            <SettingsSwitch
              checked={isMetricsLogEnabled}
              onCheckedChange={(checked) => updateObservability({ metrics_log_enabled: checked })}
              className="shrink-0"
              aria-label="切换 RAG 指标日志（observability.metrics_log_enabled）"
            />
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
                <span className="text-[11px] font-semibold text-slate-700">写入问题与答案原文</span>
              </label>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  )
}
