'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { BarChart3, RefreshCw, Coins } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { datasetApi, usageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { ChatCostUsageSummary, ChatTokenQuotaStatus, ChatTokenUsageSummary } from '@/types'
import { cn, detachPromise } from '@/lib/utils'
import { EmptyState } from '@/components/ui/empty-state'

const WINDOW_PRESETS = [
    { label: '24 小时', value: 1 },
    { label: '7 天', value: 7 },
    { label: '30 天', value: 30 },
]

function shortId(id: string) {
  const v = (id || '').trim()
  if (!v) return ''
  return v.length > 12 ? `${v.slice(0, 6)}…${v.slice(-4)}` : v
}

export default function UsagePage() {
  const [windowDays, setWindowDays] = useState<number>(7)
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState<ChatTokenUsageSummary | null>(null)
  const [cost, setCost] = useState<ChatCostUsageSummary | null>(null)
  const [quota, setQuota] = useState<ChatTokenQuotaStatus | null>(null)
  const [datasetNameById, setDatasetNameById] = useState<Record<string, string>>({})

  const formatSec = (sec: number | null | undefined) => {
    if (sec == null || !Number.isFinite(sec)) return '—'
    if (sec < 1) return `${Math.round(sec * 1000)}ms`
    return `${sec.toFixed(2)}s`
  }

  const load = useCallback(async (days: number) => {
    setLoading(true)
    try {
      const [usage, costUsage, q, datasets] = await Promise.all([
        usageApi.getChatTokenUsageSummary({ window_days: days }),
        usageApi.getChatCostUsageSummary({ window_days: days }).catch(() => null),
        usageApi.getChatTokenQuotaStatus().catch(() => null),
        datasetApi.list({ limit: 200 }),
      ])

      const nameMap: Record<string, string> = {}
      for (const ds of datasets.items || []) {
        if (!ds?.id) continue
        nameMap[String(ds.id)] = String(ds.name || '').trim() || shortId(String(ds.id))
      }
      setDatasetNameById(nameMap)
      setSummary(usage)
      setCost(costUsage)
      setQuota(q)
    } catch (err: any) {
      setSummary(null)
      setCost(null)
      setQuota(null)
      toast.error(formatApiError(err, '加载用量数据失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    detachPromise(load(windowDays))
  }, [load, windowDays])

  const rows = useMemo(() => {
    const list = summary?.by_dataset || []
    return [...list].sort((a, b) => (b.assistant_tokens || 0) - (a.assistant_tokens || 0))
  }, [summary?.by_dataset])

  const costRows = useMemo(() => {
    const list = cost?.by_dataset || []
    return [...list].sort((a, b) => (b.llm_total_tokens || 0) - (a.llm_total_tokens || 0))
  }, [cost?.by_dataset])

  const windowLabel = useMemo(() => {
    const p = WINDOW_PRESETS.find((x) => x.value === windowDays)
    return p?.label || `${windowDays} 天`
  }, [windowDays])

  const avgRetrieve = useMemo(() => {
    if (!cost) return null
    const denom = Math.max(1, cost.total_assistant_messages || 0)
    return cost.total_retrieval_elapsed_sec / denom
  }, [cost])

  const avgRerank = useMemo(() => {
    if (!cost) return null
    const denom = Math.max(1, cost.total_assistant_messages || 0)
    return cost.total_rerank_elapsed_sec / denom
  }, [cost])

  return (
    <AppFrame>
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <PageScaffold
          title="用量与成本"
          description="按数据集聚合的 Chat 助手 tokens（admin-only）"
          icon={Coins}
          iconColor="text-amber-600 dark:text-amber-400"
          size="7xl"
          actions={
            <div className="flex items-center gap-2">
              <div className="w-[140px]">
                <Select
                  value={String(windowDays)}
                  onValueChange={(v) => {
                    const next = Number.parseInt(v, 10)
                    setWindowDays(next)
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
                onClick={() => detachPromise(load(windowDays))}
                disabled={loading}
              >
                <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin motion-reduce:animate-none')} />
                刷新
              </Button>
            </div>
          }
        >
          {summary ? (
            <div className="space-y-6">
              <StatsGrid className="mt-2">
                <StatCard
                  icon={Coins}
                  label="助手 Tokens"
                  value={summary.total_assistant_tokens}
                  subValue={windowLabel}
                  color="amber"
                />
                {cost ? (
                  <StatCard
                    icon={Coins}
                    label="LLM 总 Tokens（估算）"
                    value={cost.total_llm_total_tokens}
                    subValue={`prompt ${cost.total_llm_prompt_tokens} + completion ${cost.total_llm_completion_tokens}`}
                    color="orange"
                  />
                ) : null}
                {cost ? (
                  <StatCard
                    icon={Coins}
                    label="Embedding Tokens（估算）"
                    value={cost.total_embedding_query_tokens}
                    subValue={`${cost.total_embedding_query_chars} chars · queries by retrieval`}
                    color="teal"
                  />
                ) : null}
                {cost ? (
                  <StatCard
                    icon={BarChart3}
                    label="Avg Retrieve"
                    value={formatSec(avgRetrieve)}
                    subValue={`avg rerank ${formatSec(avgRerank)}`}
                    color="sky"
                  />
                ) : null}
                <StatCard
                  icon={Coins}
                  label="配额剩余"
                  value={quota?.enabled ? quota.remaining : '-'}
                  subValue={quota?.enabled ? `${quota.window_hours}h · ${quota.mode}` : 'disabled'}
                  color={quota?.enabled && quota.exceeded ? 'red' : 'green'}
                />
                <StatCard
                  icon={BarChart3}
                  label="助手消息数"
                  value={summary.total_assistant_messages}
                  subValue="assistant role"
                  color="sky"
                />
              </StatsGrid>

              <Panel padding="lg">
                <div className="flex items-center justify-between mb-4">
                  <div className="text-sm font-semibold text-foreground">按数据集（Top）</div>
                  <div className="text-xs text-muted-foreground">
                    window: {new Date(summary.window_start).toLocaleString()} → {new Date(summary.window_end).toLocaleString()}
                  </div>
                </div>

                <div className="overflow-auto">
                  <table aria-label="令牌用量明细" className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-muted-foreground border-b border-border/60">
                        <th className="text-left py-2 pr-3 font-medium">数据集</th>
                        <th className="text-right py-2 px-3 font-medium">助手消息</th>
                        <th className="text-right py-2 pl-3 font-medium">助手 tokens</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.slice(0, 50).map((r) => {
                        const id = r.dataset_id || ''
                        const name = id ? datasetNameById[id] || shortId(id) : '(unknown)'
                        return (
                          <tr key={JSON.stringify(r)} className="border-b border-border/40 last:border-0">
                            <td className="py-2 pr-3">
                              <div className="font-medium text-foreground">{name}</div>
                              {id ? <div className="text-[11px] text-muted-foreground font-mono">{id}</div> : null}
                            </td>
                            <td className="py-2 px-3 text-right tabular-nums">{r.assistant_messages}</td>
                            <td className="py-2 pl-3 text-right tabular-nums">{r.assistant_tokens}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Panel>

              {cost ? (
                <Panel padding="lg">
                  <div className="flex items-center justify-between mb-4">
                    <div className="text-sm font-semibold text-foreground">成本归因（估算）</div>
                    <div className="text-xs text-muted-foreground">
                      window: {new Date(cost.window_start).toLocaleString()} → {new Date(cost.window_end).toLocaleString()}
                    </div>
                  </div>

                  <div className="overflow-auto">
                    <table aria-label="成本用量明细" className="w-full text-sm">
                      <thead>
                        <tr className="text-xs text-muted-foreground border-b border-border/60">
                          <th className="text-left py-2 pr-3 font-medium">数据集</th>
                          <th className="text-right py-2 px-3 font-medium">请求数</th>
                          <th className="text-right py-2 px-3 font-medium">LLM total</th>
                          <th className="text-right py-2 px-3 font-medium">Embedding</th>
                          <th className="text-right py-2 pl-3 font-medium">Avg retrieve</th>
                        </tr>
                      </thead>
                      <tbody>
                        {costRows.slice(0, 50).map((r) => {
                          const id = r.dataset_id || ''
                          const name = id ? datasetNameById[id] || shortId(id) : '(unknown)'
                          const denom = Math.max(1, r.assistant_messages || 0)
                          const avgR = (r.retrieval_elapsed_sec_sum || 0) / denom
                          return (
                            <tr key={JSON.stringify(r)} className="border-b border-border/40 last:border-0">
                              <td className="py-2 pr-3">
                                <div className="font-medium text-foreground">{name}</div>
                                {id ? <div className="text-[11px] text-muted-foreground font-mono">{id}</div> : null}
                              </td>
                              <td className="py-2 px-3 text-right tabular-nums">{r.assistant_messages}</td>
                              <td className="py-2 px-3 text-right tabular-nums">{r.llm_total_tokens}</td>
                              <td className="py-2 px-3 text-right tabular-nums">{r.embedding_query_tokens}</td>
                              <td className="py-2 pl-3 text-right tabular-nums">{formatSec(avgR)}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              ) : null}
            </div>
          ) : (
            <EmptyState
              icon={BarChart3}
              title="暂无用量数据"
              description="无法加载用量数据。请确认您拥有 owner/admin 权限，并且后端已更新到包含用量接口的版本。"
              className="mt-4"
            />
          )}
        </PageScaffold>
      </div>
    </AppFrame>
  )
}
