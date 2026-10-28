'use client'
import { useCallback, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Download, Loader2, Search } from '@/components/icons';
import { useTranslations } from 'next-intl';
import { toast } from 'sonner';
import { AuthImage, AuthImageLink } from '@/components/auth-image';
import type { Citation, EvidenceRetrieveResponse } from '@/types';
import { datasetApi, ragApi } from '@/lib/api';
import { formatApiError } from '@/lib/api-errors';
import { resolveSafeCitationImageUrl } from '@/lib/citation-images';
import { queryKeys } from '@/lib/query-keys';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { OperationalWorkspace, DirectoryWorkspace, WorkspaceMetrics, WorkspaceNotice, workspaceStyles as ws } from '@/components/ui/operational-workspace';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';

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

export function EvidenceWorkbench({ tools }: { tools?: ReactNode }) {
  const t = useTranslations('EvidenceWorkbench')

  const DATASET_ALL = '__all__'
  const [datasetScope, setDatasetScope] = useState<string>(DATASET_ALL)
  const datasetId = datasetScope === DATASET_ALL ? undefined : datasetScope

  const [query, setQuery] = useState('')
  const [profile, setProfile] = useState<RetrievalProfile>('recall50')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [pane, setPane] = useState<'directory' | 'detail'>('directory')
  const [toolsOpen, setToolsOpen] = useState(false)
  const [result, setResult] = useState<EvidenceRetrieveResponse | null>(null)
  const intent = useMemo(() => ({ datasetScope, profile, query }), [datasetScope, profile, query])
  const intentRef = useRef(intent)
  useLayoutEffect(() => { intentRef.current = intent; setResult(null); setError(null); setRunning(false) }, [intent])

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
    const context = intentRef.current
    const q = query.trim()
    if (!q) return

    setPane('detail')
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

      if (intentRef.current !== context) return
      setResult(res)
      if (res?.has_evidence) {
        toast.success(t("toasts.foundEvidence"))
      } else if (res?.abstain_triggered) {
        toast.warning(t("toasts.abstainTriggered", { reason: res.abstain_reason || 'unknown' }))
      } else {
        toast.message(t("toasts.noEvidence"))
      }
    } catch (error: unknown) {
      if (intentRef.current === context) setError(formatApiError(error, t("errors.retrieveFailed")))
    } finally {
      if (intentRef.current === context) setRunning(false)
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


  const inputClass = 'h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring'
  const queryForm = <form className="space-y-5 p-4" onSubmit={event => { event.preventDefault(); void run() }}>
    <h2 className={ws.sectionTitle}>检索问题</h2>
    <label className="block space-y-2 text-[13px]">数据集<select aria-label="证据数据集" className={inputClass} value={datasetScope} disabled={datasetsLoading} onChange={event => setDatasetScope(event.target.value)}><option value={DATASET_ALL}>{t('controls.allDocuments')}</option>{datasetOptions.map(dataset => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select></label>
    {datasetsError ? <WorkspaceNotice retry={() => { void datasetsQuery.refetch() }}>{datasetsError}</WorkspaceNotice> : null}
    <label className="block space-y-2 text-[13px]">检索预设<select className={inputClass} value={profile} onChange={event => setProfile(event.target.value as RetrievalProfile)}><option value="recall50">{t('profiles.recall50')}</option><option value="coverage80">{t('profiles.coverage80')}</option><option value="recall20">{t('profiles.recall20')}</option></select></label>
    <label className="block space-y-2 text-[13px]">问题<Textarea aria-label="检索问题" value={query} onChange={event => setQuery(event.target.value)} placeholder={t('controls.queryPlaceholder')} className="min-h-40 text-sm leading-6" onKeyDown={event => { if (!event.nativeEvent.isComposing && (event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); if (!running && query.trim()) void run() } }} /></label>
    <div className="flex flex-wrap gap-2"><Button type="submit" disabled={!query.trim() || running}>{running ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Search className="size-4" />}{running ? '正在检索…' : '运行检索'}</Button><Button type="button" variant="ghost" onClick={reset} disabled={running}>清空结果</Button></div>
  </form>
  const outcome = result?.has_evidence ? '已找到证据' : result?.abstain_triggered ? '证据不足，已拒答' : '未找到证据'
  return <OperationalWorkspace title="证据调试" icon="rag-visualization" mode="canvas" context={datasetOptions.find(dataset => dataset.id === datasetScope)?.name || '全部文档'} actions={<><Button variant="outline" onClick={exportPack} disabled={!result || running}><Download className="size-4" /><span className="hidden sm:inline">导出结果</span></Button>{tools ? <Button variant="ghost" onClick={() => setToolsOpen(true)}>高级工具</Button> : null}</>}>
    <DirectoryWorkspace directory={queryForm} pane={pane} onPaneChange={setPane} directoryLabel="问题与范围" detailLabel="引用证据">
      {error ? <WorkspaceNotice retry={() => { void run() }} retryLabel="重新检索" pending={running}>{error}</WorkspaceNotice> : null}
      {running ? <p role="status" className="py-12 text-sm text-muted-foreground">正在检索当前问题的证据…</p> : result ? <>
        <div className="border-b border-border py-4"><h2 className={cn('text-lg font-semibold', result.abstain_triggered && !result.has_evidence ? ws.warning : 'text-foreground')}>{outcome}</h2><p className="mt-2 break-words text-sm leading-6 text-muted-foreground">{result.query_for_retrieval || query}</p>{result.abstain_reason ? <p className="mt-2 text-sm leading-6">{result.abstain_reason}</p> : null}</div>
        <WorkspaceMetrics items={[{ label: '可读引用', value: citations.length }, { label: '最高相关分', value: topRel }, { label: '检索耗时（秒）', value: elapsed }]} />
        <section aria-label="引用证据列表">{citations.map(citation => {
          const title = titleForCitation(citation, t('results.citations.fallbackTitle'))
          const image = citation.has_image && citation.img_url ? resolveSafeCitationImageUrl(citation.img_url) : null
          return <article key={`${citation.document_id}:${citation.chunk_id || ''}:${citation.page_number ?? ''}`} className="border-b border-border py-5"><header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h3 className="break-words text-[15px] font-semibold leading-6">{title}</h3>{citation.header_path ? <p className="mt-1 break-words text-[13px] text-muted-foreground">{citation.header_path}</p> : null}</div><span className="whitespace-nowrap text-[13px] text-muted-foreground">相关分 <b className="font-medium tabular-nums text-foreground">{scoreLabel(citation)}</b></span></header>
            {image ? <AuthImageLink src={image} className="relative mt-4 block h-32 w-48 overflow-hidden rounded-md border border-border" title="查看引用图片"><AuthImage src={image} alt="引用图片" fill unoptimized sizes="192px" className="object-contain" /></AuthImageLink> : null}
            {citation.chunk_content ? <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7">{citation.chunk_content}</p> : <p className="mt-4 text-[13px] text-muted-foreground">当前引用未返回正文</p>}
          </article>
        })}{!citations.length ? <div className={ws.empty}><h2>{result.abstain_triggered ? '当前问题没有足够的引用证据' : '当前结果未返回可读引用'}</h2><p>可调整问题表达或数据集范围后重新检索。</p></div> : null}</section>
        <details className="py-5 text-[13px]"><summary className="cursor-pointer font-medium">原始检索结果</summary><pre tabIndex={0} className="mt-4 max-h-96 overflow-auto bg-muted/30 p-4 text-xs leading-6">{JSON.stringify(result, null, 2)}</pre></details>
      </> : !error ? <div className={ws.empty}><h2>输入问题，查看检索证据</h2><p>选择范围与检索预设后运行；这里展示引用，不生成回答。</p></div> : null}
    </DirectoryWorkspace>
    <Dialog open={toolsOpen} onOpenChange={setToolsOpen}><DialogContent className={cn(ws.dialog, ws.wideDialog)} aria-describedby={undefined}><DialogHeader className={ws.dialogHeader}><DialogTitle>证据高级工具</DialogTitle></DialogHeader><div className={ws.dialogBody}>{tools}</div><DialogFooter className={ws.dialogFooter}><Button variant="outline" onClick={() => setToolsOpen(false)}>完成</Button></DialogFooter></DialogContent></Dialog>
  </OperationalWorkspace>
}
