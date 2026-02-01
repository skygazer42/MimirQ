'use client'

import * as React from 'react'
import { Loader2, Route, Quote, Timer, Database, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'

import { chatApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { cn } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { RagTrace, RagTraceCitation, RagTraceListResponse } from '@/types'

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

function getPrimaryScore(c: RagTraceCitation) {
  // Prefer rerank score when available.
  const v = c.rerank_score ?? c.retrieval_score ?? c.relevance_score ?? null
  if (v == null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

type RagTracePanelProps = {
  conversationId: string
  className?: string
}

export function RagTracePanel({ conversationId, className }: RagTracePanelProps) {
  const { openDocument } = useDocumentView()

  const [data, setData] = React.useState<RagTraceListResponse | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [selectedIndex, setSelectedIndex] = React.useState(0)

  const items = data?.items ?? []
  const selected = items[selectedIndex] ?? items[0] ?? null

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
    void load()
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
                  <Badge variant="soft" className="text-[10px]">
                    citations: {selected.citations_count}
                  </Badge>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Timer className="h-4 w-4" />
                  Retrieve {formatSec(selected?.retrieval?.elapsed_sec)} · Rerank {formatSec(selected?.rerank?.elapsed_sec)}
                </div>
              </div>

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
                <div className="text-sm font-semibold">Steps</div>
              </div>
              <div className="p-4 space-y-2">
                {(selected.steps || []).map((s) => (
                  <div key={s.key} className="flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-muted/20 px-3 py-2">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-foreground">{s.label}</div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {s.meta?.mode ? `mode=${s.meta.mode}` : null}
                        {s.meta?.query_count != null ? ` · queries=${s.meta.query_count}` : null}
                        {s.meta?.count != null ? ` · count=${s.meta.count}` : null}
                      </div>
                    </div>
                    <div className="shrink-0 text-xs font-medium text-muted-foreground">{formatSec(s.elapsed_sec)}</div>
                  </div>
                ))}
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
                    const page = c.page_number != null ? `p.${c.page_number}` : null
                    return (
                      <div
                        key={`${docId}:${chunkId}:${idx}`}
                        className="flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-card/40 px-3 py-2"
                      >
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="soft" className="text-[10px]">
                              {c.hit_type || 'hit'}
                            </Badge>
                            {score != null ? (
                              <Badge variant="soft" className="text-[10px]">
                                score={score.toFixed(3)}
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

