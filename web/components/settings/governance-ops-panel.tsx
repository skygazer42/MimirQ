'use client'

import { useState, type ReactNode } from 'react'
import { Database, FileClock, Loader2, Trash2 } from '@/components/icons'
import type { PlatformIcon } from '@/components/icons'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DatasetSelectField } from '@/components/ops/dataset-select-field'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { DangerZonePanel } from '@/components/settings/danger-zone-panel'
import { settingsTextTokens } from '@/components/ui/system-page-tokens'
import { chunkPresetApi, governanceApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'

export function GovernanceOpsPanel() {
  const [datasetId, setDatasetId] = useState('')
  const [presetId, setPresetId] = useState('')
  const [mode, setMode] = useState<'overdue' | 'due_soon' | 'all'>('overdue')
  const [dueWithinDays, setDueWithinDays] = useState(14)
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  async function runAction(key: string, title: string, action: () => Promise<unknown>) {
    setBusy(key)
    try {
      const payload = await action()
      setResult({ title, payload })
      toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="border-t border-border/60 pt-5">
      <div>
        <div>
          <h3 className={cn(settingsTextTokens.panelTitle, 'flex items-center gap-2')}>
            <Database className="size-4 text-muted-foreground" />
            文档复核
          </h3>
          <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
            按数据集查询待复核或已过期的文档。
          </p>
        </div>
      </div>

      <div className="mt-4 grid items-end gap-3 md:grid-cols-2 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,0.8fr)_minmax(0,0.7fr)_auto]">
        <DatasetSelectField
          value={datasetId}
          onChange={setDatasetId}
          label="数据集"
          placeholder="选择要复核的数据集"
          autoSelectFirst
          className="min-w-0"
          labelClassName={settingsTextTokens.fieldLabel}
          triggerClassName="h-11 text-[13px] sm:h-9"
        />
        <Field label="复核范围">
          <Select value={mode} onValueChange={(value) => setMode(value as typeof mode)}>
            <SelectTrigger aria-label="复核范围" className="h-11 text-[13px] sm:h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="overdue">已过期</SelectItem>
              <SelectItem value="due_soon">即将到期</SelectItem>
              <SelectItem value="all">全部</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label="到期窗口（天）">
          <Input aria-label="到期窗口（天）" value={String(dueWithinDays)} onChange={(event) => setDueWithinDays(Number.parseInt(event.target.value || '0', 10) || 14)} className="h-11 text-[13px] sm:h-9" inputMode="numeric" />
        </Field>
        <ActionButton icon={FileClock} busy={busy === 'stale'} disabled={Boolean(busy) || !datasetId.trim()} label="查询待复核文档" onClick={() => runAction('stale', '待复核文档', () => governanceApi.listStaleDocumentsByDataset(datasetId.trim(), { mode, due_within_days: dueWithinDays, limit: 50 }))} />
      </div>

      <DangerZonePanel
        className="mt-3"
        title="切块预设删除"
        impact="不按上方数据集筛选；删除前请确认没有数据集或入库策略继续引用该预设"
        badge="高级维护"
        compact
        tone="neutral"
        icon="help"
      >
        <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <Field label="切块预设 ID">
            <Input aria-label="切块预设 ID" value={presetId} onChange={(event) => setPresetId(event.target.value)} className="h-11 font-mono text-[13px] sm:h-9" />
          </Field>
          <ConfirmDialog
            title="删除切块预设？"
            description={`将删除切块预设 ID=${presetId.trim() || '-'}如果数据集仍引用该预设，后续策略可能需要重新配置`}
            confirmLabel="确认删除"
            onConfirm={() => runAction('delete-preset', '删除切块预设', async () => {
              await chunkPresetApi.delete(presetId.trim())
              return { preset_id: presetId.trim(), deleted: true }
            })}
          >
            <Button variant="outline" className="h-11 gap-2 px-3 text-[13px] sm:h-9" disabled={Boolean(busy) || !presetId.trim()}>
              {busy === 'delete-preset' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Trash2 className="h-3.5 w-3.5" />}
              删除切块预设
            </Button>
          </ConfirmDialog>
        </div>
      </DangerZonePanel>

      {result ? <OperationResultPanel className="mt-3" title="治理运维结果" result={result} emptyMessage="尚无复核结果。" /> : null}
    </section>
  )
}

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label className={settingsTextTokens.fieldLabel}>{label}</Label>
      {children}
    </div>
  )
}

function ActionButton({
  busy,
  disabled,
  icon: Icon,
  label,
  onClick,
}: Readonly<{
  busy: boolean
  disabled: boolean
  icon: PlatformIcon
  label: string
  onClick: () => Promise<void>
}>) {
  return (
    <Button variant="secondary" className="h-11 gap-2 px-3 text-[13px] sm:h-9" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Icon className="h-3.5 w-3.5" />}
      {label}
    </Button>
  )
}
