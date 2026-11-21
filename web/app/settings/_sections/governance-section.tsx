'use client'

import { useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DangerZonePanel } from '@/components/settings/danger-zone-panel'
import { GovernanceOpsPanel } from '@/components/settings/governance-ops-panel'
import { SettingsSwitch } from '@/components/settings/settings-switch'
import { settingsLayoutTokens, settingsTextTokens } from '@/components/ui/system-page-tokens'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { rbacApi } from '@/lib/api/access'
import type { GovernanceConfig } from '@/types/settings'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { rtbfApi, type RtbfCascadeResponse } from '@/lib/api/rtbf'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'
import { Loader2 } from '@/components/icons'
import { toast } from 'sonner'

type GovernanceSectionProps = {
  isGovernanceEnabled: boolean
  isPiiAnonymizeEnabled: boolean
  isSecretsRedactEnabled: boolean
  isQuarantineOnDropEnabled: boolean
  updateGovernance: (patch: Partial<GovernanceConfig>) => void
}

const FIELD_LABEL = settingsTextTokens.fieldLabel
const RTBF_MEMBERS_PARAMS = { limit: 500 } as const
const RTBF_CURRENT_ACCOUNT_VALUE = '__current_account__'
const RTBF_MANUAL_ACCOUNT_VALUE = '__manual_account__'

type RtbfSubjectSource = 'current' | 'member' | 'manual'

const RTBF_SUBJECT_SOURCE_LABELS: Readonly<Record<RtbfSubjectSource, string>> = {
  current: '当前账号自动绑定',
  member: '成员列表选择',
  manual: '手动覆盖',
}

function rtbfModeButtonClass(isActive: boolean, tone: 'info' | 'destructive') {
  if (tone === 'info') {
    return isActive
      ? 'border-primary text-foreground'
      : 'border-transparent text-muted-foreground hover:border-border hover:text-foreground'
  }
  return isActive
    ? 'border-destructive text-destructive'
    : 'border-transparent text-muted-foreground hover:border-destructive/25 hover:text-destructive'
}

function rtbfMemberLabel(id: string): { primary: string; secondary: string } {
  const separator = id.indexOf('@')
  if (separator > 0 && separator < id.length - 1) {
    return { primary: id.slice(0, separator), secondary: id.slice(separator + 1) }
  }
  return { primary: id.length > 18 ? `${id.slice(0, 10)}...${id.slice(-6)}` : id, secondary: '账号 ID' }
}

