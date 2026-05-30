'use client'

import { useEffect, useState, type ReactNode } from 'react'
import { EyeOff, Loader2, Users } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { scimApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'

export function ScimProvisioningPanel() {
  const [tenantId, setTenantId] = useState('')
  const [scimToken, setScimToken] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    const storedTenant =
      globalThis.window.localStorage.getItem('mimirq_tenant_id')
    if (storedTenant) setTenantId(storedTenant)
  }, [])

  const base = { tenantId: tenantId.trim(), scimToken: scimToken.trim() }
  const baseDisabled = Boolean(busy) || !base.tenantId || !base.scimToken
  const configured = Boolean(base.tenantId && base.scimToken)

  async function runAction(
    key: string,
    title: string,
    action: () => Promise<unknown>
  ) {
    setBusy(key)
    try {
      await action()
      toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel
      padding="sm"
      className="rounded-2xl border-slate-200/80 bg-card shadow-[0_1px_3px_rgba(15,23,42,0.04)]"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
            <Users className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2 text-[14px] font-semibold text-slate-950">
              <span>SCIM 同步</span>
              <span
                className={cn(
                  'rounded-full border px-2 py-0.5 text-[10px] font-semibold',
                  configured
                    ? 'border-emerald-100 bg-emerald-50 text-emerald-700'
                    : 'border-slate-200 bg-slate-50 text-slate-500'
                )}
              >
                {configured ? '可测试' : '未启用'}
              </span>
            </div>
            <p className="mt-0.5 text-[12px] leading-5 text-slate-500">
              同步企业用户和群组，维护成员生命周期
            </p>
          </div>
        </div>
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin text-slate-400 motion-reduce:animate-none" />
        ) : null}
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(220px,1fr)_minmax(260px,1.5fr)_auto] lg:items-end">
        <Field label="租户 ID">
          <Input
            value={tenantId}
            onChange={(event) => setTenantId(event.target.value)}
            className="h-9 rounded-lg border-slate-200 bg-slate-50/50 font-mono text-[12px] shadow-none"
            placeholder="X-Tenant-ID"
          />
        </Field>
        <Field label="SCIM Token">
          <div className="relative">
            <Input
              type="password"
              value={scimToken}
              onChange={(event) => setScimToken(event.target.value)}
              className="h-9 rounded-lg border-slate-200 bg-slate-50/50 pr-9 font-mono text-[12px] shadow-none"
              placeholder="输入 SCIM Token"
            />
            <EyeOff className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          </div>
        </Field>
        <div className="flex flex-wrap gap-2">
          <ActionButton
            busy={busy === 'provider'}
            disabled={baseDisabled}
            label="测试连接"
            onClick={() =>
              runAction('provider', 'SCIM 服务配置', () =>
                scimApi.getServiceProviderConfig(base)
              )
            }
          />
        </div>
      </div>
    </Panel>
  )
}

function Field({
  label,
  children,
}: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] font-semibold text-slate-500">
        {label}
      </Label>
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
    <Button
      variant="outline"
      className="h-9 gap-1.5 rounded-lg border-slate-200 bg-card px-3 text-[12px] font-semibold text-slate-600 shadow-none"
      disabled={disabled}
      onClick={() => detachPromise(onClick())}
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
      ) : null}
      {label}
    </Button>
  )
}
