'use client'

import { useState } from 'react'
import { AppFrame } from '@/components/app-frame'
import { ChevronLeft, ChevronRight, Copy, HelpCircle, KeyRound, Loader2, MoreHorizontal, RefreshCw, Trash2, Users, X } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { formatApiError } from '@/lib/api-errors'
import type { TenantMember } from '@/lib/api/access'
import { formatMemberDate, isCurrentAccount, MEMBER_PAGE_SIZES, MEMBER_ROLES, memberIdentity, removalRestriction, roleChangeRestriction, roleLabel, type MemberRole, type MemberScope } from './members-model'
import { MembersConfirmations, IdentityToolsDialog, RoleHelpDialog } from './members-dialogs'
import { useMembers, type MembersController } from './use-members'
import styles from './members.module.css'

function RoleCell({ member, c }: { member: TenantMember; c: MembersController }) {
  const tone = MEMBER_ROLES.find(role => role.key === member.role)?.tone ?? 'neutral'
  const saving = c.busy?.kind === 'role' && c.busy.id === member.id
  return <div className={styles.roleCell} data-tone={tone}>
    {c.canManage && member.user_id ? <Select value={member.role || 'unassigned'} disabled={c.blocked} onValueChange={desired => {
      const trigger = document.querySelector<HTMLElement>(`[data-member-role="${member.id}"]`)
      if (trigger) c.requestRole(member, desired as MemberRole, trigger)
    }}>
      <SelectTrigger aria-label={`角色 ${memberIdentity(member).name}`} data-member-role={member.id} className={styles.roleTrigger}><span className={styles.roleDot} aria-hidden="true" /><SelectValue placeholder="未分配角色" /></SelectTrigger>
      <SelectContent align="start">
        {!MEMBER_ROLES.some(role => role.key === member.role) ? <SelectItem value={member.role || 'unassigned'} disabled>{roleLabel(member.role)}</SelectItem> : null}
        {MEMBER_ROLES.map(role => <SelectItem key={role.key} value={role.key} disabled={Boolean(roleChangeRestriction(member, role.key, c.admins))}>{role.label}</SelectItem>)}
      </SelectContent>
    </Select> : <span className={styles.roleText}><span className={styles.roleDot} aria-hidden="true" />{roleLabel(member.role)}</span>}
    {saving ? <span className={styles.saving} role="status"><Loader2 className="animate-spin motion-reduce:animate-none" />保存中</span> : null}
  </div>
}

