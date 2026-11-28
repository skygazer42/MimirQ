import type {
  EnterpriseOntologyDefinitionView as Definition,
  EnterpriseOntologyBindingPreviewView as BindingPreview,
} from '@/types/enterprise-ontology'
import type { OpenApiSchema } from '@/types/backend'
import { toApiErrorInfo } from '@/lib/api-errors'

export const assetCategories = [
  { id: 'object_types', label: '对象' },
  { id: 'relations', label: '关系' },
  { id: 'bindings', label: '数据绑定' },
  { id: 'metrics', label: '指标' },
  { id: 'rules', label: '规则' },
  { id: 'functions', label: '函数' },
  { id: 'actions', label: '动作' },
  { id: 'action_workflows', label: '动作流程' },
  { id: 'document_metadata', label: '文档元数据' },
  { id: 'concepts', label: '知识概念' },
  { id: 'document_templates', label: '文书模板' },
] as const

export type AssetCategory = (typeof assetCategories)[number]['id']
export type AssetEntry = { id: string; label: string; detail?: string }
export const bindingRoles: Record<string, string> = {
  primary: '主数据',
  enrichment: '补充数据',
  document_evidence: '文档证据',
}
export const propertyTypes = ['string', 'integer', 'number', 'boolean', 'date', 'datetime'] as const
export const emptyDefinition = (): Definition => ({
  schema_version: 1,
  ontology: '',
  object_types: {},
  relations: {},
  bindings: [],
})
export const commaValues = (value: string) =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)

export function getAssets(definition: Definition, category: AssetCategory): AssetEntry[] {
  if (category === 'bindings') {
    return definition.bindings.map((item, index) => ({
      id: String(index),
      label: item.asset_id || '待选择资产',
      detail: (definition.object_types[item.object_type]?.label || item.object_type) + ' · ' + bindingRoles[item.role],
    }))
  }
  if (category === 'document_templates') {
    return Object.entries(definition.document_templates ?? {}).map(([id, item]) => ({ id, label: item.title }))
  }
  if (category === 'concepts') {
    return Object.entries(definition.concepts ?? {}).map(([id, value]) => {
      const item = value as OpenApiSchema<'ConceptDefinition'>
      return { id, label: item.label, detail: item.aliases?.join('、') }
    })
  }
  return Object.entries(definition[category] ?? {}).map(([id, item]) => ({ id, label: item.label || id }))
}

export function assetObjectId(definition: Definition, category: AssetCategory, id: string): string | undefined {
  switch (category) {
    case 'object_types':
      return id
    case 'bindings':
      return definition.bindings[Number(id)]?.object_type
    case 'relations':
      return definition.relations[id]?.from
    case 'metrics':
    case 'rules':
    case 'actions':
      return definition[category]?.[id]?.object_type
    case 'functions': {
      const metric = definition.functions?.[id]?.metric
      return metric ? definition.metrics?.[metric]?.object_type : undefined
    }
    case 'action_workflows': {
      const action = definition.action_workflows?.[id]?.actions[0]
      return action ? definition.actions?.[action]?.object_type : undefined
    }
    default:
      return undefined
  }
}

export function objectLinks(definition: Definition, objectId: string) {
  const relations = Object.entries(definition.relations).filter(
    ([, item]) => item.from === objectId || item.to === objectId,
  )
  const metrics = Object.entries(definition.metrics ?? {}).filter(([, item]) => item.object_type === objectId)
  const rules = Object.entries(definition.rules ?? {}).filter(([, item]) => item.object_type === objectId)
  const functions = Object.entries(definition.functions ?? {}).filter(
    ([, item]) => definition.metrics?.[item.metric]?.object_type === objectId,
  )
  const actions = Object.entries(definition.actions ?? {}).filter(([, item]) => item.object_type === objectId)
  const workflows = Object.entries(definition.action_workflows ?? {}).filter(([, item]) =>
    item.actions.some((id) => definition.actions?.[id]?.object_type === objectId),
  )
  return { relations, metrics, rules, functions, actions, workflows }
}

export function bindingCoverage(definition: Definition, objectId: string) {
  const properties = Object.keys(definition.object_types[objectId]?.properties ?? {})
  const bindings = definition.bindings.filter(
    (item) => item.object_type === objectId && item.asset_id.trim() && item.role !== 'document_evidence',
  )
  const covered = properties.filter((id) =>
    bindings.some((binding) => {
      const mapping = binding.columns[id]
      return typeof mapping === 'string' ? Boolean(mapping.trim()) : Boolean(mapping?.column.trim())
    }),
  ).length
  return {
    total: properties.length,
    covered,
    percent: properties.length ? Math.round((covered / properties.length) * 100) : 0,
  }
}

const bindingIssues: Record<string, string> = {
  invalid_document_asset: '文档资产不可用',
  unavailable_column: '源列不可用',
  missing_value: '缺少必填值',
  invalid_value: '值无法转换为声明的类型',
  missing_or_duplicate_identity: '身份列缺值或重复',
  invalid_cardinality: '实际数据与关系基数不符',
  relation_cardinality: '实际数据与关系基数不符',
  relation_source_unavailable: '关系映射列不可用',
  asset_schema_changed: '资产结构已变化，需复核绑定',
  edo_revision_drift: 'EDO 工作修订已变化，需复核绑定',
  unavailable_asset: '数据资产不可用',
  edo_column_type_mismatch: 'EDO 字段类型与声明不符',
  edo_partial_coverage: 'EDO 数据覆盖不足',
}
export function bindingIssueText(issue: BindingPreview['issues'][number]) {
  return [issue.field, bindingIssues[issue.code] ?? issue.code].filter(Boolean).join(' · ')
}

export function ontologyErrorText(error: unknown): string {
  if (typeof error === 'object' && error && 'response' in error) {
    const response = error.response as { data?: { detail?: unknown } } | undefined
    const detail = response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item.msg) return [item.loc?.join('.'), item.msg].filter(Boolean).join(' · ')
          const issues = item.issues as BindingPreview['issues'] | undefined
          return [item.asset_id, issues ? issues.map(bindingIssueText).join(' · ') : bindingIssueText(item)]
            .filter(Boolean)
            .join(' · ')
        })
        .join(' · ')
    }
    if (detail && typeof detail === 'object' && 'precondition' in detail && 'outcome' in detail) {
      return '前置规则 ' + detail.precondition + ' 未通过 · ' + detail.outcome
    }
  }
  return toApiErrorInfo(error, '请求失败').message
}
