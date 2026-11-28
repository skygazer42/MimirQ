'use client'

import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { AppFrame } from '@/components/app-frame'
import { AlertTriangle, FileText, Layers, Network, SearchCheck, type PlatformIcon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import {
  OperationalWorkspace,
  WorkspaceMetrics,
  WorkspaceNotice,
  workspaceStyles as ws,
} from '@/components/ui/operational-workspace'
import { useRouter } from '@/i18n/navigation'
import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import type { DocumentHealthCard } from '@/types/documents'

type QualityBadgeTone = 'bad' | 'warn' | 'ok'
type HealthTone = QualityBadgeTone | 'neutral'

const DOCUMENT_HEALTH_QUERY_PARAMS = {
  window_minutes: 24 * 60,
  max_chunks_scored: 256,
} as const

function readNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function formatPercent(ratio: number | null | undefined, digits = 1): string {
  if (ratio === null || ratio === undefined) return '—'
  return `${(ratio * 100).toFixed(digits)}%`
}

function formatCount(value: number | null | undefined): string {
  return value?.toLocaleString() ?? '—'
}

function formatText(value: string | null | undefined): string {
  if (value === '') return '—'
  return value ?? '—'
}

function getQualityBadge(score: number | undefined): { label: string; tone: QualityBadgeTone } | undefined {
  if (score === undefined) return undefined
  if (score < 0.35) return { label: '解析质量偏低', tone: 'bad' }
  if (score < 0.6) return { label: '解析质量一般', tone: 'warn' }
  return { label: '解析质量良好', tone: 'ok' }
}

function retrievalHitsStatusLabel(retrievalHits: DocumentHealthCard['retrieval_hits']): string {
  if (retrievalHits === null || retrievalHits === undefined) return '未返回'
  if (!retrievalHits.enabled) return '未启用'
  if (!retrievalHits.available) return '日志不可用'
  return retrievalHits.traces_scanned === 0 ? '暂无样本' : '有样本'
}

function documentStatus(status: DocumentHealthCard['status']): { label: string; hasError: boolean } {
  const normalizedStatus = status?.toLowerCase()
  if (normalizedStatus === 'completed' || normalizedStatus === 'ready') return { label: '已就绪', hasError: false }
  if (normalizedStatus === 'processing' || normalizedStatus === 'pending') return { label: '处理中', hasError: false }
  if (normalizedStatus === 'failed') return { label: '失败', hasError: true }
  if (normalizedStatus === 'quarantined') return { label: '隔离', hasError: true }
  return { label: normalizedStatus === '' ? '未知' : (normalizedStatus ?? '未知'), hasError: false }
}

function formatBoolean(value: boolean | null | undefined): string {
  if (value === true) return '是'
  if (value === false) return '否'
  return '—'
}

function getCoverageTone(value: number | undefined): HealthTone {
  if (value === undefined) return 'neutral'
  if (value >= 0.98) return 'ok'
  if (value >= 0.9) return 'warn'
  return 'bad'
}

function getReviewTone(value: number | undefined): HealthTone {
  if (value === undefined) return 'neutral'
  if (value <= 0.05) return 'ok'
  if (value <= 0.2) return 'warn'
  return 'bad'
}

type DocumentHealthPageProps = { documentId: string }

export default function DocumentHealthPage({ documentId }: Readonly<DocumentHealthPageProps>) {
  const router = useRouter()
  const {
    data: health,
    error,
    isFetching,
    isPaused,
    isPending,
    refetch,
  } = useQuery({
    queryKey: queryKeys.documents.health(documentId, DOCUMENT_HEALTH_QUERY_PARAMS),
    queryFn: ({ signal }) => documentApi.health(documentId, DOCUMENT_HEALTH_QUERY_PARAMS, { signal }),
  })

  function reloadHealth() {
    void refetch()
  }

  return (
    <AppFrame showBackground={false}>
      <OperationalWorkspace
        title="文档健康审计"
        icon="diagnostics"
        context={health?.filename ?? documentId}
        actions={
          <Button variant="outline" disabled={isFetching} onClick={reloadHealth}>
            {isFetching ? '正在读取…' : '重新读取'}
          </Button>
        }
        back={() => router.push('/knowledge')}
      >
        {error !== null ? (
          <WorkspaceNotice
            placement={health !== undefined ? 'floating' : 'inline'}
            tone={health !== undefined ? 'warning' : 'error'}
            title="加载失败"
            error={error}
            fallbackMessage="加载失败"
            retry={reloadHealth}
            pending={isFetching}
          />
        ) : null}
        {isPending ? (
          <p role="status" className="py-12 text-sm text-muted-foreground">
            {isPaused ? '等待网络连接' : '正在读取文档健康审计…'}
          </p>
        ) : null}
        {health === undefined ? null : <DocumentHealthReport health={health} />}
      </OperationalWorkspace>
    </AppFrame>
  )
}

function DocumentHealthReport({ health }: Readonly<{ health: DocumentHealthCard }>) {
  const { parsing, chunking, kg, retrieval_hits: retrievalHits } = health
  const { coverage, semantic_quality: semanticQuality } = chunking
  const needsReviewRatio =
    semanticQuality && semanticQuality.sampled_chunks > 0 ? semanticQuality.needs_review_ratio : undefined
  const qualityScore = readNumber(parsing.parse_quality?.score)
  const qualityBadge = getQualityBadge(qualityScore)
  const kgSummary = isRecord(kg?.summary) ? kg.summary : undefined
  const kgComponents = isRecord(kg?.components) ? kg.components : undefined
  const entityCount = readNumber(kgSummary?.entities)
  const relationCount = readNumber(kgSummary?.relations)
  const retrievalHitsStatus = retrievalHitsStatusLabel(retrievalHits)
  const retrievalSample = retrievalHits?.available ? retrievalHits : undefined
  const status = documentStatus(health.status)

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border py-4">
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <span className={status.hasError ? 'text-destructive' : 'text-foreground'}>{status.label}</span>
          <span className="text-muted-foreground">
            {formatText(health.file_type?.toUpperCase())} ·{' '}
            {typeof health.file_size === 'number' ? formatFileSize(health.file_size) : '—'}
          </span>
        </div>
        <details className="text-[13px]">
          <summary className="cursor-pointer">文档信息</summary>
          <dl className="mt-3 space-y-2 break-all text-muted-foreground">
            <div>
              <dt className="inline">文档：</dt>
              <dd className="inline">{health.document_id}</dd>
            </div>
            <div>
              <dt className="inline">数据集：</dt>
              <dd className="inline">{health.dataset_id ?? '未关联数据集'}</dd>
            </div>
            <div>
              <dt className="inline">创建：</dt>
              <dd className="inline">{health.created_at ? formatDate(health.created_at) : '—'}</dd>
            </div>
            <div>
              <dt className="inline">生成：</dt>
              <dd className="inline">{formatDate(health.generated_at)}</dd>
            </div>
          </dl>
        </details>
      </div>
      <WorkspaceMetrics
        items={[
          {
            label: '解析评分',
            value:
              qualityScore === undefined ? <span className="text-muted-foreground">—</span> : qualityScore.toFixed(3),
            detail: qualityBadge?.label,
            tone: qualityBadge?.tone === 'bad' ? 'danger' : qualityBadge?.tone === 'warn' ? 'warning' : undefined,
          },
          {
            label: '字符覆盖率',
            value: (
              <span className={coverage?.coverage_ratio == null ? 'text-muted-foreground' : undefined}>
                {formatPercent(coverage?.coverage_ratio)}
              </span>
            ),
            detail: coverage ? `缺口 ${formatCount(coverage.gap_count)}` : undefined,
          },
          {
            label: 'KG 实体',
            value: (
              <span className={entityCount === undefined ? 'text-muted-foreground' : undefined}>
                {formatCount(entityCount)}
              </span>
            ),
            detail: relationCount === undefined ? undefined : `关系 ${formatCount(relationCount)}`,
          },
          {
            label: '检索命中率',
            value: (
              <span className={retrievalSample?.hit_rate == null ? 'text-muted-foreground' : undefined}>
                {formatPercent(retrievalSample?.hit_rate, 2)}
              </span>
            ),
            detail: retrievalHitsStatus,
          },
        ]}
      />
      <p className="pt-3 text-[12px] leading-5 text-muted-foreground">“—” 表示未采集或暂无统计。</p>
      <div className="grid min-w-0 gap-x-10 xl:grid-cols-2">
        <HealthSection
          icon={FileText}
          title="解析链路"
          badge={qualityBadge?.label}
          tone={qualityBadge?.tone ?? 'neutral'}
        >
          <DenseGrid>
            <Fact label="解析器" value={formatText(parsing.parser_backend)} />
            <Fact label="请求解析器" value={formatText(parsing.parser_backend_requested)} />
            <Fact label="扫描件" value={formatBoolean(parsing.is_scanned)} />
            <Fact label="页数" value={formatCount(parsing.page_count)} />
            <Fact label="处理时间" value={parsing.processed_at ? formatDate(parsing.processed_at) : '—'} />
          </DenseGrid>
        </HealthSection>
        <HealthSection
          icon={Layers}
          title="切片链路"
          badge={coverage?.coverage_ratio == null ? undefined : `覆盖 ${formatPercent(coverage.coverage_ratio)}`}
          tone={getCoverageTone(coverage?.coverage_ratio)}
        >
          <DenseGrid>
            <Fact label="策略" value={formatText(chunking.chunk_strategy)} />
            <Fact label="请求策略" value={formatText(chunking.chunk_strategy_requested)} />
            <Fact label="切片数" value={formatCount(chunking.chunk_count)} />
            <Fact label="总字符" value={formatCount(chunking.total_characters)} />
            <Fact label="覆盖率" value={formatPercent(coverage?.coverage_ratio)} />
            <Fact label="重叠冗余率" value={formatPercent(coverage?.overlap_waste_ratio)} />
            <Fact label="缺口数" value={formatCount(coverage?.gap_count)} />
            <Fact label="最大缺口" value={formatCount(coverage?.largest_gap)} />
          </DenseGrid>

          {semanticQuality ? (
            <div className="mt-5 border-t border-border pt-4">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-[12px] font-medium text-foreground">语义质量抽样</h3>
                {semanticQuality.note ? (
                  <p className="text-[10px] text-muted-foreground">{semanticQuality.note}</p>
                ) : null}
              </div>
              <DenseGrid>
                <Fact label="抽样切片" value={formatCount(semanticQuality.sampled_chunks)} />
                <Fact
                  label="需复核"
                  value={`${formatCount(semanticQuality.needs_review)} · ${formatPercent(needsReviewRatio)}`}
                  tone={getReviewTone(needsReviewRatio)}
                />
                <Fact label="信息密度" value={semanticQuality.mean_information_density?.toFixed(3) ?? '—'} />
                <Fact label="语义完整" value={semanticQuality.mean_semantic_completeness?.toFixed(3) ?? '—'} />
                <Fact label="自包含" value={semanticQuality.mean_self_containedness?.toFixed(3) ?? '—'} />
                <Fact label="代词率" value={formatPercent(semanticQuality.mean_pronoun_ratio)} />
              </DenseGrid>
            </div>
          ) : null}
        </HealthSection>
        <HealthSection
          icon={Network}
          title="KG 链路"
          badge={entityCount === undefined ? undefined : `实体 ${formatCount(entityCount)}`}
          tone="neutral"
        >
          <DenseGrid>
            <Fact label="事件" value={formatCount(readNumber(kgSummary?.events))} />
            <Fact label="实体" value={formatCount(entityCount)} />
            <Fact label="关系" value={formatCount(relationCount)} />
            <Fact label="孤立实体" value={formatPercent(readNumber(kgSummary?.isolated_entity_ratio), 2)} />
            <Fact label="连通分量" value={formatCount(readNumber(kgComponents?.components))} />
            <Fact label="最大分量" value={formatPercent(readNumber(kgComponents?.largest_component_ratio), 2)} />
          </DenseGrid>
        </HealthSection>
        <HealthSection
          icon={SearchCheck}
          title="检索命中"
          badge={retrievalHitsStatus}
          tone={retrievalSample && retrievalSample.traces_scanned > 0 ? 'ok' : 'neutral'}
        >
          <DenseGrid>
            <Fact label="窗口（分钟）" value={formatCount(retrievalHits?.window_minutes)} />
            <Fact label="扫描检索记录" value={formatCount(retrievalSample?.traces_scanned)} />
            <Fact label="命中检索记录" value={formatCount(retrievalSample?.traces_with_hits)} />
            <Fact label="引用命中" value={formatCount(retrievalSample?.citations_matched)} />
            <Fact label="去重命中切片" value={formatCount(retrievalSample?.unique_chunks_matched)} />
            <Fact label="命中率" value={formatPercent(retrievalSample?.hit_rate, 2)} />
            <Fact label="截断" value={formatBoolean(retrievalSample?.truncated)} />
          </DenseGrid>

          {retrievalHits?.enabled === false ? (
            <div className="mt-3 flex items-start gap-2 border-l-2 border-warning pl-3 text-[13px] leading-6 text-warning">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <span>检索命中统计未启用。</span>
            </div>
          ) : null}
        </HealthSection>
      </div>
    </>
  )
}

