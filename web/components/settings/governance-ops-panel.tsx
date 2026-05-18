'use client'

import { useState, type ReactNode } from 'react'
import { Database, FileClock, Loader2, Trash2 } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
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
    <Panel padding="md" className="border-border/70 bg-card/95">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className={cn(settingsTextTokens.sectionTitle, 'flex items-center gap-1.5')}>
            <Database className="h-3.5 w-3.5 text-blue-500" />
            数据集复核运维
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            待复核/过期文档是按数据集查询，已自动绑定首个可用数据集，可按需切换。
            切块预设删除不按数据集筛选，放在高级维护里单独确认。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
            {datasetId ? '已绑定数据集' : '等待数据集'}
          </span>
          {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
        </div>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <DatasetSelectField
          value={datasetId}
          onChange={setDatasetId}
          label="绑定数据集"
          placeholder="选择要巡检的数据集"
          autoSelectFirst
          className="md:col-span-2"
        />
        <Field label="复核范围">
          <Select value={mode} onValueChange={(value) => setMode(value as typeof mode)}>
            <SelectTrigger className="h-8 text-xs">
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
          <Input value={String(dueWithinDays)} onChange={(event) => setDueWithinDays(Number.parseInt(event.target.value || '0', 10) || 14)} className="h-8 text-xs" inputMode="numeric" />
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <ActionButton icon={FileClock} busy={busy === 'stale'} disabled={Boolean(busy) || !datasetId.trim()} label="查询待复核文档" onClick={() => runAction('stale', '待复核文档', () => governanceApi.listStaleDocumentsByDataset(datasetId.trim(), { mode, due_within_days: dueWithinDays, limit: 50 }))} />
        <div className="text-[11px] leading-4 text-slate-500/85">
          当前接口：<span className="font-mono">/governance/datasets/{'{dataset_id}'}/stale-documents</span>
        </div>
      </div>

      <DangerZonePanel
        className="mt-3"
        title="切块预设删除"
        impact="不按上方数据集筛选；删除前请确认没有数据集或入库策略继续引用该预设。"
        badge="高级维护"
        compact
        tone="neutral"
        icon="help"
      >
        <p className="text-xs leading-5 text-slate-500">
          这里不跟上方数据集巡检联动；删除前请确认没有数据集或入库策略继续引用该预设。
        </p>
        <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <Field label="切块预设 ID">
            <Input value={presetId} onChange={(event) => setPresetId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <ConfirmDialog
            title="删除切块预设？"
            description={`将删除切块预设 ID=${presetId.trim() || '-'}。如果数据集仍引用该预设，后续策略可能需要重新配置。`}
            confirmLabel="确认删除"
            onConfirm={() => runAction('delete-preset', '删除切块预设', async () => {
              await chunkPresetApi.delete(presetId.trim())
              return { preset_id: presetId.trim(), deleted: true }
            })}
          >
            <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy) || !presetId.trim()}>
              {busy === 'delete-preset' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Trash2 className="h-3.5 w-3.5" />}
              删除切块预设
            </Button>
          </ConfirmDialog>
        </div>
      </DangerZonePanel>

      <OperationResultPanel className="mt-3" title="治理运维结果" result={result} emptyMessage="选择绑定数据集后查询待复核文档；原始响应默认收起。" />
    </Panel>
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
  icon: LucideIcon
  label: string
  onClick: () => Promise<void>
}>) {
  return (
    <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Icon className="h-3.5 w-3.5" />}
      {label}
    </Button>
  )
}
