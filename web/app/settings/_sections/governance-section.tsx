'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DangerZonePanel } from '@/components/settings/danger-zone-panel'
import { GovernanceOpsPanel } from '@/components/settings/governance-ops-panel'
import { SettingsSwitch } from '@/components/settings/settings-switch'
import { settingsTextTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'
import { rbacApi, rtbfApi, type SystemSettings, type TenantMember } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'
import { AlertCircle, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

type GovernanceSettings = NonNullable<SystemSettings['governance']>

type GovernanceSectionProps = {
  isGovernanceEnabled: boolean
  isPiiAnonymizeEnabled: boolean
  isSecretsRedactEnabled: boolean
  isQuarantineOnDropEnabled: boolean
  updateGovernance: (patch: Partial<GovernanceSettings>) => void
}

const FIELD_LABEL = settingsTextTokens.fieldLabel
const RTBF_MEMBERS_PARAMS = { limit: 500 } as const
const RTBF_CURRENT_ACCOUNT_VALUE = '__current_account__'
const RTBF_MANUAL_ACCOUNT_VALUE = '__manual_account__'

type RtbfTone = 'idle' | 'info' | 'success' | 'danger'
type RtbfSubjectSource = 'current' | 'member' | 'manual'

type RtbfResultView = {
  title: string
  description: string
  tone: RtbfTone
  badge: string
  metrics: Array<{ label: string; value: string; hint?: string }>
  rawText: string | null
}

const RTBF_STATUS_LABELS: Record<string, string> = {
  accepted: '已受理',
  completed: '已完成',
  failed: '失败',
  pending: '等待中',
  processing: '处理中',
  running: '执行中',
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function stringValue(value: unknown, fallback = '-'): string {
  if (typeof value === 'string' && value.trim()) return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  return fallback
}

function numberValue(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10)
    if (Number.isFinite(parsed)) return parsed
  }
  return 0
}

function formatRtbfRaw(value: unknown): string | null {
  if (value == null) return null
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return '无法序列化的响应'
  }
}

function rtbfNoteCopy(value: string): string {
  if (!value) return ''
  if (value.includes('status persistence is not enabled')) {
    return '当前后端未启用状态持久化，只返回受理状态；完整执行结果以请求返回为准'
  }
  return value
}

function rtbfResultTitle(
  errors: number,
  isStatusOnly: boolean,
  dryRun: boolean,
  statusLabel: string
): string {
  if (errors > 0) return 'RTBF 执行存在错误'
  if (isStatusOnly) return `状态查询：${statusLabel}`
  if (dryRun) return '安全预演完成'
  return '级联删除已执行'
}

function rtbfResultDescription(
  note: string,
  message: string,
  dryRun: boolean,
  eligible: number,
  deleted: number
): string {
  if (note) return note
  if (message) return message
  if (dryRun) return `本次只评估影响范围，命中 ${eligible} 个候选文档，未执行删除`
  return `本次已执行级联删除，删除 ${deleted}/${eligible} 个候选文档`
}

function rtbfResultTone(errors: number, isStatusOnly: boolean): RtbfTone {
  if (errors > 0) return 'danger'
  if (isStatusOnly) return 'info'
  return 'success'
}

function rtbfResultBadge(
  errors: number,
  dryRun: boolean,
  statusLabel: string
): string {
  if (errors > 0) return '需排查'
  if (dryRun) return '安全预演'
  return statusLabel || '已执行'
}

function selectedRtbfSubjectValue(
  source: RtbfSubjectSource,
  selectedMember: TenantMember | null
): string {
  if (source === 'current') return RTBF_CURRENT_ACCOUNT_VALUE
  if (source === 'member' && selectedMember) {
    return String(selectedMember.user_id || '').trim()
  }
  return RTBF_MANUAL_ACCOUNT_VALUE
}

function rtbfSubjectSourceLabel(source: RtbfSubjectSource): string {
  if (source === 'current') return '当前账号自动绑定'
  if (source === 'member') return '成员列表选择'
  return '手动覆盖'
}

