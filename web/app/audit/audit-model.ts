import type { AuditLogItem } from '@/types'
import { formatApiError } from '@/lib/api-errors'

export const FILTER_KEYS = ['actor_id', 'action', 'resource_type', 'resource_id', 'request_id', 'since', 'until'] as const
export type FilterKey = typeof FILTER_KEYS[number]
export type AuditFilters = Record<FilterKey, string>
export type AuditScope = { filters: AuditFilters; page: number; limit: number }
export const FILTER_LABELS: Record<FilterKey, string> = { actor_id: '操作者 ID', action: '动作代码', resource_type: '资源类型', resource_id: '资源 ID', request_id: '请求 ID', since: '开始时间', until: '结束时间' }
export const PAGE_SIZES = [20, 50, 100] as const
export const QUICK_ACTIONS = [
  { label: '访问审查', value: 'compliance.access_review.daily' },
  { label: '索引审计', value: 'observability.index_audit.daily' },
  { label: '证据策略', value: 'evidence.drift_audit.daily' },
  { label: '访问回溯', value: 'compliance.access_graph.export' },
] as const

export function emptyFilters(): AuditFilters {
  return { actor_id: '', action: '', resource_type: '', resource_id: '', request_id: '', since: '', until: '' }
}

export function cleanFilters(filters: Partial<AuditFilters>): Partial<AuditFilters> {
  return Object.fromEntries(FILTER_KEYS.flatMap(key => {
    const value = typeof filters[key] === 'string' ? filters[key]!.trim() : ''
    if (!value) return []
    const date = key === 'since' || key === 'until' ? new Date(value) : null
    return [[key, date && Number.isFinite(date.getTime()) ? date.toISOString() : value]]
  }))
}

export function validateFilters(filters: Partial<AuditFilters>): string {
  const limits = { actor_id: 255, action: 128, resource_type: 64, resource_id: 255, request_id: 128 }
  for (const [key, max] of Object.entries(limits)) {
    if ((filters[key as FilterKey]?.trim().length ?? 0) > max) return `${FILTER_LABELS[key as FilterKey]}不能超过 ${max} 个字符`
  }
  for (const key of ['since', 'until'] as const) {
    if (filters[key] && !Number.isFinite(new Date(filters[key]!).getTime())) return `${FILTER_LABELS[key]}格式无效`
  }
  return filters.since && filters.until && new Date(filters.since) > new Date(filters.until) ? '开始时间不能晚于结束时间' : ''
}

export function parseAuditLocation(search: string): AuditScope {
  const params = new URLSearchParams(search), page = Number(params.get('page')), size = Number(params.get('page_size'))
  const filters = emptyFilters()
  for (const key of FILTER_KEYS) filters[key] = params.get(key)?.trim() ?? ''
  return { filters, page: Number.isSafeInteger(page) && page > 0 ? page : 1, limit: PAGE_SIZES.some(s => s === size) ? size : 20 }
}

export function persistScope(scope: AuditScope) {
  const url = new URL(window.location.href)
  for (const key of FILTER_KEYS) {
    const value = scope.filters[key].trim()
    if (value) url.searchParams.set(key, value)
    else url.searchParams.delete(key)
  }
  if (scope.page === 1) url.searchParams.delete('page')
  else url.searchParams.set('page', String(scope.page))
  if (scope.limit === 20) url.searchParams.delete('page_size')
  else url.searchParams.set('page_size', String(scope.limit))
  window.history.replaceState(window.history.state, '', url)
}

export function localDateTime(iso: string) {
  if (!iso) return ''
  const date = new Date(iso)
  if (!Number.isFinite(date.getTime())) return iso
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}
export function isoDateTime(local: string) {
  if (!local) return ''
  const date = new Date(local)
  return Number.isFinite(date.getTime()) ? date.toISOString() : local
}

export function stamp(value: string) {
  const date = new Date(value)
  return !value || !Number.isFinite(date.getTime()) ? { date: '时间未知', time: '—' } : {
    date: date.toLocaleDateString('zh-CN'), time: date.toLocaleTimeString('zh-CN', { hour12: false }),
  }
}
export function periodLabel(filters: AuditFilters) {
  if (!filters.since && !filters.until) return '全部时间'
  if (validateFilters({ since: filters.since, until: filters.until })) return '时间范围无效'
  return `${filters.since ? stamp(filters.since).date : '不限开始'} — ${filters.until ? stamp(filters.until).date : '不限结束'}`
}

