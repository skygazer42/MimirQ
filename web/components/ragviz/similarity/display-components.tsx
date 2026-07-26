'use client'

import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { SimilarityDiagnosticsGraph } from '@/components/ragviz/similarity-diagnostics-graph'
import type {
  DiagnosticDecision,
  SimilarityDiagnosticsResult,
} from '@/components/ragviz/similarity-diagnostics'
import { BarChart3, Filter, Grid3X3, Target } from 'lucide-react'
import { heatmapLegendBackground, type ColorSchemeKey } from './color-schemes'
import { formatHeatmapValue } from './similarity-matrix-math'
import {
  diagnosticCandidateStatusClass,
  diagnosticCandidateStatusLabel,
  emptyMatrixCellClass,
  emptyMatrixSwatchClass,
  formatPercent,
} from './utils'

export function IconBtn({
  active,
  icon,
  title,
  onClick,
}: Readonly<{
  active?: boolean
  icon: ReactNode
  title: string
  onClick?: () => void
}>) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className={cn(
        'flex h-9 w-9 items-center justify-center rounded-[0.95rem] border shadow-[inset_0_1px_0_hsl(var(--card)/0.52)] transition-colors',
        active
          ? 'border-info bg-info text-primary-foreground'
          : 'border-border/36 bg-background/50 text-muted-foreground hover:border-primary/26 hover:bg-background/70 hover:text-primary'
      )}
    >
      {icon}
    </button>
  )
}

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
}>) {
  return (
    <section className="rounded-[1.25rem] border border-border/34 bg-card/58 p-3.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
      {title ? (
        <div className="mb-3 text-[14px] font-semibold text-foreground/86">
          {title}
        </div>
      ) : null}
      <div
        className={cn(
          'flex flex-col items-center justify-center rounded-[1.15rem] border border-dashed border-border/34 bg-background/42 px-5 text-center',
          title ? 'min-h-[188px]' : 'min-h-[160px]'
        )}
      >
        <div className="flex size-11 items-center justify-center rounded-full border border-primary/14 bg-primary/[0.055] text-primary/58">
          {icon}
        </div>
        <p className="mt-4 text-[12px] leading-5 text-muted-foreground/68">
          {description}
        </p>
      </div>
    </section>
  )
}

