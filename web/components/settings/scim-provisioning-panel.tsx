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
import { readClientStorage } from '@/lib/client-storage'
import { cn, detachPromise } from '@/lib/utils'

const SCIM_PANEL_CLASS = 'overflow-hidden rounded-xl border border-foreground/10 bg-background shadow-none'
const SETTINGS_IDENTITY_LABEL_CLASS =
  'text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground'
const SETTINGS_IDENTITY_INPUT_CLASS =
  'h-9 rounded-xl border-border/60 bg-background/76 font-mono text-[12px] shadow-none transition-colors focus-visible:border-primary/35 focus-visible:ring-2 focus-visible:ring-primary/10'
const SETTINGS_IDENTITY_ICON_CLASS =
  'flex size-9 shrink-0 items-center justify-center rounded-lg border border-foreground/10 bg-muted/18 text-primary'
const SETTINGS_IDENTITY_META_CLASS =
  'rounded-full border border-border/60 bg-muted/42 px-2 py-0.5 text-[10px] font-medium text-muted-foreground'

export function ScimProvisioningPanel() {
  const [tenantId, setTenantId] = useState('')
  const [scimToken, setScimToken] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    const storedTenant = readClientStorage('mimirq_tenant_id')
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
      className={SCIM_PANEL_CLASS}
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-start gap-3">
          <div className={SETTINGS_IDENTITY_ICON_CLASS}>
            <Users className="h-4 w-4" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2 text-[14px] font-semibold text-foreground">
              <span>SCIM 同步</span>
              <span
                className={cn(
                  'rounded-full border px-2 py-0.5 text-[10px] font-semibold',
                  configured
                    ? 'border-success/20 bg-success/10 text-success'
                    : 'border-border/60 bg-muted/45 text-muted-foreground'
                )}
              >
                {configured ? '可测试' : '未启用'}
              </span>
            </div>
            <p className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
              同步企业用户和群组，维护成员生命周期
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className={SETTINGS_IDENTITY_META_CLASS}>Users</span>
              <span className={SETTINGS_IDENTITY_META_CLASS}>Groups</span>
              <span className={SETTINGS_IDENTITY_META_CLASS}>Lifecycle</span>
            </div>
          </div>
        </div>
        <div className="flex min-h-7 items-center gap-2 rounded-full border border-border/60 bg-background px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
          ) : (
            <span
              className={cn(
                'size-1.5 rounded-full',
                configured ? 'bg-success' : 'bg-muted-foreground/45'
              )}
            />
          )}
          <span>{busy ? '连接测试中' : configured ? '凭据已填写' : '等待配置'}</span>
        </div>
      </div>

      <div className="mt-3 rounded-xl border border-foreground/10 bg-muted/15 p-3">
        <div className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_minmax(260px,1.4fr)_auto] lg:items-end">
          <Field
            label="租户 ID"
            helper="随请求写入 X-Tenant-ID，用于隔离企业空间。"
          >
            <Input
              value={tenantId}
              onChange={(event) => setTenantId(event.target.value)}
              className={SETTINGS_IDENTITY_INPUT_CLASS}
              placeholder="X-Tenant-ID"
            />
          </Field>
          <Field
            label="SCIM Token"
            helper="用于测试 SCIM Service Provider 配置，不在页面明文展示。"
          >
            <div className="relative">
              <Input
                type="password"
                value={scimToken}
                onChange={(event) => setScimToken(event.target.value)}
                className={cn(SETTINGS_IDENTITY_INPUT_CLASS, 'pr-9')}
                placeholder="输入 SCIM Token"
              />
              <EyeOff className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            </div>
          </Field>
          <div className="flex flex-wrap gap-2 lg:justify-end">
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
      </div>
    </Panel>
  )
}

function Field({
  label,
  helper,
  children,
}: Readonly<{ label: string; helper?: string; children: ReactNode }>) {
  return (
    <div className="space-y-1.5">
      <Label className={SETTINGS_IDENTITY_LABEL_CLASS}>
        {label}
      </Label>
      {children}
      {helper ? (
        <p className="text-[11px] leading-4 text-muted-foreground/86">
          {helper}
        </p>
      ) : null}
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
      className="h-9 gap-1.5 rounded-lg border-border/70 bg-background px-3 text-[12px] font-semibold text-foreground shadow-none transition-colors hover:bg-muted/18 hover:text-primary disabled:border-border/60 disabled:bg-muted/50 disabled:text-muted-foreground"
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
