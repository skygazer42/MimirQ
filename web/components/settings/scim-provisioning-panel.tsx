'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { CheckCircle2, ExternalLink, EyeOff, Loader2, ShieldCheck, Users } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Textarea } from '@/components/ui/textarea'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { scimApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'

type ResultState = {
  title: string
  payload: unknown
}

function parseJson(raw: string) {
  const value = raw.trim()
  return value ? JSON.parse(value) : {}
}

export function ScimProvisioningPanel() {
  const [tenantId, setTenantId] = useState('')
  const [scimToken, setScimToken] = useState('')
  const [groupId, setGroupId] = useState('')
  const [userId, setUserId] = useState('')
  const [groupPayload, setGroupPayload] = useState('{\n  "displayName": "Engineering"\n}')
  const [userPayload, setUserPayload] = useState('{\n  "userName": "user@example.com",\n  "active": true\n}')
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<ResultState | null>(null)

  useEffect(() => {
    const storedTenant = globalThis.window.localStorage.getItem('mimirq_tenant_id')
    if (storedTenant) setTenantId(storedTenant)
  }, [])

  const base = { tenantId: tenantId.trim(), scimToken: scimToken.trim() }
  const baseDisabled = Boolean(busy) || !base.tenantId || !base.scimToken
  const configured = Boolean(base.tenantId && base.scimToken)

  async function runAction(key: string, title: string, action: () => Promise<unknown>) {
    setBusy(key)
    try {
      const payload = await action()
      setResult({ title, payload })
      toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel padding="md" className="rounded-2xl border-slate-200/80 bg-white shadow-[0_1px_3px_rgba(15,23,42,0.04)]">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
            <Users className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2 text-[15px] font-semibold text-slate-950">
            SCIM Provisioning
              <span className={cn(
                'rounded-full border px-2 py-0.5 text-[10px] font-semibold',
                configured ? 'border-emerald-100 bg-emerald-50 text-emerald-700' : 'border-slate-200 bg-slate-50 text-slate-500'
              )}>
                {configured ? '可测试' : '未启用'}
              </span>
          </div>
            <p className="mt-1 text-[12px] leading-5 text-slate-500">
              自动化同步组织用户与群组到 MimirQ，通过 SCIM 协议实现成员生命周期管理。
          </p>
        </div>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-slate-400 motion-reduce:animate-none" /> : null}
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(220px,1fr)_minmax(260px,1.6fr)_auto] lg:items-end">
        <Field label="租户 ID">
          <Input value={tenantId} onChange={(event) => setTenantId(event.target.value)} className="h-9 rounded-lg border-slate-200 bg-slate-50/50 font-mono text-[12px] shadow-none" placeholder="X-Tenant-ID" />
        </Field>
        <Field label="SCIM Token">
          <div className="relative">
            <Input type="password" value={scimToken} onChange={(event) => setScimToken(event.target.value)} className="h-9 rounded-lg border-slate-200 bg-slate-50/50 pr-9 font-mono text-[12px] shadow-none" placeholder="输入 SCIM Token" />
            <EyeOff className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          </div>
        </Field>
        <div className="flex flex-wrap gap-2">
          <ActionButton busy={busy === 'provider'} disabled={baseDisabled} label="测试连接" onClick={() => runAction('provider', 'SCIM 服务配置', () => scimApi.getServiceProviderConfig(base))} />
          <Button variant="outline" className="h-9 gap-2 rounded-lg border-slate-200 bg-white px-3 text-[12px] font-semibold text-slate-600" disabled>
            <ExternalLink className="h-3.5 w-3.5" />
            查看文档
          </Button>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Pill busy={busy === 'provider'} disabled={baseDisabled} label="ServiceProviderConfig" onClick={() => runAction('provider', 'SCIM 服务配置', () => scimApi.getServiceProviderConfig(base))} />
        <Pill busy={busy === 'schemas'} disabled={baseDisabled} label="Schemas" onClick={() => runAction('schemas', 'SCIM Schemas', () => scimApi.listSchemas(base))} />
        <Pill busy={busy === 'resource-types'} disabled={baseDisabled} label="ResourceTypes" onClick={() => runAction('resource-types', 'SCIM ResourceTypes', () => scimApi.listResourceTypes(base))} />
        <Pill busy={busy === 'groups'} disabled={baseDisabled} label="Group 映射" onClick={() => runAction('groups', 'SCIM Group 列表', () => scimApi.listGroups({ ...base, count: 50 }))} />
        <Pill busy={busy === 'users'} disabled={baseDisabled} label="User 映射" onClick={() => runAction('users', 'SCIM User 列表', () => scimApi.listUsers({ ...base, count: 50 }))} />
      </div>

      <details className="mt-3 rounded-xl border border-slate-200/80 bg-slate-50/60 p-3">
        <summary className="cursor-pointer text-[12px] font-semibold text-slate-700">高级写入参数</summary>
        <p className="mt-1 text-[12px] leading-5 text-slate-500">仅在需要定位单个 User/Group 或执行创建、替换、Patch、删除时填写。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <Field label="Group">
            <Input value={groupId} onChange={(event) => setGroupId(event.target.value)} className="h-8 rounded-lg border-slate-200 bg-white font-mono text-xs shadow-none" />
          </Field>
          <Field label="User">
            <Input value={userId} onChange={(event) => setUserId(event.target.value)} className="h-8 rounded-lg border-slate-200 bg-white font-mono text-xs shadow-none" />
          </Field>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <ActionButton busy={busy === 'group'} disabled={baseDisabled || !groupId.trim()} label="Group 详情" onClick={() => runAction('group', 'SCIM Group 详情', () => scimApi.getGroup({ ...base, groupId: groupId.trim() }))} />
          <ActionButton busy={busy === 'create-group'} disabled={baseDisabled} label="创建 Group" onClick={() => runAction('create-group', '创建 SCIM Group', () => scimApi.createGroup({ ...base, payload: parseJson(groupPayload) }))} />
          <ActionButton busy={busy === 'update-group'} disabled={baseDisabled || !groupId.trim()} label="替换 Group" onClick={() => runAction('update-group', '替换 SCIM Group', () => scimApi.updateGroup({ ...base, groupId: groupId.trim(), payload: parseJson(groupPayload) }))} />
          <ActionButton busy={busy === 'patch-group'} disabled={baseDisabled || !groupId.trim()} label="Patch Group" onClick={() => runAction('patch-group', 'Patch SCIM Group', () => scimApi.patchGroup({ ...base, groupId: groupId.trim(), payload: parseJson(groupPayload) }))} />
          <ConfirmDialog
            title="删除 SCIM Group？"
            description={`将删除 groupId=${groupId.trim() || '-'}。请确认该组不再参与外部身份同步或访问控制。`}
            confirmLabel="删除 Group"
            onConfirm={() => runAction('delete-group', '删除 SCIM Group', () => scimApi.deleteGroup({ ...base, groupId: groupId.trim() }))}
          >
            <Button variant="outline" className="h-8 gap-1.5 rounded-lg border-slate-200 bg-white px-3 text-xs font-semibold" disabled={baseDisabled || !groupId.trim()}>
              {busy === 'delete-group' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <ShieldCheck className="h-3.5 w-3.5" />}
              删除 Group
            </Button>
          </ConfirmDialog>
          <ActionButton busy={busy === 'user'} disabled={baseDisabled || !userId.trim()} label="User 详情" onClick={() => runAction('user', 'SCIM User 详情', () => scimApi.getUser({ ...base, userId: userId.trim() }))} />
          <ActionButton busy={busy === 'create-user'} disabled={baseDisabled} label="创建 User" onClick={() => runAction('create-user', '创建 SCIM User', () => scimApi.createUser({ ...base, payload: parseJson(userPayload) }))} />
          <ActionButton busy={busy === 'patch-user'} disabled={baseDisabled || !userId.trim()} label="Patch User" onClick={() => runAction('patch-user', 'Patch SCIM User', () => scimApi.patchUser({ ...base, userId: userId.trim(), payload: parseJson(userPayload) }))} />
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <Field label="Group 请求体（JSON）">
            <Textarea value={groupPayload} onChange={(event) => setGroupPayload(event.target.value)} className="min-h-[128px] rounded-lg border-slate-200 bg-white font-mono text-xs shadow-none" />
          </Field>
          <Field label="User 请求体（JSON）">
            <Textarea value={userPayload} onChange={(event) => setUserPayload(event.target.value)} className="min-h-[128px] rounded-lg border-slate-200 bg-white font-mono text-xs shadow-none" />
          </Field>
        </div>
      </details>

      <OperationResultPanel className="mt-3" title="SCIM 结果" result={result} emptyMessage="输入租户和 token 后执行操作；这里展示摘要，原始响应默认收起。" />
    </Panel>
  )
}

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] font-semibold text-slate-500">{label}</Label>
      {children}
    </div>
  )
}

function ActionButton({
  busy,
  disabled,
  label,
  onClick,
}: Readonly<{
  busy: boolean
  disabled: boolean
  label: string
  onClick: () => Promise<void>
}>) {
  return (
    <Button variant="outline" className="h-9 gap-1.5 rounded-lg border-slate-200 bg-white px-3 text-[12px] font-semibold text-slate-600 shadow-none" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <ShieldCheck className="h-3.5 w-3.5" />}
      {label}
    </Button>
  )
}

function Pill({
  busy,
  disabled,
  label,
  onClick,
}: Readonly<{
  busy: boolean
  disabled: boolean
  label: string
  onClick: () => Promise<void>
}>) {
  return (
    <Button variant="outline" className="h-7 gap-1.5 rounded-full border-slate-200 bg-slate-50 px-3 text-[11px] font-semibold text-slate-600 shadow-none hover:bg-white" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" /> : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
      {label}
    </Button>
  )
}
