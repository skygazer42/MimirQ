'use client'

import { useCallback, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, Loader2, Search, X } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { AuthImage, AuthImageLink } from '@/components/auth-image'
import type { Citation, EvidenceRetrieveResponse } from '@/types'
import { datasetApi, ragApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import { queryKeys } from '@/lib/query-keys'
import { cn, detachPromise } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

type RetrievalProfile = 'recall50' | 'coverage80' | 'recall20'

type JsonRecord = Record<string, unknown>

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
  } finally {
    URL.revokeObjectURL(url)
  }
}

function scoreLabel(c: Citation): string {
  const raw = c.retrieval_score ?? c.rerank_score ?? c.relevance_score ?? c.vector_score ?? c.bm25_score ?? 0
  const n = Number(raw)
  if (Number.isFinite(n)) return n.toFixed(4)
  return '0.0000'
}

function titleForCitation(c: Citation, fallbackTitle: string): string {
  const parts: string[] = []
  if (c.document_name) parts.push(c.document_name)
  if (typeof c.page_number === 'number') parts.push(`P.${c.page_number}`)
  if (typeof c.chunk_index === 'number') parts.push(`#${c.chunk_index}`)
  return parts.join(' · ') || (c.document_id ? String(c.document_id) : fallbackTitle)
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function toOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

function toOptionalNumber(value: unknown): number | undefined {
  const next = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(next) ? next : undefined
}

function toOptionalBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

function toMetricLabel(value: unknown): string {
  if (value == null) return '-'
  const text = typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value).trim()
    : ''
  return text || '-'
}

function toCitation(value: unknown): Citation | null {
  if (!isRecord(value)) return null
  const document_id = typeof value.document_id === 'string' ? value.document_id : ''
  const document_name = typeof value.document_name === 'string' ? value.document_name : ''
  const chunk_content = typeof value.chunk_content === 'string' ? value.chunk_content : ''
  const relevance_score =
    typeof value.relevance_score === 'number' ? value.relevance_score : Number(value.relevance_score ?? 0) || 0
  if (!document_id || !document_name) return null

  const citation: Citation = { document_id, document_name, chunk_content, relevance_score }
  citation.chunk_id = toOptionalString(value.chunk_id)
  citation.page_number = toOptionalNumber(value.page_number)
  citation.chunk_index = toOptionalNumber(value.chunk_index)
  citation.header_path = toOptionalString(value.header_path)
  citation.has_image = toOptionalBoolean(value.has_image)
  citation.img_url = toOptionalString(value.img_url)
  return citation
}

