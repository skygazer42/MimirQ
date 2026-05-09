'use client'

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Activity,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Coins,
  Database,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  Timer,
  UserRound,
  ArrowUpRight,
  LayoutGrid,
  Zap,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TenantQuotaPanel } from '@/components/usage/tenant-quota-panel'
import { datasetApi, usageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { cn, detachPromise } from '@/lib/utils'
import type { ChatCostUsageSummary, ChatTokenQuotaStatus, ChatTokenUsageSummary } from '@/types'

// --- Advanced Style Tokens ---

const GLASS_CARD = "bg-white/80 backdrop-blur-md rounded-2xl border border-white/40 shadow-[0_8px_32px_rgba(0,0,0,0.04)] overflow-hidden transition-all duration-300"
const GLOW_CARD = "group relative bg-white rounded-2xl border border-slate-200/60 p-6 shadow-sm hover:shadow-[0_20px_40px_rgba(59,130,246,0.08)] hover:-translate-y-1 transition-all duration-300"
const NUMBER_ACCENT = "text-2xl font-black text-slate-900 tracking-tighter font-mono bg-clip-text"
const WINDOW_PRESETS = [
  { value: 7, label: '7天' },
  { value: 14, label: '14天' },
  { value: 30, label: '30天' },
] as const

// --- Helper Functions ---

function shortId(id: string) {
  const v = (id || '').trim()
  if (!v) return ''
  return v.length > 12 ? `${v.slice(0, 6)}…${v.slice(-4)}` : v
}

function formatNumber(value: number | string | null | undefined) {
  if (value == null || value === '') return '0'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return n.toLocaleString()
}

function formatSec(sec: number | null | undefined) {
  if (sec == null || !Number.isFinite(sec)) return '0ms'
  if (sec < 1) return `${Math.round(sec * 1000)}ms`
  return `${sec.toFixed(2)}s`
}

function formatWindow(start?: string | null, end?: string | null) {
  if (!start || !end) return '---'
  try {
    const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
    return `${new Date(start).toLocaleString('zh-CN', opts)} - ${new Date(end).toLocaleString('zh-CN', opts)}`
  } catch {
    return `${start} - ${end}`
  }
}

// --- Specialized Components ---

function HUDStatus({ icon: Icon, label, value, tone = 'blue' }: { icon: LucideIcon; label: string; value: string | number; tone?: string }) {
  const toneMap = {
    blue: 'text-blue-600 bg-blue-50/50 border-blue-100',
    green: 'text-emerald-600 bg-emerald-50/50 border-emerald-100',
    slate: 'text-slate-400 bg-slate-50 border-slate-100',
  }
  return (
    <div className="relative flex min-h-[88px] items-center justify-center gap-4 border-r border-slate-100 px-6 py-4 text-center last:border-none group">
      <div className={cn("size-10 rounded-xl flex items-center justify-center border shadow-inner transition-transform group-hover:scale-110", toneMap[tone as keyof typeof toneMap])}>
        <Icon className="size-5" />
      </div>
      <div className="flex min-w-0 flex-col items-center text-center">
        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400 leading-none mb-1.5">{label}</p>
        <h4 className="text-[16px] font-black text-slate-800 leading-none tracking-tight">{value}</h4>
      </div>
    </div>
  )
}

function StylizedMetricCard({ icon: Icon, label, value, detail, tone = 'blue' }: { icon: LucideIcon; label: string; value: string | number; detail?: string; tone?: string }) {
  const accentMap = {
    blue: 'bg-blue-500',
    green: 'bg-emerald-500',
    indigo: 'bg-indigo-500',
    slate: 'bg-slate-300',
  }
  return (
    <div className={GLOW_CARD}>
      {/* Accent Strip */}
      <div className={cn("absolute left-0 top-6 bottom-6 w-1 rounded-r-full transition-all group-hover:w-1.5", accentMap[tone as keyof typeof accentMap])} />
      
      <div className="flex items-start justify-between mb-5">
        <div className="flex items-center gap-3">
           <div className="size-10 rounded-xl bg-slate-50 border border-slate-100 flex items-center justify-center text-slate-400 group-hover:bg-blue-600 group-hover:text-white group-hover:rotate-6 transition-all duration-300 shadow-sm">
             <Icon className="size-5" />
           </div>
           <span className="text-[12px] font-black text-slate-400 uppercase tracking-widest">{label}</span>
        </div>
        <div className="size-6 rounded-full bg-slate-50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
          <ArrowUpRight className="size-3 text-blue-500" />
        </div>
      </div>
      
      <div className="flex flex-col pl-2">
        <span className={NUMBER_ACCENT}>{value}</span>
        {detail && (
          <div className="mt-3 flex items-center gap-1.5">
            <span className="text-[9px] font-black px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 uppercase tracking-tighter">
              {detail}
            </span>
            <TrendingUp className="size-3 text-emerald-500 opacity-50" />
          </div>
        )}
      </div>
    </div>
  )
}

// --- Main Page ---

export default function UsagePage() {
  return (
    <TenantPermissionGate permission={TENANT_PERMISSIONS.USAGE_READ} pageName="用量/配额">
      <UsagePageContent />
    </TenantPermissionGate>
  )
}

function UsagePageContent() {
  const [windowDays, setWindowDays] = useState<number>(7)
  const [loading, setLoading] = useState(false)
  const [summary, setSummary] = useState<ChatTokenUsageSummary | null>(null)
  const [cost, setCost] = useState<ChatCostUsageSummary | null>(null)
  const [quota, setQuota] = useState<ChatTokenQuotaStatus | null>(null)
  const [datasetNameById, setDatasetNameById] = useState<Record<string, string>>({})

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
        if (ds?.id) nameMap[String(ds.id)] = String(ds.name || '').trim() || shortId(String(ds.id))
      }
      setDatasetNameById(nameMap)
      setSummary(usage); setCost(costUsage); setQuota(q)
    } catch (err: any) {
      toast.error(formatApiError(err, '数据拉取失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { detachPromise(load(windowDays)) }, [load, windowDays])

  const rows = useMemo(() => {
    const list = summary?.by_dataset || []
    return [...list].sort((a, b) => (b.assistant_tokens || 0) - (a.assistant_tokens || 0)).slice(0, 10)
  }, [summary])

  const costRows = useMemo(() => {
    const list = cost?.by_dataset || []
    return [...list].sort((a, b) => (b.llm_total_tokens || 0) - (a.llm_total_tokens || 0)).slice(0, 10)
  }, [cost])

  const avgRetrieve = cost ? cost.total_retrieval_elapsed_sec / Math.max(1, cost.total_assistant_messages || 0) : null
  const quotaExceeded = quota?.enabled && quota.exceeded
  const quotaStatus = quota?.enabled ? (quota.exceeded ? '已超额' : '运行正常') : '未启用'
  const dataStatus = summary ? '已就绪' : (loading ? '同步中' : '未连接')

  return (
    <AppFrame>
      <PageScaffold
        title="用量/配额"
        description="按数据集聚合的令牌、成本估算与接口配额占用（仅管理员）"
        icon={Coins}
        iconColor="text-blue-600"
        size="full"
        bodyClassName="bg-[#F8FAFC] relative"
      >
        {/* Ambient background glow */}
        <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
          <div className="absolute -left-[10%] -top-[10%] size-[40%] rounded-full bg-blue-400/5 blur-[120px]" />
          <div className="absolute -right-[5%] top-[20%] size-[30%] rounded-full bg-indigo-400/5 blur-[100px]" />
        </div>

        <div className="relative z-10 flex flex-col gap-10 pb-32">
          
          {/* Header Actions */}
          <div className="flex items-center justify-between">
             <div className="flex items-center gap-2">
                <div className="size-2 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
                <span className="text-[11px] font-black text-slate-400 uppercase tracking-widest">Live System Usage Monitoring</span>
             </div>
             <div className="flex items-center gap-3">
                <Select value={String(windowDays)} onValueChange={v => setWindowDays(Number(v))}>
                  <SelectTrigger className="h-10 w-[120px] rounded-xl border-white bg-white/60 backdrop-blur-sm font-bold text-[13px] shadow-sm hover:bg-white transition-all">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WINDOW_PRESETS.map(p => <SelectItem key={p.value} value={String(p.value)}>{p.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Button variant="outline" size="icon" className="size-10 rounded-xl border-white bg-white/60 backdrop-blur-sm shadow-sm hover:bg-white transition-all" onClick={() => detachPromise(load(windowDays))}>
                  <RefreshCw className={cn("size-4 text-slate-600", loading && "animate-spin")} />
                </Button>
             </div>
          </div>

          {/* HUD Status Bar (Glassmorphism) */}
          <div className="grid overflow-hidden rounded-3xl border border-white/60 bg-white/40 shadow-xl shadow-slate-200/20 backdrop-blur-xl md:grid-cols-5">
            <HUDStatus icon={CalendarDays} label="统计窗口" value={windowDays === 1 ? '24小时' : `${windowDays}天`} tone="blue" />
            <HUDStatus icon={Database} label="数据集条目" value={rows.length} tone="blue" />
            <HUDStatus icon={Coins} label="模型总令牌" value={formatNumber(cost?.total_llm_total_tokens)} tone="blue" />
            <HUDStatus icon={ShieldCheck} label="配额状态" value={quotaStatus} tone={quota?.enabled && !quota.exceeded ? 'green' : (quotaExceeded ? 'red' : 'slate')} />
            <HUDStatus icon={CheckCircle2} label="数据状态" value={dataStatus} tone={summary ? 'green' : 'slate'} />
          </div>

          {/* Main Visual KPIs */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-6">
            <StylizedMetricCard icon={UserRound} label="助手令牌" value={formatNumber(summary?.total_assistant_tokens)} detail="ASSISTANT" tone="blue" />
            <StylizedMetricCard icon={Coins} label="LLM 预估总额" value={formatNumber(cost?.total_llm_total_tokens)} detail="LLM_EST" tone="indigo" />
            <StylizedMetricCard icon={Database} label="向量令牌" value={formatNumber(cost?.total_embedding_query_tokens)} detail="EMBEDDING" tone="blue" />
            <StylizedMetricCard icon={Timer} label="平均检索耗时" value={formatSec(avgRetrieve)} detail="LATENCY" tone="indigo" />
            <StylizedMetricCard icon={Clock3} label="配额剩余" value={quota?.enabled ? formatNumber(quota.remaining) : '0'} detail="REMAINING" tone="green" />
            <StylizedMetricCard icon={MessageSquareText} label="总消息数" value={formatNumber(summary?.total_assistant_messages)} detail="TOTAL_MSG" tone="slate" />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-12 gap-10">
            
            {/* Usage Table Section */}
            <div className={cn(GLASS_CARD, "xl:col-span-5 flex flex-col border-blue-100/30")}>
               <div className="px-8 py-6 border-b border-slate-100/50 flex items-center justify-between bg-gradient-to-r from-blue-50/50 to-transparent">
                  <div>
                    <h3 className="text-[14px] font-black text-slate-900 uppercase tracking-tight flex items-center gap-2">
                       <TrendingUp className="size-4 text-blue-500" />
                       数据集用量排行
                    </h3>
                    <p className="text-[10px] text-slate-400 font-bold uppercase mt-1 tracking-tighter">{formatWindow(summary?.window_start, summary?.window_end)}</p>
                  </div>
                  <div className="size-8 rounded-lg bg-white border border-slate-100 flex items-center justify-center text-slate-200">
                    <LayoutGrid className="size-4" />
                  </div>
               </div>
               <div className="overflow-auto max-h-[520px]">
                 <table className="w-full text-left">
                   <thead>
                      <tr className="bg-slate-50/30 border-b border-slate-100/50">
                        <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">数据集</th>
                        <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">消息</th>
                        <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">消耗</th>
                      </tr>
                   </thead>
                   <tbody className="divide-y divide-slate-50/50">
                      {rows.map(r => (
                        <tr key={r.dataset_id} className="hover:bg-blue-50/30 transition-all duration-200 group">
                          <td className="px-8 py-5">
                            <p className="text-[13px] font-bold text-slate-700 truncate max-w-[200px] group-hover:text-blue-600 transition-colors">{datasetNameById[r.dataset_id || ''] || '未绑定'}</p>
                            <p className="text-[9px] font-mono text-slate-300 group-hover:text-slate-400 uppercase">{shortId(r.dataset_id || '')}</p>
                          </td>
                          <td className="px-8 py-5 text-[12px] font-mono text-slate-500 text-right">{formatNumber(r.assistant_messages)}</td>
                          <td className="px-8 py-5 text-[12px] font-mono font-black text-slate-900 text-right">{formatNumber(r.assistant_tokens)}</td>
                        </tr>
                      ))}
                   </tbody>
                 </table>
               </div>
            </div>

            {/* Cost Attribution Table Section */}
            <div className={cn(GLASS_CARD, "xl:col-span-7 flex flex-col border-indigo-100/30")}>
               <div className="px-8 py-6 border-b border-slate-100/50 flex items-center justify-between bg-gradient-to-r from-indigo-50/50 to-transparent">
                  <div>
                    <h3 className="text-[14px] font-black text-slate-900 uppercase tracking-tight flex items-center gap-2">
                       <Zap className="size-4 text-indigo-500 fill-current" />
                       成本归因分析 (估算)
                    </h3>
                    <p className="text-[10px] text-slate-400 font-bold uppercase mt-1 tracking-tighter">{formatWindow(cost?.window_start, cost?.window_end)}</p>
                  </div>
                  <div className="size-8 rounded-lg bg-white border border-slate-100 flex items-center justify-center text-slate-200">
                    <BarChart3 className="size-4" />
                  </div>
               </div>
               <div className="overflow-auto max-h-[520px]">
                 <table className="w-full text-left">
                   <thead>
                      <tr className="bg-slate-50/30 border-b border-slate-100/50">
                        <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">分析维度</th>
                        <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">LLM TOKEN</th>
                        <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">向量 TOKEN</th>
                        <th className="px-8 py-4 text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] text-right">平均检索</th>
                      </tr>
                   </thead>
                   <tbody className="divide-y divide-slate-50/50">
                      {costRows.map(r => (
                        <tr key={r.dataset_id} className="hover:bg-indigo-50/30 transition-all duration-200 group">
                          <td className="px-8 py-5">
                            <p className="text-[13px] font-bold text-slate-700 truncate max-w-[240px] group-hover:text-indigo-600 transition-colors">{datasetNameById[r.dataset_id || ''] || '未绑定'}</p>
                            <p className="text-[9px] font-mono text-slate-300 group-hover:text-slate-400 uppercase">{shortId(r.dataset_id || '')}</p>
                          </td>
                          <td className="px-8 py-5 text-[12px] font-mono font-black text-slate-800 text-right">{formatNumber(r.llm_total_tokens)}</td>
                          <td className="px-8 py-5 text-[12px] font-mono text-slate-500 text-right">{formatNumber(r.embedding_query_tokens)}</td>
                          <td className="px-8 py-5 text-[12px] font-mono text-slate-400 text-right">{formatSec(r.retrieval_elapsed_sec_sum / Math.max(1, r.assistant_messages || 0))}</td>
                        </tr>
                      ))}
                   </tbody>
                 </table>
               </div>
            </div>
          </div>

          {/* Bottom Custom Panel */}
          <div className="relative">
             <div className="absolute inset-0 bg-gradient-to-b from-transparent via-white/5 to-white/10 rounded-3xl pointer-events-none" />
             <TenantQuotaPanel />
          </div>
        </div>
      </PageScaffold>
    </AppFrame>
  )
}
