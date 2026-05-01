'use client'

import { useState, type ReactNode } from 'react'
import { Download, Loader2, LogIn } from 'lucide-react'
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
    <Panel padding="md" className="border-border/70 bg-card/95">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">SAML SSO 操作</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            获取 SAML metadata；需要粘贴 IdP 断言或覆盖 provider/ACS 时再打开高级交换参数。
          </p>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton icon={Download} busy={busy === 'metadata'} disabled={Boolean(busy)} label="获取 Metadata" onClick={() => runAction('metadata', '获取 SAML Metadata', async () => {
          const xml = await authApi.samlMetadata({ provider_id: provider || null })
          downloadText(xml, `saml-metadata.${provider || 'default'}.xml`)
          return { provider_id: provider || null, chars: xml.length, preview: xml.slice(0, 2000) }
        })} />
      </div>

      <details className="mt-3 rounded-lg border border-border/60 bg-background/70 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-foreground">高级交换参数（可选）</summary>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">仅在联调具体 IdP、ACS 或手动交换 SAML Response 时填写。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Field label="Provider">
            <Input value={providerId} onChange={(event) => setProviderId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <Field label="Relay State">
            <Input value={relayState} onChange={(event) => setRelayState(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <Field label="ACS URL">
            <Input value={acsUrl} onChange={(event) => setAcsUrl(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
        </div>

        <Field label="SAML Response">
          <Textarea value={samlResponse} onChange={(event) => setSamlResponse(event.target.value)} className="mt-3 min-h-[104px] font-mono text-xs" />
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
            <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy) || !samlResponse.trim()}>
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
      <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
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
    <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Icon className="h-3.5 w-3.5" />}
      {label}
    </Button>
  )
}
