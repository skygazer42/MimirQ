'use client'

import { useState, type FormEvent } from 'react'
import { Download, RefreshCw, Trash2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { toast } from 'sonner'

import { auditApi, type AuditLogPurgeResponse, type AuditPurgeParameters } from '@/lib/api/audit'
import { downloadBlob } from '@/lib/download'
import { getAuditQueryFilters, formatAuditError, formatAuditJson, createAuditPurgeParameters } from './audit-model'
import type { AuditState, AuditTool } from './use-audit'
import { AuditFilterSnapshot } from './audit-filters'
import styles from './audit.module.css'

type PurgeRun = { params: AuditPurgeParameters; response: AuditLogPurgeResponse; draftKey: string }
type PurgeConfirmation = { params: AuditPurgeParameters; state: 'ready' | 'unconfirmed' | 'confirmed' }
const AUDIT_EXPORT_LIMIT = 10_000

export function AuditTools({ audit }: Readonly<{ audit: AuditState }>) {
  const tool = audit.tool
  const busy = audit.busy !== null
  return (
    <Dialog
      open={tool !== null}
      onOpenChange={(open) => {
        if (!open) audit.closeTool()
      }}
    >
      <DialogContent
        className={styles.toolDialog}
        showCloseButton={!busy}
        onCloseAutoFocus={audit.restoreOpener}
        onEscapeKeyDown={(event) => {
          if (busy) event.preventDefault()
        }}
        onInteractOutside={(event) => {
          if (busy) event.preventDefault()
        }}
      >
        <div className={styles.dialogHeader}>
          <DialogTitle>{tool === null ? '审计工具' : tool.kind === 'purge' ? '清理工具' : '导出审计日志'}</DialogTitle>
          <DialogDescription>
            {tool?.kind === 'purge'
              ? '可先预演核对范围，再决定是否真实清理。'
              : `按打开工具时的筛选导出 NDJSON，从最早的记录开始，最多 ${AUDIT_EXPORT_LIMIT.toLocaleString('zh-CN')} 条。`}
          </DialogDescription>
        </div>
        {tool !== null && <AuditToolForm key={JSON.stringify([tool.kind, tool.filters])} audit={audit} tool={tool} />}
      </DialogContent>
    </Dialog>
  )
}

function AuditToolForm({ audit, tool }: Readonly<{ audit: AuditState; tool: AuditTool }>) {
  const [days, setDays] = useState('90')
  const [maximum, setMaximum] = useState('1000')
  const [purgeScope, setPurgeScope] = useState<'retention' | 'filtered'>('retention')
  const [dryRun, setDryRun] = useState(true)
  const [gzip, setGzip] = useState(true)
  const [sensitive, setSensitive] = useState(false)
  const [error, setError] = useState<string | undefined>()
  const [lastRun, setLastRun] = useState<PurgeRun | null>(null)
  const [confirmation, setConfirmation] = useState<PurgeConfirmation | null>(null)
  const applied = getAuditQueryFilters(tool.filters)
  const busy = audit.busy !== null
  const isPurge = tool.kind === 'purge'
  const draftKey = JSON.stringify([purgeScope, days, maximum, dryRun])

  async function exportLogs() {
    const operation = audit.beginOperation('export')
    if (operation === null) return
    const params = { ...applied, include_sensitive: sensitive, gzip, limit: AUDIT_EXPORT_LIMIT }
    let closeAfterDownload = false
    setError(undefined)
    try {
      const blob = await auditApi.exportLogs(params, { signal: operation.controller.signal })
      if (!audit.isCurrentOperation(operation)) return
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
      downloadBlob(`audit-logs.${timestamp}.ndjson`, blob)
      toast.success('已开始下载审计日志')
      closeAfterDownload = true
    } catch (cause) {
      const message = await formatAuditError(cause, '导出失败，请重试')
      if (audit.isCurrentOperation(operation)) setError(message)
    } finally {
      audit.finishOperation(operation)
      if (closeAfterDownload && operation.owner.active && audit.isCurrentSession()) audit.closeTool()
    }
  }

  async function runPurge(params: AuditPurgeParameters) {
    if (!audit.canManage) return
    const operation = audit.beginOperation('purge')
    if (operation === null) return
    const submittedDraftKey = draftKey
    setError(undefined)
    try {
      const response = await auditApi.purgeLogs(params)
      if (!audit.isCurrentSession()) return
      if (audit.isCurrentOperation(operation)) {
        setLastRun({ params, response, draftKey: submittedDraftKey })
        if (!params.dry_run) setConfirmation({ params, state: 'confirmed' })
      }
      try {
        await audit.afterMutation()
      } catch (cause) {
        const message = await formatAuditError(
          cause,
          response.dry_run ? '预演结果已取得，列表刷新失败' : '清理回执已收到，列表刷新失败',
        )
        if (audit.isCurrentOperation(operation)) setError(message)
        return
      }
      if (audit.isCurrentOperation(operation)) {
        setConfirmation(null)
        toast.success(response.dry_run ? '预演完成' : '清理完成')
      }
    } catch (cause) {
      const message = await formatAuditError(
        cause,
        params.dry_run ? '预演结果未取得，请重试' : '清理结果未确认，请重新读取列表核对',
      )
      if (audit.isCurrentOperation(operation)) {
        if (!params.dry_run) setConfirmation({ params, state: 'unconfirmed' })
        setError(message)
      }
      try {
        await audit.afterMutation()
      } catch {
        // The original unconfirmed write error remains visible; the list query owns its read error.
      }
    } finally {
      audit.finishOperation(operation)
    }
  }

  async function refreshPurgeResult() {
    if (confirmation === null) return
    const snapshot = confirmation
    const operation = audit.beginOperation('purge')
    if (operation === null) return
    setError(undefined)
    try {
      const listRefreshed = await audit.afterMutation()
      if (!audit.isCurrentOperation(operation)) return
      if (!listRefreshed) {
        setError(
          snapshot.state === 'unconfirmed'
            ? '本次清理结果仍未确认。请修正筛选条件后读取日志核对。'
            : '清理已确认。请修正筛选条件后重新读取列表。',
        )
        return
      }
      setConfirmation(null)
      if (snapshot.state === 'unconfirmed') {
        setError('列表已重新读取，本次清理结果仍未确认。请核对服务器记录；再次清理会发起新的操作。')
      } else {
        toast.success('清理已确认，列表已刷新')
      }
    } catch (cause) {
      const message = await formatAuditError(cause, '列表刷新失败')
      if (audit.isCurrentOperation(operation)) setError(message)
    } finally {
      audit.finishOperation(operation)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!isPurge) {
      void exportLogs()
      return
    }
    try {
      const params = createAuditPurgeParameters(tool.filters, purgeScope, days, maximum, dryRun)
      setError(undefined)
      if (params.dry_run) void runPurge(params)
      else setConfirmation({ params, state: 'ready' })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '请检查清理参数')
    }
  }

  return (
    <>
      <form className={styles.dialogForm} onSubmit={submit}>
        <div className={styles.dialogBody}>
          {isPurge ? (
            <>
              <fieldset className={styles.choiceGroup} disabled={busy || !audit.canManage}>
                <legend>清理范围</legend>
                <label>
                  <input
                    type="radio"
                    name="audit-purge-scope"
                    checked={purgeScope === 'retention'}
                    onChange={() => {
                      setPurgeScope('retention')
                      setError(undefined)
                    }}
                  />
                  按保留期
                </label>
                <label>
                  <input
                    type="radio"
                    name="audit-purge-scope"
                    checked={purgeScope === 'filtered'}
                    onChange={() => {
                      setPurgeScope('filtered')
                      setError(undefined)
                    }}
                  />
                  按当前筛选
                </label>
              </fieldset>
              <p className={styles.scopeExplanation}>
                {purgeScope === 'retention'
                  ? `当前租户中早于 ${days.length === 0 ? '未填写' : days} 天的日志，页面筛选不参与此范围。`
                  : Object.keys(applied).length > 0
                    ? '仅处理下列筛选条件命中的日志，不叠加保留天数。'
                    : '请先在页面设置筛选，再重新打开工具。'}
              </p>
              {purgeScope === 'filtered' && <AuditFilterSnapshot applied={applied} />}
              <div className={styles.numberFields}>
                {purgeScope === 'retention' && (
                  <div>
                    <Label htmlFor="audit-retention-days">保留天数</Label>
                    <Input
                      id="audit-retention-days"
                      type="number"
                      min="1"
                      max="3650"
                      step="1"
                      value={days}
                      disabled={busy}
                      onChange={(event) => {
                        setDays(event.target.value)
                        setError(undefined)
                      }}
                    />
                  </div>
                )}
                <div>
                  <Label htmlFor="audit-max-delete">最多清理</Label>
                  <Input
                    id="audit-max-delete"
                    type="number"
                    min="1"
                    max="1000000"
                    step="1"
                    value={maximum}
                    disabled={busy}
                    onChange={(event) => {
                      setMaximum(event.target.value)
                      setError(undefined)
                    }}
                  />
                </div>
              </div>
              <fieldset className={styles.choiceGroup} disabled={busy || !audit.canManage}>
                <legend>执行模式</legend>
                <label>
                  <input
                    type="radio"
                    name="audit-purge-mode"
                    checked={dryRun}
                    onChange={() => {
                      setDryRun(true)
                      setError(undefined)
                    }}
                  />
                  预演
                </label>
                <label>
                  <input
                    type="radio"
                    name="audit-purge-mode"
                    checked={!dryRun}
                    onChange={() => {
                      setDryRun(false)
                      setError(undefined)
                    }}
                  />
                  真实清理
                </label>
              </fieldset>
              {lastRun !== null && (
                <section className={styles.purgeResult} aria-label="上次清理结果">
                  <h3>{lastRun.response.dry_run ? '上次预演结果' : '上次清理结果'}</h3>
                  {lastRun.draftKey !== draftKey && <p>输入已变化，以下仍是上次请求的实际结果。</p>}
                  <dl>
                    <div>
                      <dt>可清理</dt>
                      <dd>{lastRun.response.eligible.toLocaleString('zh-CN')} 条</dd>
                    </div>
                    <div>
                      <dt>已删除</dt>
                      <dd>{lastRun.response.deleted.toLocaleString('zh-CN')} 条</dd>
                    </div>
                  </dl>
                  {lastRun.params.purge_scope === 'filtered' ? (
                    <AuditFilterSnapshot applied={getAuditQueryFilters(lastRun.params)} />
                  ) : (
                    <p>范围：早于 {new Date(lastRun.response.cutoff).toLocaleString('zh-CN', { hour12: false })}</p>
                  )}
                  <details>
                    <summary>原始响应</summary>
                    <pre className={styles.json}>{formatAuditJson(lastRun.response)}</pre>
                  </details>
                </section>
              )}
            </>
          ) : (
            <>
              <div className={styles.scopeTitle}>导出范围</div>
              <AuditFilterSnapshot applied={applied} />
              <div className={styles.exportOptions}>
                <label>
                  <Checkbox checked={gzip} disabled={busy} onCheckedChange={(checked) => setGzip(checked === true)} />
                  gzip 传输
                </label>
                <label>
                  <Checkbox
                    checked={sensitive}
                    disabled={busy}
                    onCheckedChange={(checked) => setSensitive(checked === true)}
                  />
                  保留记录明细中的敏感值
                </label>
              </div>
            </>
          )}
          {error !== undefined && (
            <p role="alert" className={styles.fieldError}>
              {error}
            </p>
          )}
        </div>
        <div className={styles.dialogFooter}>
          <Button type="button" variant="outline" disabled={busy} onClick={audit.closeTool}>
            关闭
          </Button>
          <LoadingButton
            type="submit"
            loading={busy}
            variant={isPurge && !dryRun ? 'destructive' : 'default'}
            disabled={isPurge && (!audit.canManage || (purgeScope === 'filtered' && Object.keys(applied).length === 0))}
          >
            {isPurge ? <Trash2 /> : <Download />}
            {isPurge ? (dryRun ? '预演清理' : '清理日志') : '开始导出'}
          </LoadingButton>
        </div>
      </form>
      <AlertDialog
        open={confirmation !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setConfirmation(null)
        }}
      >
        <AlertDialogContent
          className={styles.confirmDialog}
          onEscapeKeyDown={(event) => {
            if (busy) event.preventDefault()
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirmation?.state === 'confirmed'
                ? '清理已确认'
                : confirmation?.state === 'unconfirmed'
                  ? '清理结果待核对'
                  : '确认清理审计日志'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirmation !== null &&
                (confirmation.params.purge_scope === 'filtered'
                  ? '处理下列筛选条件命中的日志'
                  : `处理当前租户中早于 ${confirmation.params.retention_days} 天的日志`)}
              {confirmation !== null && `，本次上限 ${confirmation.params.max_delete} 条。`}
              {confirmation?.state === 'ready' ? '删除不可撤销。' : '请重新读取列表核对；本按钮不会再次发出清理请求。'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {confirmation !== null && confirmation.params.purge_scope === 'filtered' && (
            <AuditFilterSnapshot applied={getAuditQueryFilters(confirmation.params)} />
          )}
          {error !== undefined && (
            <p className={styles.fieldError} role="alert">
              {error}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>{confirmation?.state === 'ready' ? '取消' : '关闭'}</AlertDialogCancel>
            <LoadingButton
              loading={busy}
              variant={confirmation?.state === 'ready' ? 'destructive' : 'default'}
              disabled={confirmation?.state === 'ready' && !audit.canManage}
              onClick={() => {
                if (confirmation !== null)
                  void (confirmation.state === 'ready' ? runPurge(confirmation.params) : refreshPurgeResult())
              }}
            >
              {confirmation?.state === 'ready' ? <Trash2 /> : <RefreshCw />}
              {confirmation?.state === 'ready' ? '确认清理' : '重新读取列表'}
            </LoadingButton>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
