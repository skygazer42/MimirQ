'use client'

import type { DocumentHealthCard } from '@/types'

import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  Database,
  FileText,
  Gauge,
  GitBranch,
  Hash,
  Layers,
  Network,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Sigma,
  type LucideIcon,
} from 'lucide-react'
import { useMemo } from 'react'

import { AppFrame } from '@/components/app-frame'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { useRouter } from '@/i18n/navigation'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn, formatDate, formatFileSize } from '@/lib/utils'

type QualityBadgeTone = 'bad' | 'warn' | 'ok'
type HealthTone = QualityBadgeTone | 'neutral'

const DOCUMENT_HEALTH_QUERY_PARAMS = {
  window_minutes: 24 * 60,
  max_chunks_scored: 256,
} as const

function safeNumber(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return value
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function pct(value: number | null | undefined, digits = 1): string {
  const v = typeof value === 'number' && Number.isFinite(value) ? value : null
  if (v === null) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

function fmt(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value.toString()
  }
  if (value instanceof Date) return value.toISOString()
  try {
    return JSON.stringify(value)
  } catch {
    return '—'
  }
}

function compactNumber(value: unknown): string {
  const n = safeNumber(value)
  if (n === null) return fmt(value)
  return n.toLocaleString()
}

function parseQualityScore(card: DocumentHealthCard | null): number | null {
  const parseQuality = isRecord(card?.parsing?.parse_quality) ? card.parsing.parse_quality : {}
  const score = parseQuality.score
  return safeNumber(score)
}

function qualityBadgeClassName(tone: QualityBadgeTone): string {
  switch (tone) {
    case 'bad':
      return 'border-destructive/25 bg-destructive/[0.08] text-destructive'
    case 'warn':
      return 'border-warning/24 bg-warning/[0.08] text-warning dark:text-warning'
    default:
      return 'border-success/24 bg-success/[0.08] text-success dark:text-success'
  }
}

function toneClassName(tone: HealthTone): string {
  switch (tone) {
    case 'bad':
      return 'border-destructive/24 bg-destructive/[0.08] text-destructive'
    case 'warn':
      return 'border-warning/24 bg-warning/[0.08] text-warning dark:text-warning'
    case 'ok':
      return 'border-success/24 bg-success/[0.08] text-success dark:text-success'
    default:
      return 'border-border/50 bg-muted/22 text-muted-foreground'
  }
}

function retrievalHitsStatusLabel(
  retrievalHits: DocumentHealthCard['retrieval_hits'] | null | undefined,
): string {
  if (retrievalHits?.enabled !== true) return '未启用'
  return retrievalHits.available ? '有样本' : '暂无命中'
}

function documentStatusLabel(status: unknown): string {
  const value = String(status || '').toLowerCase()
  if (value === 'completed' || value === 'ready') return '已就绪'
  if (value === 'processing' || value === 'pending') return '处理中'
  if (value === 'failed') return '失败'
  if (value === 'quarantined') return '隔离'
  return value || '未知'
}

function documentStatusTone(status: unknown): HealthTone {
  const value = String(status || '').toLowerCase()
  if (value === 'completed' || value === 'ready') return 'ok'
  if (value === 'failed' || value === 'quarantined') return 'bad'
  if (value === 'processing' || value === 'pending') return 'warn'
  return 'neutral'
}

function formatBoolean(value: boolean | null | undefined): string {
  if (value === true) return '是'
  if (value === false) return '否'
  return '—'
}

function getCoverageTone(value: number | null | undefined): HealthTone {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'neutral'
  if (value >= 0.98) return 'ok'
  if (value >= 0.9) return 'warn'
  return 'bad'
}

function getReviewTone(value: number | null | undefined): HealthTone {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'neutral'
  if (value <= 0.05) return 'ok'
  if (value <= 0.2) return 'warn'
  return 'bad'
}

export default function DocumentHealthPage({ documentId }: Readonly<{ documentId: string }>) {
  const router = useRouter()
  const healthQuery = useQuery({
    queryKey: queryKeys.documents.health(documentId, DOCUMENT_HEALTH_QUERY_PARAMS),
    queryFn: () => documentApi.health(documentId, DOCUMENT_HEALTH_QUERY_PARAMS),
    enabled: Boolean(documentId),
  })
  const data = (healthQuery.data ?? null) as DocumentHealthCard | null
  const loading = healthQuery.isFetching
  const error = healthQuery.error ? formatApiError(healthQuery.error, '加载失败') : null

  const qualityScore = useMemo(() => parseQualityScore(data), [data])
  const kgSummary = isRecord(data?.kg?.summary) ? data.kg.summary : {}
  const kgComponents = isRecord(data?.kg?.components) ? data.kg.components : {}
  const qualityBadge = useMemo(() => {
    if (qualityScore === null) return null
    if (qualityScore < 0.35) return { label: '解析质量偏低', tone: 'bad' as const }
    if (qualityScore < 0.6) return { label: '解析质量一般', tone: 'warn' as const }
    return { label: '解析质量良好', tone: 'ok' as const }
  }, [qualityScore])
  const retrievalHitsStatus = retrievalHitsStatusLabel(data?.retrieval_hits)
  const retrievalMetricsDisabled = data?.retrieval_hits?.enabled === false
  const semanticQuality = data?.chunking?.semantic_quality ?? null
  const coverage = data?.chunking?.coverage ?? null
  const isolatedRatio = safeNumber(kgSummary.isolated_entity_ratio)
  const largestComponentRatio = safeNumber(kgComponents.largest_component_ratio)

  return (
    <AppFrame>
      <PageScaffold
        title="文档健康审计"
        size="full"
        density="system-dense"
        bodyGutter="dense"
        bodyClassName="bg-[radial-gradient(circle_at_18%_0%,hsl(var(--info)/0.10),transparent_28%),linear-gradient(180deg,hsl(var(--background)/0.96),hsl(var(--surface-2)/0.68))] pb-3"
        description={
          <div className="space-y-1">
            <div className="text-muted-foreground">
              解析 → 分块 → KG → 检索命中（聚合，PII-safe）
            </div>
            <div className="font-mono text-xs text-muted-foreground break-all">{documentId}</div>
          </div>
        }
        icon={ShieldCheck}
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 rounded-xl border-border/55 bg-background/78 px-3 text-[12px]"
              onClick={() => router.push('/knowledge')}
            >
              <ArrowLeft className="mr-2 size-3.5" />
              返回知识库
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 rounded-xl border-border/55 bg-background/78 px-3 text-[12px]"
              disabled={loading}
              onClick={() => {
                healthQuery.refetch()
              }}
            >
              <RefreshCw className={cn('mr-2 size-3.5', loading ? 'animate-spin motion-reduce:animate-none' : '')} />
              刷新
            </Button>
          </div>
        }
        top={
          data ? (
            <Panel
              variant="glass"
              className="overflow-hidden rounded-[24px] border-border/50 bg-[radial-gradient(circle_at_10%_0%,hsl(var(--info)/0.10),transparent_34%),linear-gradient(135deg,hsl(var(--card)/0.90),hsl(var(--surface-2)/0.48))] p-0 shadow-[0_18px_48px_-36px_hsl(var(--primary)/0.28)]"
            >
              <div className="flex flex-col gap-4 px-4 py-4 lg:flex-row lg:items-stretch lg:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-[16px] border border-info/18 bg-info/[0.08] text-info shadow-[inset_0_1px_0_hsl(var(--card)/0.80)]">
                      <FileText className="size-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="break-words text-[20px] font-semibold leading-6 tracking-[-0.02em] text-foreground">
                          {data.filename || '未命名文档'}
                        </h2>
                        <Badge
                          variant="secondary"
                          className={cn('border px-2 py-0.5 text-[10px] font-semibold', toneClassName(documentStatusTone(data.status)))}
                        >
                          {documentStatusLabel(data.status)}
                        </Badge>
                        {qualityBadge ? (
                          <Badge
                            variant="secondary"
                            className={cn('border px-2 py-0.5 text-[10px] font-semibold', qualityBadgeClassName(qualityBadge.tone))}
                          >
                            {qualityBadge.label}
                          </Badge>
                        ) : null}
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <InfoPill icon={Hash} value={data.document_id} />
                        <InfoPill icon={Database} value={data.dataset_id || '未绑定知识库'} />
                      </div>
                    </div>
                  </div>
                </div>
                <div className="grid min-w-[min(100%,28rem)] grid-cols-2 gap-2 sm:grid-cols-4 lg:max-w-[40rem]">
                  <HeroMetric icon={FileText} label="类型" value={fmt(data.file_type)} />
                  <HeroMetric icon={Gauge} label="大小" value={data.file_size ? formatFileSize(data.file_size) : '—'} />
                  <HeroMetric icon={Clock3} label="创建" value={data.created_at ? formatDate(data.created_at) : '—'} />
                  <HeroMetric icon={Clock3} label="生成" value={data.generated_at ? formatDate(data.generated_at) : '—'} />
                </div>
              </div>
            </Panel>
          ) : null
        }
      >
        {error ? (
          <Panel className="rounded-[18px] border border-destructive/24 bg-destructive/[0.08] text-destructive">
            {error}
          </Panel>
        ) : null}

        {!data && !loading && !error ? (
          <Panel variant="glass" className="rounded-[18px] text-muted-foreground">
            未找到数据
          </Panel>
        ) : null}

        {loading && !data ? (
          <Panel variant="glass" className="rounded-[18px] text-muted-foreground">
            加载中…
          </Panel>
        ) : null}

        {data ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <ScoreTile
                icon={Activity}
                label="解析评分"
                value={qualityScore === null ? '—' : qualityScore.toFixed(3)}
                detail={qualityBadge?.label || '暂无评分'}
                tone={qualityBadge?.tone || 'neutral'}
              />
              <ScoreTile
                icon={Layers}
                label="覆盖率"
                value={pct(coverage?.coverage_ratio)}
                detail={`缺口 ${coverage?.gap_count ?? 0}`}
                tone={getCoverageTone(coverage?.coverage_ratio)}
              />
              <ScoreTile
                icon={Network}
                label="KG 实体"
                value={compactNumber(kgSummary.entities)}
                detail={`关系 ${compactNumber(kgSummary.relations)}`}
                tone="neutral"
              />
              <ScoreTile
                icon={SearchCheck}
                label="检索命中"
                value={pct(data.retrieval_hits?.hit_rate, 2)}
                detail={retrievalHitsStatus}
                tone={data.retrieval_hits?.available ? 'ok' : 'neutral'}
              />
            </div>

            <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2 2xl:grid-cols-4">
              <HealthSection
                icon={FileText}
                title="解析链路"
                subtitle="解析器、扫描件、页数与处理时间"
                badge={qualityBadge?.label || '未评分'}
                tone={qualityBadge?.tone || 'neutral'}
              >
                <DenseGrid>
                  <Fact label="解析器" value={fmt(data.parsing?.parser_backend)} />
                  <Fact label="请求解析器" value={fmt(data.parsing?.parser_backend_requested)} />
                  <Fact label="Parse score" value={qualityScore === null ? '—' : qualityScore.toFixed(4)} />
                  <Fact label="扫描件" value={formatBoolean(data.parsing?.is_scanned)} />
                  <Fact label="页数" value={fmt(data.parsing?.page_count)} />
                  <Fact label="处理时间" value={data.parsing?.processed_at ? formatDate(data.parsing.processed_at) : '—'} />
                </DenseGrid>
              </HealthSection>

              <HealthSection
                icon={Layers}
                title="切片链路"
                subtitle="chunk 策略、字符覆盖、overlap 成本"
                badge={`覆盖 ${pct(coverage?.coverage_ratio)}`}
                tone={getCoverageTone(coverage?.coverage_ratio)}
              >
                <DenseGrid>
                  <Fact label="策略" value={fmt(data.chunking?.chunk_strategy)} />
                  <Fact label="请求策略" value={fmt(data.chunking?.chunk_strategy_requested)} />
                  <Fact label="切片数" value={compactNumber(data.chunking?.chunk_count)} />
                  <Fact label="总字符" value={compactNumber(data.chunking?.total_characters)} />
                  <Fact label="覆盖率" value={pct(coverage?.coverage_ratio)} />
                  <Fact label="Overlap waste" value={pct(coverage?.overlap_waste_ratio)} />
                  <Fact label="缺口数" value={compactNumber(coverage?.gap_count)} />
                  <Fact label="最大缺口" value={compactNumber(coverage?.largest_gap)} />
                </DenseGrid>

                {semanticQuality ? (
                  <div className="mt-3 rounded-[16px] border border-border/45 bg-muted/[0.12] p-3">
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <div className="text-[12px] font-semibold text-foreground">语义质量抽样</div>
                      {semanticQuality.note ? (
                        <div className="text-[10px] text-muted-foreground">{semanticQuality.note}</div>
                      ) : null}
                    </div>
                    <DenseGrid>
                      <Fact label="抽样切片" value={compactNumber(semanticQuality.sampled_chunks)} />
                      <Fact
                        label="需复核"
                        value={`${compactNumber(semanticQuality.needs_review)} · ${pct(semanticQuality.needs_review_ratio)}`}
                        tone={getReviewTone(semanticQuality.needs_review_ratio)}
                      />
                      <Fact label="信息密度" value={fmt(semanticQuality.mean_information_density)} />
                      <Fact label="语义完整" value={fmt(semanticQuality.mean_semantic_completeness)} />
                      <Fact label="自包含" value={fmt(semanticQuality.mean_self_containedness)} />
                      <Fact label="代词率" value={fmt(semanticQuality.mean_pronoun_ratio)} />
                    </DenseGrid>
                  </div>
                ) : null}
              </HealthSection>

              <HealthSection
                icon={Network}
                title="KG 链路"
                subtitle="事件、实体、关系与连通性摘要"
                badge={`实体 ${compactNumber(kgSummary.entities)}`}
                tone="neutral"
              >
                <DenseGrid>
                  <Fact label="事件" value={compactNumber(kgSummary.events)} />
                  <Fact label="实体" value={compactNumber(kgSummary.entities)} />
                  <Fact label="关系" value={compactNumber(kgSummary.relations)} />
                  <Fact label="孤立实体" value={isolatedRatio === null ? '—' : pct(isolatedRatio, 2)} />
                  <Fact label="连通分量" value={compactNumber(kgComponents.components)} />
                  <Fact label="最大分量" value={largestComponentRatio === null ? '—' : pct(largestComponentRatio, 2)} />
                </DenseGrid>
              </HealthSection>

              <HealthSection
                icon={SearchCheck}
                title="检索命中"
                subtitle="最近窗口内的引用命中与样本覆盖"
                badge={retrievalHitsStatus}
                tone={data.retrieval_hits?.available ? 'ok' : 'neutral'}
              >
                <DenseGrid>
                  <Fact label="指标状态" value={retrievalHitsStatus} />
                  <Fact label="窗口" value={`${data.retrieval_hits?.window_minutes ?? '—'} min`} />
                  <Fact label="扫描 trace" value={compactNumber(data.retrieval_hits?.traces_scanned)} />
                  <Fact label="命中 trace" value={compactNumber(data.retrieval_hits?.traces_with_hits)} />
                  <Fact label="引用命中" value={compactNumber(data.retrieval_hits?.citations_matched)} />
                  <Fact label="唯一 chunk" value={compactNumber(data.retrieval_hits?.unique_chunks_matched)} />
                  <Fact label="命中率" value={pct(data.retrieval_hits?.hit_rate, 2)} />
                  <Fact label="截断" value={formatBoolean(data.retrieval_hits?.truncated)} />
                </DenseGrid>

                {retrievalMetricsDisabled ? (
                  <div className="mt-3 flex items-start gap-2 rounded-[14px] border border-warning/22 bg-warning/[0.08] px-3 py-2 text-[11px] leading-4 text-warning dark:text-warning">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                    <span>提示：需要启用后端 metrics 日志（ENABLE_METRICS_LOG=true）才能统计命中频率。</span>
                  </div>
                ) : null}
              </HealthSection>
            </div>
          </div>
        ) : null}
      </PageScaffold>
    </AppFrame>
  )
}

