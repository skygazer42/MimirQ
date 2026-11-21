import type {
  ChatCostUsageRow,
  ChatCostUsageSummary,
  ChatTokenQuotaStatus,
  ChatTokenUsageSummary,
  TenantQuotaSummary,
} from '@/types/usage'

export type LabelState = 'ready' | 'pending' | 'error'
export type UsageView = 'attribution' | 'resources' | 'quotas'
export const USAGE_WINDOW_DAYS = [7, 14, 30] as const
export type UsageScope = { windowDays: (typeof USAGE_WINDOW_DAYS)[number]; view: UsageView; page: number }

export function parseUsageLocation(search: string): UsageScope {
  const params = new URLSearchParams(search)
  const days = Number(params.get('window_days'))
  const page = Number(params.get('page'))
  const view = params.get('view')
  return {
    windowDays: USAGE_WINDOW_DAYS.find((windowDays) => windowDays === days) ?? USAGE_WINDOW_DAYS[0],
    view: view === 'resources' || view === 'quotas' ? view : 'attribution',
    page: Number.isSafeInteger(page) && page >= 1 ? page : 1,
  }
}

export function buildUsageLocation(href: string, next: Partial<UsageScope>): URL {
  const url = new URL(href)
  const scope = { ...parseUsageLocation(url.search), ...next }
  url.searchParams.set('window_days', String(scope.windowDays))
  if (scope.view === 'attribution') url.searchParams.delete('view')
  else url.searchParams.set('view', scope.view)
  if (scope.page === 1) url.searchParams.delete('page')
  else url.searchParams.set('page', String(scope.page))
  return url
}

type UsageDataset =
  | { datasetId: null; visibility: 'unbound'; href: null }
  | { datasetId: string; visibility: 'available' | 'hidden' | 'unresolved'; href: string | null }

export type UsageRow = {
  key: string
  name: string
  messages: number | null
  assistantTokens: number | null
  share: number | null
  cost: ChatCostUsageRow | null
} & UsageDataset

export function shortDatasetId(id: string) {
  if (id.length === 0) return '""'
  return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id
}

