'use client'

import { useMemo, type ComponentType } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Copy,
  Database,
  FileText,
  Gauge,
  Loader2,
  RefreshCw,
  TextCursorInput,
} from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { usageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'
import type { TenantQuotaSummary } from '@/types'

function prettyJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success('已复制')
  } catch {
    toast.error('复制失败')
  }
}

function formatNumber(value: number | null | undefined) {
  if (value == null || !Number.isFinite(Number(value))) return '0'
  return Number(value).toLocaleString()
}

function formatBytes(value: number | null | undefined) {
  const n = Number(value || 0)
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = n
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`
}

type QuotaCardProps = {
  icon: ComponentType<{ className?: string }>
  title: string
  enabled: boolean
  exceeded?: boolean
  primary: string
  secondary: string
  progress?: number
}

function QuotaCard({
  icon: Icon,
  title,
  enabled,
  exceeded = false,
  primary,
  secondary,
  progress = 0,
}: QuotaCardProps) {
  const tone = exceeded
    ? 'border-rose-100 bg-rose-50 text-rose-600'
    : enabled
      ? 'border-emerald-100 bg-emerald-50 text-emerald-600'
      : 'border-slate-100 bg-slate-50 text-slate-500'

  return (
    <div className="rounded-xl border border-slate-200/70 bg-card px-4 py-3 shadow-[0_1px_2px_rgba(15,23,42,0.02)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <div className={cn('flex size-9 items-center justify-center rounded-xl border', tone)}>
            <Icon className="size-4" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-[12px] font-semibold text-slate-800">
              {title}
            </p>
            <p className="mt-0.5 truncate text-[11px] text-slate-400">
              {secondary}
            </p>
          </div>
        </div>
        <span
          className={cn(
            'shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold',
            exceeded
              ? 'border-rose-100 bg-rose-50 text-rose-600'
              : enabled
                ? 'border-emerald-100 bg-emerald-50 text-emerald-600'
                : 'border-slate-100 bg-slate-50 text-slate-500'
          )}
        >
          {exceeded ? '已超额' : enabled ? '已启用' : '未启用'}
        </span>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <p className="text-[18px] font-semibold tabular-nums text-slate-950">
          {primary}
        </p>
        <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
          租户
        </p>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className={cn(
            'h-full rounded-full',
            exceeded ? 'bg-rose-500' : enabled ? 'bg-emerald-500' : 'bg-slate-300'
          )}
          style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}
        />
      </div>
    </div>
  )
}

export function TenantQuotaPanel() {
  const quotaQuery = useQuery<TenantQuotaSummary>({
    queryKey: queryKeys.usage.tenantQuotaSummary,
    queryFn: () => usageApi.getTenantQuotaSummary(),
    staleTime: 60 * 1000,
  })
  const payload = quotaQuery.data ?? null
  const json = useMemo(() => prettyJson(payload), [payload])
  const lines = useMemo(() => json.split('\n'), [json])

  async function refreshQuota() {
    const result = await quotaQuery.refetch()
    if (result.error) {
      toast.error(formatApiError(result.error, '加载租户配额失败'))
      return
    }
    if (result.data) {
      toast.success('租户配额总览已刷新')
    }
  }

  return (
    <Panel
      padding="none"
      className="overflow-hidden rounded-2xl border border-slate-200/80 bg-card shadow-[0_1px_0_rgba(15,23,42,0.03)]"
    >
      <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-[17px] font-medium tracking-[-0.01em] text-slate-950">
            租户级配额状态
          </h2>
          <p className="mt-1 text-[13px] leading-5 text-slate-500">
            从后端配置读取文档、存储、Embedding 字符与 QPS 限额；当前按租户生效，不按数据集或用户拆分。
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="h-10 gap-2 rounded-xl border-slate-200 bg-card px-4 text-[13px] font-medium text-slate-800 shadow-sm hover:bg-slate-50"
          disabled={quotaQuery.isFetching}
          onClick={() => detachPromise(refreshQuota())}
        >
          {quotaQuery.isFetching ? (
            <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
          ) : (
            <RefreshCw className="size-4" />
          )}
          刷新
        </Button>
      </div>

      <div className="border-t border-slate-200 px-5 pb-5 pt-4">
        {payload ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <QuotaCard
              icon={FileText}
              title="文档数配额"
              enabled={payload.documents.enabled}
              exceeded={payload.documents.exceeded}
              primary={`${formatNumber(payload.documents.used)} / ${formatNumber(payload.documents.limit)}`}
              secondary={`剩余 ${formatNumber(payload.documents.remaining)} 个文档`}
              progress={
                payload.documents.enabled
                  ? (payload.documents.used / Math.max(1, payload.documents.limit)) * 100
                  : 0
              }
            />
            <QuotaCard
              icon={Database}
              title="存储配额"
              enabled={payload.storage.enabled}
              exceeded={payload.storage.exceeded}
              primary={`${formatBytes(payload.storage.used_bytes)} / ${formatBytes(payload.storage.limit_bytes)}`}
              secondary={`剩余 ${formatBytes(payload.storage.remaining_bytes)}`}
              progress={
                payload.storage.enabled
                  ? (payload.storage.used_bytes / Math.max(1, payload.storage.limit_bytes)) * 100
                  : 0
              }
            />
            <QuotaCard
              icon={TextCursorInput}
              title="Embedding 字符"
              enabled={payload.embedding_chars.enabled}
              exceeded={payload.embedding_chars.exceeded}
              primary={`${formatNumber(payload.embedding_chars.used_chars)} / ${formatNumber(payload.embedding_chars.limit_chars)}`}
              secondary={`${payload.embedding_chars.window_hours}h 窗口 · ${payload.embedding_chars.mode}`}
              progress={
                payload.embedding_chars.enabled
                  ? (payload.embedding_chars.used_chars /
                      Math.max(1, payload.embedding_chars.limit_chars)) *
                    100
                  : 0
              }
            />
            <QuotaCard
              icon={Gauge}
              title="QPS 限流"
              enabled={payload.qps.enabled}
              primary={`${formatNumber(payload.qps.rps)} rps`}
              secondary={`burst ${formatNumber(payload.qps.burst)} · ${payload.qps.scopes?.join(' / ') || 'chat / retrieval'}`}
              progress={payload.qps.enabled ? 100 : 0}
            />
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-6 text-center text-[13px] text-slate-500">
            {quotaQuery.isFetching
              ? '正在读取租户配额...'
              : '暂无配额数据，点击刷新重新读取。'}
          </div>
        )}

        <details className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-slate-50/60">
          <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-[12px] font-semibold text-slate-600 hover:bg-slate-100/70 [&::-webkit-details-marker]:hidden">
            查看原始响应
            <span className="text-[10px] font-medium text-slate-400">
              JSON
            </span>
          </summary>
          <div className="relative border-t border-slate-200">
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-3 top-3 z-10 size-8 rounded-lg border border-slate-200 bg-card text-slate-500 shadow-sm hover:bg-slate-50"
            onClick={() => detachPromise(copyText(json))}
            aria-label="复制租户配额 JSON"
          >
            <Copy className="size-4" />
          </Button>
          <pre className="max-h-[220px] overflow-auto py-3 pr-12 text-[13px] leading-7">
            {lines.map((line, index) => (
              <div
                key={`${index}-${line}`}
                className="grid grid-cols-[44px_1fr]"
              >
                <span className="select-none border-r border-slate-200 pr-3 text-right font-mono text-slate-400">
                  {index + 1}
                </span>
                <code
                  className={cn(
                    'pl-4 font-mono text-slate-700',
                    line.includes('"message"') && 'text-teal-700'
                  )}
                >
                  {line || ' '}
                </code>
              </div>
            ))}
          </pre>
          </div>
        </details>
      </div>
    </Panel>
  )
}
