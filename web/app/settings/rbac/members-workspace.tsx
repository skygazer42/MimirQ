'use client'

import { useRef, useState } from 'react'
import { AppFrame } from '@/components/app-frame'
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  HelpCircle,
  KeyRound,
  Loader2,
  MoreHorizontal,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Users,
} from '@/components/icons'
import { Button } from '@/components/ui/button'
import { WorkspaceNotice, WorkspaceNoticeStack } from '@/components/ui/operational-workspace'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { TenantMember } from '@/lib/api/access'
import {
  formatMemberDate,
  isCurrentAccount,
  MEMBER_PAGE_SIZES,
  MEMBER_ROLES,
  memberIdentity,
  removalRestriction,
  roleChangeRestriction,
  roleLabel,
} from './members-model'
import { MembersConfirmations, IdentityToolsDialog, RoleHelpDialog } from './members-dialogs'
import { useMembers, type MembersController } from './use-members'
import styles from './members.module.css'

function RoleCell({ member, c }: { member: TenantMember; c: MembersController }) {
  const roleTrigger = useRef<HTMLButtonElement>(null)
  const tone = MEMBER_ROLES.find((role) => role.key === member.role)?.tone ?? 'neutral'
  const saving = c.busy?.kind === 'role' && c.busy.id === member.id
  const roleValue = member.role === '' ? 'unassigned' : member.role
  return (
    <div className={styles.roleCell} data-tone={tone}>
      {c.canManage && member.user_id ? (
        <Select
          value={roleValue}
          disabled={c.blocked}
          onValueChange={(desired) => {
            const role = MEMBER_ROLES.find((item) => item.key === desired)
            const trigger = roleTrigger.current
            if (role !== undefined && trigger !== null) c.requestRole(member, role.key, trigger)
          }}
        >
          <SelectTrigger
            ref={roleTrigger}
            aria-label={`角色 ${memberIdentity(member).name}`}
            data-member-role={member.id}
            className={styles.roleTrigger}
          >
            <span className={styles.roleDot} aria-hidden="true" />
            <SelectValue placeholder="未分配角色" />
          </SelectTrigger>
          <SelectContent align="start">
            {!MEMBER_ROLES.some((role) => role.key === member.role) ? (
              <SelectItem value={roleValue} disabled>
                {roleLabel(member.role)}
              </SelectItem>
            ) : null}
            {MEMBER_ROLES.map((role) => (
              <SelectItem
                key={role.key}
                value={role.key}
                disabled={Boolean(roleChangeRestriction(member, role.key, c.admins))}
              >
                {role.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <span className={styles.roleText}>
          <span className={styles.roleDot} aria-hidden="true" />
          {roleLabel(member.role)}
        </span>
      )}
      {saving ? (
        <span className={styles.saving} role="status">
          <Loader2 className="animate-spin motion-reduce:animate-none" />
          保存中
        </span>
      ) : null}
    </div>
  )
}

function MembersTable({ c }: { c: MembersController }) {
  return (
    <div className={styles.tableScroll} tabIndex={0} aria-label="成员列表滚动区域">
      <table className={styles.table} aria-label="成员权限">
        <thead>
          <tr>
            <th scope="col">成员</th>
            <th scope="col" className={styles.idColumn}>
              成员 ID
            </th>
            <th scope="col">角色</th>
            <th scope="col" className={styles.statusColumn}>
              状态
            </th>
            <th scope="col">
              <span className="sr-only">操作</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {c.paged.items.map((member) => {
            const who = memberIdentity(member),
              current = isCurrentAccount(member, c.accountId),
              emailSeparator = who.email.lastIndexOf('@')
            const reason = removalRestriction(member, c.accountId, c.admins)
            const accountId = member.user_id
            return (
              <tr
                key={member.id}
                data-member-id={member.id}
                data-current={current ? true : undefined}
                data-updated={c.updatedId === member.id ? true : undefined}
                onAnimationEnd={() => {
                  if (c.updatedId === member.id) c.setUpdatedId('')
                }}
              >
                <th scope="row">
                  <div className={styles.identity}>
                    <span
                      className={styles.avatar}
                      data-tone={MEMBER_ROLES.find((role) => role.key === member.role)?.tone}
                      aria-hidden="true"
                    >
                      {who.initial}
                    </span>
                    <div>
                      <div className={styles.identityLine}>
                        <strong>{who.name}</strong>
                        {current ? <span className={styles.current}>当前账号</span> : null}
                        {!member.is_active ? <span className={styles.inactive}>已停用</span> : null}
                      </div>
                      {who.email && who.email !== who.name ? (
                        <span className={styles.email}>
                          {emailSeparator > 0 ? (
                            <>
                              {who.email.slice(0, emailSeparator)}
                              <wbr />
                              {who.email.slice(emailSeparator)}
                            </>
                          ) : (
                            who.email
                          )}
                        </span>
                      ) : null}
                      {!member.user_id ? <span className={styles.email}>未关联账号</span> : null}
                    </div>
                  </div>
                </th>
                <td className={styles.idColumn}>
                  {accountId ? (
                    <button
                      type="button"
                      className={styles.idCopy}
                      aria-label={`复制成员 ID ${accountId}`}
                      onClick={() => {
                        void c.copyId(accountId)
                      }}
                    >
                      {accountId}
                      <Copy />
                    </button>
                  ) : (
                    <span className={styles.muted}>未关联账号</span>
                  )}
                </td>
                <td>
                  <RoleCell member={member} c={c} />
                </td>
                <td className={styles.statusColumn}>
                  <span className={styles.memberStatus} data-active={member.is_active}>
                    <span aria-hidden="true" />
                    {member.is_active ? '启用' : '已停用'}
                  </span>
                </td>
                <td>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={Boolean(c.busy)}
                        aria-label={`成员操作 ${who.name}`}
                        data-member-menu={member.id}
                      >
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="end"
                      className={styles.memberMenu}
                      onCloseAutoFocus={(event) => {
                        if (c.deletion) event.preventDefault()
                      }}
                    >
                      {accountId ? (
                        <DropdownMenuItem
                          onSelect={() => {
                            void c.copyId(accountId)
                          }}
                        >
                          <Copy />
                          复制成员 ID
                        </DropdownMenuItem>
                      ) : null}
                      {!member.user_id && !c.canManage ? (
                        <div className={styles.menuReason}>未关联账号，暂无可用操作。</div>
                      ) : null}
                      <div className={styles.mobileMemberMeta}>
                        <span>成员 ID</span>
                        <p>{member.user_id || '未关联账号'}</p>
                        <span>最近更新</span>
                        <p>{formatMemberDate(member.updated_at)}</p>
                      </div>
                      {c.canManage ? (
                        <>
                          <DropdownMenuSeparator />
                          {reason ? (
                            <div className={styles.menuReason}>{reason}</div>
                          ) : (
                            <DropdownMenuItem
                              disabled={c.blocked}
                              className="text-destructive"
                              onSelect={() => {
                                const trigger = document.querySelector<HTMLElement>(`[data-member-menu="${member.id}"]`)
                                if (trigger) c.openDeletion(member, trigger)
                              }}
                            >
                              <Trash2 />
                              移除成员
                            </DropdownMenuItem>
                          )}
                        </>
                      ) : null}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function MembersInsights({ c }: { c: MembersController }) {
  const current = c.members.find((member) => isCurrentAccount(member, c.accountId))
  const inactiveCount = c.members.filter((member) => !member.is_active).length
  return (
    <aside className={styles.insights} aria-label="成员权限概览">
      <section className={styles.roleDistribution} aria-labelledby="member-roles-title">
        <div className={styles.insightHeading}>
          <h2 id="member-roles-title">角色分布</h2>
          <span>已加载成员</span>
        </div>
        {c.membersQuery.data !== undefined ? (
          <div className={styles.roleList}>
            {MEMBER_ROLES.map((role) => {
              const count = c.members.filter((member) => member.role === role.key).length
              return (
                <button
                  key={role.key}
                  type="button"
                  className={styles.roleSummary}
                  data-tone={role.tone}
                  data-member-role-filter={role.key}
                  aria-pressed={c.role === role.key}
                  aria-label={`筛选${role.label}，${count} 名成员`}
                  disabled={Boolean(c.busy)}
                  onClick={() => c.setRole(c.role === role.key ? 'all' : role.key)}
                >
                  <span className={styles.roleDot} data-tone={role.tone} aria-hidden="true" />
                  <span>{role.label}</span>
                  <strong>{count}</strong>
                  <span className={styles.roleTrack} aria-hidden="true">
                    <span style={{ width: `${c.members.length === 0 ? 0 : (count / c.members.length) * 100}%` }} />
                  </span>
                </button>
              )
            })}
          </div>
        ) : (
          <p className={styles.insightHint}>
            {c.membersQuery.isError ? '成员列表未取得，暂无法统计。' : '正在读取角色分布…'}
          </p>
        )}
      </section>
      <section className={styles.securityOverview} aria-labelledby="member-security-title">
        <div className={styles.insightHeading}>
          <ShieldCheck aria-hidden="true" />
          <h2 id="member-security-title">权限安全概览</h2>
        </div>
        <div className={styles.currentAccount}>
          <span className={styles.eyebrow}>当前账号</span>
          <strong>{current ? memberIdentity(current).name : (c.accountId ?? '账号信息未取得')}</strong>
          {c.access.data ? <span>{roleLabel(c.access.data.role)}</span> : null}
        </div>
        {c.membersQuery.data !== undefined ? (
          <>
            <div className={styles.securityFact}>
              <span>有效管理成员</span>
              <strong>
                {c.admins}
                <small> 人</small>
              </strong>
            </div>
            <p className={styles.protection}>
              <span className={styles.protectionIcon} aria-hidden="true">
                <ShieldCheck />
              </span>
              <span>
                <strong>最后一名管理员保护</strong>至少保留一名有效管理员。
              </span>
            </p>
            {inactiveCount > 0 ? (
              <div className={styles.securityFact}>
                <span>已停用成员</span>
                <strong>
                  {inactiveCount}
                  <small> 人</small>
                </strong>
              </div>
            ) : null}
          </>
        ) : null}
        <p className={styles.insightHint}>内容访问需数据集和文档授权。</p>
      </section>
    </aside>
  )
}

export default function MembersWorkspace() {
  const c = useMembers(),
    [helpOpen, setHelpOpen] = useState(false),
    [identityOpen, setIdentityOpen] = useState(false)
  const hasFilters = c.query.trim() !== '' || c.role !== 'all' || c.scope !== 'all'
  const waitingForNetwork = c.membersQuery.isPending && c.membersQuery.isPaused
  const refreshing = c.membersQuery.isFetching || c.access.isFetching
  const tenantId = c.access.data?.tenant_id
  return (
    <AppFrame>
      <section className={styles.workspace} data-members-workspace>
        <header className={styles.header}>
          <div className={styles.heading}>
            <PageTitleIcon name="members-rbac" />
            <h1>成员权限</h1>
            {c.membersQuery.data !== undefined ? (
              <span className={styles.totalCount}>共 {c.members.length} 名成员</span>
            ) : null}
            {!c.canManage && c.access.data ? <span className={styles.readOnly}>只读</span> : null}
          </div>
          <div className={styles.headerActions}>
            <Button variant="ghost" aria-label="角色说明" data-members-help onClick={() => setHelpOpen(true)}>
              <HelpCircle />
              <span>角色说明</span>
            </Button>
            <Button
              variant="outline"
              aria-label="身份接入"
              data-members-identity
              disabled={tenantId === undefined}
              onClick={() => setIdentityOpen(true)}
            >
              <KeyRound />
              <span>身份接入</span>
            </Button>
            <Button
              variant="ghost"
              aria-label="刷新成员"
              disabled={Boolean(c.busy) || refreshing}
              aria-busy={refreshing}
              onClick={() => {
                void c.refresh()
              }}
            >
              {refreshing ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <RefreshCw />}
              <span>刷新</span>
            </Button>
          </div>
        </header>
        <div className={styles.body}>
          <div className={styles.mainPane}>
            <div className={styles.filters} aria-label="成员筛选">
              <SearchInput
                data-members-search
                aria-label="搜索成员"
                placeholder="搜索姓名、邮箱或成员 ID"
                value={c.query}
                onValueChange={c.setQuery}
                containerClassName={styles.searchWrap}
                inputClassName={styles.search}
                disabled={Boolean(c.busy)}
              />
              <Select value={c.role} onValueChange={c.setRole} disabled={Boolean(c.busy)}>
                <SelectTrigger className={styles.filter} aria-label="筛选角色">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部角色</SelectItem>
                  {MEMBER_ROLES.map((role) => (
                    <SelectItem key={role.key} value={role.key}>
                      {role.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={c.scope}
                onValueChange={(scope) => {
                  if (
                    scope === 'all' ||
                    scope === 'active' ||
                    scope === 'inactive' ||
                    scope === 'current' ||
                    scope === 'others' ||
                    scope === 'unassigned'
                  )
                    c.setScope(scope)
                }}
                disabled={Boolean(c.busy)}
              >
                <SelectTrigger className={styles.filter} aria-label="筛选成员范围">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部状态 / 范围</SelectItem>
                  <SelectItem value="active">启用成员</SelectItem>
                  <SelectItem value="inactive">已停用成员</SelectItem>
                  <SelectItem value="current" disabled={!c.accountId}>
                    当前账号
                  </SelectItem>
                  <SelectItem value="others" disabled={!c.accountId}>
                    其他成员
                  </SelectItem>
                  <SelectItem value="unassigned">未分配角色</SelectItem>
                </SelectContent>
              </Select>
              {hasFilters ? (
                <Button
                  variant="ghost"
                  className={styles.clearFilters}
                  disabled={Boolean(c.busy)}
                  onClick={c.clearFilters}
                >
                  清除筛选
                </Button>
              ) : null}
            </div>
            {c.membersQuery.isError && !c.membersQuery.data ? (
              <div className="px-7 pt-3">
                <WorkspaceNotice
                  tone="error"
                  title="成员列表读取失败"
                  error={c.membersQuery.error}
                  fallbackMessage="请稍后重试"
                  retry={() => {
                    void c.refresh()
                  }}
                  retryLabel="重新读取"
                  pending={c.membersQuery.isFetching}
                />
              </div>
            ) : null}
            {c.access.isError || (c.membersQuery.isError && Boolean(c.membersQuery.data)) || Boolean(c.roleFailure) ? (
              <WorkspaceNoticeStack>
                {c.access.isError ? (
                  <WorkspaceNotice
                    tone="warning"
                    title="权限信息更新失败"
                    error={c.access.error}
                    fallbackMessage="无法读取权限"
                    retry={() => {
                      void c.access.refetch()
                    }}
                    retryLabel="重新校验"
                    pending={c.access.isFetching}
                  />
                ) : null}
                {c.membersQuery.isError && c.membersQuery.data ? (
                  <WorkspaceNotice
                    tone="warning"
                    title="成员列表更新失败，保留上次数据"
                    error={c.membersQuery.error}
                    fallbackMessage="请稍后重试"
                    retry={() => {
                      void c.refresh()
                    }}
                    retryLabel="重新读取"
                    pending={c.membersQuery.isFetching}
                  />
                ) : null}
                {c.roleFailure ? (
                  <WorkspaceNotice
                    tone="error"
                    title={`${memberIdentity(c.roleFailure.member).name}改为${roleLabel(c.roleFailure.desired)}失败`}
                    retry={() => {
                      if (c.roleFailure) void c.saveRole(c.roleFailure)
                    }}
                    retryLabel="重试修改"
                    retryDisabled={c.blocked || !c.canManage}
                    onDismiss={() => c.setRoleFailure(null)}
                    dismissLabel="关闭角色错误"
                  >
                    {`${c.roleFailure.message}。仍显示上次读取的角色。`}
                  </WorkspaceNotice>
                ) : null}
              </WorkspaceNoticeStack>
            ) : null}
            {c.membersQuery.isPending ? (
              <div className={styles.empty} role="status">
                {waitingForNetwork ? null : <Loader2 className="animate-spin motion-reduce:animate-none" />}
                <p>{waitingForNetwork ? '等待网络连接' : '正在读取成员…'}</p>
              </div>
            ) : c.paged.items.length ? (
              <MembersTable c={c} />
            ) : !c.membersQuery.isError ? (
              <div className={styles.empty}>
                <Users />
                <h2>{hasFilters ? '没有匹配的成员' : '还没有成员'}</h2>
                {hasFilters ? <p>请调整搜索内容或清除上方筛选条件。</p> : <p>暂无成员记录。</p>}
              </div>
            ) : (
              <div className={styles.remainingSpace} />
            )}
            <footer className={styles.footer}>
              <span aria-live="polite">
                {c.membersQuery.data
                  ? hasFilters
                    ? `${c.paged.total} / ${c.members.length} 名成员`
                    : `共 ${c.members.length} 名成员`
                  : c.membersQuery.isError
                    ? '未取得成员列表'
                    : null}
              </span>
              <span className={styles.spacer} />
              {c.paged.total > 0 ? (
                <>
                  <Select
                    value={String(c.size)}
                    onValueChange={(size) => c.setSize(Number(size))}
                    disabled={Boolean(c.busy)}
                  >
                    <SelectTrigger className={styles.pageSize} aria-label="每页成员数">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {MEMBER_PAGE_SIZES.map((size) => (
                        <SelectItem key={size} value={String(size)}>
                          {size} 条 / 页
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {c.membersQuery.data !== undefined && (
                    <span className={styles.pageRange}>
                      {c.paged.start}–{c.paged.end}
                    </span>
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="上一页成员"
                    disabled={c.paged.page <= 1 || Boolean(c.busy)}
                    onClick={() => c.setPage(c.paged.page - 1)}
                  >
                    <ChevronLeft />
                  </Button>
                  <span>
                    {c.paged.page} / {c.paged.pages}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="下一页成员"
                    disabled={c.paged.page >= c.paged.pages || Boolean(c.busy)}
                    onClick={() => c.setPage(c.paged.page + 1)}
                  >
                    <ChevronRight />
                  </Button>
                </>
              ) : null}
            </footer>
          </div>
          <MembersInsights c={c} />
        </div>
        <RoleHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
        {identityOpen && tenantId !== undefined ? (
          <IdentityToolsDialog tenantId={tenantId} onClose={() => setIdentityOpen(false)} />
        ) : null}
        <MembersConfirmations c={c} />
      </section>
    </AppFrame>
  )
}
