import type { RagasItem } from '@/types/evaluation'

export const LOW_SCORE_THRESHOLD = 0.8
const LABELS: Record<string, string> = {
  faithfulness: '忠实度',
  response_relevancy: '回答相关性',
  context_precision: '上下文精准度',
}
export function metricName(key: string) {
  return Object.hasOwn(LABELS, key) ? LABELS[key] : key
}
export function numericScore(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}
export function hasLowScore(item: RagasItem, metrics: readonly string[]) {
  return metrics.some((key) => {
    const value = numericScore(item.scores[key])
    return value !== null && value < LOW_SCORE_THRESHOLD
  })
}
export function metricStatistics(items: readonly RagasItem[], metrics: readonly string[]) {
  return metrics.map((key) => {
    const values = items
      .flatMap((item) => {
        const score = numericScore(item.scores[key])
        return score === null ? [] : [score]
      })
      .sort((a, b) => a - b)
    const label = metricName(key)
    const scoredCount = values.length
    if (scoredCount === 0) {
      return { key, label, scoredCount, mean: null, p50: null, p90: null, passRate: null }
    }

    const percentile = (percent: number) => values[Math.floor((percent / 100) * (scoredCount - 1))]
    return {
      key,
      label,
      scoredCount,
      mean: values.reduce((sum, value) => sum + value, 0) / scoredCount,
      p50: percentile(50),
      p90: percentile(90),
      passRate: values.filter((value) => value >= LOW_SCORE_THRESHOLD).length / scoredCount,
    }
  })
}
export function itemContexts(item: RagasItem) {
  return item.retrieved_contexts === null ? [] : item.retrieved_contexts
}
export function displayDate(value: string | null | undefined) {
  if (value === null || value === undefined) return '—'
  const date = new Date(value)
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
export function runDuration(start: string | null | undefined, end: string | null | undefined) {
  if (start === null || start === undefined || end === null || end === undefined) return null
  const durationMs = new Date(end).getTime() - new Date(start).getTime()
  return `${(durationMs / 1000).toFixed(1)} 秒`
}
