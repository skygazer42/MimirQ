'use client'

import { useMemo, useState } from 'react'
import { FileDown, SearchCode } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { evaluationApi } from '@/lib/api/evaluation'
import { cn } from '@/lib/utils'
import type { RegressionItem, RegressionRunCaseDiff, RegressionRunDetail } from '@/types'

function toRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function scoreValue(item: RegressionItem | undefined, metricKeys: string[]): number | null {
  if (!item) return null
  const scores = toRecord(item.scores)
  const values = metricKeys
    .map((key) => Number(scores[key]))
    .filter((value) => Number.isFinite(value))
  if (!values.length) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function serializableText(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return ''
  }
}

function primitiveText(value: unknown, fallback = '-'): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

function csvEscape(value: unknown): string {
  const text = serializableText(value)
  return `"${text.replaceAll('"', '""')}"`
}

function downloadCsv(rows: Array<Record<string, unknown>>) {
  const headers = ['case_id', 'question', 'base_score', 'target_score', 'delta', 'label']
  const lines = [headers.join(',')]
  for (const row of rows) lines.push(headers.map((key) => csvEscape(row[key])).join(','))
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'ablation-case-drilldown.csv'
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function AblationCaseDrilldown({
  baseRunId,
  targetRunId,
  metricKeys,
  caseDiffs,
}: Readonly<{
  baseRunId: string
  targetRunId: string
  metricKeys: string[]
  caseDiffs?: RegressionRunCaseDiff[]
}>) {
  const [baseDetail, setBaseDetail] = useState<RegressionRunDetail | null>(null)
  const [targetDetail, setTargetDetail] = useState<RegressionRunDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [expandedCaseId, setExpandedCaseId] = useState('')

  async function loadDetails() {
    if (!baseRunId || !targetRunId || baseRunId === targetRunId) return
    setLoading(true)
    try {
      const [base, target] = await Promise.all([
        evaluationApi.getRegressionRun(baseRunId, { include_items: true, include_contexts: false }),
        evaluationApi.getRegressionRun(targetRunId, { include_items: true, include_contexts: false }),
      ])
      setBaseDetail(base)
      setTargetDetail(target)
    } finally {
      setLoading(false)
    }
  }

  const rows = useMemo(() => {
    if (caseDiffs?.length) {
      return caseDiffs.map((item) => ({
        case_id: item.case_id,
        question: item.question,
        base_score: null,
        target_score: null,
        delta: item.mean_delta ?? null,
        label: item.label,
        base_response: '',
        target_response: '',
        metric_diffs: item.metric_diffs,
      }))
    }
    const baseByCase = new Map((baseDetail?.items || []).map((item) => [item.case_id, item]))
    return (targetDetail?.items || []).map((targetItem) => {
      const baseItem = baseByCase.get(targetItem.case_id)
      const baseScore = scoreValue(baseItem, metricKeys)
      const targetScore = scoreValue(targetItem, metricKeys)
      const delta = baseScore !== null && targetScore !== null ? targetScore - baseScore : null
      const label = delta === null ? '无分数' : delta > 0.05 ? '改善' : delta < -0.05 ? '退化' : '无明显变化'
      return {
        case_id: targetItem.case_id,
        question: targetItem.question,
        base_score: baseScore,
        target_score: targetScore,
        delta,
        label,
        base_response: baseItem?.response || '',
        target_response: targetItem.response || '',
        metric_diffs: [],
      }
    })
  }, [baseDetail, caseDiffs, metricKeys, targetDetail])

  return (
    <section className="rounded-2xl border border-slate-200 bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <SearchCode className="size-4 text-rose-600" />
            Per-case 失败钻取
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            拉取 base/target 的 case 级结果，对齐 case_id 后标注改善、退化和无变化。聚合指标看方向，case diff 才能解释原因。
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button type="button" variant="outline" disabled={loading || !baseRunId || !targetRunId || baseRunId === targetRunId} onClick={() => void loadDetails()} className="rounded-xl">
            加载 Cases
          </Button>
          <Button type="button" variant="outline" disabled={!rows.length} onClick={() => downloadCsv(rows)} className="gap-2 rounded-xl">
            <FileDown className="size-4" />
            导出 CSV
          </Button>
        </div>
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-slate-200">
        <div className="grid grid-cols-[minmax(180px,1fr)_82px_82px_82px_88px] bg-slate-50 px-3 py-2 text-[11px] uppercase tracking-[0.12em] text-slate-500">
          <div>case_id / question</div>
          <div className="text-right">Base</div>
          <div className="text-right">Target</div>
          <div className="text-right">Delta</div>
          <div className="text-right">标签</div>
        </div>
        {rows.length ? rows.map((row) => (
          <button
            key={row.case_id}
            type="button"
            className="block w-full border-t border-slate-100 text-left"
            onClick={() => setExpandedCaseId((prev) => (prev === row.case_id ? '' : row.case_id))}
          >
            <div className="grid grid-cols-[minmax(180px,1fr)_82px_82px_82px_88px] px-3 py-2 text-xs">
              <div className="min-w-0">
                <div className="font-mono text-[11px] text-slate-500">{row.case_id.slice(0, 8)}…</div>
                <div className="truncate text-slate-900">{row.question}</div>
              </div>
              <div className="text-right font-mono text-slate-600">{row.base_score === null ? '-' : row.base_score.toFixed(3)}</div>
              <div className="text-right font-mono text-slate-600">{row.target_score === null ? '-' : row.target_score.toFixed(3)}</div>
              <div className={cn('text-right font-mono', row.delta && row.delta > 0 ? 'text-emerald-600' : row.delta && row.delta < 0 ? 'text-rose-600' : 'text-slate-500')}>
                {row.delta === null ? '-' : row.delta >= 0 ? `+${row.delta.toFixed(3)}` : row.delta.toFixed(3)}
              </div>
              <div className="text-right text-slate-700">{row.label}</div>
            </div>
            {expandedCaseId === row.case_id ? (
              <div className="grid gap-2 border-t border-slate-100 bg-slate-50 px-3 py-3 text-xs md:grid-cols-2">
                <div>
                  <div className="mb-1 font-medium text-slate-700">Base answer</div>
                  <div className="line-clamp-5 rounded-lg bg-background p-2 text-slate-600">
                    {row.base_response || (row.metric_diffs.length ? row.metric_diffs.map((item) => `${item.key}: ${primitiveText(item.before)} -> ${primitiveText(item.after)}`).join(' / ') : '-')}
                  </div>
                </div>
                <div>
                  <div className="mb-1 font-medium text-slate-700">Target answer</div>
                  <div className="line-clamp-5 rounded-lg bg-background p-2 text-slate-600">{row.target_response || '-'}</div>
                </div>
              </div>
            ) : null}
          </button>
        )) : (
          <div className="px-3 py-8 text-center text-xs text-slate-500">选择 base/target 后加载 case 明细。</div>
        )}
      </div>
    </section>
  )
}
