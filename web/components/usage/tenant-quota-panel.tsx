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

const TENANT_QUOTA_PANEL_CLASS =
  'overflow-hidden rounded-2xl border border-border/60 bg-card/82 shadow-[0_1px_0_hsl(var(--primary)/0.05)]'
const QUOTA_CARD_CLASS =
  'rounded-xl border border-border/60 bg-card/82 px-3 py-2.5 shadow-[0_1px_2px_hsl(var(--primary)/0.04)]'
const QUOTA_DISABLED_TONE =
  'border-border/60 bg-muted/55 text-muted-foreground'
const QUOTA_ENABLED_TONE =
  'border-success/20 bg-success/10 text-success'
const QUOTA_EXCEEDED_TONE =
  'border-destructive/20 bg-destructive/10 text-destructive'

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

function disabledQuotaText(label = '后端未启用该配额') {
  return {
    primary: '',
    secondary: label,
  }
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
    ? QUOTA_EXCEEDED_TONE
    : enabled
      ? QUOTA_ENABLED_TONE
      : QUOTA_DISABLED_TONE

  return (
    <div className={QUOTA_CARD_CLASS}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className={cn('flex size-8 items-center justify-center rounded-lg border', tone)}>
            <Icon className="size-3.5" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-[12px] font-semibold text-foreground">
              {title}
            </p>
            <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
              {secondary}
            </p>
          </div>
        </div>
        <span
          className={cn(
            'shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold',
            exceeded
              ? QUOTA_EXCEEDED_TONE
              : enabled
                ? QUOTA_ENABLED_TONE
                : QUOTA_DISABLED_TONE
          )}
        >
          {exceeded ? '已超额' : enabled ? '已启用' : '未启用'}
        </span>
      </div>
      <div className="mt-2 flex min-h-5 items-end justify-between gap-3">
        {enabled ? (
          <p className="text-[17px] font-semibold tabular-nums text-foreground">
            {primary}
          </p>
        ) : (
          <p className="text-[10px] font-medium text-muted-foreground">
            等待后端开启
          </p>
        )}
        <p className="text-[9px] font-medium uppercase tracking-[0.12em] text-muted-foreground/55">
          租户
        </p>
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            'h-full rounded-full',
            exceeded
              ? 'bg-destructive'
              : enabled
                ? 'bg-success'
                : 'bg-muted-foreground/45'
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
  const documentQuotaText = payload?.documents.enabled
    ? {
        primary: `${formatNumber(payload.documents.used)} / ${formatNumber(payload.documents.limit)}`,
        secondary: `剩余 ${formatNumber(payload.documents.remaining)} 个文档`,
      }
    : disabledQuotaText()
  const storageQuotaText = payload?.storage.enabled
    ? {
        primary: `${formatBytes(payload.storage.used_bytes)} / ${formatBytes(payload.storage.limit_bytes)}`,
        secondary: `剩余 ${formatBytes(payload.storage.remaining_bytes)}`,
      }
    : disabledQuotaText()
  const embeddingQuotaText = payload?.embedding_chars.enabled
    ? {
        primary: `${formatNumber(payload.embedding_chars.used_chars)} / ${formatNumber(payload.embedding_chars.limit_chars)}`,
        secondary: `${payload.embedding_chars.window_hours}h 窗口 · ${payload.embedding_chars.mode}`,
      }
    : disabledQuotaText('后端未启用字符配额')
  const qpsQuotaText = payload?.qps.enabled
    ? {
        primary: `${formatNumber(payload.qps.rps)} rps`,
        secondary: `burst ${formatNumber(payload.qps.burst)} · ${payload.qps.scopes?.join(' / ') || 'chat / retrieval'}`,
      }
    : disabledQuotaText('后端未启用租户限流')

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
      className={TENANT_QUOTA_PANEL_CLASS}
    >
      <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-[17px] font-semibold tracking-[-0.01em] text-foreground">
            租户级配额状态
          </h2>
          <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
            由后端配额配置控制，当前按租户生效，不按数据集或用户拆分。
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="h-10 gap-2 rounded-xl border-border/60 bg-card px-4 text-[13px] font-medium text-foreground shadow-sm hover:bg-muted/45"
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

      <div className="border-t border-border/50 px-5 pb-5 pt-4">
        {payload ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
	            <QuotaCard
	              icon={FileText}
	              title="文档数配额"
	              enabled={payload.documents.enabled}
	              exceeded={payload.documents.exceeded}
	              primary={documentQuotaText.primary}
	              secondary={documentQuotaText.secondary}
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
	              primary={storageQuotaText.primary}
	              secondary={storageQuotaText.secondary}
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
	              primary={embeddingQuotaText.primary}
	              secondary={embeddingQuotaText.secondary}
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
	              primary={qpsQuotaText.primary}
	              secondary={qpsQuotaText.secondary}
              progress={payload.qps.enabled ? 100 : 0}
            />
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border/60 bg-muted/35 px-4 py-6 text-center text-[13px] text-muted-foreground">
            {quotaQuery.isFetching
              ? '正在读取租户配额...'
              : '暂无配额数据，点击刷新重新读取。'}
          </div>
        )}

        <details className="mt-4 overflow-hidden rounded-xl border border-border/60 bg-muted/35">
          <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-[12px] font-semibold text-muted-foreground hover:bg-muted/55 [&::-webkit-details-marker]:hidden">
            查看原始响应
            <span className="text-[10px] font-medium text-muted-foreground">
              JSON
            </span>
          </summary>
          <div className="relative border-t border-border/60">
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-3 top-3 z-10 size-8 rounded-lg border border-border/60 bg-card text-muted-foreground shadow-sm hover:bg-muted/45"
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
                <span className="select-none border-r border-border/60 pr-3 text-right font-mono text-muted-foreground">
                  {index + 1}
                </span>
                <code
                  className={cn(
                    'pl-4 font-mono text-foreground',
                    line.includes('"message"') && 'text-primary'
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
