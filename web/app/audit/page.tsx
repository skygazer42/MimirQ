'use client'

import { Code, Download, Loader2, MoreHorizontal, RefreshCw, Trash2 } from '@/components/icons'
import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { formatApiError } from '@/lib/api-errors'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { AuditFiltersBar } from './audit-filters'
import { AuditDialogs } from './audit-dialogs'
import { AuditTools } from './audit-tools'
import { AuditTable, AuditPagination } from './audit-table'
import { useAudit } from './use-audit'
import styles from './audit.module.css'

export default function AuditLogsPage() {
  return <TenantPermissionGate permission={TENANT_PERMISSIONS.AUDIT_READ} pageName="审计日志"><AuditWorkspace /></TenantPermissionGate>
}

function AuditWorkspace() {
  const c = useAudit(), refreshing = c.logs.isFetching || c.options.isFetching
  return <AppFrame><section className={styles.workspace} data-audit-table="a">
    <header className={styles.header}>
      <div className={styles.heading}><PageTitleIcon name="audit-log" /><h1>审计日志</h1></div>
      <div className={styles.headerActions}>
        {c.canManage ? <Button variant="ghost" aria-label="打开清理工具" disabled={Boolean(c.busy)} onClick={event => c.openTool('purge', event.currentTarget)}><Trash2 /><span>清理工具</span></Button> : null}
        <Button variant="ghost" aria-label="刷新审计日志" disabled={refreshing || Boolean(c.busy) || Boolean(c.filterError)} onClick={() => { void c.refresh() }}>{refreshing ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <RefreshCw />}<span>刷新</span></Button>
        <Button variant="outline" aria-label="导出审计日志" disabled={Boolean(c.busy) || Boolean(c.filterError)} onClick={event => c.openTool('export', event.currentTarget)}><Download /><span>导出日志</span></Button>
        <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="更多审计操作"><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem disabled={!c.logs.data} onSelect={() => { const element = document.querySelector<HTMLElement>('[aria-label="更多审计操作"]'); if (element) c.openRaw(element) }}><Code />原始响应</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
      </div>
    </header>
    <AuditFiltersBar controller={c} />
    {c.filterError ? <div className={styles.domainError} role="alert">{c.filterError}</div> : null}
    {c.logs.isError ? <div className={styles.domainError} role="alert"><span>{formatApiError(c.logs.error, '读取审计日志失败')}{c.logs.data ? '，显示上次读取结果' : ''}</span><Button variant="ghost" disabled={c.logs.isFetching} onClick={() => { void c.logs.refetch({ cancelRefetch: false }) }}>重试读取</Button></div> : null}
    {c.options.isError ? <div className={styles.optionError} role="alert"><span>筛选选项读取失败，可使用精确筛选。</span><Button variant="ghost" disabled={c.options.isFetching} onClick={() => { void c.options.refetch({ cancelRefetch: false }) }}>重试选项</Button></div> : null}
    <div className={styles.tableToolbar}>
      <h2 data-audit-records-heading tabIndex={-1}>{c.selected.length ? `已选 ${c.selected.length} 条` : '全部记录'}</h2>
      {c.selected.length ? <><span className={styles.selectionNote}>本页 {c.selectedVisible} 条</span><Button variant="ghost" disabled={Boolean(c.busy)} onClick={() => c.setSelected([])}>取消选择</Button><Button variant="ghost" className={styles.deleteAction} disabled={Boolean(c.busy)} onClick={event => c.askDelete(c.selected, event.currentTarget)}><Trash2 />删除已选</Button></> : null}
      <span className={styles.spacer} /><span className={styles.sortLabel}>{c.logs.isFetching && c.logs.data ? '正在更新 · ' : ''}按时间倒序</span>
    </div>
    <AuditTable controller={c} /><AuditPagination controller={c} />
    <AuditDialogs controller={c} /><AuditTools controller={c} />
  </section></AppFrame>
}
