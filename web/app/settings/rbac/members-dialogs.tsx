'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { Download, Loader2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { authApi, scimApi } from '@/lib/api'
import { formatApiError, toApiErrorInfo } from '@/lib/api-errors'
import { MEMBER_ROLES, memberIdentity, roleLabel } from './members-model'
import type { MembersController } from './use-members'
import styles from './members.module.css'

export function RoleHelpDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className={styles.helpDialog} onCloseAutoFocus={event => { event.preventDefault(); document.querySelector<HTMLElement>('[data-members-help]')?.focus() }}>
    <DialogHeader className={styles.dialogHeader}><DialogTitle>角色说明</DialogTitle><DialogDescription>角色控制租户管理权限，内容访问仍需数据集和文档授权。</DialogDescription></DialogHeader>
    <div className={styles.dialogBody}><dl className={styles.roleHelp}>{MEMBER_ROLES.map(role => <div key={role.key}><dt><span className={styles.roleDot} data-tone={role.tone} />{role.label}</dt><dd>{role.description}</dd></div>)}</dl><p className={styles.hint}>至少保留一名有效管理员。</p></div>
  </DialogContent></Dialog>
}

export function IdentityToolsDialog({ tenantId, onClose }: { tenantId: string; onClose: () => void }) {
  const [tenant, setTenant] = useState(tenantId), [token, setToken] = useState(''), [provider, setProvider] = useState('')
  const [busy, setBusy] = useState<'scim' | 'saml' | null>(null), [error, setError] = useState('')
  async function testScim(event: React.FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy('scim'); setError('')
    try {
      await scimApi.getServiceProviderConfig({ tenantId: tenant.trim(), scimToken: token.trim() })
      toast.success('已读取 SCIM 服务配置')
    } catch (cause) { setError(formatApiError(cause, 'SCIM 服务配置读取失败')) }
    finally { setBusy(null) }
  }
  async function downloadMetadata(event: React.FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy('saml'); setError('')
    try {
      const metadata = await authApi.samlMetadata({ provider_id: provider.trim() || null })
      const url = URL.createObjectURL(new Blob([metadata], { type: 'application/xml;charset=utf-8' }))
      const link = document.createElement('a')
      link.href = url; link.download = 'saml-metadata.xml'; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      toast.success('已下载 SAML 元数据')
    } catch (cause) {
      const info = toApiErrorInfo(cause, 'SAML 元数据读取失败')
      setError(info.message.trim().toLowerCase() === 'saml not configured' ? '尚未配置 SAML 身份源，暂时无法下载元数据。' : formatApiError(cause, 'SAML 元数据读取失败'))
    } finally { setBusy(null) }
  }
  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose() }}><DialogContent className={styles.identityDialog} onCloseAutoFocus={event => { event.preventDefault(); document.querySelector<HTMLElement>('[data-members-identity]')?.focus() }}>
    <DialogHeader className={styles.dialogHeader}><DialogTitle>身份接入</DialogTitle><DialogDescription>测试 SCIM 服务配置，或下载 SAML 元数据。</DialogDescription></DialogHeader>
    <Tabs defaultValue="scim" className={styles.identityTabs} onValueChange={() => setError('')}><TabsList className={styles.identityTabList}><TabsTrigger value="scim" disabled={Boolean(busy)}>SCIM</TabsTrigger><TabsTrigger value="saml" disabled={Boolean(busy)}>SAML</TabsTrigger></TabsList>
      <TabsContent value="scim" className={styles.tabContent}><form onSubmit={event => { void testScim(event) }}><div className={styles.dialogBody}>
        <div className={styles.field}><Label htmlFor="members-scim-tenant">租户 ID</Label><Input id="members-scim-tenant" value={tenant} disabled={Boolean(busy)} required autoComplete="off" onChange={event => { setTenant(event.target.value); setError('') }} /></div>
        <div className={styles.field}><Label htmlFor="members-scim-token">SCIM Token</Label><Input id="members-scim-token" type="password" autoComplete="off" value={token} required disabled={Boolean(busy)} onChange={event => { setToken(event.target.value); setError('') }} /></div>
        <p className={styles.hint}>凭据仅用于本次请求，关闭窗口后清除。测试不会同步或修改成员。</p>{error ? <p role="alert" className={styles.formError}>{error}</p> : null}
      </div><div className={styles.dialogFooter}><Button type="button" variant="ghost" disabled={Boolean(busy)} onClick={onClose}>关闭</Button><Button className={styles.primary} type="submit" disabled={Boolean(busy) || !tenant.trim() || !token.trim()}>{busy === 'scim' ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : null}{busy === 'scim' ? '读取中' : '测试服务配置'}</Button></div></form></TabsContent>
      <TabsContent value="saml" className={styles.tabContent}><form onSubmit={event => { void downloadMetadata(event) }}><div className={styles.dialogBody}>
        <div className={styles.field}><Label htmlFor="members-saml-provider">身份源 ID <span>选填</span></Label><Input id="members-saml-provider" value={provider} autoComplete="off" placeholder="留空使用默认身份源" disabled={Boolean(busy)} onChange={event => { setProvider(event.target.value); setError('') }} /></div>
        <p className={styles.hint}>下载当前服务的 XML 元数据，用于对接已有 SAML 身份源。</p>{error ? <p role="alert" className={styles.formError}>{error}</p> : null}
      </div><div className={styles.dialogFooter}><Button type="button" variant="ghost" disabled={Boolean(busy)} onClick={onClose}>关闭</Button><Button className={styles.primary} type="submit" disabled={Boolean(busy)}>{busy === 'saml' ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Download />}{busy === 'saml' ? '读取中' : '下载元数据'}</Button></div></form></TabsContent>
    </Tabs>
  </DialogContent></Dialog>
}

