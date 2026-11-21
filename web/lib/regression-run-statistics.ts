import { recordSchema } from '@/lib/response-schema'
import type { RegressionRun } from '@/types/evaluation'

export type RegressionRunStatistics = {
  run: RegressionRun
  metrics: Record<string, number | null>
  elapsedMs: number | null
}

type RegressionParameter = {
  key: string
  value: string | number | boolean | null | Record<string, number>
}

const NORMALIZED_METRIC_KEYS = new Set([
  'retrieval_mrr',
  'retrieval_recall',
  'retrieval_ndcg_at_10',
  'retrieval_ndcg_at_20',
  'faithfulness_det',
  'refusal_correctness',
])

export function getRegressionRunMetric(run: RegressionRun, key: string): number | null {
  const value = run.summary[key]
  if (value === undefined || value === null) return null
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`指标 ${key} 不是有限数值`)
  }
  if (NORMALIZED_METRIC_KEYS.has(key) && (value < 0 || value > 1)) {
    throw new Error(`指标 ${key} 超出 0 到 1 的范围`)
  }
  return value
}

function parseRunTimestampMs(value: string): number {
  // 后端无时区时间表示 UTC；微秒精度在此明确转换为毫秒精度。
  const preciseToMs = value.replace(/(\.\d{3})\d+/, '$1')
  const timestamp = /(?:Z|[+-]\d{2}:\d{2})$/i.test(preciseToMs) ? preciseToMs : `${preciseToMs}Z`
  const milliseconds = Date.parse(timestamp)
  if (!Number.isFinite(milliseconds)) throw new Error('运行时间格式无效')
  return milliseconds
}

function calculateRunDurationMs(run: RegressionRun): number | null {
  if (run.started_at === null || run.finished_at === null) return null
  const duration = parseRunTimestampMs(run.finished_at) - parseRunTimestampMs(run.started_at)
  if (duration < 0) throw new Error('运行完成时间早于开始时间')
  return duration
}

export function analyzeRegressionRuns(runs: readonly RegressionRun[], metricKeys: readonly string[]) {
  const completed: RegressionRunStatistics[] = []
  const errors: { runId: string; error: unknown }[] = []
  for (const run of runs) {
    if (run.status !== 'completed') continue
    try {
      completed.push({
        run,
        metrics: Object.fromEntries(metricKeys.map((key) => [key, getRegressionRunMetric(run, key)])),
        elapsedMs: calculateRunDurationMs(run),
      })
    } catch (error) {
      errors.push({ runId: run.id, error })
    }
  }
  return { runs: completed, errors }
}

export function isParetoRun(
  entry: RegressionRunStatistics,
  runs: readonly RegressionRunStatistics[],
  metricKey: string,
): boolean {
  const metric = entry.metrics[metricKey]
  const duration = entry.elapsedMs
  if (metric === null || duration === null) return false
  return !runs.some((other) => {
    if (other.run.id === entry.run.id) return false
    const otherMetric = other.metrics[metricKey]
    const otherDuration = other.elapsedMs
    if (otherMetric === null || otherDuration === null) return false
    return otherMetric >= metric && otherDuration <= duration && (otherMetric > metric || otherDuration < duration)
  })
}

export function formatRunDuration(milliseconds: number | null): string {
  if (milliseconds === null) return '未提供'
  return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(2)} s` : `${Math.round(milliseconds)} ms`
}

function readParameterValue(key: string, value: unknown): RegressionParameter['value'] {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error(`参数 ${key} 不是有限数值`)
    return value
  }
  const fields: [string, number][] = []
  for (const [name, field] of Object.entries(recordSchema.parse(value))) {
    if (typeof field !== 'number' || !Number.isFinite(field)) {
      throw new Error(`参数 ${key}.${name} 不是有限数值`)
    }
    fields.push([name, field])
  }
  fields.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
  return Object.fromEntries(fields)
}

export function getRegressionRunParameters(run: RegressionRun): RegressionParameter[] {
  const parameterValues = new Map<string, unknown>()
  for (const source of [run.params.ablation_variant, run.params.rag_params]) {
    if (source === undefined) continue
    for (const [key, value] of Object.entries(recordSchema.parse(source))) {
      parameterValues.set(key, value)
    }
  }
  return [...parameterValues].map(([key, value]) => ({ key, value: readParameterValue(key, value) }))
}
