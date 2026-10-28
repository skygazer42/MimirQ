'use client'
import type { DocumentHealthCard } from '@/types';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, FileText, Layers, Network, SearchCheck, type PlatformIcon } from '@/components/icons';
import { useMemo } from 'react';
import { AppFrame } from '@/components/app-frame';
import { Button } from '@/components/ui/button';
import { OperationalWorkspace, WorkspaceMetrics, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace';
import { useRouter } from '@/i18n/navigation';
import { documentApi } from '@/lib/api';
import { formatApiError } from '@/lib/api-errors';
import { queryKeys } from '@/lib/query-keys';
import { cn, formatDate, formatFileSize } from '@/lib/utils';

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


  return <AppFrame showBackground={false}><OperationalWorkspace title="文档健康审计" icon="diagnostics" context={data?.filename || documentId} actions={<Button variant="outline" disabled={loading} onClick={() => { void healthQuery.refetch() }}>{loading ? '正在读取…' : '重新读取'}</Button>} back={() => router.push('/knowledge')}>
    {error ? <WorkspaceNotice retry={() => { void healthQuery.refetch() }} pending={loading}>{error}</WorkspaceNotice> : null}
    {loading && !data ? <p role="status" className="py-12 text-sm text-muted-foreground">正在读取文档健康审计…</p> : null}
    {!loading && !data && !error ? <div className={ws.empty}><h2>暂无文档审计结果</h2><p>请返回知识库选择文档，确认文档已完成处理。</p></div> : null}
    {data ? <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border py-4"><div className="flex flex-wrap items-center gap-3 text-[13px]"><span className={documentStatusTone(data.status) === 'bad' ? 'text-destructive' : 'text-foreground'}>{documentStatusLabel(data.status)}</span><span className="text-muted-foreground">{data.file_type?.toUpperCase() || '—'} · {typeof data.file_size === 'number' ? formatFileSize(data.file_size) : '—'}</span></div><details className="text-[13px]"><summary className="cursor-pointer">文档信息</summary><dl className="mt-3 space-y-2 break-all text-muted-foreground"><div>文档：{data.document_id}</div><div>数据集：{data.dataset_id || '未关联数据集'}</div><div>创建：{data.created_at ? formatDate(data.created_at) : '—'}</div><div>生成：{formatDate(data.generated_at)}</div></dl></details></div>
      <WorkspaceMetrics items={[{ label: '解析评分', value: qualityScore === null ? '—' : qualityScore.toFixed(3), detail: qualityBadge?.label || '暂无评分', tone: qualityBadge?.tone === 'bad' ? 'danger' : qualityBadge?.tone === 'warn' ? 'warning' : undefined }, { label: '字符覆盖率', value: pct(coverage?.coverage_ratio), detail: coverage ? `缺口 ${compactNumber(coverage.gap_count)}` : '尚无覆盖统计' }, { label: 'KG 实体', value: compactNumber(kgSummary.entities), detail: `关系 ${compactNumber(kgSummary.relations)}` }, { label: '检索命中率', value: pct(data.retrieval_hits?.hit_rate, 2), detail: retrievalHitsStatus }]} />
      <div className="grid min-w-0 gap-x-10 xl:grid-cols-2"><HealthSection
                icon={FileText}
                title="解析链路"
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
                  <div className="mt-5 border-t border-border pt-4">
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
              </HealthSection></div>
    </> : null}
  </OperationalWorkspace></AppFrame>
}

function HealthSection({
  badge,
  children,
  icon: Icon,
  title,
  tone,
}: Readonly<{
  badge: string
  children: React.ReactNode
  icon: PlatformIcon
  title: string
  tone: HealthTone
}>) {
  return <section className={ws.section}>
    <header className="mb-5 flex flex-wrap items-start justify-between gap-3"><div><h2 className="flex items-center gap-2 text-[15px] font-semibold"><Icon className="size-5" appearance="color" />{title}</h2></div><span className={cn('text-[13px]', tone === 'bad' ? 'text-destructive' : tone === 'warn' ? ws.warning : 'text-muted-foreground')}>{badge}</span></header>
    {children}
  </section>
}

function DenseGrid({ children }: Readonly<{ children: React.ReactNode }>) {
  return <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">{children}</div>
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
    <div className="min-w-0 border-b border-border/60 py-3">
      <div className="text-[13px] leading-5 text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          'mt-1 break-words text-sm font-medium leading-6 tabular-nums text-foreground',

          tone === 'bad' ? 'text-destructive' : tone === 'warn' ? ws.warning : undefined
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  )
}
