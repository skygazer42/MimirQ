'use client'

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { BarChart3, RefreshCw, Coins } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { datasetApi, usageApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import type { ChatTokenQuotaStatus, ChatTokenUsageSummary } from '@/types'
import { cn } from '@/lib/utils'

const WINDOW_PRESETS = [
  { label: '24 小时', value: 1 },
  { label: '7 天', value: 7 },
  { label: '30 天', value: 30 },
] as const

function shortId(id: string) {
  const v = (id || '').trim()
  if (!v) return ''
  return v.length > 12 ? `${v.slice(0, 6)}…${v.slice(-4)}` : v
}

export default function UsagePage() {
  const [windowDays, setWindowDays] = useState<number>(7)
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState<ChatTokenUsageSummary | null>(null)
  const [quota, setQuota] = useState<ChatTokenQuotaStatus | null>(null)
  const [datasetNameById, setDatasetNameById] = useState<Record<string, string>>({})

  const load = async (days = windowDays) => {
    setLoading(true)
    try {
      const [usage, q, datasets] = await Promise.all([
        usageApi.getChatTokenUsageSummary({ window_days: days }),
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
      setQuota(q)
    } catch (err: any) {
      setSummary(null)
      setQuota(null)
      toast.error(formatApiError(err, '加载用量数据失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(windowDays)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const rows = useMemo(() => {
    const list = summary?.by_dataset || []
    return [...list].sort((a, b) => (b.assistant_tokens || 0) - (a.assistant_tokens || 0))
  }, [summary?.by_dataset])

  const windowLabel = useMemo(() => {
    const p = WINDOW_PRESETS.find((x) => x.value === windowDays)
    return p?.label || `${windowDays} 天`
  }, [windowDays])

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
                onClick={() => void load(windowDays)}
                disabled={loading}
              >
                <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin motion-reduce:animate-none')} />
                刷新
              </Button>
            </div>
          }
        >
          {!summary ? (
            <Panel padding="lg" className="mt-4">
              <div className="text-sm text-muted-foreground">
                无法加载用量数据。请确认你是 owner/admin，并且后端已更新到包含 /api/v1/usage 的版本。
              </div>
            </Panel>
          ) : (
            <div className="space-y-6">
              <StatsGrid className="mt-2">
                <StatCard
                  icon={Coins}
                  label="助手 Tokens"
                  value={summary.total_assistant_tokens}
                  subValue={windowLabel}
                  color="amber"
                />
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
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-muted-foreground border-b border-border/60">
                        <th className="text-left py-2 pr-3 font-medium">数据集</th>
                        <th className="text-right py-2 px-3 font-medium">助手消息</th>
                        <th className="text-right py-2 pl-3 font-medium">助手 tokens</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.slice(0, 50).map((r, idx) => {
                        const id = r.dataset_id || ''
                        const name = id ? datasetNameById[id] || shortId(id) : '(unknown)'
                        return (
                          <tr key={`${id}-${idx}`} className="border-b border-border/40 last:border-0">
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
            </div>
          )}
        </PageScaffold>
      </div>
    </AppFrame>
  )
}