type PurgeParameters = Partial<AuditFilters> & { purge_scope: 'retention' | 'filtered'; retention_days?: number; max_delete: number; dry_run: boolean }
export function purgeParameters(filters: AuditFilters, scope: 'retention' | 'filtered', days: string, maximum: string, dryRun: boolean): PurgeParameters {
  const max = Number(maximum), retention = Number(days)
  if (!/^\d+$/.test(maximum) || !Number.isSafeInteger(max) || max < 1 || max > 1_000_000) throw new Error('最多清理须为 1–1,000,000 的整数')
  if (scope === 'retention' && (!/^\d+$/.test(days) || !Number.isSafeInteger(retention) || retention < 1 || retention > 3650)) throw new Error('保留天数须为 1–3,650 的整数')
  const applied = cleanFilters(filters), error = validateFilters(applied)
  if (scope === 'filtered' && (error || !Object.keys(applied).length)) throw new Error(error || '按当前筛选清理至少需要一个筛选条件')
  return { purge_scope: scope, ...(scope === 'retention' ? { retention_days: retention } : applied), max_delete: max, dry_run: dryRun }
}

const ACTION_NAMES: Readonly<Record<string, string>> = {
  'settings.update': '更新设置', 'dataset.create': '创建数据集', 'dataset.update': '更新数据集',
  'dataset.config.import': '导入数据集配置', 'dataset.clone': '复制数据集', 'dataset.purge': '清理数据集',
  'dataset.retrieval_audit.put': '更新检索审计', 'rbac.member.remove': '移除租户成员',
  'audit.logs.purge': '清理审计日志', 'audit.logs.delete': '删除审计日志', 'audit.logs.bulk_delete': '批量删除审计日志',
  'audit.logs.retention': '审计保留清理', 'compliance.access_graph.export': '访问回溯导出',
  'compliance.access_graph.summary': '访问回溯统计', 'compliance.access_review.daily': '访问审查',
  'observability.index_audit.daily': '索引审计', 'evidence.drift_audit.daily': '证据策略检查',
  'dataset.retention.sweep': '数据集保留清理', 'document.version.retention_delete': '清理文档版本',
  'evaluations.regression_runs.retention': '评测运行保留清理', 'knowledge.assets.retention': '知识资产保留清理',
}
const RESOURCE_NAMES: Readonly<Record<string, string>> = {
  dataset: '数据集', document: '文档', document_version: '文档版本', audit_logs: '审计日志', tenant: '租户',
  tenant_member: '租户成员', settings: '系统设置', knowledge_asset: '知识资产', regression_run: '评测运行', stale_report: '过期报告',
  dataset_member_permission: '数据集成员权限', dataset_group_permission: '数据集组权限', document_member_permission: '文档成员权限', document_group_permission: '文档组权限',
}
export function actionName(action: string | null | undefined) { return action ? ACTION_NAMES[action] ?? action : '未记录动作' }
export function resourceTypeName(type: string | null | undefined) { return type ? RESOURCE_NAMES[type] ?? type : '未绑定资源' }
export function resourceLabel(row: Pick<AuditLogItem, 'resource_type' | 'resource_id' | 'details'>) {
  const type = resourceTypeName(row.resource_type)
  const name = typeof row.details?.name === 'string' && row.details.name.trim() ? row.details.name.trim() : type
  return { name, detail: [name === type ? '' : type, row.resource_id].filter(Boolean).join(' · ') }
}
export function actionTone(action: string) {
  if (/rbac|permission|access_review/.test(action)) return 'permission'
  if (/delete|purge|remove|destroy|revoke|retention/.test(action)) return 'delete'
  if (/quarantine|block|deny|fail|drift|stale|violation/.test(action)) return 'warning'
  if (/create|add|import|upload|restore|approve|publish/.test(action)) return 'create'
  if (/export|download|snapshot|backup/.test(action)) return 'export'
  if (/audit|review/.test(action)) return 'audit'
  if (/update|set|change/.test(action)) return 'update'
  return 'neutral'
}
export function compactId(value: string | null | undefined) {
  return !value ? '—' : value.length > 23 ? `${value.slice(0, 6)}…${value.slice(-4)}` : value
}
export function pretty(value: unknown) { return JSON.stringify(value, null, 2) ?? 'null' }

export async function formatAuditError(error: unknown, fallback: string) {
  const source = error as { response?: { data?: unknown }; message?: string }
  if (source?.response?.data instanceof Blob) {
    try {
      const data: unknown = JSON.parse(await source.response.data.text())
      return formatApiError({ ...source, response: { ...source.response, data } }, fallback)
    } catch { /* Keep the normal formatter for non-JSON downloads. */ }
  }
  return formatApiError(error, fallback)
}
