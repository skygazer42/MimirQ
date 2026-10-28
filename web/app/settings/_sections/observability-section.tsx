'use client'

import { SettingsSwitch } from '@/components/settings/settings-switch'
import { Input } from '@/components/ui/input'
import { settingsTextTokens } from '@/components/ui/system-page-tokens'
import type { ObservabilityConfig } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Eye, FileSearch, Settings2 } from '@/components/icons'

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
      <div className="divide-y divide-border/60">
        <div className="space-y-4 pb-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className={cn(settingsTextTokens.panelTitle, 'flex items-center gap-1.5')}>
                <FileSearch className={settingsTextTokens.panelTitleIcon} />
                工具调用记录
              </h3>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                记录调用耗时、执行结果和入参字段名，可附带截断后的结果摘要。
              </div>
            </div>
            <SettingsSwitch
              checked={isToolCallLogEnabled}
              onCheckedChange={(checked) => updateObservability({ tool_call_log_enabled: checked })}
              className="shrink-0"
              aria-label="切换工具调用记录"
            />
          </div>

          {isToolCallLogEnabled ? (
            <div className="grid gap-4 border-l border-border/60 pl-4 md:grid-cols-2">
              <div className="flex items-center justify-between gap-3">
                <span className={settingsTextTokens.fieldLabel}>记录结果摘要</span>
                <SettingsSwitch
                  checked={observability.tool_call_log_include_preview ?? false}
                  onCheckedChange={(checked) =>
                    updateObservability({ tool_call_log_include_preview: checked })
                  }
                  aria-label="切换工具调用结果摘要记录"
                />
              </div>
              <div>
                <div className={cn(settingsTextTokens.fieldLabel, 'mb-1')}>结果摘要最大字符数</div>
                <Input
                  type="number"
                  min={0}
                  max={5000}
                  value={observability.tool_call_log_max_preview_chars ?? 500}
                  className="h-11 sm:h-9 border-input bg-background text-[13px]"
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

        <div className="space-y-4 py-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className={cn(settingsTextTokens.panelTitle, 'flex items-center gap-1.5')}>
                <Settings2 className={settingsTextTokens.panelTitleIcon} />
                工作流运行记录
              </h3>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                记录任务耗时、步骤节点和执行结果，可附带完整运行路径。
              </div>
            </div>
            <SettingsSwitch
              checked={isAgentLogEnabled}
              onCheckedChange={(checked) => updateObservability({ agent_log_enabled: checked })}
              className="shrink-0"
              aria-label="切换工作流运行记录"
            />
          </div>

          {isAgentLogEnabled ? (
            <div className="grid gap-4 border-l border-border/60 pl-4 md:grid-cols-2">
              <div className="flex items-center justify-between gap-3">
                <span className={settingsTextTokens.fieldLabel}>记录步骤路径</span>
                <SettingsSwitch
                  checked={observability.agent_log_include_execution_path ?? false}
                  onCheckedChange={(checked) =>
                    updateObservability({ agent_log_include_execution_path: checked })
                  }
                  aria-label="切换工作流步骤路径记录"
                />
              </div>
              <div>
                <div className={cn(settingsTextTokens.fieldLabel, 'mb-1')}>错误摘要最大字符数</div>
                <Input
                  type="number"
                  min={0}
                  max={5000}
                  value={observability.agent_log_max_preview_chars ?? 500}
                  className="h-11 sm:h-9 border-input bg-background text-[13px]"
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

        <div className="space-y-4 pt-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className={cn(settingsTextTokens.panelTitle, 'flex items-center gap-1.5')}>
                <Eye className={settingsTextTokens.panelTitleIcon} />
                RAG 过程指标
              </h3>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                将每次问答的检索与生成指标写入 logs/rag_metrics.jsonl，用于趋势分析和问题复盘。
              </div>
            </div>
            <SettingsSwitch
              checked={isMetricsLogEnabled}
              onCheckedChange={(checked) => updateObservability({ metrics_log_enabled: checked })}
              className="shrink-0"
              aria-label="切换 RAG 过程指标记录"
            />
          </div>

          {isMetricsLogEnabled ? (
            <div className="border-l border-border/60 pl-4">
              <div className="flex items-center justify-between gap-3">
                <span className={settingsTextTokens.fieldLabel}>写入问题与答案原文</span>
                <SettingsSwitch
                  checked={observability.metrics_log_include_text ?? false}
                  onCheckedChange={(checked) => updateObservability({ metrics_log_include_text: checked })}
                  aria-label="切换 RAG 指标原文写入"
                />
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  )
}
