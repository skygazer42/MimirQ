'use client'

	import * as React from 'react'
	import { Loader2, Route, Quote, Timer, Database, ExternalLink, Download, GitCompare } from 'lucide-react'
	import { toast } from 'sonner'

import { chatApi, healthApi, metaApi, observabilityApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'
	import { Badge } from '@/components/ui/badge'
	import { Button } from '@/components/ui/button'
	import { EmptyState } from '@/components/ui/empty-state'
	import { Input } from '@/components/ui/input'
	import { Panel } from '@/components/ui/panel'
	import { ScrollArea } from '@/components/ui/scroll-area'
	import type { RagTrace, RagTraceBundleDiffResponse, RagTraceCitation, RagTraceListResponse } from '@/types'

function formatTs(tsMs: number) {
  try {
    return new Date(tsMs).toLocaleString()
  } catch {
    return String(tsMs)
  }
}

function formatSec(sec?: number | null) {
  if (sec == null || !Number.isFinite(sec)) return '—'
  if (sec < 1) return `${Math.round(sec * 1000)}ms`
  return `${sec.toFixed(2)}s`
}

function shortHash(value: string, opts?: { head?: number; tail?: number }) {
  const v = String(value || '').trim()
  if (!v) return ''
  const head = Math.max(1, Number(opts?.head ?? 8) || 8)
  const tail = Math.max(0, Number(opts?.tail ?? 4) || 4)
  if (v.length <= head + tail + 1) return v
  return `${v.slice(0, head)}...${v.slice(-tail)}`
}

function safeIsoForFilename(ts: string) {
  return (ts || new Date().toISOString()).replaceAll(/[:.]/g, '-')
}

function safeIdForFilename(value: string) {
  return String(value || '')
    .trim()
    .replaceAll(/[^a-zA-Z0-9_-]+/g, '_')
    .slice(0, 80) || 'request'
}

function formatScore(v?: number | null, digits = 3) {
  if (v == null) return null
  const n = Number(v)
  if (!Number.isFinite(n)) return null
  return n.toFixed(digits)
}

function isNonZero(v?: number | null, eps = 1e-12) {
  if (v == null) return false
  const n = Number(v)
  if (!Number.isFinite(n)) return false
  return Math.abs(n) > eps
}

function formatDiffValue(value: any, maxLen = 160): string {
  if (value == null) return '—'
  if (typeof value === 'string') return value.trim() ? value : '—'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    const s = JSON.stringify(value)
    if (!s) return '—'
    return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s
  } catch {
    const s = String(value)
    return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s
  }
}

