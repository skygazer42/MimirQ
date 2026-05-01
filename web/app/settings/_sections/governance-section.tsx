'use client'

import { useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { GovernanceOpsPanel } from '@/components/settings/governance-ops-panel'
import { systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'
import { rtbfApi, type SystemSettings } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import { AlertCircle, EyeOff, Loader2, ShieldCheck, ToggleLeft, ToggleRight } from 'lucide-react'
import { toast } from 'sonner'

type GovernanceSettings = NonNullable<SystemSettings['governance']>

type GovernanceSectionProps = {
  isGovernanceEnabled: boolean
  isPiiAnonymizeEnabled: boolean
  isSecretsRedactEnabled: boolean
  isQuarantineOnDropEnabled: boolean
  updateGovernance: (patch: Partial<GovernanceSettings>) => void
}

const FIELD_LABEL = 'text-[11px] font-medium text-muted-foreground'

export function GovernanceSection({
  isGovernanceEnabled,
  isPiiAnonymizeEnabled,
  isSecretsRedactEnabled,
  isQuarantineOnDropEnabled,
  updateGovernance,
}: Readonly<GovernanceSectionProps>) {
  const toggleIconClass = 'h-7 w-7'
  const [rtbfAccountId, setRtbfAccountId] = useState('')
  const [rtbfTicketId, setRtbfTicketId] = useState('')
  const [rtbfDryRun, setRtbfDryRun] = useState(true)
  const [rtbfMaxDocs, setRtbfMaxDocs] = useState(100)
  const [rtbfMaxRetries, setRtbfMaxRetries] = useState(1)
  const [rtbfRunningKey, setRtbfRunningKey] = useState<string | null>(null)
  const [rtbfResult, setRtbfResult] = useState<unknown>(null)

  async function runRtbfAction(key: string, title: string, action: () => Promise<unknown>) {
    setRtbfRunningKey(key)
    try {
      const payload = await action()
      setRtbfResult(payload)
      const ticketId = typeof (payload as { ticket_id?: unknown })?.ticket_id === 'string'
        ? String((payload as { ticket_id: string }).ticket_id)
        : ''
      if (ticketId) setRtbfTicketId(ticketId)
      toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setRtbfRunningKey(null)
    }
  }

  function prettyRtbfResult(value: unknown) {
    try {
      return JSON.stringify(value ?? { message: '尚未调用 RTBF 接口' }, null, 2)
    } catch {
      return String(value)
    }
  }

  return (
    <section className="space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold tracking-[-0.01em] text-foreground">
          <EyeOff className="h-4 w-4 text-primary" />
          数据治理
        </h2>
        <div className="inline-flex items-center gap-1 rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
          <span>保存后通常可立即生效</span>
        </div>
      </div>

      <div className={cn(systemWorkbenchTokens.panel, 'space-y-3 p-3.5')}>
        <Alert className="p-3 shadow-none [&>svg]:left-3 [&>svg]:top-3 [&>svg~*]:pl-6">
          <AlertCircle className="h-3.5 w-3.5" />
          <div>
            <AlertTitle className="text-xs">默认治理规则</AlertTitle>
            <AlertDescription className="text-[11px] leading-4 text-foreground/80">
              这些开关会影响“入库前清洗/脱敏”，用于没有单独配置管线（dataset/document pipeline overrides）时的默认行为。
            </AlertDescription>
          </div>
        </Alert>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={systemPageTokens.heading}>启用数据治理</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>打开后才会应用下方治理项（对新入库文档生效）</div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ enabled: !isGovernanceEnabled })}
              className="shrink-0"
              aria-label="切换数据治理开关（governance.enabled）"
            >
              {isGovernanceEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>

          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={systemPageTokens.heading}>PII 脱敏</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                尝试识别并匿名化手机号/邮箱等个人信息（可能影响检索/可读性）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ pii_anonymize: !isPiiAnonymizeEnabled })}
              className="shrink-0"
              aria-label="切换 PII 脱敏（governance.pii_anonymize）"
            >
              {isPiiAnonymizeEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>

          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={systemPageTokens.heading}>密钥信息脱敏（secrets）</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                尝试识别并遮蔽 API 密钥（API Key）/令牌（Token）等敏感信息
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ secrets_redact: !isSecretsRedactEnabled })}
              className="shrink-0"
              aria-label="切换密钥信息脱敏（governance.secrets_redact）"
            >
              {isSecretsRedactEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>

          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={systemPageTokens.heading}>质量过滤触发时隔离</div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                当触发“低密度/仅目录”等过滤时，将文档标记为“已隔离（quarantined）”（便于排查）
              </div>
            </div>
            <button
              type="button"
              onClick={() => updateGovernance({ quarantine_on_drop: !isQuarantineOnDropEnabled })}
              className="shrink-0"
              aria-label="切换过滤后隔离（governance.quarantine_on_drop）"
            >
              {isQuarantineOnDropEnabled ? (
                <ToggleRight className={cn(toggleIconClass, 'text-primary')} />
              ) : (
                <ToggleLeft className={cn(toggleIconClass, 'text-muted-foreground hover:text-muted-foreground')} />
              )}
            </button>
          </div>
        </div>

        <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div className="flex items-center gap-1.5 text-[12px] font-semibold text-foreground">
                <ShieldCheck className="h-3.5 w-3.5 text-info" />
                RTBF 级联删除闭环
              </div>
              <div className={cn(systemPageTokens.subtle, 'mt-0.5')}>
                默认 dry-run，只评估 subject_account_id 对应账号的文档/索引/反馈级联影响；关闭 dry-run 才会执行删除。
              </div>
            </div>
            <button
              type="button"
              onClick={() => setRtbfDryRun((value) => !value)}
              className={cn(
                'rounded-full border px-2.5 py-1 text-[11px] font-semibold',
                rtbfDryRun
                  ? 'border-info/20 bg-info/10 text-info'
                  : 'border-destructive/30 bg-destructive/10 text-destructive'
              )}
              aria-pressed={rtbfDryRun}
            >
              {rtbfDryRun ? 'dry-run' : 'execute'}
            </button>
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-4">
            <div className="space-y-1.5 md:col-span-2">
              <div className={FIELD_LABEL}>subject_account_id</div>
              <Input
                value={rtbfAccountId}
                onChange={(event) => setRtbfAccountId(event.target.value)}
                className="h-8 rounded-md border-border/70 bg-background text-[12px]"
                placeholder="account/user id"
              />
            </div>
            <div className="space-y-1.5">
              <div className={FIELD_LABEL}>max_docs</div>
              <Input
                value={String(rtbfMaxDocs)}
                onChange={(event) => setRtbfMaxDocs(Number.parseInt(event.target.value || '0', 10) || 100)}
                className="h-8 rounded-md border-border/70 bg-background text-[12px]"
                inputMode="numeric"
              />
            </div>
            <div className="space-y-1.5">
              <div className={FIELD_LABEL}>max_retries</div>
              <Input
                value={String(rtbfMaxRetries)}
                onChange={(event) => setRtbfMaxRetries(Number.parseInt(event.target.value || '0', 10) || 1)}
                className="h-8 rounded-md border-border/70 bg-background text-[12px]"
                inputMode="numeric"
              />
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <div className={FIELD_LABEL}>ticket_id</div>
              <Input
                value={rtbfTicketId}
                onChange={(event) => setRtbfTicketId(event.target.value)}
                className="h-8 rounded-md border-border/70 bg-background font-mono text-[12px]"
                placeholder="请求后自动回填"
              />
            </div>
            <div className="flex items-end gap-2 md:col-span-2">
              <Button
                type="button"
                variant="outline"
                className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold"
                disabled={Boolean(rtbfRunningKey) || !rtbfAccountId.trim()}
                onClick={() =>
                  detachPromise(
                    runRtbfAction('request', 'RTBF 请求', () =>
                      rtbfApi.request({
                        subject_account_id: rtbfAccountId.trim(),
                        dry_run: rtbfDryRun,
                        max_docs: rtbfMaxDocs,
                        max_retries: rtbfMaxRetries,
                      })
                    )
                  )
                }
              >
                {rtbfRunningKey === 'request' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : null}
                请求
              </Button>
              <Button
                type="button"
                variant="outline"
                className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold"
                disabled={Boolean(rtbfRunningKey) || !rtbfTicketId.trim()}
                onClick={() => detachPromise(runRtbfAction('status', 'RTBF 状态', () => rtbfApi.getStatus(rtbfTicketId.trim())))}
              >
                {rtbfRunningKey === 'status' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : null}
                查状态
              </Button>
            </div>
          </div>

          <pre className={cn('mt-3 max-h-44 overflow-auto rounded-md border border-border/60 bg-background p-2 text-xs', 'whitespace-pre-wrap break-words')}>
            {prettyRtbfResult(rtbfResult)}
          </pre>
        </div>

        <GovernanceOpsPanel />
      </div>
    </section>
  )
}
