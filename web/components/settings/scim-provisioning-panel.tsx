'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { Loader2, ShieldCheck, Users } from 'lucide-react'
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
import { detachPromise } from '@/lib/utils'

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
    <Panel padding="md" className="border-border/70 bg-card/95">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Users className="h-4 w-4 text-info" />
            SCIM Provisioning
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            面向身份同步的 SCIM v2 操作入口；常用只查服务配置和资源列表，User/Group 写操作默认收进高级参数。
          </p>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <Field label="tenantId">
          <Input value={tenantId} onChange={(event) => setTenantId(event.target.value)} className="h-8 font-mono text-xs" />
        </Field>
        <Field label="SCIM token">
          <Input type="password" value={scimToken} onChange={(event) => setScimToken(event.target.value)} className="h-8 font-mono text-xs" placeholder="Bearer token" />
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton busy={busy === 'provider'} disabled={baseDisabled} label="ServiceProviderConfig" onClick={() => runAction('provider', 'SCIM 服务配置', () => scimApi.getServiceProviderConfig(base))} />
        <ActionButton busy={busy === 'schemas'} disabled={baseDisabled} label="Schemas" onClick={() => runAction('schemas', 'SCIM Schemas', () => scimApi.listSchemas(base))} />
        <ActionButton busy={busy === 'resource-types'} disabled={baseDisabled} label="ResourceTypes" onClick={() => runAction('resource-types', 'SCIM ResourceTypes', () => scimApi.listResourceTypes(base))} />
        <ActionButton busy={busy === 'groups'} disabled={baseDisabled} label="Group 列表" onClick={() => runAction('groups', 'SCIM Group 列表', () => scimApi.listGroups({ ...base, count: 50 }))} />
        <ActionButton busy={busy === 'users'} disabled={baseDisabled} label="User 列表" onClick={() => runAction('users', 'SCIM User 列表', () => scimApi.listUsers({ ...base, count: 50 }))} />
      </div>

      <details className="mt-3 rounded-lg border border-border/60 bg-background/70 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-foreground">高级写入参数（可选）</summary>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">仅在需要定位单个 User/Group 或执行创建、替换、Patch、删除时填写。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <Field label="Group">
            <Input value={groupId} onChange={(event) => setGroupId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <Field label="User">
            <Input value={userId} onChange={(event) => setUserId(event.target.value)} className="h-8 font-mono text-xs" />
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
            <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={baseDisabled || !groupId.trim()}>
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
            <Textarea value={groupPayload} onChange={(event) => setGroupPayload(event.target.value)} className="min-h-[128px] font-mono text-xs" />
          </Field>
          <Field label="User 请求体（JSON）">
            <Textarea value={userPayload} onChange={(event) => setUserPayload(event.target.value)} className="min-h-[128px] font-mono text-xs" />
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
      <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
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
    <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <ShieldCheck className="h-3.5 w-3.5" />}
      {label}
    </Button>
  )
}
