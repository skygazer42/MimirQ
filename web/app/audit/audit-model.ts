import type { AuditLogFilters, AuditLogItem } from '@/types/audit'
import type { AuditPurgeParameters } from '@/lib/api/audit'
import { dateTimeSchema } from '@/lib/response-schema'

export { formatApiBlobError as formatAuditError } from '@/lib/api-errors'

export const FILTER_KEYS = [
  'actor_id',
  'action',
  'resource_type',
  'resource_id',
  'request_id',
  'since',
  'until',
] as const
type FilterKey = (typeof FILTER_KEYS)[number]
export type AuditFilters = Required<AuditLogFilters>
export type AuditScope = { filters: AuditFilters; page: number; limit: number }

export const FILTER_LABELS: Record<FilterKey, string> = {
  actor_id: '操作者 ID',
  action: '动作代码',
  resource_type: '资源类型',
  resource_id: '资源 ID',
  request_id: '请求 ID',
  since: '开始时间',
  until: '结束时间',
}
export const FILTER_MAX_LENGTH = {
  actor_id: 255,
  action: 128,
  resource_type: 64,
  resource_id: 255,
  request_id: 128,
} as const
export const PAGE_SIZES = [20, 50, 100] as const
const DEFAULT_PAGE_SIZE = PAGE_SIZES[0]
export const QUICK_ACTIONS = [
  { label: '访问审查', value: 'compliance.access_review.daily' },
  { label: '索引审计', value: 'observability.index_audit.daily' },
  { label: '证据策略', value: 'evidence.drift_audit.daily' },
  { label: '访问回溯', value: 'compliance.access_graph.export' },
] as const

export function createAuditFilterDraft(): AuditFilters {
  return { actor_id: '', action: '', resource_type: '', resource_id: '', request_id: '', since: '', until: '' }
}

export function getAuditQueryFilters(filters: AuditLogFilters): AuditLogFilters {
  const applied: AuditLogFilters = {}
  for (const key of FILTER_KEYS) {
    const text = filters[key]?.trim()
    if (text === undefined || text === '') continue
    if (
      (key === 'since' || key === 'until') &&
      dateTimeSchema.safeParse(text).success &&
      !/(Z|[+-]\d{2}:\d{2})$/.test(text)
    ) {
      applied[key] = new Date(text).toISOString()
    } else applied[key] = text
  }
  return applied
}

export function getAuditFilterError(filters: AuditLogFilters): string | undefined {
  for (const key of FILTER_KEYS) {
    if (key === 'since' || key === 'until') continue
    const value = filters[key]
    if (value !== undefined && value.trim().length > FILTER_MAX_LENGTH[key]) {
      return `${FILTER_LABELS[key]}不能超过 ${FILTER_MAX_LENGTH[key]} 个字符`
    }
  }
  const since = filters.since?.trim()
  const until = filters.until?.trim()
  for (const [label, value] of [
    ['开始时间', since],
    ['结束时间', until],
  ]) {
    if (value !== undefined && value.length > 0 && !dateTimeSchema.safeParse(value).success) return `${label}格式无效`
  }
  if (
    since !== undefined &&
    since.length > 0 &&
    until !== undefined &&
    until.length > 0 &&
    new Date(since) > new Date(until)
  ) {
    return '开始时间不能晚于结束时间'
  }
}

export function parseAuditLocation(search: string): AuditScope {
  const params = new URLSearchParams(search)
  const pageValue = params.get('page')
  const sizeValue = params.get('page_size')
  const page = pageValue === null ? 1 : Number(pageValue)
  const size = sizeValue === null ? DEFAULT_PAGE_SIZE : Number(sizeValue)
  const filters = createAuditFilterDraft()
  for (const key of FILTER_KEYS) {
    const value = params.get(key)
    if (value !== null) filters[key] = value.trim()
  }
  return {
    filters,
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    limit: PAGE_SIZES.some((value) => value === size) ? size : DEFAULT_PAGE_SIZE,
  }
}

export function buildAuditLocation(href: string, scope: AuditScope): URL {
  const url = new URL(href)
  for (const key of FILTER_KEYS) {
    const value = scope.filters[key].trim()
    if (value.length > 0) url.searchParams.set(key, value)
    else url.searchParams.delete(key)
  }
  if (scope.page === 1) url.searchParams.delete('page')
  else url.searchParams.set('page', String(scope.page))
  if (scope.limit === DEFAULT_PAGE_SIZE) url.searchParams.delete('page_size')
  else url.searchParams.set('page_size', String(scope.limit))
  return url
}

export function formatAuditLocalDateTime(iso: string) {
  if (iso.length === 0) return iso
  if (!dateTimeSchema.safeParse(iso).success) return iso
  const date = new Date(iso)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, -1)
}

export function parseAuditLocalDateTime(local: string) {
  if (local.length === 0) return local
  if (!dateTimeSchema.safeParse(local).success) throw new Error('时间格式无效')
  return new Date(local).toISOString()
}

export function formatAuditTimestamp(value: string) {
  const date = new Date(value)
  return {
    date: date.toLocaleDateString('zh-CN'),
    time: date.toLocaleTimeString('zh-CN', { hour12: false }),
  }
}

