'use client'

import { FlaskConical } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { RagasRegressionRunDiffResponse, RegressionRunMetricSignificance } from '@/types'

function toFinite(value: unknown): number | null {
  const next = Number(value)
  return Number.isFinite(next) ? next : null
}

function verdict(delta: number | null): { label: string; tone: string } {
  if (delta === null) return { label: '等待 metric diff', tone: 'text-muted-foreground' }
  if (Math.abs(delta) < 0.01) return { label: '无明显变化', tone: 'text-muted-foreground' }
  if (Math.abs(delta) < 0.03) return { label: '方向性变化', tone: delta > 0 ? 'text-success' : 'text-warning' }
  return { label: delta > 0 ? '显著候选' : '退化风险', tone: delta > 0 ? 'text-success' : 'text-destructive' }
}

export function AblationStatisticsPanel({
  diff,
}: Readonly<{
  diff: RagasRegressionRunDiffResponse | null
}>) {
  const significanceRows = Array.isArray(diff?.significance) ? diff.significance : []
  const fallbackRows: RegressionRunMetricSignificance[] = (Array.isArray(diff?.metric_diffs) ? diff.metric_diffs : []).map((row) => ({
    key: row.key,
    compared: 0,
    delta_mean: toFinite(row.delta),
    significant: false,
  }))
  const rows = significanceRows.length ? significanceRows : fallbackRows

  return (
    <section className="rounded-2xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <FlaskConical className="size-4 text-success" />
            统计显著性审查
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            先把 Bootstrap CI、paired test、p-value 与 BH 校正放进操作台；当前后端未返回 per-case 统计时明确显示“待计算”，避免把聚合 delta 误读成结论。
          </p>
        </div>
        <div className="rounded-full border border-warning/30 bg-warning/10 px-2.5 py-1 text-[11px] font-medium text-warning">
          Bootstrap CI / p-value / BH 校正
        </div>
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-border">
        <div className="grid grid-cols-[minmax(120px,1fr)_96px_120px_120px_120px] bg-muted/50 px-3 py-2 text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
          <div>Metric</div>
          <div className="text-right">Delta</div>
          <div className="text-right">Bootstrap CI</div>
          <div className="text-right">p-value</div>
          <div className="text-right">Verdict</div>
        </div>
        {rows.length ? (
          rows.map((row) => {
            const delta = toFinite(row.delta_mean)
            const meta = verdict(delta)
            return (
              <div key={row.key} className="grid grid-cols-[minmax(120px,1fr)_96px_120px_120px_120px] border-t border-border/50 px-3 py-2 text-xs">
                <div className="truncate font-mono text-foreground">{row.key}</div>
                <div className={cn('text-right font-mono', delta && delta > 0 ? 'text-success' : delta && delta < 0 ? 'text-destructive' : 'text-muted-foreground')}>
                  {delta === null ? '-' : delta.toFixed(4)}
                </div>
                <div className="text-right font-mono text-muted-foreground">
                  {row.bootstrap_ci_low == null || row.bootstrap_ci_high == null
                    ? '待 per-case'
                    : `[${row.bootstrap_ci_low.toFixed(3)}, ${row.bootstrap_ci_high.toFixed(3)}]`}
                </div>
                <div className="text-right font-mono text-muted-foreground">
                  {row.p_value == null ? '待计算' : `${row.p_value.toFixed(4)} / BH ${row.p_value_bh == null ? '-' : row.p_value_bh.toFixed(4)}`}
                </div>
                <div className={cn('text-right font-medium', row.significant ? 'text-success' : meta.tone)}>
                  {row.significant ? '显著' : meta.label}
                </div>
              </div>
            )
          })
        ) : (
          <div className="px-3 py-8 text-center text-xs text-muted-foreground">生成 Diff 后显示指标差异；接入 per-case scores 后可计算真实 Bootstrap CI 与 p-value。</div>
        )}
      </div>
    </section>
  )
}
