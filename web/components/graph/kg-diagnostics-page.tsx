'use client'

import {
  Activity,
  ClipboardList,
  CircleAlert,
  Download,
  FileStack,
  History,
  Info,
  Minus,
  PlayCircle,
  Plus,
  RefreshCcw,
  Sparkles,
  Target,
  TrendingUp,
  Waypoints,
} from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/ui/page-header'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { formatApiError } from '@/lib/api-errors'
import {
  datasetApi,
  evaluationApi,
  type KGHardcaseMode,
  type KGSearchDiagnosticsResponse,
  type KGSearchDiagnosticsRunDetail,
} from '@/lib/api'
import { coerceOneOf } from '@/lib/one-of'
import { queryKeys } from '@/lib/query-keys'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn } from '@/lib/utils'

const KG_EXTRACT_MODE_VALUES = ['auto', 'on', 'off'] as const
const DIAGNOSTICS_SECTION_TITLE_CLASS =
  'text-[14px] font-medium leading-5 text-foreground/85'
const DIAGNOSTICS_SECTION_DESCRIPTION_CLASS =
  'text-[12px] font-normal leading-5 text-muted-foreground'
const DIAGNOSTICS_FIELD_LABEL_CLASS =
  'text-[12px] font-normal leading-5 text-muted-foreground'
const DIAGNOSTICS_FIELD_VALUE_CLASS =
  'text-[14px] font-normal text-foreground/90'
const DIAGNOSTICS_METRIC_LABELS: Record<string, string> = {
  baseline_hit_rate: '基线命中率',
  baseline_mrr: 'Baseline MRR',
  baseline_recall: 'Baseline Recall',
  baseline_ndcg: 'Baseline NDCG@K',
  baseline_map: 'Baseline MAP@K',
  hardcase_hit_rate: '难例命中率',
  hardcase_mrr: 'Hardcase MRR',
  hardcase_recall: 'Hardcase Recall',
  hardcase_ndcg: 'Hardcase NDCG@K',
  hardcase_map: 'Hardcase MAP@K',
  hardcases_generated: '生成难例数',
  documents: '文档数',
  events: '事件数',
  entities: '实体数',
  relations: '关系数',
  event_entity_links: '事件实体关联数',
  avg_relations_per_entity: '平均每实体关系数',
  isolated_entities: '孤立实体数',
  isolated_entity_ratio: '孤立实体占比',
  nodes: '节点数',
  edges: '边数',
  components: '连通分量数',
  largest_component_ratio: '最大连通分量占比',
  relations_total: '关系总数',
  low_confidence_threshold: '低置信阈值',
  low_confidence_relations: '低置信关系数',
  missing_references_relations: '缺少引用的关系数',
  missing_chunk_relations: '缺少切片的关系数',
  relation_edges_truncated: '关系边已截断',
  relation_edges_limit: '关系边上限',
  dataset_id: '数据集',
  documents_sampled: '抽样文档数',
  documents_allowed: '有权限文档数',
}
const KG_DIAGNOSTICS_DATASET_LIST_PARAMS = { limit: 200 } as const

type DiagnosticsView = 'run' | 'quality' | 'compare'
type DiagnosticsDatasetOption = {
  id?: string
  name?: string | null
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function downloadJson(value: unknown, filename: string): void {
  const content = JSON.stringify(value ?? {}, null, 2)
  const blob = new Blob([content], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function toNumber(value: any): number | null {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function formatMetricValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (
    typeof value === 'number' ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return String(value)
  }
  return prettyJson(value)
}

function formatDiagnosticsMetricLabel(key: string): string {
  return DIAGNOSTICS_METRIC_LABELS[key] ?? key.replaceAll('_', ' ')
}

function extractBaselineMetrics(
  item: any
): {
  hit_at_k: boolean
  mrr: number
  recall: number
  ndcg: number
  map: number
} | null {
  const baseline = item?.baseline
  const metrics = baseline?.metrics
  const hit = Boolean(metrics?.hit_at_k)
  const mrr = toNumber(metrics?.mrr)
  const recall = toNumber(metrics?.recall)
  const ndcg = toNumber(metrics?.ndcg)
  const meanAveragePrecision = toNumber(metrics?.map)
  if (mrr === null || recall === null) return null
  return {
    hit_at_k: hit,
    mrr,
    recall,
    ndcg: ndcg ?? 0,
    map: meanAveragePrecision ?? 0,
  }
}

function caseKey(item: any): string | null {
  const id = item?.case_id
  const s = String(id || '').trim()
  return s || null
}

function DiagnosticsInlineStat({
  label,
  value,
  tone = 'muted',
}: Readonly<{
  label: string
  value: ReactNode
  tone?: 'muted' | 'neutral' | 'positive' | 'negative'
}>) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-border/70 bg-card/90 px-2.5 py-1">
      <span className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          'font-mono text-[11px] tabular-nums',
          tone === 'positive'
            ? 'text-emerald-700'
            : tone === 'negative'
              ? 'text-rose-700'
              : tone === 'neutral'
                ? 'text-foreground'
                : 'text-muted-foreground'
        )}
      >
        {value}
      </span>
    </div>
  )
}

