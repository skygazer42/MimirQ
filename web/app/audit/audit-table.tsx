'use client'

import { useRef } from 'react'
import { ChevronLeft, ChevronRight, Copy, FileJson, Loader2, MoreHorizontal, ScrollText, Trash2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { AuditLogItem } from '@/types'
import type { AuditController } from './use-audit'
import { PAGE_SIZES, actionName, actionTone, compactId, emptyFilters, resourceLabel, stamp } from './audit-model'
import styles from './audit.module.css'

export function AuditTable({ controller: c }: { controller: AuditController }) {
  if (!c.rows.length) {
    const loading = !c.filterError && c.logs.isPending, failed = Boolean(c.filterError) || c.logs.isError, filtered = Object.keys(c.filters).length > 0
    return <section className={styles.empty} aria-label="审计列表状态" aria-busy={loading}>
      {loading ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <ScrollText />}
      <h2>{loading ? '正在读取审计记录…' : failed ? '未取得审计记录' : filtered ? '没有符合筛选条件的记录' : '暂无审计记录'}</h2>
      <p>{loading ? '记录将按时间倒序显示。' : failed ? '请调整筛选或在上方重试读取。' : filtered ? '调整条件，或清空筛选查看全部记录。' : '当前租户还没有审计记录。'}</p>
      {!loading && !failed && filtered ? <Button variant="outline" onClick={() => c.setFilters(emptyFilters())}>清空筛选</Button> : null}
    </section>
  }
  return <div className={styles.tableArea}><p className={styles.scrollHint}>左右滑动查看表格，更多信息见明细</p>
    <div className={styles.tableScroll} role="region" aria-label="审计记录表，可横向滚动" tabIndex={0}>
      <table className={styles.table} data-manage={c.canManage}>
        <caption className="sr-only">按时间倒序排列的审计日志。查看明细可读取完整标识与原始数据。</caption>
        <thead><tr>
          {c.canManage ? <th scope="col" className={styles.checkColumn}><Checkbox className={styles.rowCheckbox} aria-label="选择当前页审计日志" disabled={Boolean(c.busy) || c.logs.isFetching} checked={c.selectedVisible === c.rows.length ? true : c.selectedVisible ? 'indeterminate' : false} onCheckedChange={checked => c.togglePage(checked === true)} /></th> : null}
          <th scope="col" className={styles.timeColumn}>时间</th><th scope="col" className={styles.actorColumn}>操作者</th><th scope="col" className={styles.eventColumn}>动作</th><th scope="col" className={styles.resourceColumn}>资源</th><th scope="col" className={styles.requestColumn}>请求 ID</th><th scope="col" className={styles.actionsColumn}>记录</th>
        </tr></thead><tbody>{c.rows.map(row => <AuditRow key={row.id} row={row} controller={c} />)}</tbody>
      </table>
    </div>
  </div>
}

function AuditRow({ row, controller: c }: { row: AuditLogItem; controller: AuditController }) {
  const menuRef = useRef<HTMLButtonElement>(null), time = stamp(row.created_at), resource = resourceLabel(row), selected = c.selectedSet.has(row.id)
  return <tr className={cn(selected && styles.selectedRow)} aria-selected={c.canManage ? selected : undefined}>
    {c.canManage ? <td className={styles.checkColumn}><Checkbox className={styles.rowCheckbox} aria-label={`选择审计日志 ${row.id}`} disabled={Boolean(c.busy) || c.logs.isFetching} checked={selected} onCheckedChange={checked => c.toggle(row.id, checked === true)} /></td> : null}
    <td className={styles.timeColumn}><time dateTime={row.created_at}><span>{time.date}</span><small>{time.time}</small></time></td>
    <td className={styles.actorColumn}><span title={row.actor_id || '未记录操作者'}>{row.actor_id ? compactId(row.actor_id) : '未记录操作者'}</span></td>
    <td className={styles.eventColumn}><div className={styles.eventTitle}><i className={styles[actionTone(row.action)]} aria-hidden="true" /><strong title={row.action}>{actionName(row.action)}</strong></div><small className={styles.eventCode} title={row.action}>{row.action}</small></td>
    <td className={styles.resourceColumn}><strong title={resource.name}>{resource.name}</strong>{resource.detail ? <small title={resource.detail}>{resource.detail}</small> : null}</td>
    <td className={styles.requestColumn}><span title={row.request_id || undefined}>{compactId(row.request_id)}</span></td>
    <td className={styles.actionsColumn}><div className={styles.rowActions}>
      <Button variant="ghost" aria-label={`查看审计记录 ${row.id}`} onClick={event => c.openRecord(row, event.currentTarget)}><span>明细</span><ChevronRight /></Button>
      <DropdownMenu><DropdownMenuTrigger asChild><Button ref={menuRef} variant="ghost" size="icon" className={styles.rowMore} aria-label={`审计记录 ${row.id} 的更多操作`}><MoreHorizontal /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => { void c.copy(c.pretty(row.details)) }}><FileJson />复制明细 JSON</DropdownMenuItem><DropdownMenuItem onSelect={() => { void c.copy(row.id) }}><Copy />复制日志 ID</DropdownMenuItem>{c.canManage ? <><DropdownMenuSeparator /><DropdownMenuItem className="text-destructive" disabled={Boolean(c.busy)} onSelect={() => c.askDelete([row.id], menuRef.current)}><Trash2 />删除记录</DropdownMenuItem></> : null}</DropdownMenuContent></DropdownMenu>
    </div></td>
  </tr>
}

export function AuditPagination({ controller: c }: { controller: AuditController }) {
  const start = c.rows.length ? (c.scope.page - 1) * c.scope.limit + 1 : 0
  return <footer className={styles.footer} data-task-center-dock>
    <span>{c.total === null ? '记录数未取得' : c.total === 0 ? '共 0 条' : `${start}–${Math.min(start + c.rows.length - 1, c.total)} · 共 ${c.total} 条`}</span>
    <span className={styles.spacer} /><span className={styles.pageSizeLabel}>每页</span>
    <Select value={String(c.scope.limit)} onValueChange={value => c.update({ limit: Number(value) })} disabled={Boolean(c.busy)}><SelectTrigger aria-label="审计每页条数" className={styles.pageSize}><SelectValue /></SelectTrigger><SelectContent>{PAGE_SIZES.map(size => <SelectItem key={size} value={String(size)}>{size} 条</SelectItem>)}</SelectContent></Select>
    <Button variant="ghost" size="icon" aria-label="审计上一页" disabled={c.scope.page <= 1 || c.logs.isFetching || Boolean(c.busy)} onClick={() => c.update({ page: c.scope.page - 1 })}><ChevronLeft /></Button><span className={styles.pageNumber}>{c.scope.page} / {c.pageCount}</span>
    <Button variant="ghost" size="icon" aria-label="审计下一页" disabled={c.total === null || c.scope.page >= c.pageCount || c.logs.isFetching || Boolean(c.busy)} onClick={() => c.update({ page: c.scope.page + 1 })}><ChevronRight /></Button>
  </footer>
}
