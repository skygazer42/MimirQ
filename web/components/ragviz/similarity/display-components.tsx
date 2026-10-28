'use client'
import type { ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { SimilarityDiagnosticsGraph } from '@/components/ragviz/similarity-diagnostics-graph';
import type { DiagnosticDecision, SimilarityDiagnosticsResult } from '@/components/ragviz/similarity-diagnostics';
import { heatmapLegendBackground, type ColorSchemeKey } from './color-schemes';
import { formatHeatmapValue } from './similarity-matrix-math';
import { diagnosticCandidateStatusClass, diagnosticCandidateStatusLabel, formatPercent } from './utils';

export function EmptyControlTile({
  icon,
  label,
}: Readonly<{ icon: ReactNode; label: string }>) {
  return (
    <div className="flex min-h-[74px] flex-col items-center justify-center rounded-[1rem] border border-border/32 bg-background/42 text-muted-foreground">
      <div className="text-primary/58">{icon}</div>
      <div className="mt-2 text-[11px] font-medium text-foreground/76">
        {label}
      </div>
    </div>
  )
}

export function RightEmptyInfoCard({
  title,
  icon,
  description,
}: Readonly<{
  title: string
  icon: ReactNode
  description: string
}>){ return <section className="border-t border-border py-5">{title ? <h3 className="text-sm font-semibold">{title}</h3> : null}<div className="mt-3 flex items-start gap-3 text-muted-foreground"><span className="shrink-0">{icon}</span><p className="text-[13px] leading-6">{description}</p></div></section> }

export function SimilarityEmptyState(){ return <div className="py-10 text-sm leading-7 text-muted-foreground">选择数据源并计算相似度后，在这里查看矩阵。</div> }

export function Panel({
  title,
  children,
  rightSlot,
  subtitle,
}: Readonly<{
  title: string
  children: ReactNode
  rightSlot?: ReactNode
  subtitle?: string
}>) {
  return (
    <div className="h-full flex flex-col">
      <div className="relative mb-2.5 min-h-8 pr-9">
        <div>
          <div className="text-[14px] font-semibold leading-5 tracking-[-0.012em] text-foreground/88">
            {title}
          </div>
          {subtitle ? (
            <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground/64">
              {subtitle}
            </div>
          ) : null}
        </div>
        {rightSlot ? (
          <div className="absolute right-0 top-0">{rightSlot}</div>
        ) : null}
      </div>
      <div className="flex-1">{children}</div>
    </div>
  )
}

export function SimilarityDiagnosticsView({
  diagnostics,
  onDecisionChange,
}: Readonly<{
  diagnostics: SimilarityDiagnosticsResult
  onDecisionChange: (
    candidateId: string,
    decision: DiagnosticDecision | null
  ) => void
}>) {
  return (
    <div className="h-full overflow-auto p-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,380px)]">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <DiagnosticMetricCard
              label="诊断节点"
              value={String(diagnostics.summary.totalNodes)}
              hint="当前 X/Y 两侧共同参与投影的节点数"
            />
            <DiagnosticMetricCard
              label="邻域连线"
              value={String(diagnostics.summary.totalLinks)}
              hint="按当前筛选保留下来的高相似度近邻边"
            />
            <DiagnosticMetricCard
              label="活跃异常点"
              value={String(diagnostics.summary.activeOutlierCount)}
              hint="仍然需要人工处理的高分异常候选"
            />
          </div>

          <section className="rounded-[1.35rem] border border-border/36 bg-card/62 p-3 shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
            <div className="flex flex-col gap-3 border-b border-border/32 pb-3 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="text-sm font-semibold">3D 投影预览</div>
                <p className="mt-1 text-xs text-muted-foreground">
                  基于当前相似度矩阵重建局部向量邻域，帮助观察高分簇、孤立点和异常连线。
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <LegendPill className="border-info/30 bg-info/10 text-info dark:bg-info/10">
                  X 侧项目
                </LegendPill>
                <LegendPill className="border-success/20 bg-success/10 text-success">
                  Y 侧项目
                </LegendPill>
                <LegendPill className="border-warning/30 bg-warning/10 text-warning">
                  异常点候选
                </LegendPill>
                <LegendPill className="border-warning/30 bg-warning/10 text-warning">
                  标记待审
                </LegendPill>
              </div>
            </div>

            <div className="mt-3">
              <SimilarityDiagnosticsGraph
                nodes={diagnostics.nodes}
                links={diagnostics.links}
              />
            </div>
          </section>
        </div>

        <section className="overflow-hidden rounded-[1.35rem] border border-border/36 bg-card/62 shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
          <div className="border-b border-border/32 p-4">
            <div className="text-sm font-semibold">异常点标注</div>
            <p className="mt-1 text-xs text-muted-foreground">
              高分但词面支撑偏弱的候选会列在这里，可直接禁用候选或标记待审。
            </p>
          </div>

          <div className="space-y-3 overflow-auto p-4">
            {diagnostics.outliers.length === 0 ? (
              <div className="rounded-xl border border-dashed border-sidebar-border/60 bg-muted/30 px-4 py-6 text-sm text-muted-foreground">
                当前筛选结果里没有需要人工干预的高分异常候选。
              </div>
            ) : (
              diagnostics.outliers.map((candidate) => {
                const isDisabled = candidate.decision === 'disabled'
                const isMarked = candidate.decision === 'marked'

                return (
                  <article
                    key={candidate.id}
                    className="rounded-[1.1rem] border border-border/34 bg-background/42 p-4 shadow-[inset_0_1px_0_hsl(var(--card)/0.45)]"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-foreground">
                          {candidate.xLabel}{' '}
                          <span className="text-muted-foreground">→</span>{' '}
                          {candidate.yLabel}
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {candidate.reason}
                        </p>
                      </div>
                      <span
                        className={cn(
                          'rounded-full border px-2 py-0.5 text-[11px]',
                          diagnosticCandidateStatusClass(isDisabled, isMarked)
                        )}
                      >
                        {diagnosticCandidateStatusLabel(isDisabled, isMarked)}
                      </span>
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-2">
                      <DiagnosticMetricCard
                        label="相似度"
                        value={formatPercent(candidate.similarity)}
                        compact
                      />
                      <DiagnosticMetricCard
                        label="词面重叠"
                        value={formatPercent(candidate.lexicalOverlap)}
                        compact
                      />
                    </div>

                    <div className="mt-3 flex gap-2">
                      <Button
                        variant={isDisabled ? 'default' : 'outline'}
                        size="sm"
                        className="flex-1"
                        onClick={() =>
                          onDecisionChange(
                            candidate.id,
                            isDisabled ? null : 'disabled'
                          )
                        }
                      >
                        {isDisabled ? '恢复候选' : '禁用候选'}
                      </Button>
                      <Button
                        variant={isMarked ? 'default' : 'outline'}
                        size="sm"
                        className="flex-1"
                        onClick={() =>
                          onDecisionChange(
                            candidate.id,
                            isMarked ? null : 'marked'
                          )
                        }
                      >
                        {isMarked ? '取消标记' : '标记待审'}
                      </Button>
                    </div>
                  </article>
                )
              })
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function LegendPill({
  className,
  children,
}: Readonly<{ className?: string; children: ReactNode }>) {
  return (
    <span className={cn('rounded-full border px-2 py-0.5', className)}>
      {children}
    </span>
  )
}

export function HeatmapScaleLegend({
  colorScheme,
  isDifference,
}: Readonly<{ colorScheme: ColorSchemeKey; isDifference: boolean }>) {
  return (
    <div className="border-t border-sidebar-border/70 px-4 py-3">
      <div className="flex max-w-md items-center gap-3 text-xs font-medium text-foreground">
        <span>{isDifference ? '差值' : '相似度'}</span>
        <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
          {isDifference ? '-1' : '0'}
        </span>
        <div
          className="h-3 flex-1 rounded-full border border-border/50"
          style={{ backgroundImage: heatmapLegendBackground(colorScheme, isDifference) }}
        />
        <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
          1
        </span>
      </div>
    </div>
  )
}

export function RelatedListCard({
  title,
  items,
}: Readonly<{
  title: string
  items: Array<{ label: string; value: number; index: number }>
}>) {
  return (
    <section className="border-t border-border py-4">
      <div className="mb-2 text-[12px] font-semibold text-foreground">
        {title}
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-muted-foreground">暂无可比较项</div>
      ) : (
        <div className="space-y-2">
          {items.map((item, index) => (
            <div
              key={`${item.label}-${item.index}`}
              className="grid grid-cols-[18px_minmax(0,1fr)_44px] items-center gap-2"
            >
              <span className="text-[11px] font-medium text-muted-foreground">
                {index + 1}
              </span>
              <div className="min-w-0">
                <div className="truncate text-[12px] font-medium text-foreground">
                  {item.label}
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-foreground/60"
                    style={{
                      width: `${Math.max(4, Math.min(100, item.value * 100))}%`,
                    }}
                  />
                </div>
              </div>
              <span className="text-right font-mono text-[11px] font-semibold tabular-nums text-foreground">
                {formatHeatmapValue(item.value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function DiagnosticMetricCard({
  label,
  value,
  hint,
  compact = false,
}: Readonly<{
  label: string
  value: string
  hint?: string
  compact?: boolean
}>) {
  return (
    <div
      className={cn(
        'rounded-[1rem] border border-border/34 bg-card/52',
        compact ? 'p-3' : 'p-4'
      )}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          'mt-1 font-semibold text-foreground',
          compact ? 'text-base' : 'text-2xl'
        )}
      >
        {value}
      </div>
      {hint ? (
        <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}

export function StatsGrid({ children }: Readonly<{ children: ReactNode }>) {
  return <div className="grid grid-cols-2 gap-2">{children}</div>
}

export function StatsItem({
  label,
  value,
  tone = 'default',
}: Readonly<{
  label: string
  value: ReactNode
  tone?: 'default' | 'muted' | 'info' | 'success' | 'warning' | 'danger'
}>) {
  const toneClass = (() => {
    if (tone === 'success') {
      return 'text-success'
    } else if (tone === 'warning') {
      return 'text-warning'
    } else if (tone === 'danger') {
      return 'text-destructive'
    } else if (tone === 'info') {
      return 'text-foreground'
    } else if (tone === 'muted') {
      return 'text-muted-foreground'
    } else {
      return 'text-foreground'
    }
  })()

  return (
    <div className={cn('border-b border-border py-3', toneClass)}>
      <div className="text-[13px] font-medium text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold mt-1">{value}</div>
    </div>
  )
}