function rtbfModeButtonClass(isActive: boolean, tone: 'info' | 'destructive') {
  if (isActive && tone === 'info') {
    return 'border-info/30 bg-info/10 text-info shadow-[0_8px_22px_hsl(var(--info)/0.08)]'
  }
  if (isActive && tone === 'destructive') {
    return 'border-destructive/35 bg-destructive/10 text-destructive shadow-[0_8px_22px_hsl(var(--destructive)/0.08)]'
  }
  if (tone === 'info') {
    return 'border-info/15 bg-info/[0.025] text-muted-foreground hover:border-info/25 hover:bg-info/[0.055] hover:text-foreground/78'
  }
  return 'border-info/15 bg-info/[0.025] text-muted-foreground hover:border-destructive/25 hover:bg-destructive/5 hover:text-foreground/78'
}

function buildRtbfResultView(value: unknown): RtbfResultView {
  const record = asRecord(value)
  if (!record) {
    return {
      title: '尚未调用 RTBF 接口',
      description: '默认会绑定当前账号需要处理其他用户时，从成员列表选择；只有列表里找不到时才手动输入账号 ID',
      tone: 'idle',
      badge: '默认自动绑定',
      metrics: [
        { label: '1 选账号', value: '自动', hint: '当前账号 / 成员列表' },
        { label: '2 先预演', value: '安全预演', hint: '只评估不删除' },
        { label: '3 再执行', value: '确认删除', hint: '确认后切换删除' },
        { label: '4 查状态', value: '工单', hint: '工单自动回填' },
      ],
      rawText: null,
    }
  }

  const eligible = numberValue(record.eligible)
  const deleted = numberValue(record.deleted)
  const errors = numberValue(record.errors)
  const cacheInvalidations = numberValue(record.cache_invalidations)
  const documents = Array.isArray(record.documents) ? record.documents.length : eligible
  const dryRun = record.dry_run !== false
  const status = stringValue(record.status, '')
  const statusLabel = status ? (RTBF_STATUS_LABELS[status] ?? status) : ''
  const subject = stringValue(record.subject_account_id, '')
  const ticketId = stringValue(record.ticket_id, '')
  const note = rtbfNoteCopy(stringValue(record.note, ''))
  const message = stringValue(record.message, '')
  const isStatusOnly = Boolean(ticketId && status && !('eligible' in record))
  const title = rtbfResultTitle(errors, isStatusOnly, dryRun, statusLabel)
  const description = rtbfResultDescription(note, message, dryRun, eligible, deleted)

  if (isStatusOnly) {
    return {
      title,
      description,
      tone: errors > 0 ? 'danger' : 'info',
      badge: statusLabel || '已查询',
      metrics: [
        { label: '工单', value: ticketId ? `${ticketId.slice(0, 10)}...` : '-', hint: '完整 ID 见输入框' },
        { label: '状态', value: statusLabel || '-', hint: '后端状态' },
        { label: '持久化', value: note ? '未启用' : '-', hint: '状态存储' },
        { label: '动作', value: '查询', hint: '未触发删除' },
      ],
      rawText: formatRtbfRaw(value),
    }
  }

  return {
    title,
    description,
    tone: rtbfResultTone(errors, isStatusOnly),
    badge: rtbfResultBadge(errors, dryRun, statusLabel),
    metrics: [
      { label: '候选文档', value: String(eligible || documents || 0), hint: subject ? `账号 ${subject}` : '按账号匹配' },
      { label: '已删除', value: String(deleted), hint: dryRun ? '安全预演未删除' : '实际删除数' },
      { label: '错误', value: String(errors), hint: errors > 0 ? '查看原始响应' : '无错误' },
      { label: '缓存刷新', value: String(cacheInvalidations), hint: '相关数据集缓存' },
    ],
    rawText: formatRtbfRaw(value),
  }
}

