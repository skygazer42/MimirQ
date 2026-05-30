'use client'

import type { DocumentHealthCard } from '@/types'

import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowLeft, RefreshCw } from 'lucide-react'
import { useMemo } from 'react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useRouter } from '@/i18n/navigation'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'

type QualityBadgeTone = 'bad' | 'warn' | 'ok'

const DOCUMENT_HEALTH_QUERY_PARAMS = {
  window_minutes: 24 * 60,
  max_chunks_scored: 256,
} as const

function safeNumber(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return value
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

function parseQualityScore(card: DocumentHealthCard | null): number | null {
  const score = (card?.parsing?.parse_quality as any)?.score
  return safeNumber(score)
}

function qualityBadgeClassName(tone: QualityBadgeTone): string {
  switch (tone) {
    case 'bad':
      return 'border-destructive/30 bg-destructive/10 text-destructive'
    case 'warn':
      return 'border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300'
    default:
      return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
  }
}

function retrievalHitsStatusLabel(
  retrievalHits: DocumentHealthCard['retrieval_hits'] | null | undefined,
): string {
  if (retrievalHits?.enabled !== true) return 'disabled'
  return retrievalHits.available ? 'available' : 'missing'
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
  const qualityBadge = useMemo(() => {
    if (qualityScore === null) return null
    if (qualityScore < 0.35) return { label: '解析质量偏低', tone: 'bad' as const }
    if (qualityScore < 0.6) return { label: '解析质量一般', tone: 'warn' as const }
    return { label: '解析质量良好', tone: 'ok' as const }
  }, [qualityScore])
  const retrievalHitsStatus = retrievalHitsStatusLabel(data?.retrieval_hits)
  const retrievalMetricsDisabled = data?.retrieval_hits?.enabled === false

  return (
    <AppFrame>
      <PageScaffold
        title="Document Health"
        description={
          <div className="space-y-1">
            <div className="text-muted-foreground">
              解析 → 分块 → KG → 检索命中（聚合，PII-safe）
            </div>
            <div className="text-xs text-muted-foreground font-mono break-all">{documentId}</div>
          </div>
        }
        icon={Activity}
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="rounded-xl"
              onClick={() => router.push('/knowledge')}
            >
              <ArrowLeft className="mr-2 size-4" />
              返回知识库
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="rounded-xl"
              disabled={loading}
              onClick={() => {
                healthQuery.refetch()
              }}
            >
              <RefreshCw className={cn('mr-2 size-4', loading ? 'animate-spin motion-reduce:animate-none' : '')} />
              刷新
            </Button>
          </div>
        }
        top={
          data ? (
            <Panel variant="glass" className="rounded-2xl">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="min-w-0">
                  <div className="text-sm text-muted-foreground">文件</div>
                  <div className="mt-0.5 text-lg font-semibold text-foreground truncate">
                    {data.filename || '—'}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono">type={fmt(data.file_type)}</span>
                    <span className="text-muted-foreground/60">·</span>
                    <span className="font-mono">{data.file_size ? formatFileSize(data.file_size) : '—'}</span>
                    <span className="text-muted-foreground/60">·</span>
                    <span className="font-mono">{data.created_at ? formatDate(data.created_at) : '—'}</span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary" className="border border-border/60 bg-muted">
                    status={fmt(data.status)}
                  </Badge>
                  {qualityBadge ? (
                    <Badge
                      variant="secondary"
                      className={cn('border', qualityBadgeClassName(qualityBadge.tone))}
                    >
                      {qualityBadge.label}
                    </Badge>
                  ) : null}
                </div>
              </div>
            </Panel>
          ) : null
        }
      >
        {error ? (
          <Panel className="rounded-2xl border border-destructive/30 bg-destructive/10 text-destructive">
            {error}
          </Panel>
        ) : null}

        {!data && !loading && !error ? (
          <Panel variant="glass" className="rounded-2xl text-muted-foreground">
            未找到数据
          </Panel>
        ) : null}

        {loading && !data ? (
          <Panel variant="glass" className="rounded-2xl text-muted-foreground">
            加载中…
          </Panel>
        ) : null}

        {data ? (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Panel variant="glass" className="rounded-2xl">
              <div className="text-sm font-semibold text-foreground">解析</div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="text-muted-foreground">Parser</div>
                <div className="font-mono">{fmt(data.parsing?.parser_backend)}</div>
                <div className="text-muted-foreground">Requested</div>
                <div className="font-mono">{fmt(data.parsing?.parser_backend_requested)}</div>
                <div className="text-muted-foreground">Parse score</div>
                <div className="font-mono tabular-nums">
                  {qualityScore === null ? '—' : qualityScore.toFixed(4)}
                </div>
                <div className="text-muted-foreground">Scanned</div>
                <div className="font-mono">{data.parsing?.is_scanned === null || data.parsing?.is_scanned === undefined ? '—' : String(Boolean(data.parsing.is_scanned))}</div>
                <div className="text-muted-foreground">Pages</div>
                <div className="font-mono tabular-nums">{data.parsing?.page_count ?? '—'}</div>
                <div className="text-muted-foreground">Processed</div>
                <div className="font-mono">{data.parsing?.processed_at ? formatDate(data.parsing.processed_at) : '—'}</div>
              </div>
            </Panel>

            <Panel variant="glass" className="rounded-2xl">
              <div className="text-sm font-semibold text-foreground">分块</div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="text-muted-foreground">Strategy</div>
                <div className="font-mono">{fmt(data.chunking?.chunk_strategy)}</div>
                <div className="text-muted-foreground">Chunks</div>
                <div className="font-mono tabular-nums">{data.chunking?.chunk_count ?? 0}</div>
                <div className="text-muted-foreground">Chars</div>
                <div className="font-mono tabular-nums">{data.chunking?.total_characters ?? 0}</div>
                <div className="text-muted-foreground">Coverage</div>
                <div className="font-mono tabular-nums">{pct(data.chunking?.coverage?.coverage_ratio)}</div>
                <div className="text-muted-foreground">Overlap waste</div>
                <div className="font-mono tabular-nums">{pct(data.chunking?.coverage?.overlap_waste_ratio)}</div>
                <div className="text-muted-foreground">Gaps</div>
                <div className="font-mono tabular-nums">{data.chunking?.coverage?.gap_count ?? 0}</div>
                <div className="text-muted-foreground">Largest gap</div>
                <div className="font-mono tabular-nums">{data.chunking?.coverage?.largest_gap ?? 0}</div>
              </div>

              {data.chunking?.semantic_quality ? (
                <div className="mt-5 border-t border-border/60 pt-4">
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-semibold text-foreground">语义质量（抽样）</div>
                    {data.chunking.semantic_quality.note ? (
                      <div className="text-[11px] text-muted-foreground">{data.chunking.semantic_quality.note}</div>
                    ) : null}
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                    <div className="text-muted-foreground">Sampled</div>
                    <div className="font-mono tabular-nums">{data.chunking.semantic_quality.sampled_chunks}</div>
                    <div className="text-muted-foreground">Needs review</div>
                    <div className="font-mono tabular-nums">
                      {data.chunking.semantic_quality.needs_review} ({pct(data.chunking.semantic_quality.needs_review_ratio)})
                    </div>
                    <div className="text-muted-foreground">Density mean</div>
                    <div className="font-mono tabular-nums">{fmt(data.chunking.semantic_quality.mean_information_density)}</div>
                    <div className="text-muted-foreground">Complete mean</div>
                    <div className="font-mono tabular-nums">{fmt(data.chunking.semantic_quality.mean_semantic_completeness)}</div>
                    <div className="text-muted-foreground">Self-contained mean</div>
                    <div className="font-mono tabular-nums">{fmt(data.chunking.semantic_quality.mean_self_containedness)}</div>
                  </div>
                </div>
              ) : null}
            </Panel>

            <Panel variant="glass" className="rounded-2xl">
              <div className="text-sm font-semibold text-foreground">KG</div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="text-muted-foreground">Events</div>
                <div className="font-mono tabular-nums">{fmt((data.kg as any)?.summary?.events)}</div>
                <div className="text-muted-foreground">Entities</div>
                <div className="font-mono tabular-nums">{fmt((data.kg as any)?.summary?.entities)}</div>
                <div className="text-muted-foreground">Relations</div>
                <div className="font-mono tabular-nums">{fmt((data.kg as any)?.summary?.relations)}</div>
                <div className="text-muted-foreground">Isolated ratio</div>
                <div className="font-mono tabular-nums">
                  {(() => {
                    const r = safeNumber((data.kg as any)?.summary?.isolated_entity_ratio)
                    return r === null ? '—' : pct(r, 2)
                  })()}
                </div>
                <div className="text-muted-foreground">Components</div>
                <div className="font-mono tabular-nums">{fmt((data.kg as any)?.components?.components)}</div>
                <div className="text-muted-foreground">Largest comp.</div>
                <div className="font-mono tabular-nums">
                  {(() => {
                    const r = safeNumber((data.kg as any)?.components?.largest_component_ratio)
                    return r === null ? '—' : pct(r, 2)
                  })()}
                </div>
              </div>
            </Panel>

            <Panel variant="glass" className="rounded-2xl">
              <div className="text-sm font-semibold text-foreground">检索命中（最近）</div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="text-muted-foreground">Metrics</div>
                <div className="font-mono">{retrievalHitsStatus}</div>
                <div className="text-muted-foreground">Window</div>
                <div className="font-mono tabular-nums">{data.retrieval_hits?.window_minutes ?? '—'} min</div>
                <div className="text-muted-foreground">Traces</div>
                <div className="font-mono tabular-nums">{data.retrieval_hits?.traces_scanned ?? 0}</div>
                <div className="text-muted-foreground">Traces w/ hits</div>
                <div className="font-mono tabular-nums">{data.retrieval_hits?.traces_with_hits ?? 0}</div>
                <div className="text-muted-foreground">Citations</div>
                <div className="font-mono tabular-nums">{data.retrieval_hits?.citations_matched ?? 0}</div>
                <div className="text-muted-foreground">Hit rate</div>
                <div className="font-mono tabular-nums">{pct(data.retrieval_hits?.hit_rate, 2)}</div>
              </div>

              {retrievalMetricsDisabled ? (
                <div className="mt-4 text-xs text-muted-foreground">
                  提示：需要启用后端 metrics 日志（ENABLE_METRICS_LOG=true）才能统计命中频率。
                </div>
              ) : null}
            </Panel>
          </div>
        ) : null}
      </PageScaffold>
    </AppFrame>
  )
}