function InfoPill({
  icon: Icon,
  value,
}: Readonly<{
  icon: LucideIcon
  value: string
}>) {
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border/45 bg-background/62 px-2 py-1 font-mono text-[10px] text-muted-foreground">
      <Icon className="size-3 shrink-0 text-info/72" />
      <span className="truncate">{value}</span>
    </span>
  )
}

function HeroMetric({
  icon: Icon,
  label,
  value,
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
}>) {
  return (
    <div className="rounded-[16px] border border-border/45 bg-background/58 px-3 py-2 shadow-[inset_0_1px_0_hsl(var(--card)/0.72)]">
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground/66">
        <Icon className="size-3 text-info/70" />
        {label}
      </div>
      <div className="mt-1 truncate font-mono text-[11px] font-semibold tabular-nums text-foreground/86" title={value}>
        {value}
      </div>
    </div>
  )
}

function ScoreTile({
  detail,
  icon: Icon,
  label,
  tone,
  value,
}: Readonly<{
  detail: string
  icon: LucideIcon
  label: string
  tone: HealthTone
  value: string
}>) {
  const ToneIcon = tone === 'ok' ? CheckCircle2 : tone === 'bad' ? AlertTriangle : Sigma

  return (
    <div className="group relative overflow-hidden rounded-[18px] border border-border/50 bg-card/58 px-3 py-2.5 shadow-[0_12px_28px_-30px_hsl(var(--primary)/0.24)]">
      <span className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-[linear-gradient(90deg,hsl(var(--primary)/0.10),hsl(var(--info)/0.42),hsl(var(--primary)/0.08))]" />
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground/72">
            <Icon className="size-3.5 text-info/78" />
            {label}
          </div>
          <div className="mt-1 truncate font-mono text-[17px] font-semibold tabular-nums tracking-[-0.02em] text-foreground">
            {value}
          </div>
          <div className="mt-0.5 truncate text-[10px] text-muted-foreground/70">
            {detail}
          </div>
        </div>
        <span className={cn('inline-flex size-7 shrink-0 items-center justify-center rounded-full border', toneClassName(tone))}>
          <ToneIcon className="size-3.5" />
        </span>
      </div>
    </div>
  )
}

