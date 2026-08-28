'use client'

import { useState, type ReactNode } from 'react'
import { Download, Loader2, ShieldCheck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { authApi } from '@/lib/api'
import { formatApiError, toApiErrorInfo } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'

const SAML_PANEL_CLASS = 'overflow-hidden rounded-xl border border-info/20 bg-background/70 shadow-none'
const SETTINGS_IDENTITY_LABEL_CLASS =
  'text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground'
const SETTINGS_IDENTITY_INPUT_CLASS =
  'h-9 rounded-xl border-border/70 bg-muted/60 text-[12px] shadow-none transition-colors focus-visible:border-info/35 focus-visible:ring-2 focus-visible:ring-info/10'
const SETTINGS_IDENTITY_ICON_CLASS =
  'flex size-9 shrink-0 items-center justify-center rounded-lg border border-info/20 bg-info/10 text-info'
const SETTINGS_IDENTITY_META_CLASS =
  'rounded-full border border-border/60 bg-muted/42 px-2 py-0.5 text-[10px] font-medium text-muted-foreground'

function downloadText(content: string, filename: string) {
  const blob = new Blob([content], { type: 'application/xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function isSamlNotConfiguredMessage(message: string): boolean {
  return message.trim().toLowerCase() === 'saml not configured'
}

export function SamlOpsPanel() {
  const [providerId, setProviderId] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function runAction(
    key: string,
    title: string,
    action: () => Promise<unknown>
  ) {
    setBusy(key)
    try {
      await action()
      setNotice(null)
      toast.success(`${title}完成`)
    } catch (error) {
      const info = toApiErrorInfo(error, `${title}失败`)
      if (isSamlNotConfiguredMessage(info.message)) {
        setNotice('身份源尚未配置：请先完成 SAML 身份源配置，再下载元数据')
        toast.warning('身份源尚未配置，暂时无法下载元数据')
        return
      }

      setNotice(null)
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setBusy(null)
    }
  }

  const provider = providerId.trim()

  return (
    <Panel
      padding="sm"
      className={SAML_PANEL_CLASS}
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-start gap-3">
          <div className={SETTINGS_IDENTITY_ICON_CLASS}>
            <ShieldCheck className="size-4" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2 text-[14px] font-semibold text-foreground">
              <span>SAML 单点登录</span>
              <span className="rounded-full border border-border/60 bg-muted/45 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                按需配置
              </span>
            </div>
            <p className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
              对接企业身份源，完成单点登录和访问控制
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className={SETTINGS_IDENTITY_META_CLASS}>SSO</span>
              <span className={SETTINGS_IDENTITY_META_CLASS}>Metadata</span>
              <span className={SETTINGS_IDENTITY_META_CLASS}>Access control</span>
            </div>
          </div>
        </div>
        <div className="flex min-h-7 items-center gap-2 rounded-full border border-border/60 bg-background/65 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
          ) : (
            <span className="size-1.5 rounded-full bg-muted-foreground/45" />
          )}
          <span>{busy ? 'Metadata 生成中' : '等待身份源'}</span>
        </div>
      </div>

      <div className="mt-3 rounded-xl border border-info/15 bg-info/[0.025] p-3">
        <div className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_auto] lg:items-end">
          <Field
            label="身份源 ID"
            helper="为空时使用默认身份源；多 IdP 场景可输入指定 provider。"
          >
            <Input
              value={providerId}
              onChange={(event) => setProviderId(event.target.value)}
              className={cn(SETTINGS_IDENTITY_INPUT_CLASS, 'min-w-[220px]')}
              placeholder="默认身份源"
            />
          </Field>
          <div className="flex flex-wrap gap-2 lg:justify-end">
            <ActionButton
              icon={Download}
              busy={busy === 'metadata'}
              disabled={Boolean(busy)}
              label="下载 Metadata"
              onClick={() =>
                runAction('metadata', '获取 SAML Metadata', async () => {
                  const xml = await authApi.samlMetadata({
                    provider_id: provider || null,
                  })
                  downloadText(xml, `saml-metadata.${provider || 'default'}.xml`)
                  return {
                    provider_id: provider || null,
                    chars: xml.length,
                    preview: xml.slice(0, 2000),
                  }
                })
              }
            />
          </div>
        </div>
      </div>
      {notice ? (
        <div className="mt-3 rounded-xl border border-warning/20 bg-warning/10 px-3 py-2 text-[12px] font-medium leading-5 text-warning">
          {notice}
        </div>
      ) : null}
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
  icon: Icon,
  label,
  onClick,
}: Readonly<{
  busy: boolean
  disabled: boolean
  icon: LucideIcon
  label: string
  onClick: () => Promise<void>
}>) {
  return (
    <Button
      variant="outline"
      className="h-9 gap-1.5 rounded-lg border-border/70 bg-background/68 px-3 text-[12px] font-medium text-foreground shadow-none transition-colors hover:border-info/30 hover:bg-info/[0.06] hover:text-info disabled:border-border/60 disabled:bg-muted/50 disabled:text-muted-foreground"
      disabled={disabled}
      onClick={() => detachPromise(onClick())}
    >
      {busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
      ) : (
        <Icon className="h-3.5 w-3.5" />
      )}
      {label}
    </Button>
  )
}
