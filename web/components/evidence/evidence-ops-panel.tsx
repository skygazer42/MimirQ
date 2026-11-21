'use client'
import { useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Download, PackageCheck, ShieldCheck } from '@/components/icons'
import type { PlatformIcon } from '@/components/icons'
import { toast } from 'sonner'
import { z } from 'zod'
import { LoadingButton } from '@/components/ui/loading-button'
import { Input } from '@/components/ui/input'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { Textarea } from '@/components/ui/textarea'
import { DatasetSelectField } from '@/components/ops/dataset-select-field'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { evidenceApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { downloadBlob } from '@/lib/download'

const capsulePayloadSchema = z.looseObject({
  capsule: z.record(z.string(), z.unknown()),
  capsule_id: z.string().nullish(),
  overwrite: z.boolean().optional(),
})

function parsePayload(raw: string): Record<string, unknown> {
  const payload: unknown = JSON.parse(raw)
  return z.record(z.string(), z.unknown()).parse(payload)
}

export function EvidenceOpsPanel() {
  const [datasetId, setDatasetId] = useState('')
  const [suiteId, setSuiteId] = useState('')
  const [itemId, setItemId] = useState('')
  const [capsuleId, setCapsuleId] = useState('')
  const [payloadJson, setPayloadJson] = useState(
    '{\n  "capsule": {\n    "schema": "mimirq.evidence_capsule.v1",\n    "claims": []\n  }\n}',
  )
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  const suite = suiteId.trim()
  const item = itemId.trim()
  const capsule = capsuleId.trim()

  const [actionError, setActionError] = useState<{ scope: 'dataset' | 'advanced'; message: string } | null>(null)

  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const activeOperation = useRef<object | null>(null)
  useLayoutEffect(() => {
    activeOperation.current = null
    setBusy(null)
    setActionError(null)
    setResult(null)
    return () => {
      activeOperation.current = null
    }
  }, [datasetId, suiteId, itemId, capsuleId, payloadJson, sessionKey])

  async function runAction<T>(
    key: string,
    title: string,
    action: () => Promise<T>,
    commit?: (response: T) => { payload: unknown; message: string; warning?: true },
  ) {
    if (activeOperation.current !== null) return
    const operation = {}
    activeOperation.current = operation
    setBusy(key)
    setActionError(null)
    setResult(null)
    const isCurrent = () => activeOperation.current === operation && getAuthSessionKey() === sessionKey
    try {
      const response = await action()
      if (!isCurrent()) return
      const outcome = commit === undefined ? { payload: response, message: `${title}完成` } : commit(response)
      setResult({ title, payload: outcome.payload })
      if (outcome.warning) toast.warning(outcome.message)
      else toast.success(outcome.message)
    } catch (error: unknown) {
      if (isCurrent()) {
        setActionError({
          scope: key === 'dataset-drift' || key === 'training-export' ? 'dataset' : 'advanced',
          message: formatApiError(error, `${title}失败`),
        })
      }
    } finally {
      if (isCurrent()) {
        activeOperation.current = null
        setBusy(null)
      }
    }
  }

  return (
    <fieldset disabled={busy !== null} className="space-y-4">
      <legend className="sr-only">Evidence 管理操作</legend>
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">Evidence 管理操作</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            围绕选中数据集完成证据漂移审计与训练集导出；suite/item/capsule 维护放在高级参数中。
          </p>
        </div>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-end">
        <DatasetSelectField value={datasetId} onChange={setDatasetId} />
        <ActionButton
          icon={ShieldCheck}
          busy={busy === 'dataset-drift'}
          disabled={datasetId === ''}
          label="数据集 Drift"
          onClick={() =>
            runAction('dataset-drift', '数据集 Drift Audit', () =>
              evidenceApi.getDatasetDriftAudit(datasetId, { include_details: true, details_limit: 20 }),
            )
          }
        />
        <ActionButton
          icon={Download}
          busy={busy === 'training-export'}
          disabled={datasetId === ''}
          label="导出训练集"
          onClick={() =>
            runAction(
              'training-export',
              '导出训练集',
              () =>
                evidenceApi.exportTrainingDataset({
                  dataset_id: datasetId,
                  format: 'jsonl',
                  include_feedback: true,
                  include_evidence: true,
                }),
              (blob) => {
                downloadBlob(`evidence-training.${datasetId.slice(0, 8)}.jsonl`, blob)
                return { payload: { bytes: blob.size, type: blob.type }, message: '训练集下载已开始' }
              },
            )
          }
        />
      </div>

      {actionError?.scope === 'dataset' ? <WorkspaceNotice>{actionError.message}</WorkspaceNotice> : null}

      <details className="mt-3 rounded-lg border border-border/60 bg-background/70 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-foreground">高级参数（可选）</summary>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          仅在需要修复引用、Patch suite/item 或处理 Evidence Capsule 时填写。
        </p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Field label="Suite 标识">
            <Input
              value={suiteId}
              onChange={(event) => setSuiteId(event.target.value)}
              className="h-8 font-mono text-xs"
            />
          </Field>
          <Field label="Item 标识">
            <Input
              value={itemId}
              onChange={(event) => setItemId(event.target.value)}
              className="h-8 font-mono text-xs"
            />
          </Field>
          <Field label="Capsule 标识">
            <Input
              value={capsuleId}
              onChange={(event) => setCapsuleId(event.target.value)}
              className="h-8 font-mono text-xs"
            />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <ActionButton
            icon={ShieldCheck}
            busy={busy === 'repair'}
            disabled={suite === ''}
            label="修复引用"
            onClick={() =>
              runAction(
                'repair',
                'Suite 引用修复',
                () => evidenceApi.repairSuiteReferenceSources(suite, parsePayload(payloadJson)),
                (report) => ({ payload: report, message: report.applied ? '已应用引用修复' : '引用修复预检完成' }),
              )
            }
          />
          <ActionButton
            icon={ShieldCheck}
            busy={busy === 'patch-suite'}
            disabled={suite === ''}
            label="Patch Suite"
            onClick={() =>
              runAction('patch-suite', 'Patch Evidence Suite', () =>
                evidenceApi.patchSuite(suite, parsePayload(payloadJson)),
              )
            }
          />
          <ActionButton
            icon={ShieldCheck}
            busy={busy === 'patch-item'}
            disabled={item === ''}
            label="Patch Item"
            onClick={() =>
              runAction('patch-item', 'Patch Evidence Item', () =>
                evidenceApi.patchItem(item, parsePayload(payloadJson)),
              )
            }
          />
          <ActionButton
            icon={PackageCheck}
            busy={busy === 'persist'}
            label="保存 Capsule"
            onClick={() =>
              runAction('persist', '保存 Evidence Capsule', () =>
                evidenceApi.persistCapsule(capsulePayloadSchema.parse(JSON.parse(payloadJson))),
              )
            }
          />
          <ActionButton
            icon={PackageCheck}
            busy={busy === 'get-capsule'}
            disabled={capsule === ''}
            label="读取 Capsule"
            onClick={() => runAction('get-capsule', '读取 Evidence Capsule', () => evidenceApi.getCapsule(capsule))}
          />
          <ActionButton
            icon={PackageCheck}
            busy={busy === 'verify'}
            label="校验 Capsule"
            onClick={() =>
              runAction(
                'verify',
                '校验 Evidence Capsule',
                () => evidenceApi.verifyCapsule(capsulePayloadSchema.parse(JSON.parse(payloadJson))),
                (report) =>
                  report.valid
                    ? { payload: report, message: 'Capsule 校验通过' }
                    : { payload: report, message: `Capsule 校验未通过（${report.reason}）`, warning: true },
              )
            }
          />
        </div>
        {actionError?.scope === 'advanced' ? <WorkspaceNotice>{actionError.message}</WorkspaceNotice> : null}
        <Field label="高级载荷（JSON）">
          <Textarea
            value={payloadJson}
            onChange={(event) => setPayloadJson(event.target.value)}
            className="mt-3 min-h-[140px] font-mono text-xs"
          />
        </Field>
      </details>

      <OperationResultPanel
        className="mt-3"
        title="Evidence 操作结果"
        result={result}
        emptyMessage="选择上方操作后，这里展示执行摘要；原始响应默认收起。"
      />
    </fieldset>
  )
}

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <label className="block space-y-2 text-[13px]">
      <span className="font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
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
  disabled?: boolean
  icon: PlatformIcon
  label: string
  onClick: () => Promise<void>
}>) {
  return (
    <LoadingButton
      loading={busy}
      variant="outline"
      className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold"
      disabled={disabled}
      onClick={onClick}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </LoadingButton>
  )
}
