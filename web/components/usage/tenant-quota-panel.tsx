'use client'

import { useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { Textarea } from '@/components/ui/textarea'
import { usageApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'

function prettyJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function TenantQuotaPanel() {
  const [loading, setLoading] = useState(false)
  const [payload, setPayload] = useState<unknown>({ message: '点击刷新查看租户配额总览' })

  async function loadQuota() {
    setLoading(true)
    try {
      const next = await usageApi.getTenantQuotaSummary()
      setPayload(next)
      toast.success('租户配额总览已刷新')
    } catch (error) {
      toast.error(formatApiError(error, '加载租户配额失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Panel padding="md" className="mt-4 border-border/70 bg-card/95">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">租户配额总览</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            展示 tenant quota API 的原始结果，用于管理员核对不同配额维度是否与聊天用量一致。
          </p>
        </div>
        <Button size="sm" variant="outline" className="h-8 gap-1.5 rounded-lg text-xs" disabled={loading} onClick={() => detachPromise(loadQuota())}>
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <RefreshCw className="h-3.5 w-3.5" />}
          刷新租户配额
        </Button>
      </div>
      <Textarea readOnly value={prettyJson(payload)} className="mt-3 min-h-[140px] font-mono text-xs" />
    </Panel>
  )
}