export function SimilarityEmptyState() {
  return (
    <section
      aria-label="相似度矩阵空状态"
      className="flex h-full w-full max-w-[920px] flex-col items-center justify-center overflow-hidden rounded-[2rem] border border-border/40 bg-[linear-gradient(180deg,hsl(var(--card)/0.86),hsl(var(--background)/0.74))] px-10 py-8 text-center shadow-[0_24px_70px_-58px_hsl(var(--foreground)/0.42),inset_0_1px_0_hsl(var(--card)/0.72)]"
    >
      <div className="relative h-48 w-72">
        <div className="absolute left-1/2 top-4 h-36 w-36 -translate-x-1/2 rounded-full border border-primary/16" />
        <div className="absolute left-1/2 top-0 h-48 w-48 -translate-x-1/2 rounded-full border border-primary/10" />
        <div className="absolute left-[88px] top-[48px] h-24 w-32 rotate-[-9deg] rounded-[1.35rem] border border-primary/18 bg-[linear-gradient(145deg,hsl(var(--card)),hsl(var(--primary)/0.06))] shadow-[0_24px_60px_-42px_hsl(var(--primary)/0.55)]">
          <div className="grid grid-cols-5 gap-1 p-5">
            {Array.from({ length: 20 }, (_, barIndex) => barIndex).map((barIndex) => (
              <span
                key={`empty-matrix-swatch-${barIndex}`}
                className={cn(
                  'h-4 rounded-[4px]',
                  emptyMatrixSwatchClass(barIndex)
                )}
              />
            ))}
          </div>
        </div>
        <div className="absolute right-12 top-7 flex size-14 rotate-[12deg] items-center justify-center rounded-2xl border border-primary/12 bg-primary/[0.045] text-primary/42 shadow-subtle">
          <BarChart3 className="size-7" />
        </div>
        <span className="absolute left-12 top-12 size-2 rounded-full border border-primary/24" />
        <span className="absolute left-7 top-28 size-3 rounded-full bg-primary/14" />
        <span className="absolute right-16 top-28 size-2 rounded-full bg-primary/20" />
      </div>

      <div className="mt-5 flex w-full max-w-[560px] items-start justify-between rounded-full border border-border/32 bg-background/42 px-3 py-2">
        <EmptyStep
          index={1}
          title="选择 X Collection"
          description="从下拉框选择横坐标 Collection"
        />
        <EmptyStepConnector />
        <EmptyStep
          index={2}
          title="选择 Y Collection"
          description="从下拉框选择纵坐标 Collection"
        />
        <EmptyStepConnector />
        <EmptyStep
          index={3}
          title="计算相似度"
          description="点击“计算相似度”生成矩阵"
        />
      </div>

      <div className="mt-6 w-full max-w-[520px] rounded-[1.35rem] border border-border/34 bg-background/54 px-8 py-5 shadow-[inset_0_1px_0_hsl(var(--card)/0.62)]">
        <div className="grid grid-cols-[56px_1fr] gap-3">
          <div className="space-y-2 pt-5">
            {Array.from({ length: 5 }, (_, rowIndex) => rowIndex).map((rowIndex) => (
              <div key={`empty-matrix-row-${rowIndex}`} className="h-2 rounded-full bg-muted" />
            ))}
          </div>
          <div className="space-y-1.5">
            <div className="grid grid-cols-8 gap-1.5">
              {Array.from({ length: 8 }, (_, colIndex) => colIndex).map((colIndex) => (
                <div key={`empty-matrix-column-${colIndex}`} className="h-2 rounded-full bg-muted" />
              ))}
            </div>
            <div className="grid grid-cols-8 gap-1.5">
              {Array.from({ length: 56 }, (_, cellIndex) => cellIndex).map((cellIndex) => (
                <span
                  key={`empty-matrix-cell-${cellIndex}`}
                  className={cn(
                    'h-4 rounded-[3px]',
                    emptyMatrixCellClass(cellIndex)
                  )}
                />
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-5 flex w-full max-w-[780px] items-center justify-between rounded-full border border-border/34 bg-background/52 px-5 py-3 text-[12px] text-muted-foreground/74 shadow-subtle">
        <div className="flex items-center gap-2">
          <span className="flex size-5 items-center justify-center rounded-full border border-primary/20 text-primary">
            i
          </span>
          <span>支持切换主图、筛选器和独占模式，进一步探索和聚焦数据</span>
        </div>
        <div className="flex items-center gap-4 text-primary/70">
          <Grid3X3 className="size-5" />
          <Filter className="size-5" />
          <Target className="size-5" />
        </div>
      </div>
    </section>
  )
}

function EmptyStep({
  index,
  title,
  description,
}: Readonly<{
  index: number
  title: string
  description: string
}>) {
  return (
    <div className="flex w-36 flex-col items-center">
      <div className="flex size-7 items-center justify-center rounded-full bg-primary/[0.11] text-[12px] font-semibold text-primary ring-1 ring-primary/14">
        {index}
      </div>
      <div className="mt-2 text-[12px] font-semibold text-foreground/84">
        {title}
      </div>
      <div className="mt-0.5 text-[11px] leading-4 text-muted-foreground/64">
        {description}
      </div>
    </div>
  )
}

function EmptyStepConnector() {
  return (
    <div className="mt-3.5 h-px flex-1 border-t border-dashed border-primary/18" />
  )
}

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
    <section className="rounded-[1.1rem] border border-border/34 bg-card/58 p-3 shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]">
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
                    className="h-full rounded-full bg-[linear-gradient(90deg,#fb923c,#ef4444)]"
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
      return 'bg-success/10 text-success border-success/20'
    } else if (tone === 'warning') {
      return 'bg-warning/10 text-warning border-warning/20'
    } else if (tone === 'danger') {
      return 'bg-destructive/10 text-destructive border-destructive/20'
    } else if (tone === 'info') {
      return 'bg-info/10 text-info border-info/20'
    } else if (tone === 'muted') {
      return 'bg-muted text-muted-foreground border-border'
    } else {
      return 'bg-card text-foreground border-border'
    }
  })()

  return (
    <div className={cn('rounded-xl border p-2.5 shadow-subtle', toneClass)}>
      <div className="text-[11px] font-medium opacity-90">{label}</div>
      <div className="text-sm font-semibold mt-1">{value}</div>
    </div>
  )
}
