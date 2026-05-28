'use client'

import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  Download,
  Loader2,
  Settings2,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { auditApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import {
  TENANT_PERMISSIONS,
  tenantAccessAllows,
} from '@/lib/tenant-permissions'
import { cn, detachPromise } from '@/lib/utils'

export type AuditOperationFilters = {
  actor_id?: string
  action?: string
  resource_type?: string
  resource_id?: string
  request_id?: string
  since?: string
  until?: string
}

type PurgeScope = 'retention' | 'filtered'
type ResultKind = 'export' | 'purge'

type OperationResult = {
  kind: ResultKind
  title: string
  payload: unknown
}

const FILTER_LABELS: Record<string, string> = {
  actor_id: '操作者',
  action: '动作',
  resource_type: '资源类型',
  resource_id: '资源 ID',
  request_id: '请求 ID',
  since: '开始时间',
  until: '结束时间',
}
const AUDIT_RETENTION_PANEL_CLASS =
  'mt-4 overflow-hidden rounded-2xl border border-border/60 bg-card/82 shadow-[0_14px_34px_hsl(var(--primary)/0.05)]'
const AUDIT_RETENTION_HEADER_CLASS =
  'flex flex-col gap-3 border-b border-border/50 bg-[linear-gradient(90deg,hsl(var(--card)/0.88),hsl(var(--primary)/0.05),hsl(var(--card)/0.88))] px-4 py-3 lg:flex-row lg:items-center lg:justify-between'
const AUDIT_RETENTION_PILL_CLASS =
  'rounded-full border border-border/60 bg-background/72 px-2.5 py-1 text-[11px] font-semibold text-muted-foreground'

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

function payloadNumber(payload: unknown, key: string) {
  if (!payload || typeof payload !== 'object') return 0
  const raw = (payload as Record<string, unknown>)[key]
  const value = Number(raw)
  return Number.isFinite(value) ? value : 0
}

function payloadString(payload: unknown, key: string) {
  if (!payload || typeof payload !== 'object') return ''
  const raw = (payload as Record<string, unknown>)[key]
  return typeof raw === 'string' ? raw : ''
}

export function AuditRetentionPanel({
  filters = {},
  activeFilterCount = 0,
  total,
  onAfterPurge,
}: Readonly<{
  filters?: AuditOperationFilters
  activeFilterCount?: number
  total?: number
  onAfterPurge?: () => void
}>) {
  const t = useTranslations('AuditPage.retention')
  const [retentionDays, setRetentionDays] = useState(90)
  const [maxDelete, setMaxDelete] = useState(1000)
  const [dryRun, setDryRun] = useState(true)
  const [purgeScope, setPurgeScope] = useState<PurgeScope>('retention')
  const [includeSensitive, setIncludeSensitive] = useState(false)
  const [gzip, setGzip] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<OperationResult | null>(null)
  const tenantAccess = useTenantAccess()
  const canManageAudit = tenantAccessAllows(
    tenantAccess.data,
    TENANT_PERMISSIONS.AUDIT_MANAGE
  )

  const exportFilters = useMemo(() => {
    const out: AuditOperationFilters = {}
    for (const [key, value] of Object.entries(filters || {})) {
      const trimmed = String(value || '').trim()
      if (trimmed) out[key as keyof AuditOperationFilters] = trimmed
    }
    return out
  }, [filters])

  const filterEntries = Object.entries(exportFilters)
  const filterCount = filterEntries.length || activeFilterCount
  const hasFilterScope = filterEntries.length > 0
  const canRunPurge =
    canManageAudit && (purgeScope === 'retention' || hasFilterScope)

  async function exportLogs() {
    setBusy('export')
    try {
      const blob = await auditApi.exportLogs({
        ...exportFilters,
        limit: 10_000,
        include_sensitive: includeSensitive,
        gzip,
      })
      downloadBlob(blob, `audit-logs.${stamp()}.ndjson${gzip ? '.gz' : ''}`)
      setResult({
        kind: 'export',
        title: t('export'),
        payload: {
          bytes: blob.size,
          include_sensitive: includeSensitive,
          gzip,
          filters: exportFilters,
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
    if (purgeScope === 'filtered' && !hasFilterScope) {
      toast.error('请先设置至少一个筛选条件')
      return
    }

    setBusy('purge')
    try {
      const payload = await auditApi.purgeLogs({
        ...(purgeScope === 'filtered' ? exportFilters : {}),
        purge_scope: purgeScope,
        retention_days: retentionDays,
        max_delete: maxDelete,
        dry_run: dryRun,
      })
      setResult({
        kind: 'purge',
        title: dryRun ? '清理预演' : t('purge'),
        payload,
      })
      toast.success(dryRun ? '预演完成' : '清理完成')
      if (!dryRun) onAfterPurge?.()
    } catch (error) {
      toast.error(formatApiError(error, '清理失败'))
    } finally {
      setBusy(null)
    }
  }

  const purgeDisabled = Boolean(busy) || !canRunPurge
  const confirmDescription =
    purgeScope === 'filtered'
      ? `将真实删除当前筛选命中的审计日志，最多 ${maxDelete} 条。请确认筛选范围无误。`
      : `将真实删除当前租户中早于 ${retentionDays} 天的审计日志，最多 ${maxDelete} 条。`

  return (
    <div className={AUDIT_RETENTION_PANEL_CLASS}>
      <div className={AUDIT_RETENTION_HEADER_CLASS}>
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
            <Settings2 className="size-5" />
          </div>
          <div className="min-w-0">
            <div className="text-[13px] font-black text-foreground">
              {t('title')}
            </div>
            <p className="mt-1 max-w-[720px] text-[11px] font-medium leading-relaxed text-muted-foreground">
              保留策略清旧日志；当前筛选只清上方筛选命中的日志。默认预演，不会直接删除。
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={AUDIT_RETENTION_PILL_CLASS}>
            当前结果 {typeof total === 'number' ? total : '-'} 条
          </span>
          <span className="rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-[11px] font-semibold text-primary">
            筛选 {filterCount} 项
          </span>
        </div>
      </div>

      <div className="grid gap-3 px-4 py-3 lg:grid-cols-[1.15fr_1fr_1.2fr]">
        <ControlBlock label="清理范围">
          <div className="grid grid-cols-2 gap-1 rounded-xl border border-border/60 bg-muted/35 p-1">
            <SegmentButton
              active={purgeScope === 'retention'}
              label="保留策略"
              onClick={() => setPurgeScope('retention')}
            />
            <SegmentButton
              active={purgeScope === 'filtered'}
              label="当前筛选"
              onClick={() => setPurgeScope('filtered')}
            />
          </div>
        </ControlBlock>

        <ControlBlock label="执行模式">
          <div className="grid grid-cols-2 gap-1 rounded-xl border border-border/60 bg-muted/35 p-1">
            <SegmentButton
              active={dryRun}
              label="预演"
              onClick={() => setDryRun(true)}
            />
            <SegmentButton
              active={!dryRun}
              label="真实清理"
              tone="danger"
              onClick={() => setDryRun(false)}
            />
          </div>
        </ControlBlock>

        <ControlBlock label="导出选项">
          <div className="flex min-h-9 flex-wrap items-center gap-3">
            <Toggle label={t('gzip')} checked={gzip} onCheckedChange={setGzip} />
            <Toggle
              label={t('includeSensitive')}
              checked={includeSensitive}
              onCheckedChange={setIncludeSensitive}
            />
          </div>
        </ControlBlock>
      </div>

      <div className="grid gap-3 border-t border-border/50 px-4 py-3 lg:grid-cols-[minmax(0,1fr)_160px_160px_auto] lg:items-end">
        <div className="rounded-xl border border-border/60 bg-muted/32 px-3 py-2 text-[11px] font-medium leading-relaxed text-muted-foreground">
          {purgeScope === 'retention' ? (
            <>
              <span className="font-black text-foreground">保留策略：</span>
              只清理早于 {retentionDays} 天的旧审计日志。若预演为 0，
              说明当前结果仍在保留期内。
            </>
          ) : hasFilterScope ? (
            <>
              <span className="font-black text-foreground">当前筛选：</span>
              将范围限制在上方 {filterEntries.length} 个筛选条件内，
              适合清理测试/回放产生的噪声日志。
            </>
          ) : (
            <span className="inline-flex items-center gap-2 font-bold text-warning">
              <AlertTriangle className="size-3.5" />
              当前筛选清理需要先设置动作、操作者、请求、资源或时间范围。
            </span>
          )}
        </div>

        <NumberField
          label={t('days')}
          value={retentionDays}
          disabled={purgeScope === 'filtered'}
          onChange={setRetentionDays}
        />
        <NumberField
          label={t('maxDelete')}
          value={maxDelete}
          onChange={setMaxDelete}
        />

        <div className="flex flex-wrap gap-2 lg:justify-end">
          <Button
            size="sm"
            variant="outline"
            className="h-9 gap-2 rounded-xl border-primary/20 bg-primary/10 text-[11px] font-bold text-primary hover:bg-primary/15 hover:text-primary"
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
          {dryRun ? (
            <PurgeButton
              busy={busy === 'purge'}
              disabled={purgeDisabled}
              label="预演清理"
              onClick={() => detachPromise(purgeLogs())}
            />
          ) : (
            <ConfirmDialog
              title="确认清理审计日志"
              description={confirmDescription}
              confirmLabel="确认清理"
              confirmVariant="destructive"
              confirmDisabled={purgeDisabled}
              onConfirm={purgeLogs}
            >
              <PurgeButton
                busy={busy === 'purge'}
                disabled={purgeDisabled}
                label="确认清理"
              />
            </ConfirmDialog>
          )}
        </div>
      </div>

      {purgeScope === 'filtered' && hasFilterScope && (
        <div className="mx-4 mb-3 flex flex-wrap gap-1.5 rounded-xl border border-primary/20 bg-primary/[0.07] p-2">
          {filterEntries.map(([key, value]) => (
            <span
              key={key}
              className="rounded-full border border-primary/20 bg-card/80 px-2 py-1 font-mono text-[10px] font-semibold text-primary"
            >
              {FILTER_LABELS[key] || key}: {String(value)}
            </span>
          ))}
        </div>
      )}

      {!canManageAudit && (
        <div className="mx-4 mb-3 rounded-xl border border-warning/20 bg-warning/10 px-3 py-2 text-[11px] font-semibold text-warning">
          清理需要 audit.manage 权限；当前权限可查看和导出审计日志。
        </div>
      )}

      {result && <AuditResultStrip result={result} />}
    </div>
  )
}

function ControlBlock({
  label,
  children,
}: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="space-y-1.5">
      <div className="text-[10px] font-black uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </div>
      {children}
    </div>
  )
}

function SegmentButton({
  active,
  label,
  tone = 'primary',
  onClick,
}: Readonly<{
  active: boolean
  label: string
  tone?: 'primary' | 'danger'
  onClick: () => void
}>) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cn(
        'h-8 rounded-lg px-3 text-[11px] font-black transition-colors',
        active &&
          tone === 'primary' &&
          'bg-primary text-primary-foreground shadow-sm shadow-[0_10px_22px_hsl(var(--primary)/0.16)]',
        active &&
          tone === 'danger' &&
          'bg-destructive text-destructive-foreground shadow-sm shadow-[0_10px_22px_hsl(var(--destructive)/0.16)]',
        !active &&
          'bg-transparent text-muted-foreground hover:bg-background/70 hover:text-foreground'
      )}
      onClick={onClick}
    >
      {label}
    </button>
  )
}

function NumberField({
  label,
  value,
  disabled,
  onChange,
}: Readonly<{
  label: string
  value: number
  disabled?: boolean
  onChange: (value: number) => void
}>) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[10px] font-black uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </Label>
      <Input
        value={String(value)}
        disabled={disabled}
        onChange={(event) =>
          onChange(Number.parseInt(event.target.value || '0', 10) || value)
        }
        className="h-9 rounded-xl border-border/60 bg-background/72 text-xs font-bold disabled:bg-muted disabled:text-muted-foreground"
        inputMode="numeric"
      />
    </div>
  )
}