function HealthSection({
  badge,
  children,
  icon: Icon,
  subtitle,
  title,
  tone,
}: Readonly<{
  badge: string
  children: React.ReactNode
  icon: LucideIcon
  subtitle: string
  title: string
  tone: HealthTone
}>) {
  return (
    <Panel
      variant="glass"
      className="overflow-hidden rounded-[20px] border-border/50 bg-card/54 p-0 shadow-[0_14px_34px_-34px_hsl(var(--primary)/0.22)]"
    >
      <div className="border-b border-border/45 bg-[linear-gradient(180deg,hsl(var(--card)/0.70),hsl(var(--surface-2)/0.34))] px-3.5 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-[12px] border border-info/16 bg-info/[0.07] text-info">
              <Icon className="size-4" />
            </div>
            <div className="min-w-0">
              <div className="text-[14px] font-semibold leading-none text-foreground">
                {title}
              </div>
              <div className="mt-1 text-[11px] leading-4 text-muted-foreground/72">
                {subtitle}
              </div>
            </div>
          </div>
          <Badge variant="secondary" className={cn('shrink-0 border px-2 py-0.5 text-[10px] font-semibold', toneClassName(tone))}>
            {badge}
          </Badge>
        </div>
      </div>
      <div className="p-3.5">{children}</div>
    </Panel>
  )
}

function DenseGrid({ children }: Readonly<{ children: React.ReactNode }>) {
  return <div className="grid grid-cols-2 gap-2">{children}</div>
}

function Fact({
  label,
  tone = 'neutral',
  value,
}: Readonly<{
  label: string
  tone?: HealthTone
  value: string
}>) {
  return (
    <div className="min-w-0 rounded-[14px] border border-border/45 bg-background/58 px-2.5 py-2">
      <div className="text-[10px] font-medium leading-none text-muted-foreground/62">
        {label}
      </div>
      <div
        className={cn(
          'mt-1.5 truncate font-mono text-[11px] font-semibold leading-none tabular-nums text-foreground/84',
          tone !== 'neutral' && 'inline-flex max-w-full rounded-md border px-1.5 py-0.5',
          tone !== 'neutral' && toneClassName(tone)
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  )
}
