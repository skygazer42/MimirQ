'use client'

import { useMemo, useState } from 'react'
import { AlertTriangle, Grid3X3, PlayCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { RegressionAblationGridValue, RegressionRunCreate } from '@/types'

type GridSpec = Record<string, RegressionAblationGridValue[]>
type GridVariant = Record<string, RegressionAblationGridValue>

export const MAX_GRID_COMBINATIONS = 50

const GRID_PARAM_KEYS = [
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
  'sparse_retrieval_enabled',
  'sparse_retrieval_provider',
  'use_llm_judge',
  'skip_empty_contexts',
  'max_cases',
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
] satisfies Array<keyof RegressionRunCreate>

const GRID_PARAM_KEY_SET = new Set<string>(GRID_PARAM_KEYS)

const DEFAULT_GRID = `{
  "retrieval_mode": ["hybrid", "vector"],
  "top_k": [10, 20],
  "enable_reranker": [false, true]
}`

function isGridValue(value: unknown): value is RegressionAblationGridValue {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value) || (typeof value === 'object' && !Array.isArray(value))
}

function parseGrid(value: string): { grid: GridSpec; variants: GridVariant[]; error: string | null } {
  let parsed: unknown
  try {
    parsed = JSON.parse(value)
  } catch {
    return { grid: {}, variants: [], error: 'Grid JSON 无法解析' }
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { grid: {}, variants: [], error: 'Grid 必须是对象，例如 {"top_k":[10,20]}' }
  }

  const parsedRecord = parsed as Record<string, unknown>
  const invalidKeys = Object.keys(parsedRecord).filter((key) => !GRID_PARAM_KEY_SET.has(key))
  if (invalidKeys.length) {
    return { grid: {}, variants: [], error: `不支持的参数：${invalidKeys.join(', ')}` }
  }

  const entries = Object.entries(parsedRecord)
    .filter(([key]) => key.trim())
    .map(([key, raw]) => {
      const values = Array.isArray(raw) ? raw.filter(isGridValue) : []
      return [key, values] as const
    })
    .filter(([, values]) => values.length > 0)

  if (!entries.length) return { grid: {}, variants: [], error: '至少配置一个参数数组' }

  const grid = Object.fromEntries(entries.map(([key, values]) => [key, values])) as GridSpec
  const variants: Array<Record<string, RegressionAblationGridValue>> = [{}]
  for (const [key, values] of entries) {
    const next: Array<Record<string, RegressionAblationGridValue>> = []
    for (const variant of variants) {
      for (const item of values) next.push({ ...variant, [key]: item })
    }
    variants.splice(0, variants.length, ...next.slice(0, MAX_GRID_COMBINATIONS + 1))
  }

  return { grid, variants: variants.map((item) => item as GridVariant), error: null }
}

export function AblationGridPanel({
  disabled,
  onRunGrid,
  onBatchComplete,
}: Readonly<{
  disabled?: boolean
  onRunGrid: (grid: GridSpec, maxCombinations: number) => Promise<void>
  onBatchComplete?: () => Promise<void> | void
}>) {
  const [gridText, setGridText] = useState(DEFAULT_GRID)
  const [running, setRunning] = useState(false)
  const [completed, setCompleted] = useState(0)
  const [batchError, setBatchError] = useState('')
  const { grid, variants, error } = useMemo(() => parseGrid(gridText), [gridText])
  const tooMany = variants.length > MAX_GRID_COMBINATIONS
  const canRun = !disabled && !running && !error && variants.length > 0 && !tooMany

  async function runBatch() {
    if (!canRun) return
    setRunning(true)
    setCompleted(0)
    setBatchError('')
    try {
      await onRunGrid(grid, MAX_GRID_COMBINATIONS)
      setCompleted(variants.length)
      await onBatchComplete?.()
    } catch (err) {
      setBatchError(err instanceof Error ? err.message : '批量创建 runs 失败')
    } finally {
      setRunning(false)
    }
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <Grid3X3 className="size-4 text-sky-600" />
            笛卡尔网格批量
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            用 JSON 定义参数数组，前端按组合顺序创建 regression runs；默认上限 {MAX_GRID_COMBINATIONS} 个，避免跑爆配额。
          </p>
          <p className="mt-1 text-[11px] leading-5 text-slate-400">
            支持字段：{GRID_PARAM_KEYS.join(' / ')}
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-right">
          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">组合数</div>
          <div className={cn('font-mono text-lg font-semibold', tooMany ? 'text-rose-600' : 'text-slate-950')}>
            {variants.length}
          </div>
        </div>
      </div>

      <Textarea
        value={gridText}
        onChange={(event) => setGridText(event.target.value)}
        spellCheck={false}
        className="mt-3 min-h-36 rounded-xl border-slate-200 bg-slate-950 font-mono text-xs text-slate-100"
      />

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="min-h-5 text-xs text-slate-500">
          {batchError ? (
            <span className="inline-flex items-center gap-1 text-rose-600">
              <AlertTriangle className="size-3.5" />
              {batchError}
            </span>
          ) : error ? (
            <span className="inline-flex items-center gap-1 text-rose-600">
              <AlertTriangle className="size-3.5" />
              {error}
            </span>
          ) : tooMany ? (
            <span className="text-rose-600">组合数超过上限，请收窄参数范围。</span>
          ) : running ? (
            <span>正在提交批量任务 {completed}/{variants.length} runs…</span>
          ) : (
            <span>预览前 {Math.min(variants.length, 3)} 组：{variants.slice(0, 3).map((item) => JSON.stringify(item)).join(' / ')}</span>
          )}
        </div>
        <Button type="button" disabled={!canRun} onClick={() => void runBatch()} className="gap-2 rounded-xl">
          <PlayCircle className="size-4" />
          批量创建 Runs
        </Button>
      </div>
    </section>
  )
}