export function MembersConfirmations({ c }: { c: MembersController }) {
  return <>
    <AlertDialog open={Boolean(c.deletion)} onOpenChange={open => { if (!open && !c.busy) c.setDeletion(null) }}><AlertDialogContent className={styles.confirmDialog} onCloseAutoFocus={event => { event.preventDefault(); c.restoreFocus() }}>
      <AlertDialogHeader className={styles.dialogHeader}><AlertDialogTitle>移除成员</AlertDialogTitle><AlertDialogDescription>将此成员移出当前租户，并撤销组成员关系及显式的数据集、文档授权。账号本身不会被删除。</AlertDialogDescription></AlertDialogHeader>
      <div className={styles.dialogBody}>{c.deletion ? <div className={styles.target}><strong>{memberIdentity(c.deletion).name}</strong><span>{c.deletion.user_id}</span><span>{roleLabel(c.deletion.role)}</span></div> : null}{c.deleteError ? <p role="alert" className={styles.formError}>{c.deleteError}</p> : null}</div>
      <div className={styles.dialogFooter}><Button variant="ghost" disabled={Boolean(c.busy)} onClick={() => c.setDeletion(null)}>取消</Button><Button variant="destructive" disabled={Boolean(c.busy)} onClick={() => { void c.removeMember() }}>{c.busy?.kind === 'remove' ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : null}{c.busy?.kind === 'remove' ? '移除中' : '移除成员'}</Button></div>
    </AlertDialogContent></AlertDialog>
    <AlertDialog open={Boolean(c.demotion)} onOpenChange={open => { if (!open && !c.busy) c.setDemotion(null) }}><AlertDialogContent className={styles.confirmDialog} onCloseAutoFocus={event => { event.preventDefault(); c.restoreFocus() }}>
      <AlertDialogHeader className={styles.dialogHeader}><AlertDialogTitle>修改自己的角色？</AlertDialogTitle><AlertDialogDescription>修改后将失去成员和设置管理权限。如需恢复，需要其他管理员调整。</AlertDialogDescription></AlertDialogHeader>
      <div className={styles.dialogBody}>{c.demotion ? <div className={styles.target}><strong>{memberIdentity(c.demotion.member).name}</strong><span>{roleLabel(c.demotion.member.role)} → {roleLabel(c.demotion.desired)}</span></div> : null}</div>
      <div className={styles.dialogFooter}><Button variant="ghost" disabled={Boolean(c.busy)} onClick={() => c.setDemotion(null)}>取消</Button><Button className={styles.primary} disabled={Boolean(c.busy)} onClick={() => { if (c.demotion) void c.saveRole(c.demotion) }}>{c.busy?.kind === 'role' ? '保存中' : '修改我的角色'}</Button></div>
    </AlertDialogContent></AlertDialog>
  </>
}
