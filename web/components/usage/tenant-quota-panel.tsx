'use client'

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { usageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'

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

export function TenantQuotaPanel() {
  const quotaQuery = useQuery({
    queryKey: queryKeys.usage.tenantQuotaSummary,
    queryFn: () => usageApi.getTenantQuotaSummary(),
    enabled: false,
  })
  const payload = quotaQuery.data ?? ({
    message: '点击刷新查看租户配额总览',
  } satisfies Record<string, string>)
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
            租户配额总览
          </h2>
          <p className="mt-1 text-[13px] leading-5 text-slate-500">
            当前 tenant quota API
            的原始结果，用于管理员核对不同配额维度是否与聊天用量一致。
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
          刷新租户配额
        </Button>
      </div>

      <div className="border-t border-slate-200 px-5 pb-5 pt-0">
        <div className="relative mt-4 overflow-hidden rounded-xl border border-slate-200 bg-slate-50/60">
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
      </div>
    </Panel>
  )
}
