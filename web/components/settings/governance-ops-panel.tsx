'use client'

import { useState, type ReactNode } from 'react'
import { FileClock, Loader2, Trash2 } from 'lucide-react'
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
import { chunkPresetApi, governanceApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'

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
          <div className="text-sm font-semibold text-foreground">治理运维操作</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            查询数据集待复核/过期文档；Chunk Preset 删除属于高风险维护，默认收进高级参数。
          </p>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <DatasetSelectField value={datasetId} onChange={setDatasetId} />
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

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton icon={FileClock} busy={busy === 'stale'} disabled={Boolean(busy) || !datasetId.trim()} label="Stale 文档" onClick={() => runAction('stale', 'Stale 文档', () => governanceApi.listStaleDocumentsByDataset(datasetId.trim(), { mode, due_within_days: dueWithinDays, limit: 50 }))} />
      </div>

      <details className="mt-3 rounded-lg border border-border/60 bg-background/70 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-foreground">高级参数（可选）</summary>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">仅在确认不再引用某个 Chunk Preset 时使用删除操作。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <Field label="Chunk Preset">
            <Input value={presetId} onChange={(event) => setPresetId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <ConfirmDialog
            title="删除 Chunk Preset？"
            description={`将删除 chunk_preset_id=${presetId.trim() || '-'}。如果数据集仍引用该 preset，后续策略可能需要重新配置。`}
            confirmLabel="删除 Preset"
            onConfirm={() => runAction('delete-preset', '删除 Chunk Preset', async () => {
              await chunkPresetApi.delete(presetId.trim())
              return { preset_id: presetId.trim(), deleted: true }
            })}
          >
            <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy) || !presetId.trim()}>
              {busy === 'delete-preset' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Trash2 className="h-3.5 w-3.5" />}
              删除 Chunk Preset
            </Button>
          </ConfirmDialog>
        </div>
      </details>

      <OperationResultPanel className="mt-3" title="治理运维结果" result={result} emptyMessage="选择上方操作后，这里展示执行摘要；原始响应默认收起。" />
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
