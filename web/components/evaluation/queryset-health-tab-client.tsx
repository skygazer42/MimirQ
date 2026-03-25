'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts'
import { RefreshCw, GitCompare, AlertTriangle, BarChart3 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { observabilityApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import type { QuerysetHealthDiffResponse, QuerysetHealthRunsResponse } from '@/types'

function formatTs(tsMs: number) {
  try {
    return new Date(tsMs).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return String(tsMs)
  }
}

function fmtPercent(v?: number | null, digits = 1) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(digits)}%`
}

function fmtNum(v?: number | null, digits = 3) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return Number(v).toFixed(digits)
}

function fmtMs(v?: number | null) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `${Math.round(Number(v))}ms`
}

export function QuerysetHealthTab({ embedded = false }: Readonly<{ embedded?: boolean }>) {
  const [runs, setRuns] = useState<QuerysetHealthRunsResponse | null>(null)
  const [diff, setDiff] = useState<QuerysetHealthDiffResponse | null>(null)
  const [loadingRuns, setLoadingRuns] = useState(false)
  const [loadingDiff, setLoadingDiff] = useState(false)

  const [baselineTs, setBaselineTs] = useState<string>('')
  const [currentTs, setCurrentTs] = useState<string>('')

  const loadRuns = useCallback(async () => {
    setLoadingRuns(true)
    try {
      const res = await observabilityApi.getQuerysetHealthRuns({ limit: 90 })
      setRuns(res)
      const items = res.items || []
      const latest = String(items?.[0]?.generated_at || '')
      const prev = String(items?.[1]?.generated_at || '')
      setCurrentTs((p) => p || latest)
      setBaselineTs((p) => p || prev || latest)
    } catch (err) {
      setRuns(null)
      toast.error(formatApiError(err, '加载 Queryset Health 历史失败（需要 owner/admin 权限）'))
    } finally {
      setLoadingRuns(false)
    }
  }, [])

  const loadDiff = useCallback(async (params: { baseline: string; current: string }) => {
    const a = String(params.baseline || '').trim()
    const b = String(params.current || '').trim()
    if (!a || !b) return
    setLoadingDiff(true)
    try {
      const res = await observabilityApi.getQuerysetHealthDiff({
        baseline_generated_at: a,
        current_generated_at: b,
        max_hard_case_ids: 20,
      })
      setDiff(res)
    } catch (err) {
      setDiff(null)
      toast.error(formatApiError(err, '加载 Queryset Health Diff 失败'))
    } finally {
      setLoadingDiff(false)
    }
  }, [])

  useEffect(() => {
    detachPromise(loadRuns())
  }, [loadRuns])

  useEffect(() => {
    if (!baselineTs || !currentTs) return
    if (baselineTs === currentTs) return
    detachPromise(loadDiff({ baseline: baselineTs, current: currentTs }))
  }, [baselineTs, currentTs, loadDiff])

  const latest = runs?.items?.[0] as Record<string, any> | undefined
  const latestMetrics = (latest?.metrics as Record<string, any>) || {}
  const latestRisk = (latest?.risk as Record<string, any>) || {}
  const latestFlags = Array.isArray(latest?.degradation_flags) ? (latest?.degradation_flags as any[]) : []

  const chartData = useMemo(() => {
    const ts = runs?.timeseries?.ts_ms || []
    const hit = runs?.timeseries?.hit_at_k || []
    const mrr = runs?.timeseries?.mrr || []
    const ndcg = runs?.timeseries?.ndcg_at_k || []
    const p95 = runs?.timeseries?.p95_latency_ms || []
    const miss = runs?.timeseries?.miss_rate || []
    const weak = runs?.timeseries?.weak_hit_rate || []
    const out: Array<Record<string, any>> = []
    for (let i = 0; i < ts.length; i++) {
      const t = Number(ts[i] || 0)
      out.push({
        t,
        time: formatTs(t),
        hit_at_k: hit[i] == null ? null : Number(hit[i] || 0),
        mrr: mrr[i] == null ? null : Number(mrr[i] || 0),
        ndcg_at_k: ndcg[i] == null ? null : Number(ndcg[i] || 0),
        p95_latency_ms: p95[i] == null ? null : Number(p95[i] || 0),
        miss_rate: miss[i] == null ? null : Number(miss[i] || 0),
        weak_hit_rate: weak[i] == null ? null : Number(weak[i] || 0),
      })
    }
    return out
  }, [runs?.timeseries])

  const diffMetricDeltas = useMemo(() => {
    const d = diff?.diff as Record<string, any> | undefined
    const deltas = (d?.metric_deltas as Record<string, any>) || {}
    return deltas
  }, [diff?.diff])

  return (
    <div className={cn('space-y-6', embedded ? '' : 'p-8')}>
      {!embedded ? (
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-foreground">Queryset Health</h2>
            <p className="text-sm text-muted-foreground mt-1">检索基准集健康度：趋势 + diff + 退化标记</p>
          </div>
          <Button variant="outline" size="sm" className="gap-2" onClick={() => loadRuns()} disabled={loadingRuns}>
            <RefreshCw className={cn('h-4 w-4', loadingRuns && 'animate-spin motion-reduce:animate-none')} />
            刷新
          </Button>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-lg font-semibold text-foreground">Queryset Health</div>
            <div className="text-sm text-muted-foreground mt-1">趋势 + diff + 退化标记</div>
          </div>
          <Button variant="outline" size="sm" className="gap-2" onClick={() => loadRuns()} disabled={loadingRuns}>
            <RefreshCw className={cn('h-4 w-4', loadingRuns && 'animate-spin motion-reduce:animate-none')} />
            刷新
          </Button>
        </div>
      )}

      <Panel variant="glass" className="rounded-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-sm font-semibold text-foreground">Latest Snapshot</div>
            <div className="text-xs text-muted-foreground mt-1">
              {latest?.generated_at ? `generated_at=${String(latest.generated_at)}` : '暂无历史记录'}
            </div>
          </div>
          <div className="text-xs text-muted-foreground">
            path: <span className="font-mono">{runs?.path || '—'}</span>
          </div>
        </div>

        <div className="mt-4">
          <StatsGrid className="xl:grid-cols-6">
            <StatCard icon={BarChart3} label="Hit@K" value={fmtPercent(latestMetrics.hit_at_k, 1)} color="sky" />
            <StatCard icon={BarChart3} label="MRR" value={fmtNum(latestMetrics.mrr, 3)} color="teal" />
            <StatCard icon={BarChart3} label="NDCG@K" value={fmtNum(latestMetrics.ndcg_at_k, 3)} color="teal" />
            <StatCard icon={BarChart3} label="P95 Latency" value={fmtMs(latestMetrics.p95_latency_ms)} color="amber" />
            <StatCard icon={AlertTriangle} label="Miss Rate" value={fmtPercent(latestRisk.miss_rate, 1)} color="rose" />
            <StatCard icon={AlertTriangle} label="Weak Hit Rate" value={fmtPercent(latestRisk.weak_hit_rate, 1)} color="rose" />
          </StatsGrid>

          {latestFlags.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {latestFlags.slice(0, 12).map((f: any) => (
                <span key={String(f)} className="text-[10px] px-2 py-0.5 rounded-full bg-destructive/10 text-destructive border border-destructive/20">
                  {String(f)}
                </span>
              ))}
            </div>
          ) : (
            <div className="mt-3 text-xs text-muted-foreground">无退化标记</div>
          )}
        </div>
      </Panel>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel variant="glass" className="rounded-2xl min-h-[340px]">
          <div className="flex items-center justify-between mb-3">
            <div className="text-sm font-semibold text-foreground">Quality Trend</div>
            <div className="text-xs text-muted-foreground">Hit@K / MRR / NDCG</div>
          </div>
          <div className="h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} domain={[0, 1]} />
                <Tooltip />
                <Line type="monotone" dataKey="hit_at_k" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="mrr" stroke="hsl(var(--info))" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="ndcg_at_k" stroke="hsl(var(--success))" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel variant="glass" className="rounded-2xl min-h-[340px]">
          <div className="flex items-center justify-between mb-3">
            <div className="text-sm font-semibold text-foreground">Latency / Risk Trend</div>
            <div className="text-xs text-muted-foreground">P95 / miss / weak-hit</div>
          </div>
          <div className="h-[260px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Line type="monotone" dataKey="p95_latency_ms" stroke="hsl(var(--warning))" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="miss_rate" stroke="hsl(var(--destructive))" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="weak_hit_rate" stroke="hsl(var(--info))" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      <Panel variant="glass" className="rounded-2xl">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <GitCompare className="h-4 w-4 text-muted-foreground" />
            <div className="text-sm font-semibold text-foreground">Diff</div>
          </div>
          <div className="text-xs text-muted-foreground">
            {loadingDiff ? '计算中…' : diff?.diff ? '已加载' : '—'}
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">Baseline</div>
            <Select value={baselineTs} onValueChange={setBaselineTs} disabled={!runs?.items?.length}>
              <SelectTrigger className="rounded-xl">
                <SelectValue placeholder="选择 baseline" />
              </SelectTrigger>
              <SelectContent>
                {(runs?.items || []).map((it: any) => (
                  <SelectItem key={String(it.generated_at)} value={String(it.generated_at)}>
                    {String(it.generated_at)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">Current</div>
            <Select value={currentTs} onValueChange={setCurrentTs} disabled={!runs?.items?.length}>
              <SelectTrigger className="rounded-xl">
                <SelectValue placeholder="选择 current" />
              </SelectTrigger>
              <SelectContent>
                {(runs?.items || []).map((it: any) => (
                  <SelectItem key={String(it.generated_at)} value={String(it.generated_at)}>
                    {String(it.generated_at)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {diffMetricDeltas && Object.keys(diffMetricDeltas).length ? (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            {[
              'hit_at_k_delta',
              'mrr_delta',
              'ndcg_at_k_delta',
              'p95_latency_ms_delta',
              'miss_rate_delta',
              'weak_hit_rate_delta',
            ].map((k) => (
              <div key={k} className="flex items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/30 px-3 py-2">
                <span className="font-mono text-muted-foreground">{k}</span>
                <span className="tabular-nums text-foreground/90">{String((diffMetricDeltas as any)[k] ?? '—')}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-4 text-xs text-muted-foreground">选择两个不同的 snapshot 以查看 diff。</div>
        )}
      </Panel>

      <Panel variant="glass" className="rounded-2xl">
        <div className="text-sm font-semibold text-foreground">Recent Runs</div>
        <div className="text-xs text-muted-foreground mt-1">展示最近 {runs?.items?.length ?? 0} 条（newest-first）</div>

        <div className="mt-4 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 text-xs text-muted-foreground">
                <th className="text-left py-2 pr-4">generated_at</th>
                <th className="text-left py-2 pr-4">status</th>
                <th className="text-right py-2 pr-4">hit@k</th>
                <th className="text-right py-2 pr-4">mrr</th>
                <th className="text-right py-2 pr-4">ndcg</th>
                <th className="text-right py-2 pr-4">p95(ms)</th>
                <th className="text-right py-2 pr-4">miss</th>
              </tr>
            </thead>
            <tbody>
              {(runs?.items || []).slice(0, 30).map((it: any) => {
                const m = (it?.metrics as any) || {}
                const r = (it?.risk as any) || {}
                const st = String(it?.status || 'unknown')
                const isDegraded = st === 'degraded'
                return (
                  <tr key={String(it.generated_at)} className="border-b border-border/40">
                    <td className="py-2 pr-4 font-mono text-xs text-muted-foreground">{String(it.generated_at || '')}</td>
                    <td className={cn('py-2 pr-4 text-xs', isDegraded ? 'text-destructive' : 'text-success')}>
                      {st}
                    </td>
                    <td className="py-2 pr-4 text-right tabular-nums">{fmtPercent(m.hit_at_k, 1)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{fmtNum(m.mrr, 3)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{fmtNum(m.ndcg_at_k, 3)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{fmtNum(m.p95_latency_ms, 1)}</td>
                    <td className="py-2 pr-4 text-right tabular-nums">{fmtPercent(r.miss_rate, 1)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
