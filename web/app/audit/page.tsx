'use client'

import { Suspense, useRef, useSyncExternalStore } from 'react'
import { Code, Download, MoreHorizontal, RefreshCw, Trash2 } from '@/components/icons'
import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { WorkspaceNotice, WorkspaceNoticeStack } from '@/components/ui/operational-workspace'
import { PageLoading } from '@/components/ui/page-loading'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { TENANT_PERMISSIONS } from '@/lib/tenant-permissions'
import { AuditFiltersBar, AuditFilterSnapshot, AuditPresets } from './audit-filters'
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
          <AuditPresets audit={audit} />
          <div className={styles.headerActions}>
            <span className={styles.tenantLabel}>当前租户</span>
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
        <AuditFiltersBar audit={audit}>
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
          ) : (
            <span className={styles.recordCount}>
              {audit.total === undefined ? '记录数未取得' : `共 ${audit.total.toLocaleString('zh-CN')} 条`}
            </span>
          )}
          <span className={styles.sortLabel}>
            {audit.logs.fetchStatus === 'paused'
              ? '读取已暂停 · '
              : audit.logs.isFetching && audit.snapshot !== undefined
                ? '正在更新 · '
                : ''}
            按时间倒序
          </span>
        </AuditFiltersBar>
        {audit.filterError !== undefined ? (
          <div className="px-7">
            <WorkspaceNotice tone="error">{audit.filterError}</WorkspaceNotice>
          </div>
        ) : null}
        {audit.logs.isError && audit.snapshot === undefined ? (
          <div className="px-7">
            <WorkspaceNotice
              tone="error"
              title="读取审计日志失败"
              error={audit.logs.error}
              fallbackMessage="请稍后重试"
              retry={() => {
                void audit.logs.refetch({ cancelRefetch: false })
              }}
              retryLabel="重试读取"
              retryDisabled={audit.filterError !== undefined}
              pending={audit.logs.isFetching}
            />
          </div>
        ) : null}
        {(audit.logs.isError && audit.snapshot !== undefined) || audit.suggestionQuery.isError ? (
          <WorkspaceNoticeStack>
            {audit.logs.isError && audit.snapshot !== undefined ? (
              <WorkspaceNotice
                tone="warning"
                title="读取审计日志失败，保留已取得的结果"
                error={audit.logs.error}
                fallbackMessage="请稍后重试"
                retry={() => {
                  void audit.logs.refetch({ cancelRefetch: false })
                }}
                retryLabel="重试读取"
                retryDisabled={audit.filterError !== undefined}
                pending={audit.logs.isFetching}
              />
            ) : null}
            {audit.suggestionQuery.isError ? (
              <WorkspaceNotice
                tone="warning"
                title="近期筛选建议读取失败，仍可使用精确筛选"
                error={audit.suggestionQuery.error}
                fallbackMessage="请稍后重试"
                retry={() => {
                  void audit.suggestionQuery.refetch({ cancelRefetch: false })
                }}
                retryLabel="重试建议"
                pending={audit.suggestionQuery.isFetching}
              />
            ) : null}
          </WorkspaceNoticeStack>
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
        <AuditTable audit={audit} />
        <AuditPagination audit={audit} />
        <AuditDialogs audit={audit} />
        <AuditTools audit={audit} />
      </section>
    </AppFrame>
  )
}