function PurgeButton({
  busy,
  disabled,
  label,
  onClick,
}: Readonly<{
  busy: boolean
  disabled: boolean
  label: string
  onClick?: () => void
}>) {
  return (
    <Button
      size="sm"
      variant="outline"
      className="h-9 gap-2 rounded-xl border-destructive/20 bg-destructive/10 text-[11px] font-bold text-destructive hover:bg-destructive/15 hover:text-destructive disabled:bg-muted disabled:text-muted-foreground"
      disabled={disabled}
      onClick={onClick}
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <Trash2 className="h-3.5 w-3.5" />
      )}
      {label}
    </Button>
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
    <label className="flex cursor-pointer select-none items-center gap-2">
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        className={checked ? 'bg-primary' : 'bg-muted'}
      />
      <span className="text-[11px] font-bold text-muted-foreground">{label}</span>
    </label>
  )
}

function AuditResultStrip({ result }: Readonly<{ result: OperationResult }>) {
  if (result.kind === 'export') {
    const bytes = payloadNumber(result.payload, 'bytes')
    const gzip = Boolean(
      result.payload &&
        typeof result.payload === 'object' &&
        (result.payload as Record<string, unknown>).gzip
    )
    return (
      <ResultShell result={result}>
        导出文件 {bytes.toLocaleString()} Bytes · {gzip ? 'gzip 传输' : 'NDJSON'}
      </ResultShell>
    )
  }

  const eligible = payloadNumber(result.payload, 'eligible')
  const deleted = payloadNumber(result.payload, 'deleted')
  const scope = payloadString(result.payload, 'scope')
  const dryRun = Boolean(
    result.payload &&
      typeof result.payload === 'object' &&
      (result.payload as Record<string, unknown>).dry_run
  )

  return (
    <ResultShell result={result}>
      {scope === 'filtered' ? '当前筛选' : '保留策略'} ·
      可清理 {eligible.toLocaleString()} 条 · 已删除{' '}
      {deleted.toLocaleString()} 条 · {dryRun ? '预演' : '已执行'}
    </ResultShell>
  )
}

function ResultShell({
  result,
  children,
}: Readonly<{ result: OperationResult; children: React.ReactNode }>) {
  return (
    <div className="mx-4 mb-4 rounded-xl border border-success/20 bg-success/10 px-3 py-2 text-[11px] text-success">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-black">
          <ShieldCheck className="size-3.5" />
          {result.title}
        </div>
        <div className="font-semibold">{children}</div>
      </div>
      <details className="mt-2">
        <summary className="cursor-pointer text-[10px] font-bold uppercase tracking-[0.12em] text-success/70 hover:text-success">
          原始 JSON
        </summary>
        <pre className="mt-2 max-h-44 overflow-auto rounded-lg bg-background/70 p-2 text-[10px] leading-relaxed text-foreground">
          {JSON.stringify(result.payload, null, 2)}
        </pre>
      </details>
    </div>
  )
}
