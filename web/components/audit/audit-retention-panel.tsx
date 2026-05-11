'use client'

import { useMemo, useState, type ReactNode } from 'react'
import {
  ChevronDown,
  Download,
  Loader2,
  Trash2,
  Zap,
  Settings2,
} from 'lucide-react'
import { toast } from 'sonner'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Switch } from '@/components/ui/switch'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { auditApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'
import { cn } from '@/lib/utils'

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
  const t = useTranslations('AuditPage.retention')
  const [action, setAction] = useState('')
  const [actorId, setActorId] = useState('')
  const [requestId, setRequestId] = useState('')
  const [retentionDays, setRetentionDays] = useState(90)
  const [maxDelete, setMaxDelete] = useState(1000)
  const [dryRun, setDryRun] = useState(true)
  const [includeSensitive, setIncludeSensitive] = useState(false)
  const [gzip, setGzip] = useState(true)
  const [softDelete, setSoftDelete] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{
    title: string
    payload: unknown
  } | null>(null)

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
      setResult({
        title: t('export'),
        payload: {
          bytes: blob.size,
          include_sensitive: includeSensitive,
          gzip,
        },
      })
      toast.success('导出完成')
    } catch (error) {
      toast.error(formatApiError(error, '导出失败'))
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
      setResult({
        title: dryRun ? `${t('purge')} (预演)` : t('purge'),
        payload,
      })
      toast.success(dryRun ? '预演完成' : '清理完成')
    } catch (error) {
      toast.error(formatApiError(error, '清理失败'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel
      padding="md"
      className="mt-6 border-slate-200 bg-card shadow-sm overflow-hidden rounded-2xl"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between border-b border-slate-50 pb-4 mb-4">
        <div className="flex items-start gap-3">
          <div className="size-10 rounded-xl bg-blue-50 flex items-center justify-center text-blue-600 shrink-0 border border-blue-100/50 shadow-inner">
            <Settings2 className="size-5" />
          </div>
          <div>
            <div className="text-[14px] font-black text-slate-900">
              {t('title')}
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500 font-medium max-w-2xl">
              {t('description')}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-8 gap-2 rounded-lg text-[11px] font-bold border-slate-200"
            disabled={Boolean(busy)}
            onClick={() => detachPromise(exportLogs())}
          >
            {busy === 'export' ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            {t('export')}
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-8 gap-2 rounded-lg text-[11px] font-bold border-slate-200 text-red-600 hover:bg-red-50 hover:text-red-700"
            disabled={Boolean(busy)}
            onClick={() => detachPromise(purgeLogs())}
          >
            {busy === 'purge' ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            {t('purge')}
          </Button>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-3 xl:grid-cols-6">
        <div className="space-y-1.5">
          <Label className="text-[10px] font-black uppercase text-slate-400">
            {t('actionType')}
          </Label>
          <Input
            value={action}
            onChange={(event) => setAction(event.target.value)}
            className="h-9 text-xs rounded-lg border-slate-200 bg-slate-50/50"
            placeholder="可选"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-[10px] font-black uppercase text-slate-400">
            {t('days')}
          </Label>
          <Input
            value={String(retentionDays)}
            onChange={(event) =>
              setRetentionDays(
                Number.parseInt(event.target.value || '0', 10) || 90
              )
            }
            className="h-9 text-xs rounded-lg border-slate-200 bg-slate-50/50"
            inputMode="numeric"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-[10px] font-black uppercase text-slate-400">
            {t('maxDelete')}
          </Label>
          <Input
            value={String(maxDelete)}
            onChange={(event) =>
              setMaxDelete(
                Number.parseInt(event.target.value || '0', 10) || 1000
              )
            }
            className="h-9 text-xs rounded-lg border-slate-200 bg-slate-50/50"
            inputMode="numeric"
          />
        </div>
        <div className="flex items-center gap-4 xl:col-span-3 pt-5">
          <Toggle
            label={t('dryRun')}
            checked={dryRun}
            onCheckedChange={setDryRun}
          />
          <Toggle label={t('gzip')} checked={gzip} onCheckedChange={setGzip} />
          <Toggle
            label={t('softDelete')}
            checked={softDelete}
            onCheckedChange={setSoftDelete}
          />
        </div>
      </div>

      <details className="mt-4 group rounded-xl border border-slate-100 bg-slate-50/30 overflow-hidden">
        <summary className="cursor-pointer px-4 py-2 text-[11px] font-black text-slate-400 uppercase flex items-center gap-2 hover:bg-slate-50 transition-colors">
          <ChevronDown className="size-3 transition-transform group-open:rotate-180" />
          {t('advanced')}
        </summary>
        <div className="p-4 grid gap-4 md:grid-cols-2 bg-card">
          <div className="space-y-1.5">
            <Label className="text-[10px] font-black text-slate-400 uppercase">
              运行名
            </Label>
            <Input
              value={actorId}
              onChange={(event) => setActorId(event.target.value)}
              className="h-8 text-xs rounded-lg border-slate-200"
              placeholder="可选"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-[10px] font-black text-slate-400 uppercase">
              请求追踪号
            </Label>
            <Input
              value={requestId}
              onChange={(event) => setRequestId(event.target.value)}
              className="h-8 text-xs rounded-lg border-slate-200"
              placeholder="可选"
            />
          </div>
        </div>
      </details>

      <OperationResultPanel
        className="mt-4 border-slate-100"
        title={t('operationResult')}
        result={result}
        emptyMessage={t('resultEmpty')}
      />
    </Panel>
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
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
      <span className="text-[11px] font-bold text-slate-600">{label}</span>
    </label>
  )
}
