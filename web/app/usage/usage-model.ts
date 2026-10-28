import type {
  ChatCostUsageRow,
  ChatCostUsageSummary,
  ChatTokenQuotaStatus,
  ChatTokenUsageSummary,
  TenantQuotaSummary,
} from '@/types'

export type LabelState = 'ready' | 'pending' | 'error'
export type UsageView = 'attribution' | 'resources' | 'quotas'
export type UsageScope = { windowDays: number; view: UsageView; page: number }

export function parseUsageLocation(search: string): UsageScope {
  const params = new URLSearchParams(search), days = Number(params.get('window_days')), page = Number(params.get('page'))
  const view = params.get('view')
  return { windowDays: [7, 14, 30].includes(days) ? days : 7,
    view: view === 'resources' || view === 'quotas' ? view : 'attribution',
    page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1 }
}
export type UsageRow = {
  key: string
  datasetId: string | null
  name: string
  visibility: 'available' | 'hidden' | 'unbound' | 'unresolved'
  href: string | null
  messages: number | null
  assistantTokens: number | null
  share: number | null
  cost: ChatCostUsageRow | null
}

function finite(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}

export function shortDatasetId(id: string) {
  return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id
}

export function formatCount(value: number | null | undefined, digits = 0) {
  const n = finite(value)
  return n === null ? '—' : n.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

export function averageRetrievalMs(seconds: number | null | undefined, messages: number | null | undefined) {
  const elapsed = finite(seconds), count = finite(messages)
  return elapsed === null || count === null || count <= 0 ? null : elapsed * 1000 / count
}

export function formatDuration(milliseconds: number | null | undefined) {
  const n = finite(milliseconds)
  if (n === null) return '—'
  return n < 1000 ? `${formatCount(n)} ms` : `${formatCount(n / 1000, 2)} s`
}

export function formatBytes(value: number | null | undefined) {
  const n = finite(value)
  if (n === null) return '—'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let size = n, index = 0
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1 }
  return `${formatCount(size, index === 0 ? 0 : 1)} ${units[index]}`
}