export function formatAuditPeriod(filters: AuditFilters) {
  const applied = getAuditQueryFilters({ since: filters.since, until: filters.until })
  if (applied.since === undefined && applied.until === undefined) return '全部时间'
  if (getAuditFilterError(applied) !== undefined) return '时间范围无效'
  const since = applied.since === undefined ? '不限开始' : formatAuditTimestamp(applied.since).date
  const until = applied.until === undefined ? '不限结束' : formatAuditTimestamp(applied.until).date
  return `${since} — ${until}`
}

export function createAuditPurgeParameters(
  filters: AuditFilters,
  scope: 'retention' | 'filtered',
  days: string,
  maximum: string,
  dryRun: boolean,
): AuditPurgeParameters {
  const max = Number(maximum)
  if (!/^\d+$/.test(maximum) || !Number.isSafeInteger(max) || max < 1 || max > 1_000_000) {
    throw new Error('最多清理须为 1–1,000,000 的整数')
  }
  if (scope === 'retention') {
    const retention = Number(days)
    if (!/^\d+$/.test(days) || !Number.isSafeInteger(retention) || retention < 1 || retention > 3650) {
      throw new Error('保留天数须为 1–3,650 的整数')
    }
    return { purge_scope: 'retention', retention_days: retention, max_delete: max, dry_run: dryRun }
  }
  const applied = getAuditQueryFilters(filters)
  const error = getAuditFilterError(applied)
  if (error !== undefined) throw new Error(error)
  if (Object.keys(applied).length === 0) throw new Error('按当前筛选清理至少需要一个筛选条件')
  return { ...applied, purge_scope: 'filtered', max_delete: max, dry_run: dryRun }
}

const ACTION_NAMES: Readonly<Record<string, string>> = {
  'settings.update': '更新设置',
  'dataset.create': '创建数据集',
  'dataset.update': '更新数据集',
  'dataset.config.import': '导入数据集配置',
  'dataset.clone': '复制数据集',
  'dataset.purge': '清理数据集',
  'dataset.retrieval_audit.put': '更新检索审计',
  'rbac.member.remove': '移除租户成员',
  'audit.logs.purge': '清理审计日志',
  'audit.logs.delete': '删除审计日志',
  'audit.logs.bulk_delete': '批量删除审计日志',
  'audit.logs.retention': '审计保留清理',
  'compliance.access_graph.export': '访问回溯导出',
  'compliance.access_graph.summary': '访问回溯统计',
  'compliance.access_review.daily': '访问审查',
  'observability.index_audit.daily': '索引审计',
  'evidence.drift_audit.daily': '证据策略检查',
  'dataset.retention.sweep': '数据集保留清理',
  'document.version.retention_delete': '清理文档版本',
  'evaluations.regression_runs.retention': '评测运行保留清理',
  'knowledge.assets.retention': '知识资产保留清理',
}
const RESOURCE_NAMES: Readonly<Record<string, string>> = {
  dataset: '数据集',
  document: '文档',
  document_version: '文档版本',
  audit_logs: '审计日志',
  tenant: '租户',
  tenant_member: '租户成员',
  settings: '系统设置',
  knowledge_asset: '知识资产',
  regression_run: '评测运行',
  stale_report: '过期报告',
  dataset_member_permission: '数据集成员权限',
  dataset_group_permission: '数据集组权限',
  document_member_permission: '文档成员权限',
  document_group_permission: '文档组权限',
}

export function getAuditActionLabel(action: string) {
  if (action.length === 0) return '""'
  return Object.hasOwn(ACTION_NAMES, action) ? ACTION_NAMES[action] : action
}

export function getAuditResourceTypeLabel(type: string | null) {
  if (type === null) return '未绑定资源'
  if (type.length === 0) return '""'
  return Object.hasOwn(RESOURCE_NAMES, type) ? RESOURCE_NAMES[type] : type
}

export function getAuditResourceLabel(row: Pick<AuditLogItem, 'resource_type' | 'resource_id' | 'details'>) {
  const type = getAuditResourceTypeLabel(row.resource_type)
  const name = typeof row.details.name === 'string' ? row.details.name : type
  const detail = row.resource_id === null ? [] : [row.resource_id]
  if (name !== type) detail.unshift(type)
  return {
    name: name.length === 0 ? '""' : name,
    detail: detail.map((value) => (value.length === 0 ? '""' : value)).join(' · '),
  }
}

export function getAuditActionTone(action: string) {
  if (/delete|purge|remove|destroy|revoke|retention|disable/.test(action)) return 'delete'
  if (/rbac|permission|role|security|access_review/.test(action)) return 'permission'
  if (/quarantine|block|deny|fail|drift|stale|violation/.test(action)) return 'warning'
  if (/create|add|import|upload|restore|approve|publish/.test(action)) return 'create'
  if (/export|download|snapshot|backup|login|logout|auth/.test(action)) return 'export'
  if (/audit|review/.test(action)) return 'audit'
  if (/update|set|change/.test(action)) return 'update'
  return 'neutral'
}

export function abbreviateAuditIdentifier(value: string | null) {
  if (value === null) return '—'
  if (value.length === 0) return '""'
  return value.length > 23 ? `${value.slice(0, 6)}…${value.slice(-4)}` : value
}

export function formatAuditJson(value: unknown): string {
  const text = JSON.stringify(value, null, 2)
  if (text === undefined) throw new TypeError('审计数据未提供，无法序列化 JSON')
  return text
}
