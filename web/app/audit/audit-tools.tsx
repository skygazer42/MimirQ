'use client'

import { useEffect, useState } from 'react'
import { Download, Loader2, Trash2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { toast } from 'sonner'
import { auditApi, type AuditLogPurgeResponse } from '@/lib/api/audit'
import { FILTER_LABELS, cleanFilters, formatAuditError, pretty, purgeParameters, type FilterKey } from './audit-model'
import type { AuditController } from './use-audit'
import styles from './audit.module.css'

export function AuditTools({ controller: c }: { controller: AuditController }) {
  const [days, setDays] = useState('90'), [maximum, setMaximum] = useState('1000')
  const [purgeScope, setPurgeScope] = useState<'retention' | 'filtered'>('retention'), [dryRun, setDryRun] = useState(true)
  const [gzip, setGzip] = useState(true), [sensitive, setSensitive] = useState(false)
  const [error, setError] = useState(''), [result, setResult] = useState<AuditLogPurgeResponse | null>(null)
  const [pendingReal, setPendingReal] = useState<ReturnType<typeof purgeParameters> | null>(null)
  const applied = cleanFilters(c.toolFilters), busy = Boolean(c.busy), isPurge = c.tool === 'purge'
  useEffect(() => {
    setError(''); setResult(null); setPendingReal(null)
    if (c.tool === 'purge') { setDryRun(true); setPurgeScope('retention') }
  }, [c.tool, c.toolFilters])
  function clearResult() { setResult(null); setError('') }
  async function exportLogs() {
    if (busy) return
    setError('')
    const snapshot = { ...applied, include_sensitive: sensitive, gzip, limit: 10_000 }
    try {
      await c.exclusive('export', async () => {
        const blob = await auditApi.exportLogs(snapshot)
        const prefix = new Uint8Array(await blob.slice(0, 2).arrayBuffer())
        const compressed = prefix[0] === 0x1f && prefix[1] === 0x8b
        const url = URL.createObjectURL(blob), anchor = document.createElement('a')
        anchor.href = url; anchor.download = `audit-logs.${new Date().toISOString().replace(/[:.]/g, '-')}.ndjson${compressed ? '.gz' : ''}`
        anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      })
      toast.success('导出完成'); c.setTool(null)
    } catch (cause) { setError(await formatAuditError(cause, '导出失败，请重试')) }
  }
  async function runPurge(params: ReturnType<typeof purgeParameters>) {
    if (!c.canManage || busy) return
    setError(''); setResult(null)
    try {
      const response = await c.exclusive('purge', () => auditApi.purgeLogs(params))
      setResult(response); setPendingReal(null)
      toast.success(response.dry_run ? '预演完成' : '清理完成')
      await c.afterMutation()
    } catch (cause) { setPendingReal(null); setError(await formatAuditError(cause, '清理失败，请重试')) }
  }
  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!isPurge) { void exportLogs(); return }
    try {
      const params = purgeParameters(c.toolFilters, purgeScope, days, maximum, dryRun)
      if (params.dry_run) void runPurge(params)
      else setPendingReal(params)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '请检查清理参数') }
  }
  return <>
    <Dialog open={Boolean(c.tool)} onOpenChange={open => { if (!open && !busy) c.setTool(null) }}>
      <DialogContent className={styles.toolDialog} onCloseAutoFocus={c.restoreOpener} onEscapeKeyDown={event => { if (busy) event.preventDefault() }} onInteractOutside={event => { if (busy) event.preventDefault() }}>
        <form className={styles.dialogForm} onSubmit={submit}>
          <div className={styles.dialogHeader}><DialogTitle>{isPurge ? '清理工具' : '导出审计日志'}</DialogTitle><DialogDescription>{isPurge ? '先预演核对范围，再决定是否真实清理。' : '导出当前筛选范围，格式为 NDJSON，最多 10,000 条。'}</DialogDescription></div>
          <div className={styles.dialogBody}>
            {isPurge ? <>
              <fieldset className={styles.choiceGroup} disabled={busy || !c.canManage}><legend>清理范围</legend><label><input type="radio" name="audit-purge-scope" checked={purgeScope === 'retention'} onChange={() => { setPurgeScope('retention'); clearResult() }} />按保留期</label><label><input type="radio" name="audit-purge-scope" checked={purgeScope === 'filtered'} onChange={() => { setPurgeScope('filtered'); clearResult() }} />按当前筛选</label></fieldset>
              <p className={styles.scopeExplanation}>{purgeScope === 'retention' ? `当前租户中早于 ${days || '—'} 天的日志，页面筛选不参与此范围。` : Object.keys(applied).length ? '仅处理下列筛选条件命中的日志，不叠加保留天数。' : '尚未设置筛选条件，请先在页面中设置后重新打开。'}</p>
              {purgeScope === 'filtered' ? <FilterSnapshot applied={applied} /> : null}
              <div className={styles.numberFields}>{purgeScope === 'retention' ? <div><Label htmlFor="audit-retention-days">保留天数</Label><Input id="audit-retention-days" type="number" min="1" max="3650" step="1" value={days} disabled={busy} onChange={event => { setDays(event.target.value); clearResult() }} /></div> : null}<div><Label htmlFor="audit-max-delete">最多清理</Label><Input id="audit-max-delete" type="number" min="1" max="1000000" step="1" value={maximum} disabled={busy} onChange={event => { setMaximum(event.target.value); clearResult() }} /></div></div>
              <fieldset className={styles.choiceGroup} disabled={busy || !c.canManage}><legend>执行模式</legend><label><input type="radio" name="audit-purge-mode" checked={dryRun} onChange={() => { setDryRun(true); clearResult() }} />预演</label><label><input type="radio" name="audit-purge-mode" checked={!dryRun} onChange={() => { setDryRun(false); clearResult() }} />真实清理</label></fieldset>
              {result ? <section className={styles.purgeResult} aria-label="清理结果"><h3>{result.dry_run ? '预演结果' : '清理结果'}</h3><dl><div><dt>可清理</dt><dd>{result.eligible.toLocaleString('zh-CN')} 条</dd></div><div><dt>已删除</dt><dd>{result.deleted.toLocaleString('zh-CN')} 条</dd></div></dl>{result.scope !== 'filtered' ? <p>范围：早于 {new Date(result.cutoff).toLocaleString('zh-CN', { hour12: false })}</p> : null}<details><summary>原始响应</summary><pre className={styles.json}>{pretty(result)}</pre></details></section> : null}
            </> : <>
              <div className={styles.scopeTitle}>导出范围</div><FilterSnapshot applied={applied} />
              <div className={styles.exportOptions}><label><Checkbox checked={gzip} disabled={busy} onCheckedChange={checked => setGzip(checked === true)} />gzip 传输</label><label><Checkbox checked={sensitive} disabled={busy} onCheckedChange={checked => setSensitive(checked === true)} />包含敏感字段</label></div>
            </>}
            {error ? <p role="alert" className={styles.fieldError}>{error}</p> : null}
          </div>
          <div className={styles.dialogFooter}><Button type="button" variant="outline" disabled={busy} onClick={() => c.setTool(null)}>关闭</Button><Button type="submit" variant={isPurge && !dryRun ? 'destructive' : 'default'} disabled={busy || (isPurge && (!c.canManage || (purgeScope === 'filtered' && !Object.keys(applied).length)))}>{busy ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : isPurge ? <Trash2 /> : <Download />}{busy ? c.busy === 'export' ? '正在导出' : '正在执行' : isPurge ? dryRun ? '预演清理' : '清理日志' : '开始导出'}</Button></div>
        </form>
      </DialogContent>
    </Dialog>
    <AlertDialog open={Boolean(pendingReal)} onOpenChange={open => { if (!open && !busy) setPendingReal(null) }}><AlertDialogContent className={styles.confirmDialog}>
      <AlertDialogHeader><AlertDialogTitle>确认清理审计日志</AlertDialogTitle><AlertDialogDescription>{pendingReal?.purge_scope === 'filtered' ? '将删除所列筛选条件命中的日志' : `将删除当前租户中早于 ${pendingReal?.retention_days ?? days} 天的日志`}，最多 {pendingReal?.max_delete ?? maximum} 条。此操作不可撤销。</AlertDialogDescription></AlertDialogHeader>
      {pendingReal?.purge_scope === 'filtered' ? <FilterSnapshot applied={applied} /> : null}
      <AlertDialogFooter><AlertDialogCancel disabled={busy}>取消</AlertDialogCancel><Button variant="destructive" disabled={busy || !c.canManage} onClick={() => { if (pendingReal) void runPurge(pendingReal) }}>{busy ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Trash2 />}{busy ? '正在清理' : '确认清理'}</Button></AlertDialogFooter>
    </AlertDialogContent></AlertDialog>
  </>
}

function FilterSnapshot({ applied }: { applied: Partial<Record<FilterKey, string>> }) {
  return Object.keys(applied).length ? <dl className={styles.scopeSnapshot}>{Object.entries(applied).map(([key, value]) => <div key={key}><dt>{FILTER_LABELS[key as FilterKey]}</dt><dd>{value}</dd></div>)}</dl> : <p className={styles.allScope}>当前租户 · 全部日志</p>
}
