'use client'

import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Database, FileClock, Trash2 } from '@/components/icons'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { LoadingButton } from '@/components/ui/loading-button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DatasetSelectField } from '@/components/ops/dataset-select-field'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { DangerZonePanel } from '@/components/settings/danger-zone-panel'
import { settingsTextTokens } from '@/components/ui/system-page-tokens'
import { chunkPresetApi, governanceApi } from '@/lib/api/governance'
import { formatApiError } from '@/lib/api-errors'
import { boundedNumberDraft } from '@/lib/number-draft-schema'
import { cn } from '@/lib/utils'

const REVIEW_MODES = [
  { value: 'overdue', label: '已过期' },
  { value: 'due_soon', label: '即将到期' },
  { value: 'all', label: '全部' },
] as const
const reviewWindowSchema = boundedNumberDraft('到期窗口', 0, 365).refine(Number.isInteger, '到期窗口必须是整数')

export function GovernanceOpsPanel() {
  const fieldId = useId()
  const [datasetId, setDatasetId] = useState('')
  const [presetId, setPresetId] = useState('')
  const [mode, setMode] = useState<(typeof REVIEW_MODES)[number]['value']>('overdue')
  const [dueWithinDays, setDueWithinDays] = useState('14')
  const [isReading, setIsReading] = useState(false)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)
  const reviewRequest = useRef<AbortController | null>(null)
  const reviewWindow = reviewWindowSchema.safeParse(dueWithinDays)
  const canRead = datasetId !== '' && reviewWindow.success
  const targetPresetId = presetId.trim()

  useEffect(
    () => () => {
      reviewRequest.current?.abort()
      reviewRequest.current = null
    },
    [],
  )

  async function loadReviewDocuments() {
    if (!canRead || reviewRequest.current !== null) return
    const controller = new AbortController()
    reviewRequest.current = controller
    setIsReading(true)
    try {
      const payload = await governanceApi.listStaleDocumentsByDataset(
        datasetId,
        { mode, due_within_days: reviewWindow.data, limit: 50 },
        { signal: controller.signal },
      )
      if (controller.signal.aborted) return
      setResult({ title: '待复核文档', payload })
      toast.success('待复核文档查询完成')
    } catch (error) {
      if (!controller.signal.aborted) toast.error(formatApiError(error, '查询待复核文档失败'))
    } finally {
      if (reviewRequest.current === controller) {
        reviewRequest.current = null
        setIsReading(false)
      }
    }
  }

  return (
    <section className="border-t border-border/60 pt-5">
      <h3 className={cn(settingsTextTokens.panelTitle, 'flex items-center gap-2')}>
        <Database className="size-4 text-muted-foreground" />
        文档复核
      </h3>
      <p className="mt-1 text-[13px] leading-5 text-muted-foreground">按数据集查询待复核或已过期的文档。</p>

      <fieldset
        disabled={isReading}
        className="mt-4 grid min-w-0 items-end gap-3 md:grid-cols-2 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,0.8fr)_minmax(0,0.7fr)_auto]"
      >
        <legend className="sr-only">查询待复核文档</legend>
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
        <Field id={`${fieldId}-mode`} label="复核范围">
          <Select
            value={mode}
            onValueChange={(value) => {
              const option = REVIEW_MODES.find((entry) => entry.value === value)
              if (option !== undefined) setMode(option.value)
            }}
          >
            <SelectTrigger id={`${fieldId}-mode`} className="h-11 text-[13px] sm:h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {REVIEW_MODES.map(({ value, label }) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field id={`${fieldId}-window`} label="到期窗口（天）">
          <Input
            id={`${fieldId}-window`}
            aria-invalid={!reviewWindow.success}
            aria-describedby={reviewWindow.success ? undefined : `${fieldId}-window-error`}
            value={dueWithinDays}
            onChange={(event) => setDueWithinDays(event.target.value)}
            className="h-11 text-[13px] sm:h-9"
            inputMode="numeric"
          />
          {!reviewWindow.success && (
            <p id={`${fieldId}-window-error`} className="text-xs text-destructive">
              请输入 0 到 365 的整数。
            </p>
          )}
        </Field>
        <LoadingButton
          variant="secondary"
          className="h-11 gap-2 px-3 text-[13px] sm:h-9"
          loading={isReading}
          disabled={!canRead}
          onClick={() => void loadReviewDocuments()}
        >
          <FileClock className="h-3.5 w-3.5" />
          查询待复核文档
        </LoadingButton>
      </fieldset>

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
          <Field id={`${fieldId}-preset`} label="切块预设 ID">
            <Input
              id={`${fieldId}-preset`}
              value={presetId}
              onChange={(event) => setPresetId(event.target.value)}
              className="h-11 font-mono text-[13px] sm:h-9"
            />
          </Field>
          <ConfirmDialog
            title="删除切块预设？"
            description={`将删除切块预设 ${targetPresetId}。如果数据集仍引用该预设，后续策略可能需要重新配置。`}
            confirmLabel="确认删除"
            onConfirm={async () => {
              await chunkPresetApi.delete(targetPresetId)
              setResult({ title: '删除切块预设', payload: { preset_id: targetPresetId, deleted: true } })
              toast.success('删除切块预设完成')
            }}
          >
            <Button
              variant="outline"
              className="h-11 gap-2 px-3 text-[13px] sm:h-9"
              disabled={isReading || targetPresetId === ''}
            >
              <Trash2 className="h-3.5 w-3.5" />
              删除切块预设
            </Button>
          </ConfirmDialog>
        </div>
      </DangerZonePanel>

      {result ? (
        <OperationResultPanel className="mt-3" title="治理运维结果" result={result} emptyMessage="尚无复核结果。" />
      ) : null}
    </section>
  )
}

function Field({ id, label, children }: Readonly<{ id: string; label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className={settingsTextTokens.fieldLabel}>
        {label}
      </Label>
      {children}
    </div>
  )
}