function getPrimaryScore(c: RagTraceCitation) {
  // Prefer rerank score when available.
  const v = c.rerank_score ?? c.retrieval_score ?? c.relevance_score ?? null
  if (v == null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export type PipelineTimelineStep = {
  key: string
  label: string
  elapsedSec: number
  share: number
  width: number
  mode: string | null
  queryCount: number | null
  itemCount: number | null
  topK: number | null
  rerankTopN: number | null
}

function asFiniteNumber(value: unknown): number | null {
  if (value == null) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function getMetaNumber(meta: Record<string, unknown> | null, key: string): number | null {
  if (!meta) return null
  return asFiniteNumber(meta[key])
}

export function buildPipelineTimelineSteps(trace: RagTrace | null): PipelineTimelineStep[] {
  const rawSteps = trace?.steps || []
  if (!rawSteps.length) return []

  const stepRows = rawSteps.map((step) => {
    const elapsed = Math.max(0, asFiniteNumber(step.elapsed_sec) ?? 0)
    const lowerKey = String(step.key || '').toLowerCase()
    const meta = (step.meta ?? null) as Record<string, unknown> | null
    const mode = typeof meta?.mode === 'string' ? meta.mode : null
    const queryCount = getMetaNumber(meta, 'query_count') ?? (lowerKey.includes('retriev') ? asFiniteNumber(trace?.retrieval?.query_count) : null)
    const itemCount = getMetaNumber(meta, 'count')
    const topK = lowerKey.includes('retriev') ? asFiniteNumber(trace?.retrieval?.top_k) : null
    const rerankTopN = lowerKey.includes('rerank') ? asFiniteNumber(trace?.rerank?.top_n) : null

    return {
      key: String(step.key || step.label || 'step'),
      label: String(step.label || step.key || 'step'),
      elapsedSec: elapsed,
      mode,
      queryCount,
      itemCount,
      topK,
      rerankTopN,
    }
  })

  const maxElapsed = stepRows.reduce((acc, s) => Math.max(acc, s.elapsedSec), 0)
  const totalElapsed = stepRows.reduce((acc, s) => acc + s.elapsedSec, 0)

  return stepRows.map((s) => ({
    ...s,
    share: totalElapsed > 0 ? (s.elapsedSec / totalElapsed) * 100 : 0,
    width: maxElapsed > 0 ? (s.elapsedSec / maxElapsed) * 100 : 0,
  }))
}

export function RagTracePipelineTimeline({ steps }: Readonly<{ steps: PipelineTimelineStep[] }>) {
  return (
    <div className="p-4 space-y-2">
      {steps.length ? (
        steps.map((step) => {
          const barWidth = step.width > 0 ? Math.max(step.width, 6) : 0
          const shareLabel = Number.isFinite(step.share) ? `${step.share.toFixed(1)}%` : '—'
          return (
            <div key={step.key} className="space-y-1 rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-semibold text-foreground">{step.label}</div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    share={shareLabel}
                    {step.mode ? ` · mode=${step.mode}` : null}
                    {step.queryCount == null ? null : ` · queries=${step.queryCount}`}
                    {step.itemCount == null ? null : ` · count=${step.itemCount}`}
                    {step.topK == null ? null : ` · top_k=${step.topK}`}
                    {step.rerankTopN == null ? null : ` · top_n=${step.rerankTopN}`}
                  </div>
                </div>
                <div className="shrink-0 text-xs font-medium text-muted-foreground">{formatSec(step.elapsedSec)}</div>
              </div>
              <div className="h-1.5 w-full rounded-full bg-border/60">
                <div
                  className="h-full rounded-full bg-sky-500/70"
                  style={{ width: `${barWidth}%` }}
                  data-pipeline-share={shareLabel}
                />
              </div>
            </div>
          )
        })
      ) : (
        <div className="text-xs text-muted-foreground">pipeline steps unavailable</div>
      )}
    </div>
  )
}

type RagTracePanelProps = {
  conversationId: string
  className?: string
}

export function RagTracePanel({ conversationId, className }: Readonly<RagTracePanelProps>) {
  const { openDocument } = useDocumentView()

  const [data, setData] = React.useState<RagTraceListResponse | null>(null)
  const [loading, setLoading] = React.useState(false)
	const [selectedIndex, setSelectedIndex] = React.useState(0)
	const [bundleDownloading, setBundleDownloading] = React.useState(false)
	const [bundleError, setBundleError] = React.useState<string | null>(null)
	const bundleDownloadingRef = React.useRef(false)
	const [diffOpen, setDiffOpen] = React.useState(false)
	const [diffOtherRequestId, setDiffOtherRequestId] = React.useState('')
	const [diffLoading, setDiffLoading] = React.useState(false)
	const [diffError, setDiffError] = React.useState<string | null>(null)
	const [diffResult, setDiffResult] = React.useState<RagTraceBundleDiffResponse | null>(null)

  const items = data?.items ?? []
  const selected = items[selectedIndex] ?? items[0] ?? null
  const retrievalConfigHash = selected?.retrieval?.retrieval_config_hash || null
  const mainQuery = (selected?.retrieval?.per_query || []).find((q) => q?.kind === 'main') ?? (selected?.retrieval?.per_query || [])[0] ?? null
  const channels = (mainQuery?.retriever_debug as any)?.channels as Record<string, any> | null | undefined
  const hierarchyRecall = (mainQuery?.retriever_debug as any)?.hierarchy_recall as Record<string, any> | null | undefined
  const rerankMeta = (channels as any)?.rerank as Record<string, any> | null | undefined
  const rerankSkipReason = rerankMeta?.skip_reason ? String(rerankMeta.skip_reason) : null
  const rerankError = rerankMeta?.error ? String(rerankMeta.error) : null
  const requestId = String(selected?.request_id || '').trim()
  const pipelineSteps = React.useMemo(() => buildPipelineTimelineSteps(selected), [selected])

  const downloadBundle = React.useCallback(async () => {
    const rid = requestId
    if (!rid) return
    if (bundleDownloadingRef.current) return

    bundleDownloadingRef.current = true
    setBundleDownloading(true)
    setBundleError(null)
    try {
      const [meta, ready, configSnapshot, traceBundle] = await Promise.all([
        metaApi.get(),
        healthApi.ready(),
        observabilityApi.getOpsConfigSnapshot(),
        observabilityApi.getRagTraceBundle({ request_id: rid }),
      ])

      const { default: JSZip } = await import('jszip')
      const zip = new JSZip()
      zip.file('meta.json', JSON.stringify(meta, null, 2))
      zip.file('health_ready.json', JSON.stringify(ready, null, 2))
      zip.file('config_snapshot.json', JSON.stringify(configSnapshot, null, 2))
      zip.file('trace_bundle.json', JSON.stringify(traceBundle, null, 2))
      zip.file(
        'README.txt',
        [
          'MimirQ Incident Bundle (PII-safe)',
          `exported_at: ${new Date().toISOString()}`,
          `request_id: ${rid}`,
          '',
          'Files:',
          '- meta.json',
          '- health_ready.json',
          '- config_snapshot.json',
          '- trace_bundle.json',
          '',
          'Notes:',
          '- query text is NOT included; only hashes/aggregates are exported.',
          '- trace_bundle.json is produced by /api/v1/observability/rag-metrics/trace-bundle',
        ].join('\n')
      )

      const blob = await zip.generateAsync({ type: 'blob' })
      const filename = `incident_bundle_${safeIdForFilename(rid)}_${safeIsoForFilename(new Date().toISOString())}.zip`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      toast.success('已下载 incident bundle')
    } catch (err) {
      const msg = formatApiError(err, '下载 bundle 失败')
      setBundleError(msg)
      toast.error(msg)
    } finally {
      bundleDownloadingRef.current = false
      setBundleDownloading(false)
    }
	  }, [requestId])

	  const runDiff = React.useCallback(async () => {
	    const a = requestId
	    const b = diffOtherRequestId.trim()
	    if (!a || !b) return
	    if (a === b) {
	      toast.error('请提供两个不同的 request_id')
	      return
	    }

	    setDiffLoading(true)
	    setDiffError(null)
	    try {
	      const res = await observabilityApi.getRagTraceBundleDiff({ request_id_a: a, request_id_b: b })
	      setDiffResult(res)
	    } catch (err) {
	      const msg = formatApiError(err, '加载 diff 失败')
	      setDiffResult(null)
	      setDiffError(msg)
	      toast.error(msg)
	    } finally {
	      setDiffLoading(false)
	    }
	  }, [diffOtherRequestId, requestId])

	  React.useEffect(() => {
	    // Clear diff results when switching the selected trace.
	    setDiffResult(null)
	    setDiffError(null)
	  }, [requestId])

	  const load = React.useCallback(async () => {
	    setLoading(true)
	    try {
	      const res = await chatApi.getRagTraces(conversationId, { limit: 40, window_minutes: 24 * 60 })
      setData(res)
      setSelectedIndex(0)
    } catch (err) {
      setData(null)
      toast.error(formatApiError(err, '加载 RAG Trace 失败'))
    } finally {
      setLoading(false)
    }
  }, [conversationId])

  React.useEffect(() => {
    detachPromise(load())
  }, [load])

  if (loading && !data) {
    return (
      <Panel className={cn('flex min-h-[420px] items-center justify-center', className)} variant="glass">
        <Loader2 className="h-6 w-6 animate-spin motion-reduce:animate-none text-muted-foreground" />
      </Panel>
    )
  }

  if (!data?.enabled) {
    return (
      <EmptyState
        className={className}
        title="RAG Trace 未启用"
        description={
          <span>
            后端未开启 metrics JSONL（ENABLE_METRICS_LOG=false），或当前环境未配置 METRICS_LOG_PATH。
          </span>
        }
        icon={Route}
        iconClassName="text-sky-600 dark:text-sky-400"
      />
    )
  }

  if (!items.length) {
    return (
      <EmptyState
        className={className}
        title="暂无 RAG Trace"
        description={
          <span className="space-y-1">
            <span className="block">提示：只有走到检索链路时才会记录 trace。</span>
            <span className="block text-xs">可尝试在该会话继续提问后再刷新。</span>
          </span>
        }
        icon={Quote}
        iconClassName="text-sky-600 dark:text-sky-400"
      >
        <Button variant="outline" onClick={load} className="rounded-xl">
          刷新
        </Button>
      </EmptyState>
    )
  }

  return (
    <div className={cn('grid grid-cols-1 gap-4 md:grid-cols-[260px,1fr]', className)}>
      <Panel variant="glass" padding="none" className="overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/60">
          <div className="flex items-center gap-2">
            <Route className="h-4 w-4 text-sky-600 dark:text-sky-400" />
            <div className="text-sm font-semibold">RAG Trace</div>
          </div>
          <Button variant="outline" size="sm" onClick={load} className="rounded-xl">
            刷新
          </Button>
        </div>
        <ScrollArea className="h-[420px]">
          <div className="p-2">
            {items.map((t, idx) => {
              const active = idx === selectedIndex
              const mode = t?.retrieval?.mode || '—'
              return (
                <button
                  key={`${t.ts_ms}-${t.request_id || idx}`}
                  type="button"
                  onClick={() => setSelectedIndex(idx)}
                  className={cn(
                    'w-full rounded-xl border px-3 py-2 text-left transition-colors',
                    'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background',
                    active
                      ? 'border-sky-500/60 bg-sky-500/10'
                      : 'border-border/60 hover:bg-muted/40'
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-xs font-medium text-foreground">{formatTs(t.ts_ms)}</div>
                    <Badge variant="soft" className="text-[10px]">
                      {mode}
                    </Badge>
                  </div>
                  <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                    <span>{t.citations_count} citations</span>
                    <span className="inline-flex items-center gap-1">
                      <Timer className="h-3 w-3" />
                      {formatSec(t?.retrieval?.elapsed_sec)}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </ScrollArea>
      </Panel>

      <div className="min-w-0 space-y-4">
        {selected ? (
          <>
            <Panel variant="glass" className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="soft" className="text-[10px]">
                    request: {selected.request_id || '—'}
                  </Badge>
                  <Badge variant="soft" className="text-[10px]">
                    mode: {selected?.retrieval?.mode || '—'}
                  </Badge>
                  {retrievalConfigHash ? (
                    <Badge
                      variant="soft"
                      className="text-[10px] font-mono"
                      title={retrievalConfigHash}
                    >
                      cfg: {shortHash(retrievalConfigHash)}
                    </Badge>
                  ) : null}
                  <Badge variant="soft" className="text-[10px]">
                    citations: {selected.citations_count}
                  </Badge>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Timer className="h-4 w-4" />
                    Retrieve {formatSec(selected?.retrieval?.elapsed_sec)} · Rerank {formatSec(selected?.rerank?.elapsed_sec)}
                  </div>
	                  <Button
	                    variant="outline"
	                    size="sm"
	                    className="gap-2 rounded-xl"
	                    disabled={!requestId || bundleDownloading}
	                    onClick={() => detachPromise(downloadBundle())}
	                    title="下载 request_id bundle（admin-only）"
	                  >
	                    {bundleDownloading ? (
	                      <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
	                    ) : (
	                      <Download className="h-4 w-4" />
	                    )}
	                    下载 bundle
	                  </Button>
	                  <Button
	                    variant="outline"
	                    size="sm"
	                    className="gap-2 rounded-xl"
	                    disabled={!requestId}
	                    onClick={() => setDiffOpen((v) => !v)}
	                    title="对比两个 request_id 的 trace bundle（admin-only）"
	                  >
	                    <GitCompare className="h-4 w-4" />
	                    对比
	                  </Button>
	                </div>
	              </div>

	              {bundleError ? (
	                <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
	                  {bundleError}
	                </div>
	              ) : null}

	              {diffOpen ? (
	                <Panel variant="muted" className="space-y-3">
	                  <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
	                    <div className="grid w-full grid-cols-1 gap-3 md:grid-cols-2">
	                      <div className="space-y-1">
	                        <div className="text-[11px] text-muted-foreground">request_id A</div>
	                        <Input value={requestId} readOnly className="font-mono text-xs" />
	                      </div>
	                      <div className="space-y-1">
	                        <div className="text-[11px] text-muted-foreground">request_id B</div>
	                        <Input
	                          value={diffOtherRequestId}
	                          onChange={(e) => setDiffOtherRequestId(e.target.value)}
	                          placeholder="输入另一个 request_id"
	                          className="font-mono text-xs"
	                        />
	                      </div>
	                    </div>
	                    <Button
	                      variant="outline"
	                      size="sm"
	                      className="gap-2 rounded-xl"
	                      disabled={!requestId || !diffOtherRequestId.trim() || diffLoading}
	                      onClick={() => detachPromise(runDiff())}
	                    >
	                      {diffLoading ? (
	                        <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
	                      ) : (
	                        <GitCompare className="h-4 w-4" />
	                      )}
	                      比较
	                    </Button>
	                  </div>

	                  {diffError ? (
	                    <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
	                      {diffError}
	                    </div>
	                  ) : null}

	                  {diffResult ? (
	                    <div className="space-y-3">
	                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
	                        <div className="rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
	                          <div className="text-[11px] text-muted-foreground">A</div>
	                          <div className="mt-1 text-xs text-muted-foreground">
	                            mode={diffResult.summary_a?.retrieval_mode || '—'} · cfg=
	                            {diffResult.summary_a?.retrieval_config_hash ? shortHash(diffResult.summary_a.retrieval_config_hash) : '—'} · citations=
	                            {diffResult.summary_a?.citations_count ?? '—'}
	                          </div>
	                        </div>
	                        <div className="rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
	                          <div className="text-[11px] text-muted-foreground">B</div>
	                          <div className="mt-1 text-xs text-muted-foreground">
	                            mode={diffResult.summary_b?.retrieval_mode || '—'} · cfg=
	                            {diffResult.summary_b?.retrieval_config_hash ? shortHash(diffResult.summary_b.retrieval_config_hash) : '—'} · citations=
	                            {diffResult.summary_b?.citations_count ?? '—'}
	                          </div>
	                        </div>
	                      </div>

	                      <div className="text-[11px] text-muted-foreground">
	                        changes: {diffResult.diff?.length ?? 0} · truncated: {diffResult.truncated ? 'yes' : 'no'}
	                      </div>
	                      <div className="space-y-2">
	                        {(diffResult.diff || []).map((it) => (
	                          <div
	                            key={String(it.key)}
	                            className="grid grid-cols-1 gap-2 rounded-xl border border-border/60 bg-muted/20 px-3 py-2 md:grid-cols-3"
	                          >
	                            <div className="text-xs font-mono text-foreground">{it.key}</div>
	                            <div className="text-xs text-muted-foreground break-words">{formatDiffValue(it.a)}</div>
	                            <div className="text-xs text-muted-foreground break-words">
	                              {formatDiffValue(it.b)}
	                              {it.delta != null && Number.isFinite(Number(it.delta)) ? (
	                                <span className="ml-2 font-mono text-[11px] text-foreground/80">Δ {String(it.delta)}</span>
	                              ) : null}
	                            </div>
	                          </div>
	                        ))}
	                      </div>
	                    </div>
	                  ) : null}
	                </Panel>
	              ) : null}

	              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <Panel variant="muted" className="flex items-center gap-3">
                  <Timer className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                  <div>
                    <div className="text-xs font-semibold text-foreground">Retrieve</div>
                    <div className="text-xs text-muted-foreground">{formatSec(selected?.retrieval?.elapsed_sec)}</div>
                  </div>
                </Panel>
                <Panel variant="muted" className="flex items-center gap-3">
                  <Database className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                  <div>
                    <div className="text-xs font-semibold text-foreground">Reranker</div>
                    <div className="text-xs text-muted-foreground">
                      {selected?.rerank?.enabled ? selected?.rerank?.provider || 'enabled' : 'disabled'}
                    </div>
                  </div>
                </Panel>
                <Panel variant="muted" className="flex items-center gap-3">
                  <Quote className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                  <div>
                    <div className="text-xs font-semibold text-foreground">Citations</div>
                    <div className="text-xs text-muted-foreground">{selected.citations_count}</div>
                  </div>
                </Panel>
              </div>
            </Panel>

            <Panel variant="glass" className="overflow-hidden" padding="none">
              <div className="px-4 py-3 border-b border-border/60">
                <div className="text-sm font-semibold">Pipeline Timeline</div>
              </div>
              <RagTracePipelineTimeline steps={pipelineSteps} />
            </Panel>

            <Panel variant="glass" className="overflow-hidden" padding="none">
              <div className="px-4 py-3 border-b border-border/60">
                <div className="text-sm font-semibold">Channels</div>
              </div>
              <div className="p-4 space-y-3">
                {channels ? (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      {channels.retrieval_mode ? (
                        <Badge variant="soft" className="text-[10px]">
                          mode={String(channels.retrieval_mode)}
                        </Badge>
                      ) : null}
                      {channels.fusion_strategy ? (
                        <Badge variant="soft" className="text-[10px]">
                          fusion={String(channels.fusion_strategy)}
                        </Badge>
                      ) : null}
                      {channels.vector_backend ? (
                        <Badge variant="soft" className="text-[10px]">
                          vec={String(channels.vector_backend)}
                        </Badge>
                      ) : null}
                      {typeof channels.rrf_k === 'number' ? (
                        <Badge variant="soft" className="text-[10px]">
                          rrf_k={channels.rrf_k}
                        </Badge>
                      ) : null}
                      {channels?.timing?.vector_ms == null ? null : (
                        <Badge variant="soft" className="text-[10px]">
                          vector_ms={channels.timing.vector_ms}
                        </Badge>
                      )}
                      {channels?.timing?.bm25_ms == null ? null : (
                        <Badge variant="soft" className="text-[10px]">
                          bm25_ms={channels.timing.bm25_ms}
                        </Badge>
                      )}
                      {channels?.timing?.fusion_ms == null ? null : (
                        <Badge variant="soft" className="text-[10px]">
                          fusion_ms={channels.timing.fusion_ms}
                        </Badge>
                      )}
                    </div>

                    {hierarchyRecall ? (
                      <div className="flex flex-wrap items-center gap-2">
                        {hierarchyRecall.enabled == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            hierarchy={hierarchyRecall.enabled ? 'on' : 'off'}
                          </Badge>
                        )}
                        {hierarchyRecall.family_collapse == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            family_collapse={String(Boolean(hierarchyRecall.family_collapse))}
                          </Badge>
                        )}
                        {hierarchyRecall.family_aggregation ? (
                          <Badge variant="soft" className="text-[10px]">
                            family_aggregation={String(hierarchyRecall.family_aggregation)}
                          </Badge>
                        ) : null}
                        {hierarchyRecall.tree_dedup == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            tree_dedup={String(Boolean(hierarchyRecall.tree_dedup))}
                          </Badge>
                        )}
                        {hierarchyRecall.overfetch_factor == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            overfetch_factor={String(hierarchyRecall.overfetch_factor)}
                          </Badge>
                        )}
                        {hierarchyRecall.parent_depth == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            parent_depth={String(hierarchyRecall.parent_depth)}
                          </Badge>
                        )}
                        {hierarchyRecall.sibling_window == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            sibling_window={String(hierarchyRecall.sibling_window)}
                          </Badge>
                        )}
                        {hierarchyRecall.context_expansion_used == null ? null : (
                          <Badge variant="soft" className="text-[10px]">
                            context_expansion_used={String(Boolean(hierarchyRecall.context_expansion_used))}
                          </Badge>
                        )}
                        {hierarchyRecall.context_expansion_error ? (
                          <Badge variant="soft" className="text-[10px]">
                            context_expansion_error={String(hierarchyRecall.context_expansion_error)}
                          </Badge>
                        ) : null}
                      </div>
                    ) : null}

                    {(rerankSkipReason || rerankError) ? (
                      <div className="flex flex-wrap items-center gap-2">
                        {rerankSkipReason ? (
                          <Badge variant="soft" className="text-[10px]">
                            skip_reason={rerankSkipReason}
                          </Badge>
                        ) : null}
                        {rerankError ? (
                          <Badge variant="soft" className="text-[10px]">
                            rerank_error={rerankError}
                          </Badge>
                        ) : null}
                      </div>
                    ) : null}

                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                      {(['vector', 'colbert_ann', 'bm25', 'lexical_db', 'sparse']).map((k) => {
                        const box = (channels as any)?.[k] as Record<string, any> | null | undefined
                        if (!box) return null
                        return (
                          <Panel key={k} variant="muted" className="flex items-center justify-between gap-3">
                            <div className="min-w-0">
                              <div className="text-xs font-semibold text-foreground">{k}</div>
                              <div className="mt-0.5 text-[11px] text-muted-foreground">
                                {box.enabled == null ? null : `enabled=${String(box.enabled)}`}
                                {box.used == null ? null : ` · used=${String(box.used)}`}
                                {box.filter_applied == null ? null : ` · filter=${String(box.filter_applied)}`}
                                {box.index_enabled == null ? null : ` · index=${String(box.index_enabled)}`}
                                {box.provider ? ` · provider=${String(box.provider)}` : null}
                                {box.skipped_reason ? ` · skipped=${String(box.skipped_reason)}` : null}
                              </div>
                            </div>
                            <div className="shrink-0 text-xs font-medium text-muted-foreground">
                              {box.candidates == null ? '—' : `${box.candidates}`}
                            </div>
                          </Panel>
                        )
                      })}
                    </div>
                  </>
                ) : (
                  <div className="text-xs text-muted-foreground">暂无 per-channel 指标（旧 trace 或 retriever_debug 被裁剪）。</div>
                )}
              </div>
            </Panel>

            <Panel variant="glass" className="overflow-hidden" padding="none">
              <div className="px-4 py-3 border-b border-border/60">
                <div className="text-sm font-semibold">TopK Citations</div>
              </div>
              <ScrollArea className="h-[360px]">
                <div className="p-2">
                  {(selected.citations || []).map((c, idx) => {
                    const score = getPrimaryScore(c)
                    const docId = c.document_id || ''
                    const chunkId = c.chunk_id || ''
                    const page = c.page_number == null ? null : `p.${c.page_number}`
                    const rerankScore = formatScore(c.rerank_score, 3)
                    const retrievalScore = formatScore(c.retrieval_score, 3)
                    const relScore = formatScore(c.relevance_score, 3)
                    const vectorScore = isNonZero(c.vector_score) ? formatScore(c.vector_score, 3) : null
                    const bm25Score = isNonZero(c.bm25_score) ? formatScore(c.bm25_score, 3) : null
                    const lexicalScore = isNonZero(c.lexical_score) ? formatScore(c.lexical_score, 3) : null
                    const sparseScore = isNonZero(c.sparse_score) ? formatScore(c.sparse_score, 3) : null
                    const colbertScore = isNonZero(c.colbert_score) ? formatScore(c.colbert_score, 3) : null
                    const role = c.retrieval_role ? String(c.retrieval_role) : null
                    const neighborOf = c.neighbor_of ? String(c.neighbor_of) : null
                    return (
                      <div
                        key={`${docId}:${chunkId}:${role || ''}:${neighborOf || ''}`}
                        className="flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card/40 px-3 py-2"
                      >
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="soft" className="text-[10px]">
                              {c.hit_type || 'hit'}
                            </Badge>
                            {role ? (
                              <Badge variant="soft" className="text-[10px]">
                                role={role}
                              </Badge>
                            ) : null}
                            {neighborOf ? (
                              <Badge variant="soft" className="text-[10px]" title={neighborOf}>
                                neighbor_of={shortHash(neighborOf, { head: 10, tail: 6 })}
                              </Badge>
                            ) : null}
                            {score == null ? null : (
                              <Badge variant="soft" className="text-[10px]">
                                score={score.toFixed(3)}
                              </Badge>
                            )}
                            {rerankScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                rerank={rerankScore}
                              </Badge>
                            ) : null}
                            {retrievalScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                retrieval={retrievalScore}
                              </Badge>
                            ) : null}
                            {relScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                rel={relScore}
                              </Badge>
                            ) : null}
                            {vectorScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                v={vectorScore}
                              </Badge>
                            ) : null}
                            {bm25Score ? (
                              <Badge variant="soft" className="text-[10px]">
                                bm25={bm25Score}
                              </Badge>
                            ) : null}
                            {lexicalScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                lex={lexicalScore}
                              </Badge>
                            ) : null}
                            {sparseScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                sparse={sparseScore}
                              </Badge>
                            ) : null}
                            {colbertScore ? (
                              <Badge variant="soft" className="text-[10px]">
                                colbert={colbertScore}
                              </Badge>
                            ) : null}
                            {page ? (
                              <Badge variant="soft" className="text-[10px]">
                                {page}
                              </Badge>
                            ) : null}
                            {c.has_image ? (
                              <Badge variant="soft" className="text-[10px]">
                                image
                              </Badge>
                            ) : null}
                          </div>
                          <div className="mt-1 text-[11px] text-muted-foreground break-all">
                            doc {docId || '—'}
                          </div>
                          <div className="text-[11px] text-muted-foreground break-all">
                            chunk {chunkId || '—'}
                          </div>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          className="rounded-xl"
                          disabled={!docId}
                          onClick={() => {
                            const start = c.start_char
                            const end = c.end_char
                            openDocument(docId, chunkId || undefined, start != null && end != null ? { start, end } : undefined)
                            toast.message('已打开引用文档', { description: '右侧面板可查看对应 chunk 位置' })
                          }}
                        >
                          <ExternalLink className="h-4 w-4" />
                          <span className="ml-1 hidden sm:inline">打开</span>
                        </Button>
                      </div>
                    )
                  })}
                </div>
              </ScrollArea>
            </Panel>
          </>
        ) : null}
      </div>
    </div>
  )
}