export function EvidenceWorkbench() {
  const t = useTranslations('EvidenceWorkbench')

  const DATASET_ALL = '__all__'
  const [datasetScope, setDatasetScope] = useState<string>(DATASET_ALL)
  const datasetId = datasetScope === DATASET_ALL ? undefined : datasetScope

  const [query, setQuery] = useState('')
  const [profile, setProfile] = useState<RetrievalProfile>('recall50')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [result, setResult] = useState<EvidenceRetrieveResponse | null>(null)

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive({ purpose: 'evidence-workbench' }),
    queryFn: () => datasetApi.listAll(),
  })
  const datasets = useMemo(() => datasetsQuery.data || [], [datasetsQuery.data])
  const datasetsLoading = datasetsQuery.isFetching
  const datasetsError = datasetsQuery.error
    ? formatApiError(datasetsQuery.error, t("errors.loadDatasetsFailed"))
    : null

  const datasetOptions = useMemo(() => {
    const opts = (datasets || []).map((d) => ({ id: String(d.id), name: d.name || String(d.id) }))
    opts.sort((a, b) => a.name.localeCompare(b.name))
    return opts
  }, [datasets])

  const reset = useCallback(() => {
    setError(null)
    setResult(null)
  }, [])

  const run = useCallback(async () => {
    const q = query.trim()
    if (!q) return

    setRunning(true)
    setError(null)
    setResult(null)

    try {
      const res = await ragApi.retrieveEvidence({
        query: q,
        history: [],
        dataset_id: datasetId,
        document_ids: [],
        rag_config: {
          // Use presets so the backend can apply the full recall profile contract (not just top_k).
          retrieval_profile: profile,
          // Satisfy the strict OpenAPI schema (backend applies its own defaults anyway).
          max_tokens: 2000,
          retrieval_mode: 'hybrid',
          alpha: 0.6,
          enable_weight_rerank: true,
          vector_weight: 0.6,
          keyword_weight: 0.4,
          use_graph: false,
          visible_evidence_only: false,
          answer_mode: 'llm',
        },
      })

      setResult(res || null)
      if (res?.has_evidence) {
        toast.success(t("toasts.foundEvidence"))
      } else if (res?.abstain_triggered) {
        toast.warning(t("toasts.abstainTriggered", { reason: res.abstain_reason || 'unknown' }))
      } else {
        toast.message(t("toasts.noEvidence"))
      }
    } catch (error: unknown) {
      setError(formatApiError(error, t("errors.retrieveFailed")))
    } finally {
      setRunning(false)
    }
  }, [datasetId, profile, query, t])

  const exportPack = useCallback(() => {
    if (!result) return

    const exportedAt = new Date().toISOString()
    const safeTs = exportedAt.replaceAll(/[:.]/g, '-')
    const ds = datasetId || 'all'
    const filename = `evidence-pack-${ds}-${safeTs}.json`

    const payload = {
      version: 1,
      dataset_id: datasetId || null,
      query: query.trim(),
      retrieval_profile: profile,
      query_for_retrieval: result.query_for_retrieval || query.trim(),
      has_evidence: Boolean(result.has_evidence),
      abstain_triggered: Boolean(result.abstain_triggered),
      abstain_reason: result.abstain_reason ?? null,
      citations: result.citations || [],
      metrics: result.metrics || null,
      exported_at: exportedAt,
    }

    downloadJson(filename, payload)
    toast.success(t("toasts.exportedPack"))
  }, [datasetId, profile, query, result, t])

  const citations: Citation[] = useMemo(() => {
    const raw = result?.citations
    if (!Array.isArray(raw)) return []
    return raw.map(toCitation).filter((citation): citation is Citation => citation !== null)
  }, [result?.citations])
  const metrics = isRecord(result?.metrics) ? result.metrics : null
  const topRel = toMetricLabel(metrics?.top_relevance_score)
  const elapsed = toMetricLabel(metrics?.retrieval_elapsed_sec)

  return (
    <div className="space-y-4">
      <Panel variant="glass" className="p-4">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col md:flex-row gap-3 md:items-end">
            <div className="flex-1 min-w-0">
              <div className="text-xs text-muted-foreground mb-1">{t("controls.datasetScope")}</div>
              <Select value={datasetScope} onValueChange={(v) => setDatasetScope(String(v))}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t("controls.datasetPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DATASET_ALL}>{t("controls.allDocuments")}</SelectItem>
                  {datasetOptions.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {(() => {
    if (datasetsLoading) {
        return (<div className="mt-1 text-[11px] text-muted-foreground">{t("controls.loadingDatasets")}</div>);
    }
    else if (datasetsError) {
            return (<div className="mt-1 text-[11px] text-destructive">{datasetsError}</div>);
        }
        else {
            return null;
        }
})()}
            </div>

            <div className="w-full md:w-[220px]">
              <div className="text-xs text-muted-foreground mb-1">{t("controls.profile")}</div>
              <Select value={profile} onValueChange={(v) => setProfile(v as RetrievalProfile)}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder={t("controls.profilePlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="recall50">{t("profiles.recall50")}</SelectItem>
                  <SelectItem value="coverage80">{t("profiles.coverage80")}</SelectItem>
                  <SelectItem value="recall20">{t("profiles.recall20")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col md:flex-row gap-3 md:items-end">
            <div className="flex-1 min-w-0">
              <div className="text-xs text-muted-foreground mb-1">{t("controls.query")}</div>
              <Textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("controls.queryPlaceholder")}
                className="min-h-[44px]"
              />
            </div>

            <div className="flex items-center gap-2">
              <Button type="button" onClick={() => detachPromise(run())} disabled={!query.trim() || running}>
                {running ? (
                  <span className="inline-flex items-center gap-2">
                    <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                    {t("actions.searching")}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-2">
                    <Search className="size-4" />
                    {t("actions.search")}
                  </span>
                )}
              </Button>

              <Button type="button" variant="outline" onClick={reset} disabled={running && !result && !error}>
                <span className="inline-flex items-center gap-2">
                  <X className="size-4" />
                  {t("actions.reset")}
                </span>
              </Button>

              <Button type="button" variant="outline" onClick={exportPack} disabled={!result || running}>
                <span className="inline-flex items-center gap-2">
                  <Download className="size-4" />
                  {t("actions.export")}
                </span>
              </Button>
            </div>
          </div>

          {error ? (
            <div className="text-[11px] text-destructive bg-destructive/10 border border-destructive/25 px-2 py-1 rounded-lg">
              {error}
            </div>
          ) : null}
        </div>
      </Panel>

      {result ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Panel variant="glass" className="p-4 lg:col-span-1">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">{t("results.summary.title")}</div>
                <div className="text-xs text-muted-foreground mt-1">{t("results.summary.description")}</div>
              </div>
              <div
                className={cn(
                  'px-2 py-1 rounded-md text-xs font-mono border',
                  (() => {
    if (result.has_evidence) {
        return 'bg-success/10 border-success/20 text-success';
    }
    else if (result.abstain_triggered) {
            return 'bg-warning/10 border-warning/20 text-warning';
        }
        else {
            return 'bg-sidebar/45 border-sidebar-border/70 text-muted-foreground';
        }
})()
                )}
                title="has_evidence / abstain"
              >
                has_evidence={String(Boolean(result.has_evidence))}
              </div>
            </div>

            <div className="mt-3 space-y-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="text-muted-foreground">{t("results.summary.abstainTriggered")}</div>
                <div className="font-mono">{String(Boolean(result.abstain_triggered))}</div>
              </div>
              <div className="flex items-center justify-between gap-2">
                <div className="text-muted-foreground">{t("results.summary.abstainReason")}</div>
                <div className="font-mono max-w-[220px] truncate" title={String(result.abstain_reason || '')}>
                  {result.abstain_reason || '-'}
                </div>
              </div>
              <div className="flex items-center justify-between gap-2">
                <div className="text-muted-foreground">{t("results.summary.topRelevanceScore")}</div>
                <div className="font-mono">{topRel}</div>
              </div>
              <div className="flex items-center justify-between gap-2">
                <div className="text-muted-foreground">{t("results.summary.retrievalElapsed")}</div>
                <div className="font-mono">{elapsed}</div>
              </div>
              <div className="flex items-center justify-between gap-2">
                <div className="text-muted-foreground">{t("results.summary.citations")}</div>
                <div className="font-mono">{citations.length}</div>
              </div>
              <div className="pt-2">
                <div className="text-muted-foreground text-[11px]">{t("results.summary.queryForRetrieval")}</div>
                <Input
                  readOnly
                  value={result.query_for_retrieval || ''}
                  className="mt-1 border-sidebar-border/70 bg-sidebar/40 font-mono text-[12px]"
                />
              </div>
            </div>
          </Panel>

          <Panel variant="glass" className="p-4 lg:col-span-2">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold">{t("results.citations.title")}</div>
                <div className="text-xs text-muted-foreground mt-1">
                  {citations.length ? t("results.citations.hitsHint") : t("results.citations.emptyHits")}
                </div>
              </div>
            </div>

            {citations.length ? (
              <div className="mt-3 space-y-2 max-h-[560px] overflow-auto pr-1">
                {citations.map((c) => {
                  const content = String(c.chunk_content || '')
                  const safeImgUrl = c.has_image && c.img_url ? resolveSafeCitationImageUrl(c.img_url) : null
                  const citationTitle = titleForCitation(c, t("results.citations.fallbackTitle"))
                  return (
                    <div
                      key={`${String(c.document_id || '')}:${String(c.chunk_id || '')}:${String(c.page_number ?? '')}`}
                      className={cn(
                        'rounded-xl border border-sidebar-border/70 bg-sidebar/55 px-3 py-3 shadow-soft backdrop-blur-sm',
                        'hover:border-primary/25 hover:bg-sidebar/70 transition-colors'
                      )}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-xs font-medium truncate" title={citationTitle}>
                            {citationTitle}
                          </div>
                          {c.header_path ? (
                            <div className="text-[11px] text-muted-foreground truncate" title={String(c.header_path)}>
                              {c.header_path}
                            </div>
                          ) : null}
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {safeImgUrl ? (
                            <AuthImageLink
                              src={safeImgUrl}
                              className="shrink-0 relative h-10 w-14 rounded-md overflow-hidden border border-sidebar-border/70 bg-sidebar/40 shadow-soft/70"
                              title="Open image"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <AuthImage
                                src={safeImgUrl}
                                alt="citation thumbnail"
                                fill
                                unoptimized
                                sizes="56px"
                                className="object-cover"
                              />
                            </AuthImageLink>
                          ) : null}
                          <div className="text-[11px] text-muted-foreground">{t("results.citations.scoreLabel")}</div>
                          <div className="text-[11px] font-mono">{scoreLabel(c)}</div>
                        </div>
                      </div>

                      {content ? (
                        <pre className="mt-2 text-xs leading-relaxed whitespace-pre-wrap font-mono text-foreground/90 max-h-[180px] overflow-auto">
                          {content}
                        </pre>
                      ) : (
                        <div className="mt-2 text-[11px] text-muted-foreground">{t("results.citations.emptyContent")}</div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="mt-4 text-sm text-muted-foreground">{t("results.citations.noCitations")}</div>
            )}
          </Panel>
        </div>
      ) : null}
    </div>
  )
}
