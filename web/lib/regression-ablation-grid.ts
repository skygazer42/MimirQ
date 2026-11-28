import { recordSchema } from '@/lib/response-schema'
import type { RegressionAblationGridValue, RegressionRunCreate } from '@/types/evaluation'

export const MAX_GRID_COMBINATIONS = 50
export const ABLATION_GRID_KEYS = [
  'retrieval_profile',
  'enable_query_alias_expansion',
  'query_alias_max_queries',
  'enable_multi_query',
  'multi_query_count',
  'multi_query_temperature',
  'multi_query_max_chars',
  'enable_hyde',
  'enable_hierarchy_recall',
  'hierarchy_family_collapse',
  'hierarchy_family_aggregation',
  'hierarchy_tree_dedup',
  'hierarchy_parent_depth',
  'hierarchy_sibling_window',
  'hierarchy_overfetch_factor',
  'enable_query_rewrite',
  'query_rewrite_strategy',
  'query_rewrite_temperature',
  'query_rewrite_max_chars',
  'top_k',
  'score_threshold',
  'retrieval_mode',
  'alpha',
  'enable_weight_rerank',
  'vector_weight',
  'keyword_weight',
  'mmr_lambda',
  'enable_reranker',
  'reranker_provider',
  'reranker_top_n',
  'fusion_strategy',
  'fusion_budgets',
  'fusion_min_scores',
  'fusion_weights',
  'prompt_template_id',
  'prompt_template_key',
  'prompt_ab_experiment_key',
] satisfies Array<
  keyof Omit<
    RegressionRunCreate,
    'dataset_id' | 'case_ids' | 'metrics' | 'use_llm_judge' | 'skip_empty_contexts' | 'max_cases'
  >
>

const gridKeys = new Set<string>(ABLATION_GRID_KEYS)
type GridSpec = Record<string, RegressionAblationGridValue[]>
type GridVariant = Record<string, RegressionAblationGridValue>

type AblationGridPreview =
  | { status: 'invalid'; message: string }
  | { status: 'overLimit'; message: string }
  | { status: 'ready'; grid: GridSpec; variants: GridVariant[] }

function isFiniteJsonValue(value: unknown): boolean {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true
  if (typeof value === 'number') return Number.isFinite(value)
  if (Array.isArray(value)) return value.every(isFiniteJsonValue)
  const object = recordSchema.safeParse(value)
  return object.success && Object.values(object.data).every(isFiniteJsonValue)
}

function isGridValue(value: unknown): value is RegressionAblationGridValue {
  return !Array.isArray(value) && isFiniteJsonValue(value)
}

export function parseAblationGrid(text: string): AblationGridPreview {
  let value: unknown
  try {
    value = JSON.parse(text)
  } catch {
    return { status: 'invalid', message: '参数网格必须是有效 JSON' }
  }
  const parsed = recordSchema.safeParse(value)
  if (!parsed.success) return { status: 'invalid', message: '参数网格必须是对象' }
  const entries = Object.entries(parsed.data)
  if (entries.length === 0) return { status: 'invalid', message: '至少配置一个参数数组' }

  const grid: GridSpec = {}
  for (const [key, values] of entries) {
    if (!gridKeys.has(key)) return { status: 'invalid', message: `不支持的参数：${key}` }
    if (!Array.isArray(values) || values.length === 0) {
      return { status: 'invalid', message: `参数 ${key} 必须是非空数组` }
    }
    if (!values.every(isGridValue)) {
      return { status: 'invalid', message: `参数 ${key} 含不支持的取值或非有限数值` }
    }
    grid[key] = values
  }

  let combinations = 1
  for (const values of Object.values(grid)) {
    if (combinations > MAX_GRID_COMBINATIONS / values.length) {
      return { status: 'overLimit', message: `组合数超过 ${MAX_GRID_COMBINATIONS}，请收窄参数范围` }
    }
    combinations *= values.length
  }
  let variants: GridVariant[] = [{}]
  for (const [key, values] of Object.entries(grid)) {
    const next: GridVariant[] = []
    for (const variant of variants) {
      for (const value of values) next.push({ ...variant, [key]: value })
    }
    variants = next
  }
  return { status: 'ready', grid, variants }
}
