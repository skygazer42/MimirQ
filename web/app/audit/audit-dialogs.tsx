'use client'

import { Copy, Loader2, Trash2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { actionName, resourceTypeName, stamp } from './audit-model'
import type { AuditController } from './use-audit'
import styles from './audit.module.css'

export function AuditDialogs({ controller: c }: { controller: AuditController }) {
  const record = c.record
  return <>
    <Dialog open={Boolean(record)} onOpenChange={open => { if (!open) c.setRecord(null) }}><DialogContent className={styles.recordDialog} onCloseAutoFocus={c.restoreRecordOpener}>{record ? <>
      <div className={styles.dialogHeader}><DialogTitle>{actionName(record.action)}</DialogTitle><DialogDescription>{record.action}</DialogDescription></div>
      <div className={styles.dialogBody}>
        <dl className={styles.recordFields}>{[['时间', `${stamp(record.created_at).date} ${stamp(record.created_at).time}`], ['操作者 ID', record.actor_id], ['资源类型', resourceTypeName(record.resource_type)], ['资源 ID', record.resource_id], ['请求 ID', record.request_id], ['来源 IP', record.ip], ['租户', record.tenant_id], ['日志 ID', record.id]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ? <button title={`复制${label}`} onClick={() => { void c.copy(value) }}>{value}</button> : '未记录'}</dd></div>)}</dl>
        <dl className={styles.userAgent}><dt>User-Agent</dt><dd>{record.user_agent || '未记录'}</dd></dl>
        <div className={styles.detailHeading}><h3>原始明细</h3><Button variant="ghost" onClick={() => { void c.copy(c.pretty(record.details)) }}><Copy />复制明细</Button></div><pre className={styles.json} tabIndex={0} aria-label="审计原始明细">{c.pretty(record.details)}</pre>
      </div>
      <div className={styles.dialogFooter}>{c.canManage ? <Button variant="ghost" className={styles.deleteAction} disabled={Boolean(c.busy)} onClick={event => c.askDelete([record.id], event.currentTarget)}><Trash2 />删除记录</Button> : null}<span className={styles.spacer} /><Button variant="outline" onClick={() => { void c.copy(c.pretty(record)) }}><Copy />复制记录</Button><Button onClick={() => c.setRecord(null)}>关闭</Button></div>
    </> : null}</DialogContent></Dialog>
    <Dialog open={c.rawOpen} onOpenChange={c.setRawOpen}><DialogContent className={styles.recordDialog} onCloseAutoFocus={c.restoreOpener}><div className={styles.dialogHeader}><DialogTitle>原始响应</DialogTitle><DialogDescription>当前筛选与当前页返回的审计数据。</DialogDescription></div><div className={styles.dialogBody}><pre className={styles.json} tabIndex={0}>{c.pretty(c.logs.data ?? null)}</pre></div><div className={styles.dialogFooter}><Button variant="outline" onClick={() => { void c.copy(c.pretty(c.logs.data ?? null)) }}><Copy />复制响应</Button><span className={styles.spacer} /><Button onClick={() => c.setRawOpen(false)}>关闭</Button></div></DialogContent></Dialog>
    <AlertDialog open={Boolean(c.deleteTarget)} onOpenChange={open => { if (!open && c.busy !== 'delete') c.setDeleteTarget(null) }}><AlertDialogContent className={styles.confirmDialog} onCloseAutoFocus={c.restoreDeleteOpener}>
      <AlertDialogHeader><AlertDialogTitle>确认删除审计日志</AlertDialogTitle><AlertDialogDescription>将删除{c.deleteTarget?.length === 1 ? '这条' : `已选 ${c.deleteTarget?.length ?? 0} 条`}审计日志。此操作不可撤销，删除操作本身会生成新的审计记录。</AlertDialogDescription></AlertDialogHeader>
      <div className={styles.confirmIds}>{c.deleteTarget?.map(id => <span key={id}>{id}</span>)}</div>{c.deleteError ? <p className={styles.fieldError} role="alert">{c.deleteError}</p> : null}
      <AlertDialogFooter><AlertDialogCancel disabled={c.busy === 'delete'}>取消</AlertDialogCancel><Button variant="destructive" disabled={!c.canManage || Boolean(c.busy)} onClick={() => { void c.deleteRecords() }}>{c.busy === 'delete' ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Trash2 />}{c.busy === 'delete' ? '正在删除' : '确认删除'}</Button></AlertDialogFooter>
    </AlertDialogContent></AlertDialog>
  </>
}