export function formatCount(value: number | null | undefined, digits = 0) {
  return value === null || value === undefined ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

export function averageRetrievalMs(seconds: number | undefined, messages: number | undefined) {
  return seconds === undefined || messages === undefined || messages <= 0 ? undefined : (seconds * 1000) / messages
}

export function formatDuration(milliseconds: number | null | undefined) {
  if (milliseconds === null || milliseconds === undefined) return '—'
  return milliseconds < 1000 ? `${formatCount(milliseconds)} ms` : `${formatCount(milliseconds / 1000, 2)} s`
}

export function formatBytes(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let size = value
  let index = 0
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${formatCount(size, index === 0 ? 0 : 1)} ${units[index]}`
}

export function formatUsageDateTime(value: string | number) {
  const date = new Date(value)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function formatWindow(start: string, end: string) {
  return `${formatUsageDateTime(start)} — ${formatUsageDateTime(end)}`
}

export function buildUsageRows(
  summary: ChatTokenUsageSummary | undefined,
  cost: ChatCostUsageSummary | undefined,
  labels: ReadonlyMap<string, string> | undefined,
  labelState: LabelState,
): UsageRow[] {
  const rows = new Map<string, UsageRow>()
  const getRow = (datasetId: string | null) => {
    const key = datasetId === null ? 'unbound' : `dataset:${datasetId}`
    const found = rows.get(key)
    if (found !== undefined) return found
    const knownName = datasetId === null ? undefined : labels?.get(datasetId)
    const identity: UsageDataset =
      datasetId === null
        ? { datasetId: null, visibility: 'unbound', href: null }
        : {
            datasetId,
            visibility: knownName !== undefined ? 'available' : labelState === 'ready' ? 'hidden' : 'unresolved',
            href:
              knownName === undefined
                ? null
                : `/knowledge?${new URLSearchParams({ dataset: datasetId, lifecycle: 'all', status: 'all' })}`,
          }
    const row: UsageRow = {
      ...identity,
      key,
      name:
        knownName !== undefined
          ? knownName.length === 0
            ? '""'
            : knownName
          : datasetId === null
            ? '未绑定数据集'
            : identity.visibility === 'hidden'
              ? '不可见数据集'
              : `数据集 ${shortDatasetId(datasetId)}`,
      messages: null,
      assistantTokens: null,
      share: null,
      cost: null,
    }
    rows.set(key, row)
    return row
  }
  if (summary !== undefined) {
    for (const item of summary.by_dataset) {
      const row = getRow(item.dataset_id)
      row.messages = item.assistant_messages
      row.assistantTokens = item.assistant_tokens
      row.share =
        summary.total_assistant_tokens > 0 ? (item.assistant_tokens / summary.total_assistant_tokens) * 100 : null
    }
  }
  if (cost !== undefined) {
    for (const item of cost.by_dataset) {
      const row = getRow(item.dataset_id)
      row.cost = item
      if (row.messages === null) row.messages = item.assistant_messages
    }
  }
  return [...rows.values()].sort((a, b) => {
    if (a.assistantTokens !== b.assistantTokens) {
      if (a.assistantTokens === null) return 1
      if (b.assistantTokens === null) return -1
      return b.assistantTokens - a.assistantTokens
    }
    if (a.cost === null && b.cost !== null) return 1
    if (b.cost === null && a.cost !== null) return -1
    if (a.cost !== null && b.cost !== null && a.cost.llm_total_tokens !== b.cost.llm_total_tokens) {
      return b.cost.llm_total_tokens - a.cost.llm_total_tokens
    }
    return a.key.localeCompare(b.key)
  })
}

export type QuotaKey = 'chat' | 'documents' | 'storage' | 'embedding' | 'qps'
export type QuotaReading = {
  key: QuotaKey
  title: string
  enabled: boolean | undefined
  used: number | undefined
  limit: number | undefined
  remaining?: number
  percentage: number | undefined
  progress: number | undefined
  exceeded?: boolean
  tone: 'neutral' | 'blue' | 'teal' | 'violet' | 'warning' | 'danger'
  scope: string
  windowHours?: number
  windowStart?: string
  windowEnd?: string
  unit: string
  mode?: string
  scopes?: readonly string[]
}

export function buildQuotaReadings(
  chat: ChatTokenQuotaStatus | undefined,
  tenant: TenantQuotaSummary | undefined,
): QuotaReading[] {
  const docs = tenant?.documents
  const storage = tenant?.storage
  const embed = tenant?.embedding_chars
  const qps = tenant?.qps
  const inputs: Omit<QuotaReading, 'percentage' | 'progress' | 'scope'>[] = [
    {
      key: 'chat',
      title: '聊天 token',
      enabled: chat?.enabled,
      exceeded: chat?.exceeded,
      used: chat?.used,
      limit: chat?.limit,
      remaining: chat?.remaining,
      windowHours: chat?.window_hours,
      windowStart: chat?.window_start,
      windowEnd: chat?.window_end,
      unit: 'token',
      tone: 'violet',
      mode: chat?.mode,
    },
    {
      key: 'documents',
      title: '文档数量',
      enabled: docs?.enabled,
      exceeded: docs?.exceeded,
      used: docs?.used,
      limit: docs?.limit,
      remaining: docs?.remaining,
      unit: '个',
      tone: 'blue',
    },
    {
      key: 'storage',
      title: '存储空间',
      enabled: storage?.enabled,
      exceeded: storage?.exceeded,
      used: storage?.used_bytes,
      limit: storage?.limit_bytes,
      remaining: storage?.remaining_bytes,
      unit: 'bytes',
      tone: 'teal',
    },
    {
      key: 'embedding',
      title: '向量化字符',
      enabled: embed?.enabled,
      exceeded: embed?.exceeded,
      used: embed?.used_chars,
      limit: embed?.limit_chars,
      remaining: embed?.remaining_chars,
      windowHours: embed?.window_hours,
      windowStart: embed?.window_start,
      windowEnd: embed?.window_end,
      unit: '字符',
      tone: 'blue',
      mode: embed?.mode,
    },
    {
      key: 'qps',
      title: '请求限流',
      enabled: qps?.enabled,
      used: qps?.rps,
      limit: qps?.burst,
      unit: '请求 / 秒',
      tone: 'violet',
      mode: qps?.mode,
      scopes: qps?.scopes.map((scope) => (Object.hasOwn(scopeNames, scope) ? scopeNames[scope] : scope)),
    },
  ]
  return inputs.map<QuotaReading>((input) => {
    const percentage =
      input.key !== 'qps' &&
      input.enabled === true &&
      input.used !== undefined &&
      input.limit !== undefined &&
      input.limit > 0
        ? (input.used / input.limit) * 100
        : undefined
    return {
      ...input,
      percentage,
      progress: percentage === undefined ? undefined : Math.min(100, Math.max(0, percentage)),
      tone:
        input.enabled !== true
          ? 'neutral'
          : input.exceeded === true
            ? 'danger'
            : percentage !== undefined && percentage >= 80
              ? 'warning'
              : input.tone,
      scope:
        input.key === 'qps'
          ? '速率配置'
          : input.windowHours !== undefined && input.windowHours > 0
            ? `近 ${formatCount(input.windowHours)} 小时`
            : ['storage', 'documents'].includes(input.key)
              ? '当前占用'
              : '独立窗口',
    }
  })
}

export function quotaValue(value: number | undefined, quota: QuotaReading) {
  return quota.unit === 'bytes' ? formatBytes(value) : formatCount(value, quota.key === 'qps' ? 2 : 0)
}

export function quotaStatus(quota: QuotaReading) {
  if (quota.enabled === undefined) return '未取得'
  if (!quota.enabled) return '未启用'
  if (quota.exceeded) return '已达上限'
  if (quota.key !== 'qps' && quota.percentage === undefined) return '状态待确认'
  return quota.mode === 'warn' ? '仅告警' : '已启用'
}

export function quotaMode(mode: string) {
  if (mode.length === 0) return '""'
  return Object.hasOwn(modeNames, mode) ? modeNames[mode] : mode
}

const scopeNames: Readonly<Record<string, string>> = { chat: '聊天', retrieval: '检索' }
const modeNames: Readonly<Record<string, string>> = { block: '超限阻止请求', warn: '仅告警', disabled: '未启用' }