type HealthSectionProps = {
  badge?: string
  children: ReactNode
  icon: PlatformIcon
  title: string
  tone: HealthTone
}

function HealthSection({ badge, children, icon: Icon, title, tone }: Readonly<HealthSectionProps>) {
  return (
    <section className={ws.section}>
      <header className="mb-3 flex flex-wrap items-start justify-between gap-3 sm:mb-5">
        <div>
          <h2 className="flex items-center gap-2 text-[15px] font-medium">
            <Icon className="size-5" appearance="color" />
            {title}
          </h2>
        </div>
        {badge === undefined ? null : (
          <span
            className={cn(
              'text-[13px]',
              tone === 'bad' ? 'text-destructive' : tone === 'warn' ? ws.warning : 'text-muted-foreground',
            )}
          >
            {badge}
          </span>
        )}
      </header>
      {children}
    </section>
  )
}

function DenseGrid({ children }: Readonly<{ children: ReactNode }>) {
  return <div className="grid grid-cols-2 gap-x-4 sm:gap-x-6">{children}</div>
}

type FactProps = {
  label: string
  tone?: HealthTone
  value: string
}

function Fact({ label, tone = 'neutral', value }: Readonly<FactProps>) {
  return (
    <div className="min-w-0 border-b border-border/60 py-2 sm:py-3">
      <div className="text-[13px] leading-5 text-muted-foreground">{label}</div>
      <div
        className={cn(
          'mt-1 break-words text-[13px] leading-5 tabular-nums sm:text-sm sm:leading-6',
          tone === 'bad'
            ? 'text-destructive'
            : tone === 'warn'
              ? ws.warning
              : value === '—'
                ? 'text-muted-foreground'
                : 'text-foreground',
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  )
}