function rtbfToneClass(tone: RtbfTone): string {
  if (tone === 'danger') return 'border-destructive/25 bg-destructive/10 text-destructive'
  if (tone === 'success') return 'border-success/25 bg-success/10 text-success'
  if (tone === 'info') return 'border-info/25 bg-info/10 text-info'
  return 'border-border/70 bg-muted/40 text-muted-foreground'
}

function rtbfMemberLabel(member: TenantMember): { primary: string; secondary: string } {
  const id = String(member.user_id || '').trim()
  if (!id) return { primary: '未知成员', secondary: '缺少账号 ID' }
  if (id.includes('@')) {
    const [name, domain] = id.split('@')
    return { primary: name || id, secondary: domain || id }
  }
  return { primary: id.length > 18 ? `${id.slice(0, 10)}...${id.slice(-6)}` : id, secondary: '账号 ID' }
}

function RtbfResultSummary({ value }: Readonly<{ value: unknown }>) {
  const result = buildRtbfResultView(value)

  return (
    <div
      data-testid="rtbf-result-summary"
      className="mt-3 rounded-xl border border-info/15 bg-info/[0.025] p-3 shadow-none"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground/75">个人数据操作结果</div>
          <div className="mt-1 text-[12px] font-medium tracking-[-0.005em] text-foreground">{result.title}</div>
          <p className="mt-1 max-w-3xl text-[11px] leading-[1.55] text-muted-foreground">{result.description}</p>
        </div>
        <span className={cn('inline-flex w-fit shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold', rtbfToneClass(result.tone))}>
          {result.badge}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
        {result.metrics.map((metric) => (
          <div key={metric.label} className="rounded-lg border border-border/50 bg-muted/10 px-2.5 py-2">
            <div className="flex items-center justify-between gap-2">
              <div className="truncate text-[10px] font-medium text-muted-foreground/85">{metric.label}</div>
              <div className="rounded-full bg-info/[0.06] px-1.5 py-0.5 text-[10px] font-medium text-foreground/78">{metric.value}</div>
            </div>
            {metric.hint ? <div className="mt-1.5 truncate text-[10px] leading-3 text-muted-foreground/72">{metric.hint}</div> : null}
          </div>
        ))}
      </div>

      <details
        data-testid="rtbf-raw-response"
        className="group mt-2.5 rounded-lg border border-border/60 bg-muted/15 px-2.5 py-2 text-[11px] text-muted-foreground"
      >
        <summary className="cursor-pointer select-none font-medium text-muted-foreground transition-colors hover:text-info">
          原始响应（排障时展开）
        </summary>
        {result.rawText ? (
          <pre className="mt-2 max-h-44 overflow-auto rounded-md border border-info/15 bg-muted/35 p-2 font-mono text-[11px] leading-4 text-muted-foreground whitespace-pre-wrap break-words">
            {result.rawText}
          </pre>
        ) : (
          <div className="mt-2 rounded-md border border-dashed border-info/15 bg-info/[0.025] px-2 py-1.5 text-[11px] text-muted-foreground">
            暂无后端响应提交请求或查询状态后，这里会保留原始材料
          </div>
        )}
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
  const [rtbfAccountId, setRtbfAccountId] = useState('')
  const [rtbfTicketId, setRtbfTicketId] = useState('')
  const [rtbfDryRun, setRtbfDryRun] = useState(true)
  const [rtbfMaxDocs, setRtbfMaxDocs] = useState(100)
  const [rtbfMaxRetries, setRtbfMaxRetries] = useState(1)
  const [rtbfRunningKey, setRtbfRunningKey] = useState<string | null>(null)
  const [rtbfResult, setRtbfResult] = useState<unknown>(null)
  const [rtbfSubjectSource, setRtbfSubjectSource] =
    useState<RtbfSubjectSource>('current')

  const currentAccessQuery = useQuery({
    queryKey: queryKeys.access.current,
    queryFn: () => rbacApi.getCurrentTenantAccess(),
    retry: false,
  })
  const membersQuery = useQuery({
    queryKey: queryKeys.rbac.members(RTBF_MEMBERS_PARAMS),
    queryFn: async () => {
      const res = await rbacApi.listTenantMembers(RTBF_MEMBERS_PARAMS)
      return Array.isArray(res.items) ? res.items : []
    },
    retry: false,
  })
  const members = useMemo(() => membersQuery.data || [], [membersQuery.data])
  const currentAccountId = String(currentAccessQuery.data?.account_id || '').trim()
  const currentMember = useMemo(() => {
    return (
      members.find((member) => member.is_current && String(member.user_id || '').trim()) ||
      members.find((member) => String(member.user_id || '').trim() === currentAccountId) ||
      null
    )
  }, [currentAccountId, members])
  const autoSubjectId = String(currentMember?.user_id || currentAccountId || '').trim()
  const selectableMembers = useMemo(() => {
    const seen = new Set<string>()
    return members.filter((member) => {
      const id = String(member.user_id || '').trim()
      if (!id || id === autoSubjectId || seen.has(id)) return false
      seen.add(id)
      return true
    })
  }, [autoSubjectId, members])
  const selectedMember = useMemo(
    () => members.find((member) => String(member.user_id || '').trim() === rtbfAccountId.trim()) || null,
    [members, rtbfAccountId]
  )
  const selectedSubjectValue = selectedRtbfSubjectValue(
    rtbfSubjectSource,
    selectedMember
  )
  const subjectSourceLabel = rtbfSubjectSourceLabel(rtbfSubjectSource)
  const isDeleteMode = rtbfDryRun === false

  useEffect(() => {
    if (rtbfSubjectSource !== 'current') return
    if (!autoSubjectId) return
    setRtbfAccountId(autoSubjectId)
  }, [autoSubjectId, rtbfSubjectSource])

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

  return (
    <section>
      <div className={cn(systemWorkbenchTokens.panel, 'space-y-3 border-info/15 bg-info/[0.025] p-3.5')}>
        <div className="flex items-start justify-between gap-3">
          <Alert className="flex-1 p-3 shadow-none [&>svg]:left-3 [&>svg]:top-3 [&>svg~*]:pl-6">
            <AlertCircle className="h-3.5 w-3.5" />
            <div>
              <AlertTitle className="text-xs">默认治理规则</AlertTitle>
              <AlertDescription className={settingsTextTokens.helpText}>
                这些开关会影响“入库前清洗/脱敏”，用于没有单独配置数据集或文档级管线时的默认行为
              </AlertDescription>
            </div>
          </Alert>
          <div className="inline-flex shrink-0 items-center gap-1 rounded-full border border-info/20 bg-info/10 px-2 py-0.5 text-[11px] font-semibold text-info">
            保存后通常可立即生效
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={settingsTextTokens.panelTitle}>启用数据治理</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>打开后才会应用下方治理项（对新入库文档生效）</div>
            </div>
            <SettingsSwitch
              checked={isGovernanceEnabled}
              onCheckedChange={(checked) => updateGovernance({ enabled: checked })}
              className="shrink-0"
              aria-label="切换数据治理开关（governance.enabled）"
            />
          </div>

          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={settingsTextTokens.panelTitle}>个人信息脱敏</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                尝试识别并匿名化手机号/邮箱等个人信息（可能影响检索/可读性）
              </div>
            </div>
            <SettingsSwitch
              checked={isPiiAnonymizeEnabled}
              onCheckedChange={(checked) => updateGovernance({ pii_anonymize: checked })}
              className="shrink-0"
              aria-label="切换 PII 脱敏（governance.pii_anonymize）"
            />
          </div>

          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={settingsTextTokens.panelTitle}>密钥信息脱敏</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                尝试识别并遮蔽 API 密钥、访问令牌等敏感凭据
              </div>
            </div>
            <SettingsSwitch
              checked={isSecretsRedactEnabled}
              onCheckedChange={(checked) => updateGovernance({ secrets_redact: checked })}
              className="shrink-0"
              aria-label="切换密钥信息脱敏（governance.secrets_redact）"
            />
          </div>

          <div className="flex items-start justify-between gap-3 rounded-lg border border-border/70 bg-muted/20 px-3 py-2.5">
            <div>
              <div className={settingsTextTokens.panelTitle}>质量过滤触发时隔离</div>
              <div className={cn(settingsTextTokens.helpText, 'mt-0.5')}>
                当触发“低密度/仅目录”等过滤时，将文档标记为“已隔离（quarantined）”（便于排查）
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
          title="个人数据删除闭环（RTBF）"
          impact="会按账号级联影响文档、分块、向量、图谱和缓存；默认只做安全预演，确认范围后才执行删除"
          badge="默认收起"
          compact
          tone="neutral"
          icon="help"
        >
          <div className="grid gap-2 md:grid-cols-2">
            <button
              type="button"
              onClick={() => setRtbfDryRun(true)}
              className={cn(
                'rounded-xl border px-3 py-2 text-left transition-colors',
                rtbfModeButtonClass(rtbfDryRun, 'info')
              )}
              aria-pressed={rtbfDryRun}
            >
              <div className="text-[12px] font-medium">安全预演</div>
              <div className="mt-0.5 text-[11px] leading-4 opacity-80">推荐先点这个，只返回命中文档和影响范围，不删除数据</div>
            </button>
            <button
              type="button"
              onClick={() => setRtbfDryRun(false)}
              className={cn(
                'rounded-xl border px-3 py-2 text-left transition-colors',
                rtbfModeButtonClass(isDeleteMode, 'destructive')
              )}
              aria-pressed={isDeleteMode}
            >
              <div className="text-[12px] font-medium">执行删除</div>
              <div className="mt-0.5 text-[11px] leading-4 opacity-80">只在预演结果确认后使用，会调用后端级联删除并刷新相关缓存</div>
            </button>
          </div>

          <div className="mt-3 rounded-xl border border-info/15 bg-info/[0.025] p-3">
            <div className="grid gap-3 md:grid-cols-4">
              <div className="space-y-1.5 md:col-span-2">
                <div className="flex items-center justify-between gap-2">
                  <div className={FIELD_LABEL}>目标账号</div>
                  <span className="rounded-full border border-info/20 bg-info/10 px-1.5 py-0.5 text-[10px] font-semibold text-info">
                    {subjectSourceLabel}
                  </span>
                </div>
                <Select
                  value={selectedSubjectValue}
                  onValueChange={(value) => {
                    if (value === RTBF_CURRENT_ACCOUNT_VALUE) {
                      setRtbfSubjectSource('current')
                      if (autoSubjectId) setRtbfAccountId(autoSubjectId)
                      return
                    }
                    if (value === RTBF_MANUAL_ACCOUNT_VALUE) {
                      setRtbfSubjectSource('manual')
                      return
                    }
                    setRtbfSubjectSource('member')
                    setRtbfAccountId(value)
                  }}
                >
                  <SelectTrigger className="h-8 rounded-md border-info/15 bg-info/[0.025] text-[12px]">
                    <SelectValue placeholder="自动绑定当前账号" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={RTBF_CURRENT_ACCOUNT_VALUE}>
                      当前账号（自动绑定）{autoSubjectId ? ` · ${autoSubjectId}` : ' · 加载中'}
                    </SelectItem>
                    {selectableMembers.map((member) => {
                      const id = String(member.user_id || '').trim()
                      const label = rtbfMemberLabel(member)
                      return (
                        <SelectItem key={id} value={id}>
                          {label.primary} · {label.secondary}
                        </SelectItem>
                      )
                    })}
                    <SelectItem value={RTBF_MANUAL_ACCOUNT_VALUE}>
                      手动输入账号 ID
                    </SelectItem>
                  </SelectContent>
                </Select>
                <div className={cn('rounded-lg border border-border/60 bg-muted/10 px-2.5 py-2', settingsTextTokens.microText)}>
                  将提交：<span className="font-mono text-foreground/78">{rtbfAccountId.trim() || '等待自动绑定'}</span>
                  {membersQuery.isError ? '成员列表加载失败时仍可使用手动输入' : '下拉会优先使用当前账号，也可切换到其他租户成员'}
                </div>
              </div>
              <div className="space-y-1.5 md:col-span-2">
                <div className={FIELD_LABEL}>手动覆盖（找不到成员时使用）</div>
                <Input
                  value={rtbfSubjectSource === 'manual' ? rtbfAccountId : ''}
                  onChange={(event) => {
                    setRtbfSubjectSource('manual')
                    setRtbfAccountId(event.target.value)
                  }}
                  className="h-8 rounded-md border-info/15 bg-info/[0.025] text-[12px]"
                  placeholder="例如 user-123 / acct-1 / 用户 UUID"
                />
                <div className={settingsTextTokens.microText}>
                  后端会按文档归属账号和生命周期负责人匹配；如果填写用户 UUID，也会一并匹配建议从成员权限或审计日志复制，不要填昵称
                </div>
              </div>
              <div className="space-y-1.5">
                <div className={FIELD_LABEL}>最多扫描文档</div>
                <Input
                  value={String(rtbfMaxDocs)}
                  onChange={(event) => setRtbfMaxDocs(Number.parseInt(event.target.value || '0', 10) || 100)}
                  className="h-8 rounded-md border-info/15 bg-info/[0.025] text-[12px]"
                  inputMode="numeric"
                />
                <div className={settingsTextTokens.microText}>保护阈值，后端允许 1-1000</div>
              </div>
              <div className="space-y-1.5">
                <div className={FIELD_LABEL}>失败重试</div>
                <Input
                  value={String(rtbfMaxRetries)}
                  onChange={(event) => setRtbfMaxRetries(Number.parseInt(event.target.value || '0', 10) || 1)}
                  className="h-8 rounded-md border-info/15 bg-info/[0.025] text-[12px]"
                  inputMode="numeric"
                />
                <div className={settingsTextTokens.microText}>删除失败时重试，后端允许 0-10</div>
              </div>
              <div className="space-y-1.5 md:col-span-2">
                <div className={FIELD_LABEL}>状态查询工单</div>
                <Input
                  value={rtbfTicketId}
                  onChange={(event) => setRtbfTicketId(event.target.value)}
                  className="h-8 rounded-md border-info/15 bg-info/[0.025] font-mono text-[12px]"
                  placeholder="提交请求后自动回填；也可粘贴已有工单 ID"
                />
              </div>
              <div className="flex flex-col gap-2 md:col-span-2">
                <div className={cn('rounded-lg border border-dashed border-border/70 bg-muted/15 px-2.5 py-2', settingsTextTokens.helpText)}>
                  操作顺序：确认目标账号 → 点“开始安全预演” → 看候选文档数量 → 确认无误后切换“执行删除”
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant={rtbfDryRun ? 'outline' : 'destructive'}
                    className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold"
                    disabled={Boolean(rtbfRunningKey) || !rtbfAccountId.trim()}
                    onClick={() =>
                      detachPromise(
                        runRtbfAction('RTBF 请求', rtbfDryRun ? 'RTBF 安全预演' : 'RTBF 删除执行', () =>
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
                    {rtbfRunningKey === 'RTBF 请求' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : null}
                    {rtbfDryRun ? '开始安全预演' : '确认执行删除'}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold"
                    disabled={Boolean(rtbfRunningKey) || !rtbfTicketId.trim()}
                    onClick={() => detachPromise(runRtbfAction('RTBF 状态', 'RTBF 状态查询', () => rtbfApi.getStatus(rtbfTicketId.trim())))}
                  >
                    {rtbfRunningKey === 'RTBF 状态' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : null}
                    查询工单状态
                  </Button>
                </div>
              </div>
            </div>
          </div>

          <RtbfResultSummary value={rtbfResult} />
        </DangerZonePanel>

        <GovernanceOpsPanel />
      </div>
    </section>
  )
}
