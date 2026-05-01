'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { BarChart3, RefreshCw, Coins } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { Button } from '@/components/ui/button'
import { SystemDataStrip } from '@/components/ui/system-data-strip'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { datasetApi, usageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { ChatCostUsageSummary, ChatTokenQuotaStatus, ChatTokenUsageSummary } from '@/types'
import { cn, detachPromise } from '@/lib/utils'
import { EmptyState } from '@/components/ui/empty-state'
import { systemDenseControls, systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'
import { TenantQuotaPanel } from '@/components/usage/tenant-quota-panel'

const WINDOW_PRESETS = [
    { label: '24 小时', value: 1 },
    { label: '7 天', value: 7 },
    { label: '30 天', value: 30 },
]

const DENSE_OUTLINE_BUTTON = systemDenseControls.outlineButton
const DENSE_SELECT_TRIGGER = systemDenseControls.selectTrigger
const DENSE_PANEL = systemWorkbenchTokens.panel
const DENSE_TABLE_HEAD = cn(systemPageTokens.tableHead, 'tracking-[0.1em]')
const DENSE_TABLE_CELL = 'py-1.5 px-2.5 text-[12px] tabular-nums'
const DENSE_TABLE = 'w-full table-fixed text-[12px]'
const DENSE_PRIMARY_COL = 'w-[52%]'
const DENSE_NUM_COL = 'w-[24%]'
const DENSE_NUM_COL_WIDE = 'w-[16%]'

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

  const usageStripItems = useMemo(
    () => [
      { label: '统计窗口', value: windowLabel },
      { label: '数据集条目', value: rows.length, mono: true },
      {
        label: '模型总令牌（LLM）',
        value: cost?.total_llm_total_tokens ?? '-',
        mono: true,
      },
      {
        label: '配额状态',
        value: quota?.enabled ? (quota.exceeded ? '已超额' : '正常') : '未启用',
        tone: quota?.enabled ? (quota.exceeded ? 'danger' : 'success') : 'default',
      },
      {
        label: '数据状态',
        value: loading ? '加载中' : summary ? '已就绪' : '无数据',
        tone: loading ? 'warning' : summary ? 'success' : 'default',
      },
    ],
    [windowLabel, rows.length, cost?.total_llm_total_tokens, quota?.enabled, quota?.exceeded, loading, summary]
  )

  return (
    <AppFrame>
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <PageScaffold
          title="用量/配额"
          description="按数据集聚合的令牌、成本估算与窗口配额占用（仅管理员）"
          icon={Coins}
          iconColor="text-amber-600 dark:text-amber-400"
          size="full"
          density="system-dense"
          top={<SystemDataStrip items={usageStripItems} minColumnWidth={160} />}
          actions={
            <div className="flex w-full flex-col items-stretch gap-2 sm:w-auto sm:flex-row sm:items-center">
              <div className="w-full sm:w-[140px]">
                <Select
                  value={String(windowDays)}
                  onValueChange={(v) => {
                    const next = Number.parseInt(v, 10)
                    setWindowDays(next)
                  }}
                >
                  <SelectTrigger className={DENSE_SELECT_TRIGGER}>
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
                className={cn(DENSE_OUTLINE_BUTTON, 'justify-center')}
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
            <div className="space-y-4">
              <StatsGrid dense className="mt-1">
                <StatCard
                  icon={Coins}
                  label="助手令牌"
                  value={summary.total_assistant_tokens}
                  subValue={windowLabel}
                  color="amber"
                  dense
                />
                {cost ? (
                  <StatCard
                    icon={Coins}
                    label="模型总令牌（LLM，估算）"
                    value={cost.total_llm_total_tokens}
                    subValue={`输入 ${cost.total_llm_prompt_tokens} + 输出 ${cost.total_llm_completion_tokens}`}
                    color="orange"
                    dense
                  />
                ) : null}
                {cost ? (
                  <StatCard
                    icon={Coins}
                    label="向量令牌（估算）"
                    value={cost.total_embedding_query_tokens}
                    subValue={`${cost.total_embedding_query_chars} 字符 · 按检索请求估算`}
                    color="teal"
                    dense
                  />
                ) : null}
                {cost ? (
                  <StatCard
                    icon={BarChart3}
                    label="平均检索耗时"
                    value={formatSec(avgRetrieve)}
                    subValue={`平均重排 ${formatSec(avgRerank)}`}
                    color="sky"
                    dense
                  />
                ) : null}
                <StatCard
                  icon={Coins}
                  label="配额剩余"
                  value={quota?.enabled ? quota.remaining : '-'}
                  subValue={quota?.enabled ? `${quota.window_hours}h · ${quota.mode}` : '未启用'}
                  color={quota?.enabled && quota.exceeded ? 'red' : 'green'}
                  dense
                />
                <StatCard
                  icon={BarChart3}
                  label="助手消息数"
                  value={summary.total_assistant_messages}
                  subValue="助手角色"
                  color="sky"
                  dense
                />
              </StatsGrid>

              <Panel padding="md" className={DENSE_PANEL}>
                  <div className="mb-2.5 flex items-center justify-between">
                    <div className={cn(systemPageTokens.heading, 'text-sm')}>按数据集（Top 排名）</div>
                    <div className={systemPageTokens.subtle}>
                      窗口: {new Date(summary.window_start).toLocaleString()} → {new Date(summary.window_end).toLocaleString()}
                  </div>
                </div>

                <div className="overflow-auto">
                  <table aria-label="令牌用量明细" className={DENSE_TABLE}>
                    <thead className="sticky top-0 z-10 bg-background">
                        <tr className={cn(DENSE_TABLE_HEAD, 'border-b border-border/60')}>
                          <th className={cn('py-1.5 pr-3 text-left font-semibold', DENSE_PRIMARY_COL)}>数据集</th>
                          <th className={cn('py-1.5 px-3 text-right font-semibold', DENSE_NUM_COL)}>助手消息</th>
                          <th className={cn('py-1.5 pl-3 text-right font-semibold', DENSE_NUM_COL)}>助手令牌</th>
                        </tr>
                      </thead>
                    <tbody>
                      {rows.slice(0, 50).map((r) => {
                        const id = r.dataset_id || ''
                        const name = id ? datasetNameById[id] || shortId(id) : '(未知数据集)'
                        return (
                          <tr key={JSON.stringify(r)} className="border-b border-border/40 text-[12px] transition-colors hover:bg-muted/20 last:border-0">
                            <td className="py-1.5 pr-3">
                              <div className="truncate font-semibold text-foreground" title={name}>{name}</div>
                              {id ? <div className={cn(systemPageTokens.monoMeta, 'truncate text-[11px]')} title={id}>{id}</div> : null}
                            </td>
                            <td className={cn(DENSE_TABLE_CELL, 'text-right')}>{r.assistant_messages}</td>
                            <td className={cn(DENSE_TABLE_CELL, 'pl-3 text-right')}>{r.assistant_tokens}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Panel>

              {cost ? (
                <Panel padding="md" className={DENSE_PANEL}>
                  <div className="mb-2.5 flex items-center justify-between">
                    <div className={cn(systemPageTokens.heading, 'text-sm')}>成本归因（估算）</div>
                    <div className={systemPageTokens.subtle}>
                      窗口: {new Date(cost.window_start).toLocaleString()} → {new Date(cost.window_end).toLocaleString()}
                    </div>
                  </div>

                  <div className="overflow-auto">
                    <table aria-label="成本用量明细" className={DENSE_TABLE}>
                      <thead className="sticky top-0 z-10 bg-background">
                        <tr className={cn(DENSE_TABLE_HEAD, 'border-b border-border/60')}>
                          <th className={cn('py-1.5 pr-3 text-left font-semibold', DENSE_PRIMARY_COL)}>数据集</th>
                          <th className={cn('py-1.5 px-3 text-right font-semibold', DENSE_NUM_COL_WIDE)}>请求数</th>
                          <th className={cn('py-1.5 px-3 text-right font-semibold', DENSE_NUM_COL_WIDE)}>模型总令牌（LLM）</th>
                          <th className={cn('py-1.5 px-3 text-right font-semibold', DENSE_NUM_COL_WIDE)}>向量令牌</th>
                          <th className={cn('py-1.5 pl-3 text-right font-semibold', DENSE_NUM_COL_WIDE)}>平均检索</th>
                        </tr>
                      </thead>
                      <tbody>
                        {costRows.slice(0, 50).map((r) => {
                          const id = r.dataset_id || ''
                          const name = id ? datasetNameById[id] || shortId(id) : '(未知数据集)'
                          const denom = Math.max(1, r.assistant_messages || 0)
                          const avgR = (r.retrieval_elapsed_sec_sum || 0) / denom
                          return (
                            <tr key={JSON.stringify(r)} className="border-b border-border/40 text-[12px] transition-colors hover:bg-muted/20 last:border-0">
                              <td className="py-1.5 pr-3">
                                <div className="truncate font-semibold text-foreground" title={name}>{name}</div>
                                {id ? <div className={cn(systemPageTokens.monoMeta, 'truncate text-[11px]')} title={id}>{id}</div> : null}
                              </td>
                              <td className={cn(DENSE_TABLE_CELL, 'text-right')}>{r.assistant_messages}</td>
                              <td className={cn(DENSE_TABLE_CELL, 'text-right')}>{r.llm_total_tokens}</td>
                              <td className={cn(DENSE_TABLE_CELL, 'text-right')}>{r.embedding_query_tokens}</td>
                              <td className={cn(DENSE_TABLE_CELL, 'pl-3 text-right')}>{formatSec(avgR)}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              ) : null}

              <TenantQuotaPanel />
            </div>
          ) : (
            <EmptyState
              icon={BarChart3}
              title="暂无用量数据"
              description="无法加载用量数据。请确认您拥有管理员权限，并且后端已更新到包含用量接口的版本。"
              className="mt-4"
            />
          )}
        </PageScaffold>
      </div>
    </AppFrame>
  )
}
