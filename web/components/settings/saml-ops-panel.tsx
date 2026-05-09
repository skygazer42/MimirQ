'use client'

import { useState, type ReactNode } from 'react'
import { ChevronUp, Download, Loader2, LogIn, ShieldCheck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Textarea } from '@/components/ui/textarea'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { authApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
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

function redactSensitive(value: unknown): unknown {
  if (!value || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(redactSensitive)

  const next: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) {
    if (/token|assertion|saml_response|secret|password/i.test(key)) {
      next[key] = '[REDACTED]'
    } else {
      next[key] = redactSensitive(item)
    }
  }
  return next
}

export function SamlOpsPanel() {
  const [providerId, setProviderId] = useState('')
  const [relayState, setRelayState] = useState('')
  const [acsUrl, setAcsUrl] = useState('')
  const [samlResponse, setSamlResponse] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

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

  const provider = providerId.trim()

  return (
    <Panel padding="md" className="rounded-2xl border-slate-200/80 bg-white shadow-[0_1px_3px_rgba(15,23,42,0.04)]">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
            <ShieldCheck className="size-4" />
          </div>
          <div>
            <div className="flex items-center gap-2 text-[15px] font-semibold text-slate-950">
              SAML SSO
              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold text-slate-500">按需配置</span>
            </div>
            <p className="mt-1 text-[12px] leading-5 text-slate-500">
              配置 SAML 单点登录，支持企业 IdP 进行身份验证与访问控制。
          </p>
        </div>
        </div>
        <div className="flex items-center gap-2">
          {busy ? <Loader2 className="h-4 w-4 animate-spin text-slate-400 motion-reduce:animate-none" /> : null}
          <ChevronUp className="size-4 text-slate-400" />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton icon={Download} busy={busy === 'metadata'} disabled={Boolean(busy)} label="配置 Metadata" onClick={() => runAction('metadata', '获取 SAML Metadata', async () => {
          const xml = await authApi.samlMetadata({ provider_id: provider || null })
          downloadText(xml, `saml-metadata.${provider || 'default'}.xml`)
          return { provider_id: provider || null, chars: xml.length, preview: xml.slice(0, 2000) }
        })} />
        <div className="flex min-h-9 flex-1 items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-3 text-center text-[12px] text-slate-400">
          配置完成后，将在此显示 SAML 回应结果或状态信息。
        </div>
      </div>

      <details className="mt-3 rounded-xl border border-slate-200/80 bg-slate-50/60 p-3">
        <summary className="cursor-pointer text-[12px] font-semibold text-slate-700">高级交换参数</summary>
        <p className="mt-1 text-[12px] leading-5 text-slate-500">仅在联调具体 IdP、ACS 或手动交换 SAML Response 时填写。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Field label="Provider">
            <Input value={providerId} onChange={(event) => setProviderId(event.target.value)} className="h-8 rounded-lg border-slate-200 bg-white font-mono text-xs shadow-none" />
          </Field>
          <Field label="Relay State">
            <Input value={relayState} onChange={(event) => setRelayState(event.target.value)} className="h-8 rounded-lg border-slate-200 bg-white font-mono text-xs shadow-none" />
          </Field>
          <Field label="ACS URL">
            <Input value={acsUrl} onChange={(event) => setAcsUrl(event.target.value)} className="h-8 rounded-lg border-slate-200 bg-white font-mono text-xs shadow-none" />
          </Field>
        </div>

        <Field label="SAML Response">
          <Textarea value={samlResponse} onChange={(event) => setSamlResponse(event.target.value)} className="mt-3 min-h-[104px] rounded-lg border-slate-200 bg-white font-mono text-xs shadow-none" />
        </Field>
        <div className="mt-3 flex flex-wrap gap-2">
          <ConfirmDialog
            title="执行 SAML Exchange？"
            description="该接口会签发登录 token。面板只会展示脱敏后的响应，但请确认当前环境和 IdP 断言来源可信。"
            confirmLabel="执行 Exchange"
            confirmVariant="default"
            onConfirm={() => runAction('exchange', 'SAML Exchange', async () => {
              const payload = await authApi.samlExchange({
                provider_id: provider || null,
                saml_response: samlResponse.trim(),
                relay_state: relayState.trim() || null,
                acs_url: acsUrl.trim() || null,
              })
              return redactSensitive(payload)
            })}
          >
            <Button variant="outline" className="h-8 gap-1.5 rounded-lg border-slate-200 bg-white px-3 text-xs font-semibold" disabled={Boolean(busy) || !samlResponse.trim()}>
              {busy === 'exchange' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <LogIn className="h-3.5 w-3.5" />}
              Exchange
            </Button>
          </ConfirmDialog>
        </div>
      </details>

      <OperationResultPanel className="mt-3" title="SAML 操作结果" result={result} emptyMessage="获取 metadata 或执行 exchange 后，这里展示脱敏摘要；原始响应默认收起。" />
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
    <Button variant="outline" className="h-9 gap-1.5 rounded-lg border-slate-200 bg-white px-3 text-[12px] font-semibold text-slate-600 shadow-none" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Icon className="h-3.5 w-3.5" />}
      {label}
    </Button>
  )
}