function DiagnosticsInfoTooltip({
  label,
  children,
  side = 'right',
}: Readonly<{
  label: string
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
}>) {
  return (
    <TooltipProvider delayDuration={120}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={label}
            className="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-sky-50 hover:text-sky-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          >
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </TooltipTrigger>
        <TooltipContent
          side={side}
          align="center"
          className="max-w-[260px] text-[11px] leading-5"
        >
          {children}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

function DiagnosticsHeaderPill({
  label,
  value,
  icon,
  children,
  className,
}: Readonly<{
  label: string
  value?: ReactNode
  icon?: ReactNode
  children?: ReactNode
  className?: string
}>) {
  return (
    <div
      className={cn(
        'inline-flex h-9 items-center gap-2.5 rounded-lg border border-border/70 bg-card/95 px-3 shadow-sm',
        className
      )}
    >
      {icon ? (
        <span className="flex h-5 w-5 items-center justify-center text-muted-foreground">
          {icon}
        </span>
      ) : null}
      <span className="text-[10.5px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
      <div className="min-w-0 flex-1">
        {children ?? (
          <span className={cn('block truncate', DIAGNOSTICS_FIELD_VALUE_CLASS)}>
            {value}
          </span>
        )}
      </div>
    </div>
  )
}

function DiagnosticsStepper({
  value,
  min,
  max,
  onChange,
}: Readonly<{
  value: number
  min: number
  max: number
  onChange: (value: number) => void
}>) {
  return (
    <div className="flex h-9 items-center rounded-lg border border-border/70 bg-card/95 shadow-sm">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-full w-10 rounded-r-none text-muted-foreground"
        aria-label="减少阈值"
        onClick={() => onChange(Math.max(min, value - 1))}
      >
        <Minus className="h-4 w-4" aria-hidden="true" />
      </Button>
      <div className="flex flex-1 items-center justify-center border-x border-border/70 text-[15px] font-medium tabular-nums text-foreground/90">
        {value}
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-full w-10 rounded-l-none text-muted-foreground"
        aria-label="增加阈值"
        onClick={() => onChange(Math.min(max, value + 1))}
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
      </Button>
    </div>
  )
}

function DiagnosticsSection({
  label,
  description,
  children,
  className,
}: Readonly<{
  label: string
  description?: string
  children: ReactNode
  className?: string
}>) {
  return (
    <section
      className={cn(
        'space-y-2.5 rounded-lg border border-border/70 bg-card px-3.5 py-3',
        className
      )}
    >
      <div className="space-y-1">
        <div className={DIAGNOSTICS_SECTION_TITLE_CLASS}>{label}</div>
        {description ? (
          <p className={DIAGNOSTICS_SECTION_DESCRIPTION_CLASS}>{description}</p>
        ) : null}
      </div>
      {children}
    </section>
  )
}

function DiagnosticsMetricTile({
  label,
  value,
  caption,
  tone = 'neutral',
  accent = 'neutral',
  icon,
}: Readonly<{
  label: string
  value: ReactNode
  caption?: ReactNode
  tone?: 'neutral' | 'positive' | 'negative' | 'muted'
  accent?: 'neutral' | 'sky' | 'violet' | 'emerald' | 'amber'
  icon?: ReactNode
}>) {
  const accentClasses =
    accent === 'sky'
      ? {
          surface: 'border-border/70 bg-background',
          label: 'text-sky-700',
          dot: 'bg-sky-400',
          value: 'text-foreground',
          caption: 'text-muted-foreground',
        }
      : accent === 'violet'
        ? {
            surface: 'border-border/70 bg-background',
            label: 'text-violet-700',
            dot: 'bg-violet-400',
            value: 'text-foreground',
            caption: 'text-muted-foreground',
          }
        : accent === 'emerald'
          ? {
              surface: 'border-border/70 bg-background',
              label: 'text-emerald-700',
              dot: 'bg-emerald-400',
              value: 'text-foreground',
              caption: 'text-muted-foreground',
            }
          : accent === 'amber'
            ? {
                surface: 'border-border/70 bg-background',
                label: 'text-amber-700',
                dot: 'bg-amber-400',
                value: 'text-foreground',
                caption: 'text-muted-foreground',
              }
            : {
                surface: 'border-border/70 bg-background',
                label: 'text-muted-foreground',
                dot: 'bg-muted-foreground/40',
                value: 'text-foreground',
                caption: 'text-muted-foreground',
              }

  const valueClass =
    tone === 'positive'
      ? 'text-emerald-700'
      : tone === 'negative'
        ? 'text-rose-700'
        : tone === 'muted'
          ? 'text-muted-foreground'
          : accentClasses.value
  const isPending = value === '-'

  return (
    <div
      className={cn(
        'flex min-h-[112px] flex-col items-center justify-center rounded-xl border px-3.5 py-3 text-center shadow-[inset_0_1px_0_rgba(255,255,255,0.85)]',
        accentClasses.surface
      )}
    >
      <div
        className={cn(
          'flex items-center justify-center gap-1.5 text-[12px] font-semibold ',
          accentClasses.label
        )}
      >
        {icon ? (
          <span className="flex h-4 w-4 items-center justify-center">
            {icon}
          </span>
        ) : (
          <span
            className={cn('h-1.5 w-1.5 rounded-full', accentClasses.dot)}
            aria-hidden="true"
          />
        )}
        <span>{label}</span>
      </div>
      <div
        className={cn(
          'mt-3 text-[17px] font-semibold tabular-nums',
          valueClass
        )}
      >
        {isPending ? (
          <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
            待评测
          </span>
        ) : (
          value
        )}
      </div>
      {caption ? (
        <div
          className={cn('mt-2 text-[11px] leading-5', accentClasses.caption)}
        >
          {isPending ? '运行后显示' : caption}
        </div>
      ) : null}
    </div>
  )
}

function DiagnosticsToggleCard({
  title,
  description,
  badge,
  checked,
  onCheckedChange,
  tone,
  stateLabel,
}: Readonly<{
  title: string
  description?: string
  badge: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  tone: 'sky' | 'emerald'
  stateLabel: string
}>) {
  const toneClasses =
    tone === 'sky'
      ? {
          surface: 'border-border/70 bg-background',
          badge: 'text-sky-700',
          dot: 'bg-sky-400',
        }
      : {
          surface: 'border-border/70 bg-background',
          badge: 'text-emerald-700',
          dot: 'bg-emerald-400',
        }

  return (
    <label
      className={cn(
        'block cursor-pointer select-none rounded-lg border px-3 py-1.5 transition-colors',
        toneClasses.surface
      )}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div
                className={cn(
                  'flex items-center gap-1.5 text-[10.5px] font-normal ',
                  toneClasses.badge
                )}
              >
                <span
                  className={cn('h-1.5 w-1.5 rounded-full', toneClasses.dot)}
                />
                <span>{badge}</span>
              </div>
              <div className="mt-0.5 text-[13px] font-medium leading-4 text-foreground/90">
                {title}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <span className="inline-flex items-center rounded-full border border-border/70 bg-card/90 px-2 py-0.5 text-[11px] font-normal text-muted-foreground">
                {stateLabel}
              </span>
              <Switch checked={checked} onCheckedChange={onCheckedChange} />
            </div>
          </div>
          {description ? (
            <p className="mt-0.5 truncate text-[11px] font-normal leading-5 text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
      </div>
    </label>
  )
}

function DiagnosticsEmptyState({
  title,
  description,
  icon,
  className,
}: Readonly<{
  title: string
  description: string
  icon?: ReactNode
  className?: string
}>) {
  return (
    <div
      className={cn(
        'rounded-lg border border-dashed border-border/70 bg-background px-5 py-6 text-center',
        className
      )}
    >
      {icon ? (
        <div className="mb-3 flex justify-center text-sky-300">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-sky-100 bg-sky-50/80 shadow-sm">
            <div className="scale-90">{icon}</div>
          </div>
        </div>
      ) : null}
      <div className="text-[13px] font-medium text-foreground">{title}</div>
      <p className="mx-auto mt-1.5 max-w-xl text-[11px] leading-5 text-muted-foreground">
        {description}
      </p>
    </div>
  )
}

function DiagnosticsRunHeroPanel({
  summary,
  emptyTitle,
  emptyDescription,
}: Readonly<{
  summary: Record<string, any> | null
  emptyTitle: string
  emptyDescription: string
}>) {
  if (summary) {
    return (
      <div className="min-h-[160px] rounded-xl border border-border/70 bg-background px-6 py-5 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-[11px] font-medium tracking-[0.12em] text-sky-600">
              最新结果
            </div>
            <h3 className="mt-1 text-[22px] font-semibold tracking-[-0.03em] text-foreground">
              本轮评测已完成
            </h3>
            <p className="mt-1.5 text-[12px] leading-5 text-muted-foreground">
              优先查看上方核心指标，再结合下方失败样本和运行记录判断这次检索质量是否稳定。
            </p>
          </div>
          <div className="hidden h-14 w-14 items-center justify-center rounded-[18px] border border-sky-100 bg-sky-50 text-sky-500 shadow-sm md:flex">
            <ClipboardList className="h-6 w-6" aria-hidden="true" />
          </div>
        </div>
      </div>
    )
  }

  const resultPreviewItems = [
    {
      title: '核心指标',
      description: 'Hit Rate、MRR、Recall、NDCG、MAP 会集中显示在顶部指标卡。',
      icon: <Target className="h-4 w-4" aria-hidden="true" />,
    },
    {
      title: '失败样本',
      description: '未命中问题、召回位置和错误分布会进入下方分析区。',
      icon: <CircleAlert className="h-4 w-4" aria-hidden="true" />,
    },
    {
      title: '原始结果',
      description: '保存后的 run 记录与 JSON 明细可直接查看或导出。',
      icon: <FileStack className="h-4 w-4" aria-hidden="true" />,
    },
  ]

  return (
    <div className="grid min-h-[220px] gap-5 rounded-xl border border-border/70 bg-[radial-gradient(circle_at_16%_0%,hsl(var(--info)/0.10),transparent_34%),linear-gradient(180deg,hsl(var(--background)),hsl(var(--card)/0.92))] px-6 py-5 shadow-sm md:grid-cols-[minmax(0,0.95fr)_minmax(320px,1.05fr)]">
      <div className="flex items-center gap-5">
        <div className="relative flex h-[112px] w-[132px] shrink-0 items-center justify-center text-sky-300">
          <div
            className="absolute inset-5 rounded-[30px] bg-sky-100/70 blur-2xl"
            aria-hidden="true"
          />
          <div className="relative flex h-[84px] w-[84px] items-center justify-center rounded-[24px] border border-sky-100 bg-sky-50/90 shadow-sm">
            <ClipboardList className="h-10 w-10" aria-hidden="true" />
          </div>
        </div>
        <div className="min-w-0">
          <div className="inline-flex rounded-full border border-sky-100 bg-sky-50 px-2.5 py-1 text-[11px] font-medium text-sky-700">
            运行后会自动填充
          </div>
          <h3 className="mt-3 text-[22px] font-semibold tracking-[-0.03em] text-foreground">
            {emptyTitle}
          </h3>
          <p className="mt-2 max-w-[520px] text-[12px] leading-5 text-muted-foreground">
            {emptyDescription}
          </p>
        </div>
      </div>

      <div className="rounded-[18px] border border-border/70 bg-card/86 p-3 shadow-[inset_0_1px_0_hsl(var(--background)/0.86)]">
        <div className="flex items-center justify-between gap-3 px-1 pb-2">
          <div>
            <div className="text-[12px] font-semibold text-foreground">
              结果工作台
            </div>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              一次评测完成后，关键证据会按下面三个区域落位。
            </p>
          </div>
          <div className="hidden rounded-full border border-border/70 bg-background px-2.5 py-1 text-[10.5px] font-medium text-muted-foreground sm:block">
            KG Eval
          </div>
        </div>

        <div className="grid gap-2.5">
          {resultPreviewItems.map((item) => (
            <div
              key={item.title}
              className="flex items-start gap-3 rounded-[14px] border border-border/60 bg-background/82 px-3.5 py-3"
            >
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[12px] border border-sky-100 bg-sky-50 text-sky-600">
                {item.icon}
              </div>
              <div className="min-w-0">
                <div className="text-[12px] font-semibold text-foreground">
                  {item.title}
                </div>
                <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">
                  {item.description}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function DiagnosticsFailuresPanel({
  failedCases,
  activeTab,
  onTabChange,
}: Readonly<{
  failedCases: Array<{
    case_id: string
    question: string
    recall: number
    mrr: number
  }>
  activeTab: 'failures' | 'distribution'
  onTabChange: (value: 'failures' | 'distribution') => void
}>) {
  return (
    <div className="rounded-xl border border-border/70 bg-background shadow-sm">
      <div className="border-b border-border/70 px-5 py-3">
        <div className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
          <span>失败样本 / 错误分析</span>
          <DiagnosticsInfoTooltip label="查看失败样本与错误分析说明">
            展示本轮未命中的评测样本，以及后续错误分布汇总；优先排查这些样本通常最有效。
          </DiagnosticsInfoTooltip>
        </div>
        <div className="mt-2.5 flex items-center gap-5">
          <button
            type="button"
            className={cn(
              'border-b-2 pb-2 text-[13px] font-medium transition-colors',
              activeTab === 'failures'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground'
            )}
            onClick={() => onTabChange('failures')}
          >
            失败样本
          </button>
          <button
            type="button"
            className={cn(
              'border-b-2 pb-2 text-[13px] font-medium transition-colors',
              activeTab === 'distribution'
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground'
            )}
            onClick={() => onTabChange('distribution')}
          >
            错误分布
          </button>
        </div>
      </div>

      <div className="px-5 py-3.5">
        {activeTab === 'failures' ? (
          failedCases.length ? (
            <div className="space-y-2">
              {failedCases.map((item) => (
                <div
                  key={`${item.case_id}:${item.question}`}
                  className="rounded-xl border border-border/70 bg-card/90 px-3.5 py-3"
                >
                  <div className="text-[11px] font-mono text-muted-foreground">
                    {item.case_id || '--------'}
                  </div>
                  <div className="mt-1.5 text-[13px] leading-6 text-foreground">
                    {item.question || '（无问题文本）'}
                  </div>
                  <div className="mt-2 text-[11px] tabular-nums text-muted-foreground">
                    Recall {String(item.recall)} · MRR {String(item.mrr)}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <DiagnosticsEmptyState
              title="暂无失败样本"
              description="运行评测后，这里会显示失败样本详情，帮助你定位问题。"
              icon={<CircleAlert className="h-8 w-8" aria-hidden="true" />}
            />
          )
        ) : (
          <DiagnosticsEmptyState
            title="暂无错误分布"
            description="执行评测后，这里会汇总常见错误类型和分布情况。"
            icon={<Waypoints className="h-8 w-8" aria-hidden="true" />}
          />
        )}
      </div>
    </div>
  )
}

function DiagnosticsRunRecordsPanel({
  runs,
  runRespJson,
}: Readonly<{
  runs: any[]
  runRespJson: string
}>) {
  return (
    <div className="rounded-xl border border-border/70 bg-background shadow-sm">
      <div className="border-b border-border/70 px-5 py-3">
        <div className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
          <span>原始结果 / 运行记录</span>
          <DiagnosticsInfoTooltip label="查看原始结果与运行记录说明">
            显示最近保存的评测运行记录，并可展开查看本次评测接口返回的原始数据。
          </DiagnosticsInfoTooltip>
        </div>
      </div>

      <div className="px-5 py-3">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-[12px]">
            <thead className="text-muted-foreground">
              <tr className="border-b border-border/70">
                <th className="px-2 py-2 font-medium">运行 ID</th>
                <th className="px-2 py-2 font-medium">开始时间</th>
                <th className="px-2 py-2 font-medium">数据集</th>
                <th className="px-2 py-2 font-medium">样本数</th>
                <th className="px-2 py-2 font-medium">TOP-K</th>
                <th className="px-2 py-2 font-medium">
                  主要指标（MRR / Recall）
                </th>
                <th className="px-2 py-2 font-medium">状态</th>
                <th className="px-2 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {runs.length ? (
                runs.slice(0, 8).map((run) => {
                  const summary =
                    run?.summary && typeof run.summary === 'object'
                      ? run.summary
                      : {}
                  return (
                    <tr
                      key={String(run.id)}
                      className="border-b border-border/60"
                    >
                      <td className="px-2 py-3 font-mono text-foreground">
                        {String(run.id || '').slice(0, 8)}
                      </td>
                      <td className="px-2 py-3 text-muted-foreground">
                        {String(run.created_at || '').slice(0, 16) || '-'}
                      </td>
                      <td className="px-2 py-3 text-muted-foreground">
                        {String(run.dataset_id || '').slice(0, 8) || '-'}
                      </td>
                      <td className="px-2 py-3 text-muted-foreground">
                        {String(run.max_cases ?? '-')}
                      </td>
                      <td className="px-2 py-3 text-muted-foreground">
                        {String(run.k ?? '-')}
                      </td>
                      <td className="px-2 py-3 text-muted-foreground">
                        {String(summary?.baseline_mrr ?? '-')} /{' '}
                        {String(summary?.baseline_recall ?? '-')}
                      </td>
                      <td className="px-2 py-3 text-muted-foreground">
                        {run.persisted ? '已保存' : '临时'}
                      </td>
                      <td className="px-2 py-3 text-muted-foreground">-</td>
                    </tr>
                  )
                })
              ) : (
                <tr>
                  <td colSpan={8} className="py-10">
                    <DiagnosticsEmptyState
                      title="暂无运行记录"
                      description="保存评测结果后，这里会列出历史运行记录，便于对比效果变化。"
                      icon={
                        <FileStack className="h-8 w-8" aria-hidden="true" />
                      }
                    />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <details className="mt-3 rounded-xl border border-border/70 bg-card/90 px-4 py-3">
          <summary className="cursor-pointer select-none text-[12px] font-medium text-muted-foreground transition-colors hover:text-foreground">
            查看原始数据
          </summary>
          <Textarea
            value={runRespJson}
            readOnly
            rows={12}
            className="mt-3 resize-none border-border/70 bg-background font-mono text-xs"
          />
        </details>
      </div>
    </div>
  )
}

function DiagnosticsJsonPanel({
  label,
  value,
  rows = 14,
}: Readonly<{
  label: string
  value: string
  rows?: number
}>) {
  return (
    <div className="rounded-lg border border-border/70 bg-card">
      <div className="border-b border-border/70 px-4 py-3">
        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {label}
        </div>
      </div>
      <details className="px-4 py-3">
        <summary className="cursor-pointer select-none text-xs font-medium text-muted-foreground transition-colors hover:text-foreground">
          展开原始数据
        </summary>
        <Textarea
          value={value}
          readOnly
          rows={rows}
          className="mt-3 resize-none border-border/70 bg-background font-mono text-xs"
        />
      </details>
    </div>
  )
}

export function KGDiagnosticsPage() {
  const t = useTranslations('KGDiagnosticsPage')
  const [datasetId, setDatasetId] = useState('')
  const [activeView, setActiveView] = useState<DiagnosticsView>('run')
  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.list(KG_DIAGNOSTICS_DATASET_LIST_PARAMS),
    queryFn: () => datasetApi.list(KG_DIAGNOSTICS_DATASET_LIST_PARAMS),
    staleTime: 30_000,
  })
  const datasets = useMemo<DiagnosticsDatasetOption[]>(() => {
    const items = datasetsQuery.data?.items
    return Array.isArray(items) ? items : []
  }, [datasetsQuery.data])
  const datasetsLoading = datasetsQuery.isLoading || datasetsQuery.isFetching

  const [qualityDocLimit, setQualityDocLimit] = useState(200)
  const [qualityPipelineHash, setQualityPipelineHash] = useState('')
  const [qualityLoading, setQualityLoading] = useState(false)
  const [qualityReport, setQualityReport] = useState<any | null>(null)
  const qualityJson = useMemo(
    () => prettyJson(qualityReport ?? { hint: t('qualityReport.hint') }),
    [qualityReport, t]
  )

  const [maxCases, setMaxCases] = useState(50)
  const [k, setK] = useState(10)
  const [autoExtractKg, setAutoExtractKg] = useState(true)
  const [extractSkills, setExtractSkills] = useState<'auto' | 'on' | 'off'>(
    'auto'
  )
  const [extractRelations, setExtractRelations] = useState<
    'auto' | 'on' | 'off'
  >('auto')
  const [hardcaseMode, setHardcaseMode] =
    useState<KGHardcaseMode>('deterministic')
  const [hardcasesPerFailed, setHardcasesPerFailed] = useState(4)
  const [maxFailedForHardcase, setMaxFailedForHardcase] = useState(20)
  const [llmTemperature, setLlmTemperature] = useState(0.2)
  const [persistRun, setPersistRun] = useState(true)
  const [runAnalysisTab, setRunAnalysisTab] = useState<
    'failures' | 'distribution'
  >('failures')

  const [running, setRunning] = useState(false)
  const [runResp, setRunResp] = useState<KGSearchDiagnosticsResponse | null>(
    null
  )
  const runRespJson = useMemo(
    () => prettyJson(runResp ?? { hint: t('summary.runHint') }),
    [runResp, t]
  )

  const [runsLoading, setRunsLoading] = useState(false)
  const [runs, setRuns] = useState<any[]>([])
  const [selectedRunA, setSelectedRunA] = useState<string>('')
  const [selectedRunB, setSelectedRunB] = useState<string>('')
  const [detailA, setDetailA] = useState<KGSearchDiagnosticsRunDetail | null>(
    null
  )
  const [detailB, setDetailB] = useState<KGSearchDiagnosticsRunDetail | null>(
    null
  )

  useEffect(() => {
    if (!datasets.length) return
    setDatasetId((current) => {
      if (current.trim()) return current
      const firstDatasetId = String(datasets[0]?.id || '').trim()
      return firstDatasetId || current
    })
  }, [datasets])

  const diff = useMemo(() => {
    if (!detailA?.run || !detailB?.run) return null
    const a = detailA
    const b = detailB

    const aSummary =
      a.run?.summary && typeof a.run.summary === 'object' ? a.run.summary : {}
    const bSummary =
      b.run?.summary && typeof b.run.summary === 'object' ? b.run.summary : {}

    const keys = [
      'baseline_hit_rate',
      'baseline_mrr',
      'baseline_recall',
      'baseline_ndcg',
      'baseline_map',
      'hardcase_hit_rate',
      'hardcase_mrr',
      'hardcase_recall',
      'hardcase_ndcg',
      'hardcase_map',
    ]
    const summaryDelta: Record<string, any> = {}
    for (const key of keys) {
      const av = toNumber(aSummary[key])
      const bv = toNumber(bSummary[key])
      if (av === null && bv === null) continue
      summaryDelta[key] = {
        a: av,
        b: bv,
        delta: av !== null && bv !== null ? Number((bv - av).toFixed(4)) : null,
      }
    }

    const byCaseA = new Map<
      string,
      { question: string; metrics: ReturnType<typeof extractBaselineMetrics> }
    >()
    for (const item of a.items || []) {
      const key = caseKey(item)
      if (!key) continue
      byCaseA.set(key, {
        question: String(item?.question || ''),
        metrics: extractBaselineMetrics(item),
      })
    }

    const byCaseB = new Map<
      string,
      { question: string; metrics: ReturnType<typeof extractBaselineMetrics> }
    >()
    for (const item of b.items || []) {
      const key = caseKey(item)
      if (!key) continue
      byCaseB.set(key, {
        question: String(item?.question || ''),
        metrics: extractBaselineMetrics(item),
      })
    }

    const allKeys = new Set<string>([
      ...Array.from(byCaseA.keys()),
      ...Array.from(byCaseB.keys()),
    ])
    const rows: Array<{
      case_id: string
      question: string
      a_hit: boolean | null
      b_hit: boolean | null
      a_mrr: number | null
      b_mrr: number | null
      a_recall: number | null
      b_recall: number | null
      delta_recall: number | null
      delta_mrr: number | null
    }> = []

    for (const key of allKeys) {
      const ra = byCaseA.get(key)
      const rb = byCaseB.get(key)
      const qa = ra?.question || ''
      const qb = rb?.question || ''
      const question = qa || qb
      const ma = ra?.metrics
      const mb = rb?.metrics
      const a_hit = ma ? Boolean(ma.hit_at_k) : null
      const b_hit = mb ? Boolean(mb.hit_at_k) : null
      const a_mrr = ma ? ma.mrr : null
      const b_mrr = mb ? mb.mrr : null
      const a_recall = ma ? ma.recall : null
      const b_recall = mb ? mb.recall : null
      rows.push({
        case_id: key,
        question,
        a_hit,
        b_hit,
        a_mrr,
        b_mrr,
        a_recall,
        b_recall,
        delta_recall:
          a_recall !== null && b_recall !== null
            ? Number((b_recall - a_recall).toFixed(4))
            : null,
        delta_mrr:
          a_mrr !== null && b_mrr !== null
            ? Number((b_mrr - a_mrr).toFixed(4))
            : null,
      })
    }

    const changed = rows
      .filter(
        (r) =>
          r.delta_recall !== null ||
          r.delta_mrr !== null ||
          (r.a_hit !== null && r.b_hit !== null && r.a_hit !== r.b_hit)
      )
      .sort(
        (x, y) => Math.abs(y.delta_recall ?? 0) - Math.abs(x.delta_recall ?? 0)
      )
      .slice(0, 20)

    const flips = rows.filter(
      (r) => r.a_hit !== null && r.b_hit !== null && r.a_hit !== r.b_hit
    )
    const improved = flips.filter(
      (r) => r.a_hit === false && r.b_hit === true
    ).length
    const regressed = flips.filter(
      (r) => r.a_hit === true && r.b_hit === false
    ).length

    return {
      run_a: a.run,
      run_b: b.run,
      summary_delta: summaryDelta,
      changed_cases: changed,
      hit_flips: { total: flips.length, improved, regressed },
    }
  }, [detailA, detailB])

  const diffJson = useMemo(
    () => prettyJson(diff ?? { hint: t('compare.diffHint') }),
    [diff, t]
  )

  async function refreshRuns(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error(t('toasts.datasetRequired'))
      return
    }
    setRunsLoading(true)
    try {
      const res = await evaluationApi.listKgSearchDiagnosticsRuns({
        dataset_id: ds,
        limit: 50,
      })
      const items = Array.isArray(res.items) ? res.items : []
      setRuns(items)
      if (!selectedRunA && items?.[0]?.id) setSelectedRunA(items[0].id)
      if (!selectedRunB && items?.[1]?.id) setSelectedRunB(items[1].id)
      if (!selectedRunB && !items?.[1]?.id && items?.[0]?.id)
        setSelectedRunB(items[0].id)
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.runsLoadFailed')))
    } finally {
      setRunsLoading(false)
    }
  }

  async function loadRun(which: 'a' | 'b', runId: string): Promise<void> {
    const id = String(runId || '').trim()
    if (!id) return
    try {
      const detail = await evaluationApi.getKgSearchDiagnosticsRun(id)
      if (which === 'a') setDetailA(detail)
      else setDetailB(detail)
    } catch (err) {
      toast.error(
        formatApiError(err, t('toasts.runLoadFailed', { id: id.slice(0, 8) }))
      )
    }
  }

  async function loadQualityReport(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error(t('toasts.datasetRequired'))
      return
    }
    setQualityLoading(true)
    try {
      const resp = await evaluationApi.getKgQualityReport({
        dataset_id: ds,
        document_limit: Math.max(1, Math.min(qualityDocLimit, 2000)),
        pipeline_hash: qualityPipelineHash.trim() || undefined,
      })
      setQualityReport(resp ?? null)
      setActiveView('quality')
      toast.success(t('toasts.qualityReportLoaded'))
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.qualityReportLoadFailed')))
    } finally {
      setQualityLoading(false)
    }
  }

  async function runDiagnostics(): Promise<void> {
    const ds = datasetId.trim()
    if (!ds) {
      toast.error(t('toasts.datasetRequired'))
      return
    }
    setRunning(true)
    setRunResp(null)
    try {
      const resp = await evaluationApi.runKgSearchDiagnostics({
        dataset_id: ds,
        max_cases: Math.max(1, Math.min(maxCases, 200)),
        k: Math.max(1, Math.min(k, 50)),
        auto_extract_kg: Boolean(autoExtractKg),
        extract_skills:
          extractSkills === 'auto' ? null : extractSkills === 'on',
        extract_relations:
          extractRelations === 'auto' ? null : extractRelations === 'on',
        hardcase_mode: hardcaseMode,
        hardcases_per_failed_case: Math.max(
          0,
          Math.min(hardcasesPerFailed, 20)
        ),
        max_failed_cases_for_hardcase: Math.max(
          0,
          Math.min(maxFailedForHardcase, 200)
        ),
        llm_temperature: Math.max(0, Math.min(llmTemperature, 2)),
        persist_run: Boolean(persistRun),
      })
      setRunResp(resp || null)
      setActiveView('run')
      toast.success(t('toasts.diagnosticsRan'))
      if (persistRun) {
        await refreshRuns()
      }
    } catch (err) {
      toast.error(formatApiError(err, t('toasts.diagnosticsRunFailed')))
    } finally {
      setRunning(false)
    }
  }

  const summary =
    runResp?.summary && typeof runResp.summary === 'object'
      ? runResp.summary
      : null
  const runItems = useMemo(
    () => (Array.isArray(runResp?.items) ? runResp.items : []),
    [runResp?.items]
  )
  const runIdShort = String(runResp?.run_id || '').slice(0, 8)
  const selectedDataset = useMemo(() => {
    const selectedId = datasetId.trim()
    return (
      datasets.find(
        (dataset) => String(dataset.id || '').trim() === selectedId
      ) ?? null
    )
  }, [datasetId, datasets])
  const datasetLabel = selectedDataset?.name || datasetId.trim() || '未选择'
  const qualityObject =
    qualityReport && typeof qualityReport === 'object'
      ? (qualityReport as Record<string, unknown>)
      : null
  const qualityHighlights = useMemo(() => {
    if (!qualityObject) return []
    return Object.entries(qualityObject)
      .filter(([, value]) =>
        ['string', 'number', 'boolean'].includes(typeof value)
      )
      .slice(0, 8)
  }, [qualityObject])
  const failedCases = useMemo(() => {
    return runItems
      .map((item) => {
        const metrics = extractBaselineMetrics(item)
        if (!metrics || metrics.hit_at_k) return null
        return {
          case_id: String(item?.case_id || '').slice(0, 8),
          question: String(item?.question || '').trim(),
          recall: metrics.recall,
          mrr: metrics.mrr,
        }
      })
      .filter(Boolean)
      .slice(0, 12) as Array<{
      case_id: string
      question: string
      recall: number
      mrr: number
    }>
  }, [runItems])
  const diffSummaryEntries = useMemo(
    () => Object.entries(diff?.summary_delta || {}),
    [diff]
  )

  const viewDescription =
    activeView === 'run'
      ? t('workspace.runIntro')
      : activeView === 'quality'
        ? t('workspace.qualityIntro')
        : t('workspace.compareIntro')

  function handleDatasetChange(nextDatasetId: string): void {
    setDatasetId(nextDatasetId)
    setRunResp(null)
    setQualityReport(null)
    setQualityPipelineHash('')
    setRuns([])
    setSelectedRunA('')
    setSelectedRunB('')
    setDetailA(null)
    setDetailB(null)
    setActiveView('run')
  }

  return (
    <AppFrame showBackground={false}>
      <div className="h-full bg-[linear-gradient(180deg,#f8fbff_0%,#ffffff_32%)] p-2">
        <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[18px] border border-border/70 bg-background/95 shadow-sm">
          <header className="shrink-0 border-b border-border/70 px-6 py-5">
            <PageHeader
              title={t('page.title')}
              description={t('page.description')}
              iconImage="kg-retrieval-evaluation"
              icon={ClipboardList}
              iconColor="text-info"
              badge="KG"
              compact
              className="p-0"
            >
              <div className="flex flex-wrap items-center gap-2.5">
                <DiagnosticsHeaderPill
                  label={t('runConfig.datasetId')}
                  className="min-w-[220px]"
                >
                  <Select
                    value={datasetId}
                    onValueChange={handleDatasetChange}
                    disabled={datasetsLoading || !datasets.length}
                  >
                    <SelectTrigger
                      aria-label={t('runConfig.datasetId')}
                      className="h-auto min-h-0 border-0 bg-transparent px-0 py-0 text-right text-[13px] font-medium shadow-none focus-visible:ring-2 focus-visible:ring-ring/30 [&>svg]:ml-2 [&>svg]:h-3.5 [&>svg]:w-3.5"
                    >
                      <SelectValue
                        placeholder={
                          datasetsLoading
                            ? '加载中...'
                            : t('runConfig.datasetPlaceholder')
                        }
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {datasets.map((dataset) => {
                        const id = String(dataset.id || '').trim()
                        if (!id) return null
                        return (
                          <SelectItem key={id} value={id}>
                            {dataset.name || id}
                          </SelectItem>
                        )
                      })}
                    </SelectContent>
                  </Select>
                </DiagnosticsHeaderPill>
                <DiagnosticsHeaderPill
                  label={t('runConfig.k')}
                  className="min-w-[112px]"
                >
                  <Input
                    type="number"
                    value={String(k)}
                    onChange={(e) => setK(Number(e.target.value || 0))}
                    min={1}
                    max={50}
                    className="h-auto border-0 bg-transparent px-0 py-0 text-right text-[13px] font-medium shadow-none focus-visible:ring-2 focus-visible:ring-ring/30"
                  />
                </DiagnosticsHeaderPill>
                <Button
                  variant="outline"
                  className="h-9 rounded-lg border-border/70 bg-card/95 px-3.5 text-[13px] shadow-sm"
                  onClick={() => {
                    setActiveView('compare')
                    if (datasetId.trim()) void refreshRuns()
                  }}
                >
                  <History className="mr-2 h-4 w-4" aria-hidden="true" />
                  {t('runs.title')}
                </Button>
              </div>
            </PageHeader>
          </header>

          <div className="min-h-0 flex-1 overflow-hidden px-5 pb-4 pt-4">
            <div className="grid h-full min-h-0 gap-4 xl:grid-cols-[356px_minmax(0,1fr)]">
              <aside className="min-h-0 rounded-xl border border-border/70 bg-background shadow-sm">
                <div className="flex h-full min-h-0 flex-col">
                  <div className="min-h-0 flex-1 overflow-y-auto p-3">
                    <div className="space-y-2.5">
                      <DiagnosticsSection
                        label={t('runConfig.title')}
                        className="rounded-xl px-3.5 py-2.5"
                      >
                        <div className="space-y-2.5">
                          <div className="space-y-1">
                            <div
                              className={cn(
                                'flex items-center gap-1',
                                DIAGNOSTICS_FIELD_LABEL_CLASS
                              )}
                            >
                              <span>阈值设置</span>
                              <DiagnosticsInfoTooltip label="查看阈值设置说明">
                                控制本轮最多抽取多少条评测样本。数值越大覆盖越充分，但评测耗时也会更长。
                              </DiagnosticsInfoTooltip>
                            </div>
                            <DiagnosticsStepper
                              value={maxCases}
                              min={1}
                              max={200}
                              onChange={setMaxCases}
                            />
                          </div>

                          <div className="space-y-1">
                            <Label className={DIAGNOSTICS_FIELD_LABEL_CLASS}>
                              {t('runConfig.llmTemperature')}
                            </Label>
                            <Select
                              value={String(llmTemperature)}
                              onValueChange={(value) =>
                                setLlmTemperature(Number(value))
                              }
                            >
                              <SelectTrigger
                                className={cn(
                                  'h-9 rounded-lg border-border/70 bg-card/95 shadow-none',
                                  DIAGNOSTICS_FIELD_VALUE_CLASS
                                )}
                              >
                                <SelectValue placeholder="0.2" />
                              </SelectTrigger>
                              <SelectContent>
                                {[
                                  '0',
                                  '0.1',
                                  '0.2',
                                  '0.3',
                                  '0.5',
                                  '0.7',
                                  '1.0',
                                ].map((value) => (
                                  <SelectItem key={value} value={value}>
                                    {value}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>

                          <div className="space-y-1">
                            <Label
                              title={t('runConfig.extractSkills')}
                              className={DIAGNOSTICS_FIELD_LABEL_CLASS}
                            >
                              智能裁度
                            </Label>
                            <Select
                              value={extractSkills}
                              onValueChange={(value) =>
                                setExtractSkills(
                                  coerceOneOf(
                                    KG_EXTRACT_MODE_VALUES,
                                    value,
                                    'auto'
                                  )
                                )
                              }
                            >
                              <SelectTrigger
                                className={cn(
                                  'h-9 rounded-lg border-border/70 bg-card/95 shadow-none',
                                  DIAGNOSTICS_FIELD_VALUE_CLASS
                                )}
                              >
                                <SelectValue
                                  placeholder={t(
                                    'runConfig.extractModePlaceholder'
                                  )}
                                />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="auto">自动</SelectItem>
                                <SelectItem value="on">开启</SelectItem>
                                <SelectItem value="off">关闭</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>

                          <div className="space-y-1">
                            <Label
                              title={t('runConfig.extractRelations')}
                              className={DIAGNOSTICS_FIELD_LABEL_CLASS}
                            >
                              基线模式
                            </Label>
                            <Select
                              value={extractRelations}
                              onValueChange={(value) =>
                                setExtractRelations(
                                  coerceOneOf(
                                    KG_EXTRACT_MODE_VALUES,
                                    value,
                                    'auto'
                                  )
                                )
                              }
                            >
                              <SelectTrigger
                                className={cn(
                                  'h-9 rounded-lg border-border/70 bg-card/95 shadow-none',
                                  DIAGNOSTICS_FIELD_VALUE_CLASS
                                )}
                              >
                                <SelectValue
                                  placeholder={t(
                                    'runConfig.extractModePlaceholder'
                                  )}
                                />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="auto">自动</SelectItem>
                                <SelectItem value="on">开启</SelectItem>
                                <SelectItem value="off">关闭</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>

                          <details className="rounded-lg border border-dashed border-border/60 bg-card/45 px-3 py-1.5">
                            <summary className="cursor-pointer select-none text-[11.5px] font-normal leading-5 text-muted-foreground">
                              高级参数
                            </summary>
                            <div className="mt-3 space-y-3">
                              <div className="space-y-1">
                                <Label
                                  className={DIAGNOSTICS_FIELD_LABEL_CLASS}
                                >
                                  {t('runConfig.hardcaseMode')}
                                </Label>
                                <Select
                                  value={hardcaseMode}
                                  onValueChange={(v) =>
                                    setHardcaseMode(v as KGHardcaseMode)
                                  }
                                >
                                  <SelectTrigger
                                    className={cn(
                                      'h-9 rounded-lg border-border/70 bg-background shadow-none',
                                      DIAGNOSTICS_FIELD_VALUE_CLASS
                                    )}
                                  >
                                    <SelectValue
                                      placeholder={t(
                                        'runConfig.hardcaseModePlaceholder'
                                      )}
                                    />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="off">关闭</SelectItem>
                                    <SelectItem value="deterministic">
                                      规则生成
                                    </SelectItem>
                                    <SelectItem value="llm">
                                      LLM 生成
                                    </SelectItem>
                                  </SelectContent>
                                </Select>
                              </div>
                              <div className="grid gap-3 md:grid-cols-2">
                                <div className="space-y-1">
                                  <Label
                                    className={DIAGNOSTICS_FIELD_LABEL_CLASS}
                                  >
                                    {t('runConfig.hardcasesPerFailedCase')}
                                  </Label>
                                  <Input
                                    type="number"
                                    value={String(hardcasesPerFailed)}
                                    onChange={(e) =>
                                      setHardcasesPerFailed(
                                        Number(e.target.value || 0)
                                      )
                                    }
                                    min={0}
                                    max={20}
                                    className={cn(
                                      'h-9 rounded-lg border-border/70 bg-background shadow-none',
                                      DIAGNOSTICS_FIELD_VALUE_CLASS
                                    )}
                                  />
                                </div>
                                <div className="space-y-1">
                                  <Label
                                    className={DIAGNOSTICS_FIELD_LABEL_CLASS}
                                  >
                                    {t('runConfig.maxFailedCasesForHardcase')}
                                  </Label>
                                  <Input
                                    type="number"
                                    value={String(maxFailedForHardcase)}
                                    onChange={(e) =>
                                      setMaxFailedForHardcase(
                                        Number(e.target.value || 0)
                                      )
                                    }
                                    min={0}
                                    max={200}
                                    className={cn(
                                      'h-9 rounded-lg border-border/70 bg-background shadow-none',
                                      DIAGNOSTICS_FIELD_VALUE_CLASS
                                    )}
                                  />
                                </div>
                              </div>
                            </div>
                          </details>
                        </div>
                      </DiagnosticsSection>

                      <DiagnosticsSection
                        label={t('workspace.extractionOptions')}
                        description={t('workspace.extractionHint')}
                        className="rounded-xl px-3.5 py-2.5"
                      >
                        <div className="space-y-2">
                          <DiagnosticsToggleCard
                            title={t('runConfig.autoExtractKg')}
                            description={t('workspace.autoExtractHint')}
                            badge={t('workspace.autoExtractBadge')}
                            checked={autoExtractKg}
                            onCheckedChange={setAutoExtractKg}
                            tone="sky"
                            stateLabel={
                              autoExtractKg
                                ? t('workspace.enabled')
                                : t('workspace.disabled')
                            }
                          />
                          <DiagnosticsToggleCard
                            title={t('runConfig.persistRun')}
                            description={t('runs.hint')}
                            badge={t('workspace.persistRunBadge')}
                            checked={persistRun}
                            onCheckedChange={setPersistRun}
                            tone="emerald"
                            stateLabel={
                              persistRun
                                ? t('workspace.enabled')
                                : t('workspace.disabled')
                            }
                          />
                        </div>
                      </DiagnosticsSection>
                    </div>
                  </div>

                  <div className="shrink-0 border-t border-border/70 px-4 py-3.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <DiagnosticsInlineStat label="样本" value={maxCases} />
                      <DiagnosticsInlineStat label="TOP-K" value={k} />
                      <DiagnosticsInlineStat
                        label="保存"
                        value={persistRun ? '开启' : '关闭'}
                        tone={persistRun ? 'neutral' : 'muted'}
                      />
                    </div>

                    <Button
                      className="mt-2 h-9 w-full rounded-lg text-[13px] font-medium shadow-none"
                      onClick={runDiagnostics}
                      disabled={running}
                    >
                      <PlayCircle className="mr-2 h-4 w-4" aria-hidden="true" />
                      {running
                        ? `${t('page.actions.run')}…`
                        : t('page.actions.run')}
                    </Button>

                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <Button
                        variant="outline"
                        className="h-8 rounded-lg border-border/70 bg-card/95 text-[11.5px]"
                        onClick={refreshRuns}
                        disabled={runsLoading}
                      >
                        <RefreshCcw
                          className="mr-1.5 h-4 w-4"
                          aria-hidden="true"
                        />
                        {t('page.actions.refreshRuns')}
                      </Button>
                      <Button
                        variant="outline"
                        className="h-8 rounded-lg border-border/70 bg-card/95 text-[11.5px]"
                        onClick={() => {
                          const base = sanitizeFilename(
                            `kg_diagnostics_${datasetId.trim() || 'dataset'}`
                          )
                          downloadJson(runResp ?? {}, `${base}.json`)
                          toast.success(t('toasts.runExported'))
                        }}
                        disabled={!runResp}
                      >
                        <Download
                          className="mr-1.5 h-4 w-4"
                          aria-hidden="true"
                        />
                        {t('page.actions.exportRun')}
                      </Button>
                    </div>

                    <p className="mt-2 text-[10.5px] leading-5 text-muted-foreground">
                      {t('summary.runHint')}
                    </p>
                  </div>
                </div>
              </aside>

              <section className="min-w-0 min-h-0 rounded-xl border border-border/70 bg-background shadow-sm">
                <Tabs
                  value={activeView}
                  onValueChange={(value) =>
                    setActiveView(value as DiagnosticsView)
                  }
                  className="flex h-full min-h-0 flex-col"
                >
                  <div className="shrink-0 border-b border-border/70 px-5 pt-4">
                    <TabsList className="h-auto justify-start gap-7 rounded-none border-none bg-transparent p-0">
                      <TabsTrigger
                        value="run"
                        className="rounded-none border-b-2 border-transparent px-0 pb-3 pt-0 text-[13px] font-medium text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=active]:text-foreground data-[state=active]:shadow-none"
                      >
                        {t('summary.title')}
                      </TabsTrigger>
                      <TabsTrigger
                        value="quality"
                        title={t('qualityReport.title')}
                        className="rounded-none border-b-2 border-transparent px-0 pb-3 pt-0 text-[13px] font-medium text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=active]:text-foreground data-[state=active]:shadow-none"
                      >
                        抽取数据
                      </TabsTrigger>
                      <TabsTrigger
                        value="compare"
                        className="rounded-none border-b-2 border-transparent px-0 pb-3 pt-0 text-[13px] font-medium text-muted-foreground data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:font-semibold data-[state=active]:text-foreground data-[state=active]:shadow-none"
                      >
                        {t('compare.title')}
                      </TabsTrigger>
                    </TabsList>

                    <div className="flex flex-wrap items-center gap-3 py-4">
                      <DiagnosticsHeaderPill
                        label={t('runConfig.datasetId')}
                        value={datasetLabel}
                        className="min-w-[148px]"
                      />
                      <DiagnosticsHeaderPill
                        label={t('runConfig.maxCases')}
                        value={maxCases}
                        className="min-w-[132px]"
                      />
                      <DiagnosticsHeaderPill
                        label={t('runConfig.k')}
                        value={k}
                        className="min-w-[112px]"
                      />
                    </div>
                  </div>

                  <TabsContent
                    value="run"
                    className="mt-0 min-h-0 flex-1 overflow-auto px-5 py-3.5"
                  >
                    <div className="space-y-3.5">
                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
                        <DiagnosticsMetricTile
                          label={t('summary.baselineHitRate')}
                          value={formatMetricValue(summary?.baseline_hit_rate)}
                          caption="整体是否命中参考基础指标"
                          accent="sky"
                          icon={
                            <Target className="h-4 w-4" aria-hidden="true" />
                          }
                        />
                        <DiagnosticsMetricTile
                          label={t('summary.baselineMrr')}
                          value={formatMetricValue(summary?.baseline_mrr)}
                          caption="命中位置越靠前越好"
                          accent="violet"
                          icon={
                            <TrendingUp
                              className="h-4 w-4"
                              aria-hidden="true"
                            />
                          }
                        />
                        <DiagnosticsMetricTile
                          label={t('summary.baselineRecall')}
                          value={formatMetricValue(summary?.baseline_recall)}
                          caption="召回覆盖越高越好"
                          accent="emerald"
                          icon={
                            <RefreshCcw
                              className="h-4 w-4"
                              aria-hidden="true"
                            />
                          }
                        />
                        <DiagnosticsMetricTile
                          label={t('summary.baselineNdcg')}
                          value={formatMetricValue(summary?.baseline_ndcg)}
                          caption="兼顾命中位置与排序质量"
                          accent="sky"
                          icon={
                            <Activity className="h-4 w-4" aria-hidden="true" />
                          }
                        />
                        <DiagnosticsMetricTile
                          label={t('summary.baselineMap')}
                          value={formatMetricValue(summary?.baseline_map)}
                          caption="多位置平均精度"
                          accent="violet"
                          icon={
                            <Waypoints className="h-4 w-4" aria-hidden="true" />
                          }
                        />
                        <DiagnosticsMetricTile
                          label={t('summary.hardcasesGenerated')}
                          value={formatMetricValue(
                            summary?.hardcases_generated
                          )}
                          caption="深挖样本生成的案例数量"
                          accent="amber"
                          icon={
                            <Sparkles className="h-4 w-4" aria-hidden="true" />
                          }
                        />
                      </div>

                      <DiagnosticsRunHeroPanel
                        summary={summary}
                        emptyTitle={t('summary.empty')}
                        emptyDescription={t('summary.runHint')}
                      />

                      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
                        <DiagnosticsFailuresPanel
                          failedCases={failedCases}
                          activeTab={runAnalysisTab}
                          onTabChange={setRunAnalysisTab}
                        />
                        <DiagnosticsRunRecordsPanel
                          runs={runs}
                          runRespJson={runRespJson}
                        />
                      </div>
                    </div>
                  </TabsContent>

                  <TabsContent value="quality" className="mt-0 min-h-0 flex-1">
                    <div className="flex h-full min-h-0 flex-col">
                      <div className="border-b border-border/70 px-4 py-4">
                        <div className="grid gap-3 xl:grid-cols-[180px_minmax(0,1fr)_auto]">
                          <div className="space-y-1.5">
                            <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                              {t('qualityReport.documentLimit')}
                            </Label>
                            <Input
                              type="number"
                              value={String(qualityDocLimit)}
                              onChange={(e) =>
                                setQualityDocLimit(Number(e.target.value || 0))
                              }
                              min={1}
                              max={2000}
                              className="h-10 rounded-lg border-border/70 bg-card text-sm shadow-none"
                            />
                          </div>
                          <div className="space-y-1.5">
                            <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                              {t('qualityReport.pipelineHash')}
                            </Label>
                            <Input
                              value={qualityPipelineHash}
                              onChange={(e) =>
                                setQualityPipelineHash(e.target.value)
                              }
                              placeholder={t(
                                'qualityReport.pipelineHashPlaceholder'
                              )}
                              className="h-10 rounded-lg border-border/70 bg-card font-mono text-xs shadow-none"
                            />
                          </div>
                          <div className="flex items-end">
                            <Button
                              variant="outline"
                              className="h-10 rounded-lg border-border/70 bg-card text-xs"
                              onClick={loadQualityReport}
                              disabled={qualityLoading}
                            >
                              <RefreshCcw
                                className="mr-1.5 h-4 w-4"
                                aria-hidden="true"
                              />
                              {t('qualityReport.pull')}
                            </Button>
                          </div>
                        </div>
                        <p className="mt-3 text-[11px] leading-5 text-muted-foreground">
                          {t('qualityReport.hint')}
                        </p>
                      </div>

                      <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
                        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
                          <div className="space-y-4">
                            {qualityObject ? (
                              <div className="rounded-lg border border-border/70 bg-card">
                                <div className="border-b border-border/70 px-4 py-3">
                                  <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                                    {t('workspace.qualityHighlightsTitle')}
                                  </div>
                                </div>
                                <div className="grid gap-3 px-4 py-4 md:grid-cols-2">
                                  <DiagnosticsMetricTile
                                    label={t('workspace.qualityKeyCount')}
                                    value={Object.keys(qualityObject).length}
                                    caption={t('workspace.qualityKeyCountHint')}
                                  />
                                  <DiagnosticsMetricTile
                                    label={t('qualityReport.documentLimit')}
                                    value={qualityDocLimit}
                                    caption={
                                      qualityPipelineHash.trim() ||
                                      t('workspace.currentPipelineLabel')
                                    }
                                  />
                                  {qualityHighlights.map(([key, value]) => (
                                    <DiagnosticsMetricTile
                                      key={key}
                                      label={formatDiagnosticsMetricLabel(key)}
                                      value={formatMetricValue(value)}
                                      tone="neutral"
                                    />
                                  ))}
                                </div>
                              </div>
                            ) : (
                              <DiagnosticsEmptyState
                                title={t('workspace.qualityEmptyTitle')}
                                description={t('qualityReport.hint')}
                              />
                            )}
                          </div>

                          <DiagnosticsJsonPanel
                            label={t('workspace.rawQualityJson')}
                            value={qualityJson}
                            rows={18}
                          />
                        </div>
                      </div>
                    </div>
                  </TabsContent>

                  <TabsContent value="compare" className="mt-0 min-h-0 flex-1">
                    <div className="flex h-full min-h-0 flex-col">
                      <div className="border-b border-border/70 px-4 py-4">
                        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
                          <div className="space-y-1.5">
                            <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                              {t('runs.runA')}
                            </Label>
                            <div className="flex gap-2">
                              <Select
                                value={selectedRunA}
                                onValueChange={(v) => setSelectedRunA(v)}
                              >
                                <SelectTrigger className="h-10 rounded-lg border-border/70 bg-card text-sm shadow-none">
                                  <SelectValue
                                    placeholder={t('runs.runAPlaceholder')}
                                  />
                                </SelectTrigger>
                                <SelectContent>
                                  {runs.map((r) => (
                                    <SelectItem key={r.id} value={r.id}>
                                      {String(r.created_at || '').slice(0, 19)}{' '}
                                      · {String(r.id).slice(0, 8)}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              <Button
                                variant="outline"
                                className="h-10 rounded-lg border-border/70 bg-card text-xs"
                                onClick={() => loadRun('a', selectedRunA)}
                                disabled={!selectedRunA}
                              >
                                {t('runs.loadA')}
                              </Button>
                            </div>
                          </div>

                          <div className="space-y-1.5">
                            <Label className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                              {t('runs.runB')}
                            </Label>
                            <div className="flex gap-2">
                              <Select
                                value={selectedRunB}
                                onValueChange={(v) => setSelectedRunB(v)}
                              >
                                <SelectTrigger className="h-10 rounded-lg border-border/70 bg-card text-sm shadow-none">
                                  <SelectValue
                                    placeholder={t('runs.runBPlaceholder')}
                                  />
                                </SelectTrigger>
                                <SelectContent>
                                  {runs.map((r) => (
                                    <SelectItem key={r.id} value={r.id}>
                                      {String(r.created_at || '').slice(0, 19)}{' '}
                                      · {String(r.id).slice(0, 8)}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              <Button
                                variant="outline"
                                className="h-10 rounded-lg border-border/70 bg-card text-xs"
                                onClick={() => loadRun('b', selectedRunB)}
                                disabled={!selectedRunB}
                              >
                                {t('runs.loadB')}
                              </Button>
                            </div>
                          </div>

                          <div className="flex items-end">
                            <Button
                              variant="outline"
                              className="h-10 rounded-lg border-border/70 bg-card text-xs"
                              onClick={refreshRuns}
                              disabled={runsLoading}
                            >
                              <RefreshCcw
                                className="mr-1.5 h-4 w-4"
                                aria-hidden="true"
                              />
                              {t('runs.refresh')}
                            </Button>
                          </div>

                          <div className="flex items-end">
                            <Button
                              variant="outline"
                              className="h-10 rounded-lg border-border/70 bg-card text-xs"
                              onClick={() => {
                                const a =
                                  String(detailA?.run?.id || '').slice(0, 8) ||
                                  'A'
                                const b =
                                  String(detailB?.run?.id || '').slice(0, 8) ||
                                  'B'
                                downloadJson(
                                  diff ?? {},
                                  `${sanitizeFilename(`kg_diagnostics_diff_${a}_vs_${b}`)}.json`
                                )
                                toast.success(t('compare.exported'))
                              }}
                              disabled={!diff}
                            >
                              <Download
                                className="mr-1.5 h-4 w-4"
                                aria-hidden="true"
                              />
                              {t('compare.export')}
                            </Button>
                          </div>
                        </div>

                        <p className="mt-3 text-[11px] leading-5 text-muted-foreground">
                          {t('runs.hint')}
                        </p>
                      </div>

                      <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
                        {diff ? (
                          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_420px]">
                            <div className="space-y-4">
                              <div className="grid gap-3 md:grid-cols-4">
                                <DiagnosticsMetricTile
                                  label={t('compare.hitFlips')}
                                  value={diff.hit_flips.total}
                                />
                                <DiagnosticsMetricTile
                                  label={t('workspace.compareImproved')}
                                  value={diff.hit_flips.improved}
                                  tone="positive"
                                />
                                <DiagnosticsMetricTile
                                  label={t('workspace.compareRegressed')}
                                  value={diff.hit_flips.regressed}
                                  tone="negative"
                                />
                                <DiagnosticsMetricTile
                                  label={t('compare.summaryKeys')}
                                  value={diffSummaryEntries.length}
                                />
                              </div>

                              <div className="rounded-lg border border-border/70 bg-card">
                                <div className="border-b border-border/70 px-4 py-3">
                                  <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                                    {t('compare.changedCases')}
                                  </div>
                                </div>
                                <div className="px-4 py-4">
                                  {diff.changed_cases?.length ? (
                                    <div className="grid gap-2">
                                      {diff.changed_cases.map((r: any) => (
                                        <div
                                          key={r.case_id}
                                          className="rounded-lg border border-border/70 bg-background px-3 py-3"
                                        >
                                          <div className="text-[11px] font-mono text-muted-foreground">
                                            {String(r.case_id).slice(0, 8)}
                                          </div>
                                          <div className="mt-1 text-sm text-foreground">
                                            {r.question ||
                                              t('compare.noQuestion')}
                                          </div>
                                          <div className="mt-2 text-[11px] leading-5 tabular-nums text-muted-foreground">
                                            命中 {String(r.a_hit)} →{' '}
                                            {String(r.b_hit)} · Recall{' '}
                                            {String(r.a_recall)} →{' '}
                                            {String(r.b_recall)} · 变化{' '}
                                            {String(r.delta_recall)}
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    <DiagnosticsEmptyState
                                      title={t(
                                        'workspace.compareCasesEmptyTitle'
                                      )}
                                      description={t('compare.diffHint')}
                                    />
                                  )}
                                </div>
                              </div>
                            </div>

                            <div className="space-y-4">
                              <div className="rounded-lg border border-border/70 bg-card">
                                <div className="border-b border-border/70 px-4 py-3">
                                  <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                                    {t('workspace.compareSummaryTitle')}
                                  </div>
                                </div>
                                <div className="px-4 py-4">
                                  {diffSummaryEntries.length ? (
                                    <div className="grid gap-2">
                                      {diffSummaryEntries.map(
                                        ([key, value]) => {
                                          const row = value as {
                                            a?: number | null
                                            b?: number | null
                                            delta?: number | null
                                          }
                                          const delta = Number(row.delta ?? 0)
                                          return (
                                            <div
                                              key={key}
                                              className="rounded-lg border border-border/70 bg-background px-3 py-3"
                                            >
                                              <div className="text-[11px] tracking-[0.08em] text-muted-foreground">
                                                {formatDiagnosticsMetricLabel(
                                                  key
                                                )}
                                              </div>
                                              <div className="mt-1 text-sm font-medium tabular-nums text-foreground">
                                                {String(row.a ?? '-')} →{' '}
                                                {String(row.b ?? '-')}
                                              </div>
                                              <div
                                                className={cn(
                                                  'mt-1 text-[11px] tabular-nums',
                                                  delta > 0
                                                    ? 'text-emerald-700'
                                                    : delta < 0
                                                      ? 'text-rose-700'
                                                      : 'text-muted-foreground'
                                                )}
                                              >
                                                Δ {String(row.delta ?? '-')}
                                              </div>
                                            </div>
                                          )
                                        }
                                      )}
                                    </div>
                                  ) : (
                                    <DiagnosticsEmptyState
                                      title={t(
                                        'workspace.compareSummaryEmptyTitle'
                                      )}
                                      description={t('compare.diffHint')}
                                    />
                                  )}
                                </div>
                              </div>

                              <DiagnosticsJsonPanel
                                label={t('compare.diffJson')}
                                value={diffJson}
                                rows={18}
                              />
                            </div>
                          </div>
                        ) : (
                          <DiagnosticsEmptyState
                            title={t('workspace.compareEmptyTitle')}
                            description={t('compare.empty')}
                          />
                        )}
                      </div>
                    </div>
                  </TabsContent>
                </Tabs>
              </section>
            </div>
          </div>
        </div>
      </div>
    </AppFrame>
  )
}
