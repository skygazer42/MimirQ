'use client'

import { useMemo, useState, type ReactNode } from 'react'
import { Download, Loader2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Switch } from '@/components/ui/switch'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { auditApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function stamp() {
  return new Date().toISOString().replace(/[:.]/g, '-')
}

export function AuditRetentionPanel() {
  const [action, setAction] = useState('')
  const [actorId, setActorId] = useState('')
  const [requestId, setRequestId] = useState('')
  const [retentionDays, setRetentionDays] = useState(90)
  const [maxDelete, setMaxDelete] = useState(1000)
  const [dryRun, setDryRun] = useState(true)
  const [includeSensitive, setIncludeSensitive] = useState(false)
  const [gzip, setGzip] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  const filters = useMemo(
    () => ({
      action: action.trim() || undefined,
      actor_id: actorId.trim() || undefined,
      request_id: requestId.trim() || undefined,
    }),
    [action, actorId, requestId]
  )

  async function exportLogs() {
    setBusy('export')
    try {
      const blob = await auditApi.exportLogs({
        ...filters,
        limit: 10_000,
        include_sensitive: includeSensitive,
        gzip,
      })
      downloadBlob(blob, `audit-logs.${stamp()}.ndjson${gzip ? '.gz' : ''}`)
      setResult({ title: '导出审计日志', payload: { bytes: blob.size, include_sensitive: includeSensitive, gzip } })
      toast.success('导出审计日志完成')
    } catch (error) {
      toast.error(formatApiError(error, '导出审计日志失败'))
    } finally {
      setBusy(null)
    }
  }

  async function purgeLogs() {
    setBusy('purge')
    try {
      const payload = await auditApi.purgeLogs({
        retention_days: retentionDays,
        max_delete: maxDelete,
        dry_run: dryRun,
      })
      setResult({ title: dryRun ? '清理审计日志预演' : '清理审计日志', payload })
      toast.success(dryRun ? '清理审计日志 Dry-run 完成' : '清理审计日志完成')
    } catch (error) {
      toast.error(formatApiError(error, '清理审计日志失败'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel padding="md" className="mt-3 border-border/70 bg-card/95">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">审计导出与保留策略</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            将审计日志导出和保留期清理从纯 API 能力产品化到审计页面；清理默认 dry-run，避免误删。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" className="h-8 gap-1.5 rounded-lg text-xs" disabled={Boolean(busy)} onClick={() => detachPromise(exportLogs())}>
            {busy === 'export' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Download className="h-3.5 w-3.5" />}
            导出审计日志
          </Button>
          <Button size="sm" variant="outline" className="h-8 gap-1.5 rounded-lg text-xs" disabled={Boolean(busy)} onClick={() => detachPromise(purgeLogs())}>
            {busy === 'purge' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Trash2 className="h-3.5 w-3.5" />}
            清理审计日志
          </Button>
        </div>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-3 xl:grid-cols-5">
        <Field label="操作类型">
          <Input value={action} onChange={(event) => setAction(event.target.value)} className="h-8 text-xs" placeholder="可选" />
        </Field>
        <Field label="保留天数">
          <Input value={String(retentionDays)} onChange={(event) => setRetentionDays(Number.parseInt(event.target.value || '0', 10) || 90)} className="h-8 text-xs" inputMode="numeric" />
        </Field>
        <Field label="最多清理">
          <Input value={String(maxDelete)} onChange={(event) => setMaxDelete(Number.parseInt(event.target.value || '0', 10) || 1000)} className="h-8 text-xs" inputMode="numeric" />
        </Field>
        <div className="flex items-end gap-3">
          <Toggle label="仅预演" checked={dryRun} onCheckedChange={setDryRun} />
          <Toggle label="gzip" checked={gzip} onCheckedChange={setGzip} />
          <Toggle label="敏感" checked={includeSensitive} onCheckedChange={setIncludeSensitive} />
        </div>
      </div>

      <details className="mt-3 rounded-lg border border-border/60 bg-background/70 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-foreground">高级筛选（可选）</summary>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">仅在按操作者或请求链路定位审计记录时填写。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <Field label="操作者">
            <Input value={actorId} onChange={(event) => setActorId(event.target.value)} className="h-8 text-xs" placeholder="可选" />
          </Field>
          <Field label="请求编号">
            <Input value={requestId} onChange={(event) => setRequestId(event.target.value)} className="h-8 text-xs" placeholder="可选" />
          </Field>
        </div>
      </details>

      <OperationResultPanel className="mt-3" title="审计操作结果" result={result} emptyMessage="导出或清理后，这里展示执行摘要；原始响应默认收起。" />
    </Panel>
  )
}

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

function Toggle({
  label,
  checked,
  onCheckedChange,
}: Readonly<{
  label: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}>) {
  return (
    <label className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
      {label}
    </label>
  )
}
