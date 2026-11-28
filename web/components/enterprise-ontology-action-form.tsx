'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { enterpriseOntologyApi } from '@/lib/api/enterprise-ontology'
import type {
  EnterpriseOntologyActionView as ActionView,
  EnterpriseOntologyHeaders,
  OntologyActionProposal,
} from '@/types/enterprise-ontology'
import styles from './enterprise-ontology-published.module.css'

type Run = (action: string, task: () => Promise<void>) => Promise<void>

const field = 'grid min-w-0 gap-1 text-sm'
const scopeFields = 'grid min-w-0 gap-3 md:grid-cols-2'
const status = 'text-sm text-muted-foreground'

const actionStates: Record<string, string> = {
  awaiting_approval: '等待审批',
  ready: '待执行',
  dispatching: '派发中',
  unknown: '结果待核实',
  submitted: '已提交',
  manual_review: '待人工核实',
  succeeded: '已执行',
  failed: '执行失败',
}
const syncStates: Record<string, string> = { pending: '待同步', synced: '已同步', failed: '同步失败' }

export function OntologyActionForm({
  proposal,
  initialRequestId = '',
  edoHeaders,
  run,
}: {
  proposal: OntologyActionProposal
  initialRequestId?: string
  edoHeaders?: EnterpriseOntologyHeaders
  run: Run
}) {
  const { ontology_id: ontologyId, version_id: versionId, action_id: actionId } = proposal
  const [key, setKey] = useState(proposal.key)
  const [parameters, setParameters] = useState(() =>
    Object.fromEntries(Object.entries(proposal.parameters).map(([name, value]) => [name, String(value)])),
  )
  const [requestId, setRequestId] = useState(initialRequestId)
  const [prepared, setPrepared] = useState<ActionView | null>(null)

  function prepare() {
    const id = requestId || globalThis.crypto.randomUUID()
    setRequestId(id)
    void run('预演业务动作', async () => {
      const data = await enterpriseOntologyApi.prepareAction(
        ontologyId,
        versionId,
        actionId,
        {
          request_id: id,
          key,
          parameters: Object.fromEntries(Object.entries(parameters).filter(([, value]) => value.trim())),
        },
        { headers: edoHeaders },
      )
      setPrepared(data)
    })
  }

  function advance(operation: 'approve' | 'execute' | 'receipt', label: string) {
    if (!prepared) return
    void run(label, async () => {
      const data = await enterpriseOntologyApi.advanceAction(ontologyId, versionId, prepared.request_id, operation, {
        headers: edoHeaders,
      })
      setPrepared(data)
    })
  }

  if (prepared) {
    const receipt = prepared.receipt
    return (
      <div className={styles.actionReceipt}>
        <p className={styles.receiptHeading}>
          {proposal.label} ·{' '}
          <span className={styles.statusBadge} data-state={prepared.state}>
            {actionStates[prepared.state]}
          </span>
        </p>
        <p>目标系统 · {proposal.target}</p>
        <p>
          业务主键 ·{' '}
          {Object.entries(prepared.inputs.key)
            .map(([id, value]) => id + '=' + String(value))
            .join('、')}
        </p>
        {Object.keys(prepared.inputs.parameters).length > 0 && (
          <p>
            动作参数 ·{' '}
            {Object.entries(prepared.inputs.parameters)
              .map(([id, value]) => id + '=' + String(value))
              .join('、')}
          </p>
        )}
        <p className="break-all font-mono text-xs text-muted-foreground">请求 ID · {prepared.request_id}</p>
        {prepared.approved_by && <p>已审批 · {prepared.approved_by}</p>}
        {receipt && (
          <p>
            回执 {receipt.receipt_id} · {actionStates[receipt.status]} · {syncStates[receipt.sync_status]}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {prepared.state === 'awaiting_approval' && (
            <Button type="button" variant="outline" onClick={() => advance('approve', '审批动作')}>
              审批动作
            </Button>
          )}
          {prepared.state === 'ready' && (
            <Button type="button" onClick={() => advance('execute', '确认执行业务动作')}>
              确认执行业务动作
            </Button>
          )}
          {(['ready', 'dispatching', 'unknown', 'submitted', 'manual_review'].includes(prepared.state) ||
            receipt?.sync_status === 'pending') && (
            <Button type="button" variant="outline" onClick={() => advance('receipt', '查询动作回执')}>
              查询动作回执
            </Button>
          )}
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setPrepared(null)
            }}
          >
            返回动作输入
          </Button>
        </div>
      </div>
    )
  }

  const keyComplete = Object.keys(proposal.key_fields).every((id) => key[id]?.trim())
  const parametersComplete = Object.entries(proposal.parameter_fields).every(
    ([id, item]) => !item.required || parameters[id]?.trim(),
  )
  return (
    <div className={styles.actionForm}>
      <p className={proposal.approval_required ? styles.statusBadge : status} data-state="awaiting_approval">
        {proposal.approval_required ? '执行前需审批' : '预演后确认执行'}
      </p>
      <div className={scopeFields}>
        {Object.entries(proposal.key_fields).map(([id, label]) => {
          return (
            <label key={id} className={field}>
              主键 · {label}
              <Input
                value={key[id] ?? ''}
                onChange={(event) => {
                  setKey({ ...key, [id]: event.target.value })
                  setRequestId('')
                }}
              />
            </label>
          )
        })}
        {Object.entries(proposal.parameter_fields).map(([id, item]) => (
          <label className={field} key={id}>
            参数 · {item.label}
            {item.required && '（必填）'}
            <Input
              value={parameters[id] ?? ''}
              onChange={(event) => {
                setParameters({ ...parameters, [id]: event.target.value })
                setRequestId('')
              }}
            />
          </label>
        ))}
      </div>
      <Button
        type="button"
        variant="outline"
        className="justify-self-start"
        disabled={!keyComplete || !parametersComplete}
        onClick={prepare}
      >
        预演业务动作
      </Button>
    </div>
  )
}
