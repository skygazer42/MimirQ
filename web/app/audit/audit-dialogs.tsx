'use client'

import { Copy, RefreshCw, Trash2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
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
import { formatAuditJson, formatAuditTimestamp, getAuditActionLabel, getAuditResourceTypeLabel } from './audit-model'
import type { AuditState } from './use-audit'
import styles from './audit.module.css'

export function AuditDialogs({ audit }: Readonly<{ audit: AuditState }>) {
  const record = audit.record
  const raw = audit.rawResponse
  const target = audit.deleteTarget
  const receipt = audit.deleteResult
  const busy = audit.busy !== null
  const fields: Array<[string, string | null]> =
    record === null
      ? []
      : [
          ['时间', `${formatAuditTimestamp(record.created_at).date} ${formatAuditTimestamp(record.created_at).time}`],
          ['操作者 ID', record.actor_id],
          ['资源类型', getAuditResourceTypeLabel(record.resource_type)],
          ['资源 ID', record.resource_id],
          ['请求 ID', record.request_id],
          ['来源 IP', record.ip],
          ['租户', record.tenant_id],
          ['日志 ID', record.id],
        ]
  return (
    <>
      <Dialog
        open={record !== null}
        onOpenChange={(open) => {
          if (!open) audit.setRecord(null)
        }}
      >
        <DialogContent className={styles.recordDialog} onCloseAutoFocus={audit.restoreRecordOpener}>
          <div className={styles.dialogHeader}>
            <DialogTitle>{record === null ? '审计记录' : getAuditActionLabel(record.action)}</DialogTitle>
            <DialogDescription>{record === null ? '审计记录明细' : record.action}</DialogDescription>
          </div>
          {record !== null && (
            <>
              <div className={styles.dialogBody}>
                <dl className={styles.recordFields}>
                  {fields.map(([label, value]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>
                        {value === null ? (
                          '未记录'
                        ) : (
                          <button type="button" title={`复制${label}`} onClick={() => void audit.copy(value)}>
                            {value.length === 0 ? '""' : value}
                          </button>
                        )}
                      </dd>
                    </div>
                  ))}
                </dl>
                <dl className={styles.userAgent}>
                  <dt>User-Agent</dt>
                  <dd>
                    {record.user_agent === null ? '未记录' : record.user_agent.length === 0 ? '""' : record.user_agent}
                  </dd>
                </dl>
                <div className={styles.detailHeading}>
                  <h3>原始明细</h3>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => void audit.copy(formatAuditJson(record.details))}
                  >
                    <Copy />
                    复制明细
                  </Button>
                </div>
                <pre className={styles.json} tabIndex={0} aria-label="审计原始明细">
                  {formatAuditJson(record.details)}
                </pre>
              </div>
              <div className={styles.dialogFooter}>
                {audit.canManage && (
                  <Button
                    type="button"
                    variant="ghost"
                    className={styles.deleteAction}
                    disabled={busy || audit.showingPrevious}
                    onClick={(event) => audit.askDelete([record.id], event.currentTarget)}
                  >
                    <Trash2 />
                    删除记录
                  </Button>
                )}
                <span className={styles.spacer} />
                <Button type="button" variant="outline" onClick={() => void audit.copy(formatAuditJson(record))}>
                  <Copy />
                  复制记录
                </Button>
                <Button type="button" onClick={() => audit.setRecord(null)}>
                  关闭
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
      <Dialog
        open={raw !== null}
        onOpenChange={(open) => {
          if (!open) audit.setRawResponse(null)
        }}
      >
        <DialogContent className={styles.recordDialog} onCloseAutoFocus={audit.restoreOpener}>
          <div className={styles.dialogHeader}>
            <DialogTitle>原始响应</DialogTitle>
            <DialogDescription>打开此窗口时所读取的筛选、页范围与服务器响应。</DialogDescription>
          </div>
          {raw !== null && (
            <>
              <div className={styles.dialogBody}>
                <details>
                  <summary>请求范围</summary>
                  <pre className={styles.json}>{formatAuditJson(raw.params)}</pre>
                </details>
                <pre className={styles.json} tabIndex={0}>
                  {formatAuditJson(raw.data)}
                </pre>
              </div>
              <div className={styles.dialogFooter}>
                <Button type="button" variant="outline" onClick={() => void audit.copy(formatAuditJson(raw.data))}>
                  <Copy />
                  复制响应
                </Button>
                <span className={styles.spacer} />
                <Button type="button" onClick={() => audit.setRawResponse(null)}>
                  关闭
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
      <AlertDialog
        open={target !== null}
        onOpenChange={(open) => {
          if (!open) audit.closeDelete()
        }}
      >
        <AlertDialogContent
          className={styles.confirmDialog}
          onCloseAutoFocus={audit.restoreDeleteOpener}
          onEscapeKeyDown={(event) => {
            if (busy) event.preventDefault()
          }}
        >
          <AlertDialogHeader>
            <AlertDialogTitle>{audit.deletionConfirmed ? '删除已确认' : '确认删除审计日志'}</AlertDialogTitle>
            <AlertDialogDescription>
              {target !== null &&
                (audit.deletionConfirmed
                  ? '所列日志已确认删除或原已不存在，请重新读取列表核对当前记录。'
                  : `将处理所列 ${target.length} 条审计日志。删除不可撤销，删除操作本身会生成新的审计记录。`)}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {target !== null && (
            <div className={styles.confirmIds}>
              {target.map((id) => (
                <span key={id}>{id}</span>
              ))}
            </div>
          )}
          {receipt !== null && (
            <p>
              本次已确认删除 {receipt.deleted} 条，{receipt.missing} 条原已不存在。
            </p>
          )}
          {audit.deleteError !== undefined && (
            <p className={styles.fieldError} role="alert">
              {audit.deleteError}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>{audit.deletionConfirmed ? '关闭' : '取消'}</AlertDialogCancel>
            <LoadingButton
              loading={busy}
              variant={audit.deletionConfirmed ? 'default' : 'destructive'}
              disabled={!audit.deletionConfirmed && !audit.canManage}
              onClick={() => void (audit.deletionConfirmed ? audit.retryDeleteRefresh() : audit.deleteRecords())}
            >
              {audit.deletionConfirmed ? <RefreshCw /> : <Trash2 />}
              {audit.deletionConfirmed ? '重新读取列表' : '确认删除'}
            </LoadingButton>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
