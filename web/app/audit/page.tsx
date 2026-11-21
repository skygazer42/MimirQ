'use client'

import { Suspense, useRef, useSyncExternalStore } from 'react'
import { Code, Download, MoreHorizontal, RefreshCw, Trash2 } from '@/components/icons'
import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { PageLoading } from '@/components/ui/page-loading'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { AuditFiltersBar, AuditFilterSnapshot } from './audit-filters'
import { AuditDialogs } from './audit-dialogs'
import { AuditTools } from './audit-tools'
import { AuditTable, AuditPagination } from './audit-table'
import { useAudit } from './use-audit'
import styles from './audit.module.css'

export default function AuditLogsPage() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return (
    <TenantPermissionGate permission={TENANT_PERMISSIONS.AUDIT_READ} pageName="审计日志">
      <Suspense fallback={<PageLoading message="正在加载审计日志…" srMessage="正在加载审计日志" />}>
        <AuditWorkspace key={sessionKey} sessionKey={sessionKey} />
      </Suspense>
    </TenantPermissionGate>
  )
}

function AuditWorkspace({ sessionKey }: Readonly<{ sessionKey: string }>) {
  const recordsHeading = useRef<HTMLHeadingElement>(null)
  const audit = useAudit(sessionKey, () => recordsHeading.current?.focus())
  const rawOpener = useRef<HTMLButtonElement>(null)
  const refreshing = audit.logs.isFetching || audit.suggestionQuery.isFetching
  return (
    <AppFrame>
      <section className={styles.workspace} data-audit-table="a">
        <header className={styles.header}>
          <div className={styles.heading}>
            <PageTitleIcon name="audit-log" />
            <h1>审计日志</h1>
          </div>
          <div className={styles.headerActions}>
            {audit.canManage ? (
              <Button
                variant="ghost"
                aria-label="打开清理工具"
                disabled={audit.busy !== null}
                onClick={(event) => audit.openTool('purge', event.currentTarget)}
              >
                <Trash2 />
                <span className={styles.actionLabel}>清理工具</span>
              </Button>
            ) : null}
            <LoadingButton
              variant="ghost"
              aria-label="刷新审计日志"
              loading={refreshing}
              disabled={audit.busy !== null || audit.filterError !== undefined}
              onClick={() => {
                void audit.refresh()
              }}
            >
              <RefreshCw />
              <span className={styles.actionLabel}>刷新</span>
            </LoadingButton>
            <Button
              variant="outline"
              aria-label="导出审计日志"
              disabled={audit.busy !== null || audit.filterError !== undefined}
              onClick={(event) => audit.openTool('export', event.currentTarget)}
            >
              <Download />
              <span className={styles.actionLabel}>导出日志</span>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button ref={rawOpener} variant="ghost" size="icon" aria-label="更多审计操作">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  disabled={audit.snapshot === undefined}
                  onSelect={() => {
                    if (rawOpener.current !== null) audit.openRaw(rawOpener.current)
                  }}
                >
                  <Code />
                  原始响应
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <AuditFiltersBar audit={audit} />
        {audit.filterError !== undefined ? (
          <div className={styles.domainError} role="alert">
            {audit.filterError}
          </div>
        ) : null}
        {audit.logs.isError ? (
          <div className={styles.domainError} role="alert">
            <span>
              {formatApiError(audit.logs.error, '读取审计日志失败')}
              {audit.snapshot === undefined ? '' : '，保留已取得的结果'}
            </span>
            <Button
              variant="ghost"
              disabled={audit.logs.isFetching || audit.filterError !== undefined}
              onClick={() => {
                void audit.logs.refetch({ cancelRefetch: false })
              }}
            >
              重试读取
            </Button>
          </div>
        ) : null}
        {audit.suggestionQuery.isError ? (
          <div className={styles.optionError} role="alert">
            <span>{formatApiError(audit.suggestionQuery.error, '近期筛选建议读取失败')}，仍可使用精确筛选。</span>
            <Button
              variant="ghost"
              disabled={audit.suggestionQuery.isFetching}
              onClick={() => {
                void audit.suggestionQuery.refetch({ cancelRefetch: false })
              }}
            >
              重试建议
            </Button>
          </div>
        ) : null}
        {audit.showingPrevious && audit.snapshot !== undefined && (
          <section className={styles.snapshotNotice} aria-label="当前已显示范围">
            <p role="status">
              新条件尚未取得结果。当前显示已读取的第 {audit.snapshot.scope.page} 页，每页 {audit.snapshot.scope.limit}{' '}
              条。
            </p>
            <AuditFilterSnapshot applied={audit.snapshot.params} />
            <Button type="button" variant="ghost" onClick={audit.restoreSnapshotScope}>
              使用已显示范围
            </Button>
          </section>
        )}
        {audit.countChangedDuringRead && (
          <p className={styles.snapshotNotice} role="status">
            统计总数与本页记录暂不一致，本页记录已保留，可刷新核对。
          </p>
        )}
        <div className={styles.tableToolbar}>
          <h2 ref={recordsHeading} data-audit-records-heading tabIndex={-1}>
            {audit.selected.length > 0
              ? `已选 ${audit.selected.length} 条`
              : audit.displayedFilters !== undefined && Object.keys(audit.displayedFilters).length > 0
                ? '筛选记录'
                : '全部记录'}
          </h2>
          {audit.selected.length > 0 ? (
            <>
              <span className={styles.selectionNote}>
                本页 {audit.selectedVisible} 条，另有 {audit.selected.length - audit.selectedVisible} 条未显示
              </span>
              <Button variant="ghost" disabled={audit.busy !== null} onClick={() => audit.setSelected([])}>
                取消选择
              </Button>
              <Button
                variant="ghost"
                className={styles.deleteAction}
                disabled={audit.busy !== null || audit.showingPrevious}
                onClick={(event) => audit.askDelete(audit.selected, event.currentTarget)}
              >
                <Trash2 />
                删除已选
              </Button>
            </>
          ) : null}
          <span className={styles.spacer} />
          <span className={styles.sortLabel}>
            {audit.logs.fetchStatus === 'paused'
              ? '读取已暂停 · '
              : audit.logs.isFetching && audit.snapshot !== undefined
                ? '正在更新 · '
                : ''}
            按时间倒序
          </span>
        </div>
        <AuditTable audit={audit} />
        <AuditPagination audit={audit} />
        <AuditDialogs audit={audit} />
        <AuditTools audit={audit} />
      </section>
    </AppFrame>
  )
}
