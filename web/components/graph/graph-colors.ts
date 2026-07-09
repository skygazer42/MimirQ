import { toTrimmedPrimitiveString } from '@/lib/primitive-text'

type GraphNodeColorLike = Readonly<{
  meta?: Record<string, unknown> | null
  type?: unknown
}>

const GRAPH_TYPE_COLOR_FAMILIES = [
  {
    color: '#f59e0b',
    aliases: ['person', 'people', 'human', '人物', '人员', '个人', '申请人', '法人'],
  },
  {
    color: '#2563eb',
    aliases: ['organization', 'organisation', 'org', 'company', 'institution', 'department', '机构', '组织', '单位', '公司', '部门'],
  },
  {
    color: '#10b981',
    aliases: ['location', 'place', 'address', 'region', 'area', 'city', 'district', '地区', '地点', '地址', '区域', '城市'],
  },
  {
    color: '#8b5cf6',
    aliases: ['regulation', 'policy', 'law', 'rule', 'statute', 'ordinance', '法规', '政策', '政策法规', '条例', '办法', '规范'],
  },
  {
    color: '#ef4444',
    aliases: ['material', 'document', 'certificate', 'license', 'form', 'file', '材料', '证件', '许可证', '表单', '文档'],
  },
  {
    color: '#06b6d4',
    aliases: ['time', 'date', 'period', 'deadline', 'schedule', '时间', '日期', '时限', '期限'],
  },
  {
    color: '#14b8a6',
    aliases: ['service', 'product', 'item', 'category', '事项', '服务', '产品', '品类'],
  },
  {
    color: '#ec4899',
    aliases: ['phone', 'email', 'contact', 'channel', '联系方式', '电话', '邮箱', '渠道'],
  },
  {
    color: '#84cc16',
    aliases: ['amount', 'price', 'fee', 'money', '收费', '价格', '金额', '费用'],
  },
  {
    color: '#f97316',
    aliases: ['process', 'step', 'action', 'workflow', '流程', '步骤', '环节', '动作'],
  },
]

const GRAPH_TYPE_COLOR_ALIASES = new Map<string, string>(
  GRAPH_TYPE_COLOR_FAMILIES.flatMap((family) => family.aliases.map((alias) => [alias, family.color] as const))
)

export const NODE_COLOR_PALETTE = [
  '#2563eb',
  '#10b981',
  '#f59e0b',
  '#8b5cf6',
  '#ef4444',
  '#06b6d4',
  '#f97316',
  '#84cc16',
  '#ec4899',
  '#0ea5e9',
  '#14b8a6',
  '#eab308',
  '#6366f1',
  '#22c55e',
  '#f43f5e',
  '#a855f7',
  '#3b82f6',
  '#16a34a',
  '#d946ef',
  '#ea580c',
  '#0891b2',
  '#65a30d',
  '#7c3aed',
  '#dc2626',
]

export const EVENT_COLOR = '#8ea2ff'

function normalizeGraphType(value: unknown): string {
  return toTrimmedPrimitiveString(value).toLowerCase()
}

function hashTypeToIndex(type: string): number {
  let hash = 0
  for (let index = 0; index < type.length; index += 1) {
    hash = Math.trunc((hash * 31 + (type.codePointAt(index) ?? 0)) % 0x7fffffff)
  }
  return Math.abs(hash) % NODE_COLOR_PALETTE.length
}

function graphNodeRecord(node: unknown): GraphNodeColorLike {
  return node && typeof node === 'object' ? (node as GraphNodeColorLike) : {}
}

export function resolveGraphTypeColor(type: unknown): string {
  const normalizedType = normalizeGraphType(type)
  if (!normalizedType) {
    return NODE_COLOR_PALETTE[hashTypeToIndex('unknown')]
  }
  const semanticColor = GRAPH_TYPE_COLOR_ALIASES.get(normalizedType)
  if (semanticColor) return semanticColor
  return NODE_COLOR_PALETTE[hashTypeToIndex(normalizedType)]
}

export function buildTypeColorMap(nodes: readonly unknown[]): Map<string, string> {
  const map = new Map<string, string>()
  for (const node of nodes) {
    const record = graphNodeRecord(node)
    const meta = record.meta && typeof record.meta === 'object' ? record.meta : {}
    const kind = toTrimmedPrimitiveString(meta.kind)
    if (kind === 'event') continue
    const type = toTrimmedPrimitiveString(meta.type ?? record.type, 'unknown')
    if (!map.has(type)) {
      map.set(type, resolveGraphTypeColor(type))
    }
  }
  return map
}
