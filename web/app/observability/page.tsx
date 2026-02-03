'use client'

import { useEffect, useMemo, useState } from 'react'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { observabilityApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import type { RagMetricsSummaryResponse } from '@/types'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'
import {
  BarChart3,
  RefreshCw,
  AlertTriangle,
  Timer,
  Quote,
  Zap,
} from 'lucide-react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  BarChart,
  Bar,
} from 'recharts'

const WINDOW_PRESETS = [
  { label: '15 分钟', value: 15 },
  { label: '1 小时', value: 60 },
  { label: '4 小时', value: 240 },
  { label: '24 小时', value: 1440 },
] as const

function formatTs(tsMs: number) {
  try {
    return new Date(tsMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return String(tsMs)
  }
}

export default function ObservabilityPage() {
  const [summary, setSummary] = useState<RagMetricsSummaryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [windowMinutes, setWindowMinutes] = useState<number>(60)

  const load = async (windowMin = windowMinutes) => {
    setLoading(true)
    try {
      const data = await observabilityApi.getRagMetricsSummary({ window_minutes: windowMin })
      setSummary(data)
    } catch (err: any) {
      setSummary(null)
      toast.error(formatApiError(err, '加载监控数据失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(windowMinutes)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const chartData = useMemo(() => {
    if (!summary?.timeseries) return []
    const ts = summary.timeseries.ts_ms || []
    const ragTrace = summary.timeseries.rag_trace || []
    const rerankerApi = summary.timeseries.reranker_api || []
    const retrievalAvg = summary.timeseries.retrieval_avg_elapsed_sec || []
    const out = []
    for (let i = 0; i < ts.length; i++) {
      const t = Number(ts[i] || 0)
      out.push({
        t,
        time: formatTs(t),
        rag_trace: Number(ragTrace[i] || 0),
        reranker_api: Number(rerankerApi[i] || 0),
        retrieval_avg_elapsed_sec:
          retrievalAvg[i] == null ? null : Number(retrievalAvg[i] || 0),
      })
    }
    return out
  }, [summary?.timeseries])

  const topErrors = useMemo(() => {
    const raw: Record<string, number> = summary?.error_counts ?? {}
    const entries = Object.entries(raw).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
    return entries.slice(0, 8)
  }, [summary?.error_counts])

  return (
    <AppFrame>
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <PageScaffold
          title="监控面板"
          description="检索 / 重排 / 引用的全链路指标（来自 metrics JSONL）"
          icon={BarChart3}
          iconColor="text-sky-600 dark:text-sky-400"
          size="7xl"
          actions={
            <div className="flex items-center gap-2">
              <div className="w-[140px]">
                <Select
                  value={String(windowMinutes)}
                  onValueChange={(v) => {
                    const next = parseInt(v, 10)
                    setWindowMinutes(next)
                    void load(next)
                  }}
                >
                  <SelectTrigger className="h-9 rounded-xl">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WINDOW_PRESETS.map((p) => (
                      <SelectItem key={p.value} value={String(p.value)}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button
                size="sm"
                variant="outline"
                className="gap-2 rounded-xl"
                onClick={() => void load(windowMinutes)}
                disabled={loading}
              >
                <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin motion-reduce:animate-none')} />
                刷新
              </Button>
              <a
                href="/settings"
                className="inline-flex h-9 items-center justify-center rounded-xl border border-input bg-background px-3 text-xs font-medium shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                去设置开启/配置
              </a>
            </div>
          }
        >
          {!summary ? (
            <Alert variant="destructive" className="mt-4">
              <AlertTriangle className="h-4 w-4" />
              <AlertTitle>无法加载监控数据</AlertTitle>
              <AlertDescription>
                请确认你是 owner/admin，并且后端已更新到包含 /api/v1/observability 的版本。
              </AlertDescription>
            </Alert>
          ) : (
            <div className="space-y-6">
              {!summary.enabled && (
                <Alert className="mt-4">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Metrics 日志未开启</AlertTitle>
                  <AlertDescription>
                    当前 ENABLE_METRICS_LOG=false。你仍可能看到少量历史数据，但建议到“设置 → 观测与调试”开启。
                  </AlertDescription>
                </Alert>
              )}

              {summary.truncated && (
                <Alert className="mt-4">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>数据可能不完整</AlertTitle>
                  <AlertDescription>
                    本次查询仅读取 metrics 文件尾部（max_bytes）。若窗口内数据量过大，请缩短时间窗口或调整后端 max_bytes。
                  </AlertDescription>
                </Alert>
              )}

              <StatsGrid className="mt-2">
                <StatCard
                  icon={Zap}
                  label="RAG Trace"
                  value={summary.rag_trace_count}
                  subValue={`${summary.window_minutes} 分钟`}
                  color="sky"
                />
                <StatCard
                  icon={Timer}
                  label="检索平均耗时"
                  value={summary.retrieval_avg_elapsed_sec != null ? `${summary.retrieval_avg_elapsed_sec.toFixed(3)}s` : '-'}
                  subValue={summary.retrieval_p95_elapsed_sec != null ? `p95 ${summary.retrieval_p95_elapsed_sec.toFixed(3)}s` : undefined}
                  color="teal"
                />
                <StatCard
                  icon={Timer}
                  label="重排平均耗时"
                  value={summary.rerank_avg_elapsed_sec != null ? `${summary.rerank_avg_elapsed_sec.toFixed(3)}s` : '-'}
                  subValue={`${summary.reranker_api_count} 次 reranker_api`}
                  color="amber"
                />
                <StatCard
                  icon={Quote}
                  label="平均引用数"
                  value={summary.citations_avg_count != null ? summary.citations_avg_count.toFixed(2) : '-'}
                  subValue="每次回答"
                  color="green"
                />
              </StatsGrid>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <Panel padding="lg" className="min-h-[320px]">
                  <div className="flex items-center justify-between mb-4">
                    <div className="text-sm font-semibold text-foreground">请求量（rag_trace）</div>
                    <div className="text-xs text-muted-foreground">按分钟聚合</div>
                  </div>
                  <div className="h-[260px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                        <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                        <Tooltip />
                        <Bar dataKey="rag_trace" fill="hsl(var(--primary))" opacity={0.85} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>

                <Panel padding="lg" className="min-h-[320px]">
                  <div className="flex items-center justify-between mb-4">
                    <div className="text-sm font-semibold text-foreground">检索平均耗时</div>
                    <div className="text-xs text-muted-foreground">每分钟均值</div>
                  </div>
                  <div className="h-[260px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                        <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                        <YAxis tick={{ fontSize: 10 }} />
                        <Tooltip />
                        <Line
                          type="monotone"
                          dataKey="retrieval_avg_elapsed_sec"
                          stroke="hsl(var(--info))"
                          strokeWidth={2}
                          dot={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </Panel>
              </div>

              <Panel padding="lg" variant="muted">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  <div>
                    <div className="text-sm font-semibold text-foreground mb-2">检索模式分布</div>
                    <pre className="text-[11px] font-mono text-muted-foreground whitespace-pre-wrap">
                      {JSON.stringify(summary.retrieval_mode_counts || {}, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-foreground mb-2">命中类型分布</div>
                    <pre className="text-[11px] font-mono text-muted-foreground whitespace-pre-wrap">
                      {JSON.stringify(summary.hit_type_counts || {}, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-foreground mb-2">Top Errors</div>
                    {topErrors.length ? (
                      <div className="space-y-2">
                        {topErrors.map(([k, v]) => (
                          <div key={k} className="flex items-center justify-between gap-3 text-xs">
                            <span className="font-mono text-muted-foreground truncate" title={k}>
                              {k}
                            </span>
                            <span className="text-muted-foreground">{v}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground">无错误</div>
                    )}
                  </div>
                </div>
              </Panel>
            </div>
          )}
        </PageScaffold>
      </div>
    </AppFrame>
  )
}