function parseRtbfLimit(raw: string, label: string, minimum: number, maximum: number): number {
  const trimmed = raw.trim()
  const value = Number(trimmed)
  if (!/^\d+$/.test(trimmed) || !Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${label}应为 ${minimum}-${maximum} 的整数`)
  }
  return value
}

function RtbfResultSummary({ result }: Readonly<{ result: RtbfCascadeResponse }>) {
  const {
    subject_account_id: subject,
    dry_run: dryRun,
    eligible,
    deleted,
    errors,
    cache_invalidations: cacheInvalidations,
  } = result
  const hasErrors = errors > 0
  const title = hasErrors ? 'RTBF 执行存在错误' : dryRun ? '安全预演完成' : '级联删除已执行'
  const description = dryRun
    ? `本次只评估影响范围，命中 ${eligible} 个候选文档，未执行删除`
    : `本次已执行级联删除，删除 ${deleted}/${eligible} 个候选文档`
  const metrics = [
    { label: '候选文档', value: eligible, hint: `账号 ${subject}` },
    { label: '已删除', value: deleted, hint: dryRun ? '安全预演未删除' : '实际删除数' },
    { label: '错误', value: errors, hint: hasErrors ? '查看原始响应' : '无错误' },
    { label: '缓存刷新', value: cacheInvalidations, hint: '相关数据集缓存' },
  ]

  return (
    <div data-testid="rtbf-result-summary" className="mt-5 space-y-4 border-t border-border/60 pt-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className={settingsTextTokens.panelTitle}>{title}</h3>
          <p className="mt-1 max-w-3xl text-[13px] leading-[1.55] text-muted-foreground">{description}</p>
        </div>
        <span
          className={cn(
            'inline-flex w-fit shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-semibold',
            hasErrors
              ? 'border-destructive/25 bg-destructive/10 text-destructive'
              : 'border-success/25 bg-success/10 text-success',
          )}
        >
          {hasErrors ? '需排查' : dryRun ? '安全预演' : '已执行'}
        </span>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
        {metrics.map((metric) => (
          <div key={metric.label} className="grid grid-cols-[1fr_auto] items-center gap-x-2">
            <dt className="text-[13px] font-medium text-muted-foreground/85">{metric.label}</dt>
            <dd className="text-[13px] font-medium tabular-nums text-foreground">{metric.value}</dd>
            <dd className="col-span-2 mt-1 break-words text-xs leading-5 text-muted-foreground">{metric.hint}</dd>
          </div>
        ))}
      </dl>

      <details data-testid="rtbf-raw-response" className="group mt-2.5 text-[13px] text-muted-foreground">
        <summary className="cursor-pointer select-none font-medium text-muted-foreground transition-colors hover:text-foreground">
          原始响应（排障时展开）
        </summary>
        <pre className="mt-2 max-h-44 overflow-auto rounded-md bg-muted/30 p-3 font-mono text-[13px] leading-5 text-foreground whitespace-pre-wrap break-words">
          {JSON.stringify(result, null, 2)}
        </pre>
      </details>
    </div>
  )
}

export function GovernanceSection({
  isGovernanceEnabled,
  isPiiAnonymizeEnabled,
  isSecretsRedactEnabled,
  isQuarantineOnDropEnabled,
  updateGovernance,
}: Readonly<GovernanceSectionProps>) {
  const subjectFieldId = useId()
  const [rtbfAccountId, setRtbfAccountId] = useState('')
  const [rtbfDryRun, setRtbfDryRun] = useState(true)
  const [rtbfMaxDocs, setRtbfMaxDocs] = useState('100')
  const [rtbfMaxRetries, setRtbfMaxRetries] = useState('1')
  const [rtbfRunning, setRtbfRunning] = useState(false)
  const [rtbfResult, setRtbfResult] = useState<RtbfCascadeResponse | null>(null)
  const [rtbfSubjectSource, setRtbfSubjectSource] = useState<RtbfSubjectSource>('current')
  const rtbfOwnerRef = useRef({ active: true, running: false })

  useLayoutEffect(() => {
    const owner = { active: true, running: false }
    rtbfOwnerRef.current = owner
    return () => {
      owner.active = false
    }
  }, [])

  const currentAccessQuery = useTenantAccess()
  const membersQuery = useQuery({
    queryKey: queryKeys.rbac.members(RTBF_MEMBERS_PARAMS),
    queryFn: ({ signal }) => rbacApi.listTenantMembers(RTBF_MEMBERS_PARAMS, { signal }),
    select: (response) => response.items,
    retry: false,
  })
  const autoSubjectId = currentAccessQuery.data?.account_id.trim()
  const selectableMembers = useMemo(() => {
    const seen = new Set<string>()
    return (membersQuery.data ?? []).filter((member) => {
      const id = member.user_id.trim()
      if (!id || id === autoSubjectId || seen.has(id)) return false
      seen.add(id)
      return true
    })
  }, [autoSubjectId, membersQuery.data])
  const selectedMember = selectableMembers.find((member) => member.user_id.trim() === rtbfAccountId)
  const subjectAccountId =
    rtbfSubjectSource === 'current'
      ? autoSubjectId
      : rtbfSubjectSource === 'member'
        ? selectedMember?.user_id.trim()
        : rtbfAccountId.trim()
  const selectedSubjectValue =
    rtbfSubjectSource === 'current'
      ? RTBF_CURRENT_ACCOUNT_VALUE
      : rtbfSubjectSource === 'member'
        ? (subjectAccountId ?? '')
        : RTBF_MANUAL_ACCOUNT_VALUE
  const subjectSourceLabel = RTBF_SUBJECT_SOURCE_LABELS[rtbfSubjectSource]
  const isDeleteMode = rtbfDryRun === false

  async function runRtbfRequest() {
    const owner = rtbfOwnerRef.current
    if (!owner.active || owner.running || subjectAccountId === undefined || subjectAccountId === '') return
    owner.running = true
    const sessionKey = getAuthSessionKey()
    const title = rtbfDryRun ? 'RTBF 安全预演' : 'RTBF 删除执行'
    const isCurrent = () => owner.active && sessionKey === getAuthSessionKey()
    setRtbfRunning(true)
    try {
      const payload = await rtbfApi.request({
        subject_account_id: subjectAccountId,
        dry_run: rtbfDryRun,
        max_docs: parseRtbfLimit(rtbfMaxDocs, '最多扫描文档', 1, 1000),
        max_retries: parseRtbfLimit(rtbfMaxRetries, '失败重试', 0, 10),
      })
      if (!isCurrent()) return
      setRtbfResult(payload)
      if (payload.errors > 0) toast.error(`${title}存在错误，请查看结果`)
      else toast.success(`${title}完成`)
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, `${title}失败`))
    } finally {
      owner.running = false
      if (owner.active) setRtbfRunning(false)
    }
  }

  return (
    <section>
      <div className="space-y-4">
        <div className="grid gap-x-8 md:grid-cols-2">
          <div className={cn(settingsLayoutTokens.row, 'border-b border-border/60')}>
            <div>
              <div className={settingsTextTokens.fieldLabel}>启用数据治理</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>对新入库文档应用下方策略。</div>
            </div>
            <SettingsSwitch
              checked={isGovernanceEnabled}
              onCheckedChange={(checked) => updateGovernance({ enabled: checked })}
              className="shrink-0"
              aria-label="切换数据治理开关（governance.enabled）"
            />
          </div>

          <div className={cn(settingsLayoutTokens.row, 'border-b border-border/60')}>
            <div>
              <div className={settingsTextTokens.fieldLabel}>个人信息脱敏</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                匿名化手机号、邮箱等信息，可能影响检索和可读性。
              </div>
            </div>
            <SettingsSwitch
              checked={isPiiAnonymizeEnabled}
              onCheckedChange={(checked) => updateGovernance({ pii_anonymize: checked })}
              className="shrink-0"
              aria-label="切换 PII 脱敏（governance.pii_anonymize）"
            />
          </div>

          <div className={cn(settingsLayoutTokens.row, 'border-b border-border/60')}>
            <div>
              <div className={settingsTextTokens.fieldLabel}>密钥信息脱敏</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>识别并遮蔽 API 密钥、访问令牌等凭据。</div>
            </div>
            <SettingsSwitch
              checked={isSecretsRedactEnabled}
              onCheckedChange={(checked) => updateGovernance({ secrets_redact: checked })}
              className="shrink-0"
              aria-label="切换密钥信息脱敏（governance.secrets_redact）"
            />
          </div>

          <div className={cn(settingsLayoutTokens.row, 'border-b border-border/60')}>
            <div>
              <div className={settingsTextTokens.fieldLabel}>质量过滤触发时隔离</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                低密度、仅目录等过滤命中时，将文档移入隔离队列。
              </div>
            </div>
            <SettingsSwitch
              checked={isQuarantineOnDropEnabled}
              onCheckedChange={(checked) => updateGovernance({ quarantine_on_drop: checked })}
              className="shrink-0"
              aria-label="切换过滤后隔离（governance.quarantine_on_drop）"
            />
          </div>
        </div>

        <DangerZonePanel
          title="删除个人数据（RTBF）"
          impact="按账号删除文档、切片、向量和图谱数据，并清理相关缓存。默认预演，确认范围后再执行。"
          badge=""
          compact
          tone="neutral"
          icon="help"
        >
          <div className="grid gap-4 md:grid-cols-2">
            <button
              type="button"
              onClick={() => setRtbfDryRun(true)}
              disabled={rtbfRunning}
              className={cn(
                'min-h-11 border-b-2 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                rtbfModeButtonClass(rtbfDryRun, 'info'),
              )}
              aria-pressed={rtbfDryRun}
            >
              <div className="text-[13px] font-medium">安全预演</div>
              <div className="mt-1 text-[13px] leading-5 text-muted-foreground">仅统计受影响的文档和相关数据。</div>
            </button>
            <button
              type="button"
              onClick={() => setRtbfDryRun(false)}
              disabled={rtbfRunning}
              className={cn(
                'min-h-11 border-b-2 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                rtbfModeButtonClass(isDeleteMode, 'destructive'),
              )}
              aria-pressed={isDeleteMode}
            >
              <div className="text-[13px] font-medium">执行删除</div>
              <div className="mt-1 text-[13px] leading-5 text-muted-foreground">
                删除所选账号的相关数据，并清理相关缓存。
              </div>
            </button>
          </div>

          <div className="mt-5">
            <div className="grid gap-4 md:grid-cols-4">
              <div className="space-y-1.5 md:col-span-2">
                <div className="flex items-center justify-between gap-2">
                  <label htmlFor={subjectFieldId} className={FIELD_LABEL}>
                    目标账号
                  </label>
                  <span className={settingsTextTokens.microText}>{subjectSourceLabel}</span>
                </div>
                <Select
                  value={selectedSubjectValue}
                  disabled={rtbfRunning}
                  onValueChange={(value) => {
                    if (value === RTBF_CURRENT_ACCOUNT_VALUE) {
                      setRtbfSubjectSource('current')
                      return
                    }
                    if (value === RTBF_MANUAL_ACCOUNT_VALUE) {
                      setRtbfSubjectSource('manual')
                      setRtbfAccountId(rtbfSubjectSource === 'current' ? (autoSubjectId ?? '') : rtbfAccountId)
                      return
                    }
                    setRtbfSubjectSource('member')
                    setRtbfAccountId(value)
                  }}
                >
                  <SelectTrigger
                    id={subjectFieldId}
                    className="h-11 sm:h-9 rounded-md border-input bg-background text-[13px]"
                  >
                    <SelectValue placeholder="请选择有效成员" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={RTBF_CURRENT_ACCOUNT_VALUE}>
                      当前账号（自动绑定） · {autoSubjectId ?? (currentAccessQuery.isPending ? '加载中' : '未取得')}
                    </SelectItem>
                    {selectableMembers.map((member) => {
                      const id = member.user_id.trim()
                      const label = rtbfMemberLabel(id)
                      return (
                        <SelectItem key={id} value={id}>
                          {label.primary} · {label.secondary}
                        </SelectItem>
                      )
                    })}
                    <SelectItem value={RTBF_MANUAL_ACCOUNT_VALUE}>手动输入账号 ID</SelectItem>
                  </SelectContent>
                </Select>
                <div className={cn('break-words', settingsTextTokens.helpText)}>
                  将提交：
                  <span className="break-all font-mono text-foreground">
                    {subjectAccountId === undefined || subjectAccountId === '' ? '待确认目标账号' : subjectAccountId}
                  </span>
                  。
                  {membersQuery.isError
                    ? '成员列表加载失败时仍可使用手动输入'
                    : '下拉会优先使用当前账号，也可切换到其他租户成员'}
                </div>
              </div>
              <div className="space-y-1.5 md:col-span-2">
                <label className="block space-y-1.5">
                  <span className={cn(FIELD_LABEL, 'block')}>手动覆盖（找不到成员时使用）</span>
                  <Input
                    value={rtbfSubjectSource === 'manual' ? rtbfAccountId : ''}
                    disabled={rtbfRunning}
                    onChange={(event) => {
                      setRtbfSubjectSource('manual')
                      setRtbfAccountId(event.currentTarget.value)
                    }}
                    className="h-11 sm:h-9 rounded-md border-input bg-background text-[13px]"
                    placeholder="例如 user-123 / acct-1 / 用户 UUID"
                  />
                </label>
                <div className={settingsTextTokens.helpText}>
                  后端会按文档归属账号和生命周期负责人匹配；如果填写用户
                  UUID，也会一并匹配建议从成员权限或审计日志复制，不要填昵称
                </div>
              </div>
              <div className="space-y-1.5">
                <label className="block space-y-1.5">
                  <span className={cn(FIELD_LABEL, 'block')}>最多扫描文档</span>
                  <Input
                    value={rtbfMaxDocs}
                    disabled={rtbfRunning}
                    onChange={(event) => setRtbfMaxDocs(event.currentTarget.value)}
                    className="h-11 sm:h-9 rounded-md border-input bg-background text-[13px]"
                    inputMode="numeric"
                  />
                </label>
                <div className={settingsTextTokens.microText}>保护阈值，后端允许 1-1000</div>
              </div>
              <div className="space-y-1.5">
                <label className="block space-y-1.5">
                  <span className={cn(FIELD_LABEL, 'block')}>失败重试</span>
                  <Input
                    value={rtbfMaxRetries}
                    disabled={rtbfRunning}
                    onChange={(event) => setRtbfMaxRetries(event.currentTarget.value)}
                    className="h-11 sm:h-9 rounded-md border-input bg-background text-[13px]"
                    inputMode="numeric"
                  />
                </label>
                <div className={settingsTextTokens.microText}>删除失败时重试，后端允许 0-10</div>
              </div>
              <div className="flex flex-col gap-2 md:col-span-2">
                <div className={settingsTextTokens.helpText}>
                  操作顺序：确认目标账号 → 点“开始安全预演” → 看候选文档数量 → 确认无误后切换“执行删除”
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant={rtbfDryRun ? 'outline' : 'destructive'}
                    className="h-11 sm:h-9 gap-1.5 rounded-lg px-3 text-xs font-semibold"
                    disabled={rtbfRunning || subjectAccountId === undefined || subjectAccountId === ''}
                    onClick={() => detachPromise(runRtbfRequest())}
                  >
                    {rtbfRunning ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : null}
                    {rtbfDryRun ? '开始安全预演' : '确认执行删除'}
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {rtbfResult !== null && <RtbfResultSummary result={rtbfResult} />}
        </DangerZonePanel>

        <GovernanceOpsPanel />
      </div>
    </section>
  )
}
