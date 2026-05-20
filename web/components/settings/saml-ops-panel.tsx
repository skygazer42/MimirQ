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
import { detachPromise } from '@/lib/utils'

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
      className="rounded-2xl border-slate-200/80 bg-card shadow-[0_1px_3px_rgba(15,23,42,0.04)]"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
            <ShieldCheck className="size-4" />
          </div>
          <div>
            <div className="flex items-center gap-2 text-[14px] font-semibold text-slate-950">
              SAML 单点登录
              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold text-slate-500">
                按需配置
              </span>
            </div>
            <p className="mt-0.5 text-[12px] leading-5 text-slate-500">
              对接企业身份源，完成单点登录和访问控制
            </p>
          </div>
        </div>
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin text-slate-400 motion-reduce:animate-none" />
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Field label="身份源 ID">
          <Input
            value={providerId}
            onChange={(event) => setProviderId(event.target.value)}
            className="h-9 min-w-[220px] rounded-lg border-slate-200 bg-slate-50/50 text-[12px] shadow-none"
            placeholder="默认身份源"
          />
        </Field>
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
      {notice ? (
        <div className="mt-3 rounded-xl border border-amber-200/80 bg-amber-50/80 px-3 py-2 text-[12px] font-medium leading-5 text-amber-800">
          {notice}
        </div>
      ) : null}
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
      className="h-9 gap-1.5 rounded-lg border-slate-200 bg-card px-3 text-[12px] font-semibold text-slate-600 shadow-none"
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
