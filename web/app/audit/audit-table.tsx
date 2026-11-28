'use client'

import { useRef } from 'react'
import { ChevronLeft, ChevronRight, Copy, FileJson, MoreHorizontal, ScrollText, Trash2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { AuditLogItem } from '@/types/audit'
import type { AuditState } from './use-audit'
import {
  PAGE_SIZES,
  getAuditActionLabel,
  getAuditActionTone,
  abbreviateAuditIdentifier,
  createAuditFilterDraft,
  getAuditResourceLabel,
  formatAuditTimestamp,
  formatAuditJson,
} from './audit-model'
import styles from './audit.module.css'

export function AuditTable({ audit }: Readonly<{ audit: AuditState }>) {
  const loading = audit.snapshot === undefined && audit.filterError === undefined && audit.logs.isPending
  if (!loading && audit.rows.length === 0) {
    const failed = audit.snapshot === undefined && (audit.filterError !== undefined || audit.logs.isError)
    const emptyPage = audit.snapshot !== undefined && audit.snapshot.data.total > 0
    const filtered = audit.displayedFilters !== undefined && Object.keys(audit.displayedFilters).length > 0
    let title = filtered ? '没有符合筛选条件的记录' : '暂无审计记录'
    let message = filtered ? '调整条件，或清空筛选查看全部记录。' : '当前租户还没有审计记录。'
    if (failed) {
      title = '未取得审计记录'
      message = '请调整筛选或在上方重试读取。'
    } else if (emptyPage) {
      title = '当前页没有审计记录'
      message = '请切换页码，或刷新后核对当前记录。'
    } else if (audit.showingPrevious) {
      title = '已显示范围没有记录'
    }
    return (
      <section className={styles.empty} aria-label="审计列表状态" aria-busy={loading}>
        <ScrollText />
        <h2>{title}</h2>
        <p>{message}</p>
        {!failed && !emptyPage && filtered ? (
          <Button variant="outline" onClick={() => audit.setFilters(createAuditFilterDraft())}>
            清空筛选
          </Button>
        ) : null}
      </section>
    )
  }
  return (
    <div className={styles.tableArea} aria-busy={audit.logs.isFetching}>
      {loading && (
        <p role="status" className="sr-only">
          正在读取审计记录…
        </p>
      )}
      <p className={styles.scrollHint}>左右滑动查看表格，更多信息见明细</p>
      <div className={styles.tableScroll} role="region" aria-label="审计记录表，可横向滚动" tabIndex={0}>
        <table className={styles.table} data-manage={audit.canManage}>
          <caption className="sr-only">按时间倒序排列的审计日志。查看明细可读取完整标识与原始数据。</caption>
          <thead>
            <tr>
              {audit.canManage ? (
                <th scope="col" className={styles.checkColumn}>
                  <Checkbox
                    className={styles.rowCheckbox}
                    aria-label="选择当前页审计日志"
                    disabled={audit.busy !== null || loading || audit.showingPrevious || audit.logs.isFetching}
                    checked={
                      audit.rows.length > 0 && audit.selectedVisible === audit.rows.length
                        ? true
                        : audit.selectedVisible > 0
                          ? 'indeterminate'
                          : false
                    }
                    onCheckedChange={(checked) => audit.togglePage(checked === true)}
                  />
                </th>
              ) : null}
              <th scope="col" className={styles.timeColumn}>
                时间
              </th>
              <th scope="col" className={styles.actorColumn}>
                操作者
              </th>
              <th scope="col" className={styles.eventColumn}>
                动作
              </th>
              <th scope="col" className={styles.resourceColumn}>
                资源
              </th>
              <th scope="col" className={styles.requestColumn}>
                请求 ID
              </th>
              <th scope="col" className={styles.actionsColumn}>
                记录
              </th>
            </tr>
          </thead>
          <tbody>
            {loading
              ? [0, 1, 2, 3].map((index) => (
                  <tr key={index} aria-hidden="true">
                    {audit.canManage && (
                      <td className={styles.checkColumn}>
                        <Skeleton className="size-4" />
                      </td>
                    )}
                    <td className={styles.timeColumn}>
                      <Skeleton className="h-4 w-20" />
                      <Skeleton className="mt-2 h-3 w-16" />
                    </td>
                    <td className={styles.actorColumn}>
                      <Skeleton className="h-4 w-24" />
                    </td>
                    <td className={styles.eventColumn}>
                      <Skeleton className="h-4 w-24" />
                      <Skeleton className="mt-2 h-3 w-32" />
                    </td>
                    <td className={styles.resourceColumn}>
                      <Skeleton className="h-4 w-24" />
                      <Skeleton className="mt-2 h-3 w-32" />
                    </td>
                    <td className={styles.requestColumn}>
                      <Skeleton className="h-4 w-24" />
                    </td>
                    <td className={styles.actionsColumn}>
                      <Skeleton className="h-8 w-20" />
                    </td>
                  </tr>
                ))
              : audit.rows.map((row) => <AuditRow key={row.id} row={row} audit={audit} />)}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function AuditRow({ row, audit }: Readonly<{ row: AuditLogItem; audit: AuditState }>) {
  const menuRef = useRef<HTMLButtonElement>(null)
  const time = formatAuditTimestamp(row.created_at)
  const resource = getAuditResourceLabel(row)
  const selected = audit.selectedSet.has(row.id)
  return (
    <tr className={cn(selected && styles.selectedRow)} aria-selected={audit.canManage ? selected : undefined}>
      {audit.canManage ? (
        <td className={styles.checkColumn}>
          <Checkbox
            className={styles.rowCheckbox}
            aria-label={`选择审计日志 ${row.id}`}
            disabled={audit.busy !== null || audit.showingPrevious || audit.logs.isFetching}
            checked={selected}
            onCheckedChange={(checked) => audit.toggle(row.id, checked === true)}
          />
        </td>
      ) : null}
      <td className={styles.timeColumn}>
        <time dateTime={row.created_at}>
          <span>{time.date}</span>
          <small>{time.time}</small>
        </time>
      </td>
      <td className={styles.actorColumn}>
        <span title={row.actor_id === null ? '未记录操作者' : row.actor_id}>
          <span className={styles.avatar} aria-hidden="true">
            {row.actor_id ? Array.from(row.actor_id)[0].toUpperCase() : '—'}
          </span>
          <span>{row.actor_id === null ? '未记录操作者' : abbreviateAuditIdentifier(row.actor_id)}</span>
        </span>
      </td>
      <td className={styles.eventColumn}>
        <div className={cn(styles.eventTitle, styles[getAuditActionTone(row.action)])}>
          <i aria-hidden="true" />
          <strong title={row.action}>{getAuditActionLabel(row.action)}</strong>
        </div>
        <small className={styles.eventCode} title={row.action}>
          {row.action}
        </small>
      </td>
      <td className={styles.resourceColumn}>
        <strong title={resource.name}>{resource.name}</strong>
        {resource.detail ? <small title={resource.detail}>{resource.detail}</small> : null}
      </td>
      <td className={styles.requestColumn}>
        <span title={row.request_id === null ? undefined : row.request_id}>
          {abbreviateAuditIdentifier(row.request_id)}
        </span>
      </td>
      <td className={styles.actionsColumn}>
        <div className={styles.rowActions}>
          <Button
            variant="ghost"
            aria-label={`查看审计记录 ${row.id}`}
            onClick={(event) => audit.openRecord(row, event.currentTarget)}
          >
            <span>明细</span>
            <ChevronRight />
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                ref={menuRef}
                variant="ghost"
                size="icon"
                className={styles.rowMore}
                aria-label={`审计记录 ${row.id} 的更多操作`}
              >
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onSelect={() => {
                  void audit.copy(formatAuditJson(row.details))
                }}
              >
                <FileJson />
                复制明细 JSON
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => {
                  void audit.copy(row.id)
                }}
              >
                <Copy />
                复制日志 ID
              </DropdownMenuItem>
              {audit.canManage ? (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="text-destructive"
                    disabled={audit.busy !== null || audit.showingPrevious}
                    onSelect={() => audit.askDelete([row.id], menuRef.current)}
                  >
                    <Trash2 />
                    删除记录
                  </DropdownMenuItem>
                </>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </td>
    </tr>
  )
}

export function AuditPagination({ audit }: Readonly<{ audit: AuditState }>) {
  return (
    <footer className={styles.footer} data-task-center-dock>
      <span>
        {audit.total === undefined
          ? '记录数未取得'
          : audit.total === 0 && audit.rows.length === 0
            ? '共 0 条'
            : `本页 ${audit.rows.length} 条 · 统计 ${audit.total} 条`}
      </span>
      <span className={styles.spacer} />
      <span className={styles.pageSizeLabel}>每页</span>
      <Select
        value={String(audit.scope.limit)}
        onValueChange={(value) => audit.setPageSize(Number(value))}
        disabled={audit.busy !== null || audit.showingPrevious}
      >
        <SelectTrigger aria-label="审计每页条数" className={styles.pageSize}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PAGE_SIZES.map((size) => (
            <SelectItem key={size} value={String(size)}>
              {size} 条
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        variant="ghost"
        size="icon"
        aria-label="审计上一页"
        disabled={
          audit.snapshot === undefined ||
          audit.snapshot.scope.page <= 1 ||
          audit.showingPrevious ||
          audit.logs.isFetching ||
          audit.busy !== null
        }
        onClick={() => audit.changePage(-1)}
      >
        <ChevronLeft />
      </Button>
      <span className={styles.pageNumber}>
        {audit.snapshot === undefined
          ? '页数未取得'
          : audit.pageCount === undefined
            ? `第 ${audit.snapshot.scope.page} 页，页数待核对`
            : audit.pageCount === 0
              ? '0 / 0'
              : audit.snapshot.scope.page > audit.pageCount
                ? '请求页超过统计页数'
                : `${audit.snapshot.scope.page} / ${audit.pageCount}`}
      </span>
      <Button
        variant="ghost"
        size="icon"
        aria-label="审计下一页"
        disabled={
          audit.pageCount === undefined ||
          audit.snapshot === undefined ||
          audit.snapshot.scope.page >= audit.pageCount ||
          audit.showingPrevious ||
          audit.logs.isFetching ||
          audit.busy !== null
        }
        onClick={() => audit.changePage(1)}
      >
        <ChevronRight />
      </Button>
    </footer>
  )
}