function MembersTable({ c }: { c: MembersController }) {
  return <div className={styles.tableScroll} tabIndex={0} aria-label="成员列表滚动区域">
    <table className={styles.table} aria-label="成员权限"><thead><tr><th scope="col">成员</th><th scope="col" className={styles.idColumn}>成员 ID</th><th scope="col">角色</th><th scope="col" className={styles.dateColumn}>最近更新</th><th scope="col"><span className="sr-only">操作</span></th></tr></thead>
      <tbody>{c.paged.items.map(member => {
        const who = memberIdentity(member), current = isCurrentAccount(member, c.accountId), emailSeparator = who.email.lastIndexOf('@')
        const reason = removalRestriction(member, c.accountId, c.admins)
        return <tr key={member.id} data-member-id={member.id} data-current={current || undefined} data-updated={c.updatedId === member.id || undefined} onAnimationEnd={() => { if (c.updatedId === member.id) c.setUpdatedId('') }}>
          <th scope="row"><div className={styles.identity}><span className={styles.avatar} aria-hidden="true">{who.initial}</span><div><div className={styles.identityLine}><strong>{who.name}</strong>{current ? <span className={styles.current}>当前账号</span> : null}{!member.is_active ? <span className={styles.inactive}>已停用</span> : null}</div>{who.email && who.email !== who.name ? <span className={styles.email}>{emailSeparator > 0 ? <>{who.email.slice(0, emailSeparator)}<wbr />{who.email.slice(emailSeparator)}</> : who.email}</span> : null}{!member.user_id ? <span className={styles.email}>未关联账号</span> : null}</div></div></th>
          <td className={styles.idColumn}>{member.user_id ? <button className={styles.idCopy} aria-label={`复制成员 ID ${member.user_id}`} onClick={() => { void c.copyId(member.user_id!) }}>{member.user_id}<Copy /></button> : <span className={styles.muted}>未关联账号</span>}</td>
          <td><RoleCell member={member} c={c} /></td>
          <td className={styles.dateColumn}>{member.updated_at ? <time dateTime={member.updated_at}>{formatMemberDate(member.updated_at)}</time> : <span>未记录</span>}</td>
          <td><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" disabled={Boolean(c.busy)} aria-label={`成员操作 ${who.name}`} data-member-menu={member.id}><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className={styles.memberMenu} onCloseAutoFocus={event => { if (c.deletion) event.preventDefault() }}>
              {member.user_id ? <DropdownMenuItem onSelect={() => { void c.copyId(member.user_id!) }}><Copy />复制成员 ID</DropdownMenuItem> : null}
              {!member.user_id && !c.canManage ? <div className={styles.menuReason}>未关联账号，暂无可用操作。</div> : null}
              <div className={styles.mobileMemberMeta}><span>成员 ID</span><p>{member.user_id || '未关联账号'}</p><span>最近更新</span><p>{formatMemberDate(member.updated_at)}</p></div>
              {c.canManage ? <><DropdownMenuSeparator />{reason ? <div className={styles.menuReason}>{reason}</div> : <DropdownMenuItem disabled={c.blocked} className="text-destructive" onSelect={() => {
                const trigger = document.querySelector<HTMLElement>(`[data-member-menu="${member.id}"]`)
                if (trigger) c.openDeletion(member, trigger)
              }}><Trash2 />移除成员</DropdownMenuItem>}</> : null}
            </DropdownMenuContent>
          </DropdownMenu></td>
        </tr>
      })}</tbody>
    </table>
  </div>
}