export function dateTime(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

export function formatWindow(start: string | null | undefined, end: string | null | undefined) {
  const first = dateTime(start), last = dateTime(end)
  return first === '—' || last === '—' ? '未返回统计窗口' : `${first} — ${last}`
}

export function buildUsageRows(
  summary: ChatTokenUsageSummary | null | undefined,
  cost: ChatCostUsageSummary | null | undefined,
  labels: Readonly<Record<string, string>>,
  labelState: LabelState,
): UsageRow[] {
  const rows = new Map<string, UsageRow>()
  const getRow = (rawId: string | null | undefined) => {
    const datasetId = rawId || null, key = datasetId ? `dataset:${datasetId}` : 'unbound'
    const found = rows.get(key)
    if (found) return found
    const knownName = datasetId ? labels[datasetId] : undefined
    const visibility = !datasetId ? 'unbound' : knownName ? 'available' : labelState === 'ready' ? 'hidden' : 'unresolved'
    const href = datasetId && visibility === 'available'
      ? `/knowledge?${new URLSearchParams({ dataset: datasetId, lifecycle: 'all', status: 'all' })}` : null
    const row: UsageRow = { key, datasetId, visibility, href,
      name: knownName || (!datasetId ? '未绑定数据集' : visibility === 'hidden' ? '不可见数据集' : `数据集 ${shortDatasetId(datasetId)}`),
      messages: null, assistantTokens: null, share: null, cost: null }
    rows.set(key, row)
    return row
  }
  for (const item of summary?.by_dataset ?? []) {
    const row = getRow(item.dataset_id)
    row.messages = finite(item.assistant_messages)
    row.assistantTokens = finite(item.assistant_tokens)
    const total = finite(summary?.total_assistant_tokens)
    row.share = row.assistantTokens !== null && total !== null && total > 0 ? row.assistantTokens / total * 100 : null
  }
  for (const item of cost?.by_dataset ?? []) {
    const row = getRow(item.dataset_id)
    row.cost = item
    row.messages ??= finite(item.assistant_messages)
  }
  return [...rows.values()].sort((a, b) =>
    (b.assistantTokens ?? -1) - (a.assistantTokens ?? -1) ||
    (b.cost?.llm_total_tokens ?? -1) - (a.cost?.llm_total_tokens ?? -1) || a.key.localeCompare(b.key))
}

export type QuotaKey = 'chat' | 'documents' | 'storage' | 'embedding' | 'qps'
export type QuotaReading = {
  key: QuotaKey
  title: string
  enabled: boolean | null
  used: number | null
  limit: number | null
  remaining: number | null
  percentage: number | null
  progress: number | null
  exceeded: boolean
  tone: 'neutral' | 'blue' | 'teal' | 'violet' | 'warning' | 'danger'
  scope: string
  windowHours: number | null
  windowStart: string | null
  windowEnd: string | null
  unit: string
  mode: string | null
  scopes: string[]
}

export function buildQuotaReadings(
  chat: ChatTokenQuotaStatus | null | undefined,
  tenant: TenantQuotaSummary | null | undefined,
): QuotaReading[] {
  const docs = tenant?.documents, storage = tenant?.storage, embed = tenant?.embedding_chars, qps = tenant?.qps
  const inputs = [
    { key: 'chat' as const, title: '聊天 token', data: chat, used: chat?.used, limit: chat?.limit, remaining: chat?.remaining, windowHours: chat?.window_hours, windowStart: chat?.window_start, windowEnd: chat?.window_end, unit: 'token', tone: 'violet' as const, mode: chat?.mode },
    { key: 'documents' as const, title: '文档数量', data: docs, used: docs?.used, limit: docs?.limit, remaining: docs?.remaining, unit: '个', tone: 'blue' as const },
    { key: 'storage' as const, title: '存储空间', data: storage, used: storage?.used_bytes, limit: storage?.limit_bytes, remaining: storage?.remaining_bytes, unit: 'bytes', tone: 'teal' as const },
    { key: 'embedding' as const, title: '向量化字符', data: embed, used: embed?.used_chars, limit: embed?.limit_chars, remaining: embed?.remaining_chars, windowHours: embed?.window_hours, windowStart: embed?.window_start, windowEnd: embed?.window_end, unit: '字符', tone: 'blue' as const, mode: embed?.mode },
    { key: 'qps' as const, title: '请求限流', data: qps, used: qps?.rps, limit: qps?.burst, unit: '请求 / 秒', tone: 'violet' as const, mode: qps?.mode },
  ]
  return inputs.map(input => {
    const enabled = input.data?.enabled ?? null
    const used = enabled ? finite(input.used) : null, limit = enabled ? finite(input.limit) : null
    const percentage = input.key !== 'qps' && used !== null && limit !== null && limit > 0 ? used / limit * 100 : null
    const exceeded = enabled === true && Boolean(input.data && 'exceeded' in input.data && input.data.exceeded === true)
    const windowHours = 'windowHours' in input ? finite(input.windowHours) : null
    return { key: input.key, title: input.title, enabled, used, limit,
      remaining: enabled && 'remaining' in input ? finite(input.remaining) : null,
      percentage, progress: percentage === null ? null : Math.min(100, Math.max(0, percentage)), exceeded,
      tone: enabled === null || !enabled ? 'neutral' : exceeded ? 'danger' : percentage !== null && percentage >= 80 ? 'warning' : input.tone,
      scope: input.key === 'qps' ? '速率配置' : windowHours !== null && windowHours > 0 ? `近 ${formatCount(windowHours)} 小时` : ['storage', 'documents'].includes(input.key) ? '当前占用' : '独立窗口',
      windowHours, windowStart: 'windowStart' in input ? input.windowStart || null : null,
      windowEnd: 'windowEnd' in input ? input.windowEnd || null : null,
      unit: input.unit, mode: 'mode' in input ? input.mode ?? null : null,
      scopes: input.key === 'qps' ? (qps?.scopes ?? []).map(s => scopeNames[s] ?? s) : [],
    }
  })
}

export function quotaValue(value: number | null, quota: QuotaReading) {
  return quota.unit === 'bytes' ? formatBytes(value) : formatCount(value, quota.key === 'qps' ? 2 : 0)
}

export function quotaStatus(quota: QuotaReading) {
  if (quota.enabled === null) return '未取得'
  if (!quota.enabled) return '未启用'
  if (quota.exceeded) return '已达上限'
  if (quota.key !== 'qps' && quota.percentage === null) return '状态待确认'
  return quota.mode === 'warn' ? '仅告警' : '已启用'
}

export function quotaMode(mode: string | null) {
  return mode ? modeNames[mode] ?? mode : '—'
}

const scopeNames: Readonly<Record<string, string>> = { chat: '聊天', retrieval: '检索' }
const modeNames: Readonly<Record<string, string>> = { block: '超限阻止请求', warn: '仅告警', disabled: '未启用' }
