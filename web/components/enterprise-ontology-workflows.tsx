'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Workflow } from '@/components/icons'
import { enterpriseOntologyApi } from '@/lib/api/enterprise-ontology'
import type {
  EnterpriseOntologyDefinitionView,
  EnterpriseOntologyHeaders,
  EnterpriseOntologyWorkflowView,
} from '@/types/enterprise-ontology'
import styles from './enterprise-ontology-published.module.css'

type Operation = Parameters<typeof enterpriseOntologyApi.advanceWorkflow>[4]

const stateLabels: Record<string, string> = {
  awaiting_approval: '等待审批',
  ready: '待执行',
  succeeded: '已执行',
  submitted: '已提交',
  dispatching: '派发中',
  unknown: '待核实',
  manual_review: '待人工核实',
  failed: '执行失败',
}

export function PublishedOntologyWorkflows({
  definition,
  ontologyId,
  versionId,
  edoHeaders,
  run,
}: Readonly<{
  definition: EnterpriseOntologyDefinitionView
  ontologyId: string
  versionId: string
  edoHeaders?: EnterpriseOntologyHeaders
  run: (label: string, task: () => Promise<void>) => Promise<void>
}>) {
  const workflows = definition.action_workflows ?? {}
  const [selected, setSelected] = useState('')
  const [requestId, setRequestId] = useState('')
  const [creationId, setCreationId] = useState('')
  const [plan, setPlan] = useState<EnterpriseOntologyWorkflowView | null>(null)
  const [fields, setFields] = useState<Record<string, string>>({})
  const workflow = workflows[selected]
  const actions = definition.actions ?? {}
  const steps = workflow?.actions.map((id) => ({ id, action: actions[id] })) ?? []
  const inputs = steps.map(({ action }, index) => {
    const object = definition.object_types[action.object_type]
    return {
      key: Object.fromEntries(object.key.map((name) => [name, fields[index + ':key:' + name]?.trim() ?? ''])),
      parameters: Object.fromEntries(
        Object.keys(action.parameters).flatMap((name) => {
          const value = fields[index + ':parameter:' + name]?.trim()
          return value ? [[name, value]] : []
        }),
      ),
    }
  })
  const ready =
    inputs.length > 0 &&
    inputs.every(
      (input, index) =>
        Object.values(input.key).every(Boolean) &&
        Object.entries(steps[index].action.parameters).every(
          ([name, parameter]) => !parameter.required || Object.hasOwn(input.parameters, name),
        ),
    )

  function changeField(name: string, value: string) {
    setCreationId('')
    setFields((previous) => ({ ...previous, [name]: value }))
  }

  function create() {
    const id = creationId || globalThis.crypto.randomUUID()
    setCreationId(id)
    setRequestId(id)
    void run('创建流程请求', async () => {
      setPlan(
        await enterpriseOntologyApi.createWorkflow(ontologyId, versionId, selected, { request_id: id, steps: inputs }),
      )
    })
  }

  function advance(index: number, operation: Operation, label: string) {
    if (!plan) return
    void run(label, async () => {
      setPlan(
        await enterpriseOntologyApi.advanceWorkflow(ontologyId, versionId, plan.request_id, index, operation, {
          headers: edoHeaders,
        }),
      )
    })
  }

  return (
    <section className={styles.operationCard} aria-label="动作流程">
      <h3 className={styles.cardHeading}>
        <span className={styles.sectionIcon} data-tone="workflow" aria-hidden="true">
          <Workflow />
        </span>
        动作流程
      </h3>
      {!plan ? (
        <>
          <label className="grid gap-1">
            已发布流程
            <select
              className="h-9 rounded-md border border-input bg-background px-2"
              value={selected}
              onChange={(event) => {
                setSelected(event.target.value)
                setFields({})
                setCreationId('')
              }}
            >
              <option value="">选择流程</option>
              {Object.entries(workflows).map(([id, item]) => (
                <option key={id} value={id}>
                  {item.label || id}
                </option>
              ))}
            </select>
          </label>
          {steps.map(({ id, action }, index) => (
            <fieldset key={index} className={styles.workflowInput}>
              <legend className="font-medium">
                <span className={styles.stepNumber} aria-hidden="true">
                  {index + 1}
                </span>
                {action.label || id}
              </legend>
              {action.approval_required && (
                <span className={styles.statusBadge} data-state="awaiting_approval">
                  需审批
                </span>
              )}
              {definition.object_types[action.object_type].key.map((name) => (
                <label className="grid gap-1" key={name}>
                  主键 · {name}
                  <Input
                    value={fields[index + ':key:' + name] ?? ''}
                    onChange={(event) => changeField(index + ':key:' + name, event.target.value)}
                  />
                </label>
              ))}
              {Object.entries(action.parameters).map(([name, parameter]) => (
                <label className="grid gap-1" key={name}>
                  参数 · {parameter.label || name}
                  {parameter.required && '（必填）'}
                  <Input
                    value={fields[index + ':parameter:' + name] ?? ''}
                    onChange={(event) => changeField(index + ':parameter:' + name, event.target.value)}
                  />
                </label>
              ))}
            </fieldset>
          ))}
          {workflow && (
            <Button className="justify-self-start" disabled={!ready} onClick={create}>
              创建流程请求
            </Button>
          )}
          <label className="grid gap-1">
            流程请求 ID
            <Input value={requestId} onChange={(event) => setRequestId(event.target.value)} />
          </label>
          <Button
            variant="outline"
            className="justify-self-start"
            disabled={!requestId.trim()}
            onClick={() =>
              void run('读取流程请求', async () =>
                setPlan(await enterpriseOntologyApi.getWorkflow(ontologyId, versionId, requestId.trim())),
              )
            }
          >
            读取流程请求
          </Button>
        </>
      ) : (
        <>
          <p className="font-medium">
            {workflows[plan.workflow_id]?.label || plan.workflow_id} ·{' '}
            {plan.canceled ? '已停止' : plan.current_step === null ? '已完成' : '进行中'}
          </p>
          <p className="break-all text-muted-foreground">{plan.request_id}</p>
          <ol className={styles.workflowSteps}>
            {plan.steps.map((step, index) => {
              const current = !plan.canceled && plan.current_step === index
              const action = step.action
              const state = action?.state
              return (
                <li className={styles.workflowStep} data-current={current} key={step.inputs.request_id}>
                  <span className={styles.stepNumber} aria-hidden="true">
                    {index + 1}
                  </span>
                  <p>
                    {actions[step.action_id]?.label || step.action_id} ·{' '}
                    <span className={styles.statusBadge} data-state={state}>
                      {state ? (stateLabels[state] ?? state) : '待预演'}
                    </span>
                  </p>
                  <p className="break-words text-muted-foreground">
                    {Object.entries({ ...step.inputs.key, ...step.inputs.parameters })
                      .map(([name, value]) => name + '=' + value)
                      .join(' · ')}
                  </p>
                  {action?.receipt && <p>回执 {action.receipt.receipt_id}</p>}
                  <div className="flex flex-wrap gap-2">
                    {current && !action && (
                      <Button variant="outline" onClick={() => advance(index, 'preview', '预演当前动作')}>
                        预演当前动作
                      </Button>
                    )}
                    {current && state === 'awaiting_approval' && (
                      <Button variant="outline" onClick={() => advance(index, 'approve', '审批当前动作')}>
                        审批当前动作
                      </Button>
                    )}
                    {current && state === 'ready' && (
                      <Button onClick={() => advance(index, 'execute', '执行当前动作')}>执行当前动作</Button>
                    )}
                    {action &&
                      (['dispatching', 'unknown', 'manual_review', 'submitted'].includes(action.state) ||
                        action.receipt?.sync_status === 'pending') && (
                        <Button variant="outline" onClick={() => advance(index, 'receipt', '查询动作回执')}>
                          查询动作回执
                        </Button>
                      )}
                  </div>
                </li>
              )
            })}
          </ol>
          <div className="flex flex-wrap gap-2">
            {!plan.canceled && plan.current_step !== null && (
              <Button variant="outline" onClick={() => advance(plan.current_step ?? 0, 'cancel', '停止后续步骤')}>
                停止后续步骤
              </Button>
            )}
            <Button
              variant="ghost"
              onClick={() => {
                setPlan(null)
                setCreationId('')
              }}
            >
              返回流程选择
            </Button>
          </div>
        </>
      )}
    </section>
  )
}