export default function MembersWorkspace() {
  const c = useMembers(), [helpOpen, setHelpOpen] = useState(false), [identityOpen, setIdentityOpen] = useState(false)
  const hasFilters = Boolean(c.query || c.role !== 'all' || c.scope !== 'all')
  return <AppFrame><section className={styles.workspace} data-members-workspace>
    <header className={styles.header}><div className={styles.heading}><PageTitleIcon name="members-rbac" /><h1>成员权限</h1></div><div className={styles.headerActions}>
      <Button variant="ghost" aria-label="角色说明" data-members-help onClick={() => setHelpOpen(true)}><HelpCircle /><span>角色说明</span></Button>
      <Button variant="outline" aria-label="身份接入" data-members-identity onClick={() => setIdentityOpen(true)}><KeyRound /><span>身份接入</span></Button>
    </div></header>
    <div className={styles.filters} aria-label="成员筛选">
      <SearchInput data-members-search aria-label="搜索成员" placeholder="搜索姓名、邮箱或成员 ID" value={c.query} onValueChange={c.setQuery} containerClassName={styles.searchWrap} inputClassName={styles.search} disabled={Boolean(c.busy)} />
      <Select value={c.role} onValueChange={c.setRole} disabled={Boolean(c.busy)}><SelectTrigger className={styles.filter} aria-label="筛选角色"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">全部角色</SelectItem>{MEMBER_ROLES.map(role => <SelectItem key={role.key} value={role.key}>{role.label}</SelectItem>)}</SelectContent></Select>
      <Select value={c.scope} onValueChange={scope => c.setScope(scope as MemberScope)} disabled={Boolean(c.busy)}><SelectTrigger className={styles.filter} aria-label="筛选成员范围"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">全部成员</SelectItem><SelectItem value="current" disabled={!c.accountId}>当前账号</SelectItem><SelectItem value="others" disabled={!c.accountId}>其他成员</SelectItem><SelectItem value="unassigned">未分配角色</SelectItem></SelectContent></Select>
      {hasFilters ? <Button variant="ghost" className={styles.clearFilters} disabled={Boolean(c.busy)} onClick={c.clearFilters}>清除筛选</Button> : null}
      <span className={styles.spacer} />
      <Button variant="ghost" className={styles.refresh} aria-label="刷新成员" disabled={Boolean(c.busy) || c.membersQuery.isFetching} onClick={() => { void c.refresh() }}>{c.membersQuery.isFetching ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <RefreshCw />}<span>刷新</span></Button>
    </div>
    <div className={styles.listHeading}><h2>租户成员</h2>{c.membersQuery.data ? <span>{c.members.length} 人</span> : null}<span className={styles.spacer} />{!c.canManage && c.access.data ? <span>只读</span> : null}</div>
    {c.access.isError ? <div className={styles.notice} role="alert"><span>权限信息更新失败：{formatApiError(c.access.error, '无法读取权限')}</span><button onClick={() => { void c.access.refetch() }}>重新校验</button></div> : null}
    {c.membersQuery.isError ? <div className={styles.notice} role="alert"><span>{c.membersQuery.data ? '成员列表更新失败，保留上次数据。' : '成员列表读取失败。'}{formatApiError(c.membersQuery.error, '请稍后重试')}</span><button disabled={c.membersQuery.isFetching} onClick={() => { void c.refresh() }}>重新读取</button></div> : null}
    {c.roleFailure ? <div className={styles.notice} role="alert"><span>{memberIdentity(c.roleFailure.member).name}改为{roleLabel(c.roleFailure.desired)}失败：{c.roleFailure.message}。仍显示上次读取的角色。</span><button disabled={c.blocked || !c.canManage} onClick={() => { if (c.roleFailure) void c.saveRole(c.roleFailure) }}>重试修改</button><button aria-label="关闭角色错误" onClick={() => c.setRoleFailure(null)}><X /></button></div> : null}
    {c.membersQuery.isPending ? <div className={styles.empty} role="status"><Loader2 className="animate-spin motion-reduce:animate-none" /><p>正在读取成员…</p></div> : c.paged.items.length ? <MembersTable c={c} /> : !c.membersQuery.isError ? <div className={styles.empty}><Users /><h2>{hasFilters ? '没有匹配的成员' : '还没有成员'}</h2>{hasFilters ? <Button variant="ghost" onClick={c.clearFilters}>清除筛选</Button> : <p>成员注册或加入租户后会显示在这里。</p>}</div> : <div className={styles.remainingSpace} />}
    <footer className={styles.footer}><span aria-live="polite">{c.membersQuery.data ? hasFilters ? `${c.paged.total} / ${c.members.length} 名成员` : `共 ${c.members.length} 名成员` : c.membersQuery.isPending ? '正在读取' : '未取得成员列表'}</span><span className={styles.spacer} /><Select value={String(c.size)} onValueChange={size => c.setSize(Number(size))} disabled={Boolean(c.busy)}><SelectTrigger className={styles.pageSize} aria-label="每页成员数"><SelectValue /></SelectTrigger><SelectContent>{MEMBER_PAGE_SIZES.map(size => <SelectItem key={size} value={String(size)}>{size} 条 / 页</SelectItem>)}</SelectContent></Select><span className={styles.pageRange}>{c.paged.start}–{c.paged.end}</span><Button variant="ghost" size="icon" aria-label="上一页成员" disabled={c.paged.page <= 1 || Boolean(c.busy)} onClick={() => c.setPage(c.paged.page - 1)}><ChevronLeft /></Button><span>{c.paged.page} / {c.paged.pages}</span><Button variant="ghost" size="icon" aria-label="下一页成员" disabled={c.paged.page >= c.paged.pages || Boolean(c.busy)} onClick={() => c.setPage(c.paged.page + 1)}><ChevronRight /></Button></footer>
    <RoleHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    {identityOpen ? <IdentityToolsDialog tenantId={c.access.data?.tenant_id || ''} onClose={() => setIdentityOpen(false)} /> : null}
    <MembersConfirmations c={c} />
  </section></AppFrame>
}
