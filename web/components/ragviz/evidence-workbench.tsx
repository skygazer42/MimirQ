'use client'
import { useLayoutEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, Search } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { z } from 'zod'
import { evidenceCitationSchema, formatEvidenceScore, type EvidenceCitation } from '@/lib/evidence-citations'
import { AuthImageLink } from '@/components/auth-image'
import type { EvidenceRetrieveResponse } from '@/types'
import type { EvidenceRetrieveInput } from '@/lib/api/rag'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { downloadBlob } from '@/lib/download'
import { datasetApi, ragApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { LoadingButton } from '@/components/ui/loading-button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  OperationalWorkspace,
  DirectoryWorkspace,
  WorkspaceMetrics,
  WorkspaceNotice,
  workspaceStyles as ws,
} from '@/components/ui/operational-workspace'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

const retrievalProfileSchema = z.enum(['recall50', 'coverage80', 'recall20'])
const DATASET_ALL = '__all__'

const evidenceViewSchema = z.object({
  citations: z.array(evidenceCitationSchema),
  metrics: z
    .object({
      top_relevance_score: z.number().nullish(),
      retrieval_elapsed_sec: z.number().nullish(),
    })
    .optional(),
})

type RetrievalProfile = z.infer<typeof retrievalProfileSchema>
type RetrievalRequest = {
  id: number
  sessionKey: string
  input: EvidenceRetrieveInput & {
    rag_config: NonNullable<EvidenceRetrieveInput['rag_config']> & { retrieval_profile: RetrievalProfile }
  }
}
type RetrievalResult = {
  request: RetrievalRequest
  response: EvidenceRetrieveResponse
  view: z.infer<typeof evidenceViewSchema>
}
type RetrievalState = { status: 'idle' } | { status: 'running' } | { status: 'error'; message: string }

function titleForCitation(citation: EvidenceCitation, unnamedTitle: string): string {
  const parts: string[] = []
  if (citation.document_name) parts.push(citation.document_name)
  else if (citation.document_id) parts.push(citation.document_id)
  else parts.push(unnamedTitle)
  if (citation.page_number !== undefined && citation.page_number !== null) parts.push(`P.${citation.page_number}`)
  if (citation.chunk_index !== undefined && citation.chunk_index !== null) parts.push(`#${citation.chunk_index}`)
  return parts.join(' · ')
}

function metricLabel(value: number | null | undefined): string {
  return value === undefined || value === null ? '未提供' : String(value)
}

export function EvidenceWorkbench({ tools }: { tools?: ReactNode }) {
  const t = useTranslations('EvidenceWorkbench')

  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const [datasetScope, setDatasetScope] = useState(DATASET_ALL)
  const datasetId = datasetScope === DATASET_ALL ? undefined : datasetScope
  const [query, setQuery] = useState('')
  const [profile, setProfile] = useState<RetrievalProfile>('recall50')
  const [retrieval, setRetrieval] = useState<RetrievalState>({ status: 'idle' })
  const [result, setResult] = useState<RetrievalResult | null>(null)
  const activeRequest = useRef<RetrievalRequest | null>(null)
  const requestNumber = useRef(0)
  const [pane, setPane] = useState<'directory' | 'detail'>('directory')
  const [toolsOpen, setToolsOpen] = useState(false)

  useLayoutEffect(() => {
    activeRequest.current = null
    setResult(null)
    setRetrieval({ status: 'idle' })
    return () => {
      activeRequest.current = null
    }
  }, [datasetScope, profile, query, sessionKey])

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
  })
  const datasetOptions =
    datasetsQuery.data === undefined ? [] : [...datasetsQuery.data].sort((a, b) => a.name.localeCompare(b.name))
  const datasetsLoading = datasetsQuery.isFetching
  const datasetsError = datasetsQuery.error ? formatApiError(datasetsQuery.error, t('errors.loadDatasetsFailed')) : null
  const running = retrieval.status === 'running'
  const error = retrieval.status === 'error' ? retrieval.message : null

  function reset() {
    setResult(null)
    setRetrieval({ status: 'idle' })
  }

  async function run() {
    const question = query.trim()
    if (question.length === 0 || activeRequest.current !== null) return
    const request: RetrievalRequest = {
      id: ++requestNumber.current,
      sessionKey,
      input: {
        query: question,
        history: [],
        dataset_id: datasetId,
        document_ids: [],
        rag_config: {
          retrieval_profile: profile,
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
      },
    }
    activeRequest.current = request
    setPane('detail')
    setRetrieval({ status: 'running' })
    const isCurrent = () => activeRequest.current === request && getAuthSessionKey() === request.sessionKey
    try {
      const response = await ragApi.retrieveEvidence(request.input)
      if (!isCurrent()) return
      const view = evidenceViewSchema.parse(response)
      setResult({ request, response, view })
      setRetrieval({ status: 'idle' })
      if (response.has_evidence) toast.success(t('toasts.foundEvidence'))
      else if (response.abstain_triggered) {
        const reason =
          response.abstain_reason === undefined || response.abstain_reason === null
            ? '未提供原因'
            : response.abstain_reason
        toast.warning(t('toasts.abstainTriggered', { reason }))
      } else toast.message(t('toasts.noEvidence'))
    } catch (error: unknown) {
      if (isCurrent()) setRetrieval({ status: 'error', message: formatApiError(error, t('errors.retrieveFailed')) })
    } finally {
      if (isCurrent()) activeRequest.current = null
    }
  }

  function exportPack() {
    if (result === null) return
    const { input } = result.request
    const exportedAt = new Date().toISOString()
    const timestamp = exportedAt.replaceAll(/[:.]/g, '-')
    const datasetLabel = input.dataset_id === undefined ? 'all' : input.dataset_id
    const payload = {
      ...result.response,
      version: 1,
      dataset_id: input.dataset_id === undefined ? null : input.dataset_id,
      query: input.query,
      retrieval_profile: input.rag_config.retrieval_profile,
      request: input,
      exported_at: exportedAt,
    }
    downloadBlob(
      `evidence-pack-${datasetLabel}-${timestamp}.json`,
      new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }),
    )
    toast.success(t('toasts.exportedPack'))
  }

  const response = result?.response
  const citations = result === null ? [] : result.view.citations
  const topRel = metricLabel(result?.view.metrics?.top_relevance_score)
  const elapsed = metricLabel(result?.view.metrics?.retrieval_elapsed_sec)
  const datasetName = datasetOptions.find((dataset) => dataset.id === datasetScope)?.name
  const context = datasetScope === DATASET_ALL ? '全部文档' : datasetName === undefined ? datasetScope : datasetName

  const inputClass =
    'h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring'
  const queryForm = (
    <form
      className="space-y-5 p-4"
      onSubmit={(event) => {
        event.preventDefault()
        void run()
      }}
    >
      <h2 className={ws.sectionTitle}>检索问题</h2>
      <label className="block space-y-2 text-[13px]">
        数据集
        <select
          aria-label="证据数据集"
          className={inputClass}
          value={datasetScope}
          disabled={datasetsLoading}
          onChange={(event) => setDatasetScope(event.target.value)}
        >
          <option value={DATASET_ALL}>{t('controls.allDocuments')}</option>
          {datasetOptions.map((dataset) => (
            <option key={dataset.id} value={dataset.id}>
              {dataset.name}
            </option>
          ))}
        </select>
      </label>
      {datasetsError ? (
        <WorkspaceNotice
          retry={() => {
            void datasetsQuery.refetch()
          }}
        >
          {datasetsError}
        </WorkspaceNotice>
      ) : null}
      <label className="block space-y-2 text-[13px]">
        检索预设
        <select
          className={inputClass}
          value={profile}
          onChange={(event) => setProfile(retrievalProfileSchema.parse(event.target.value))}
        >
          <option value="recall50">{t('profiles.recall50')}</option>
          <option value="coverage80">{t('profiles.coverage80')}</option>
          <option value="recall20">{t('profiles.recall20')}</option>
        </select>
      </label>
      <label className="block space-y-2 text-[13px]">
        问题
        <Textarea
          aria-label="检索问题"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t('controls.queryPlaceholder')}
          className="min-h-40 text-sm leading-6"
          onKeyDown={(event) => {
            if (!event.nativeEvent.isComposing && (event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.preventDefault()
              if (!running && query.trim()) void run()
            }
          }}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <LoadingButton type="submit" loading={running} disabled={query.trim().length === 0}>
          <Search className="size-4" />
          运行检索
        </LoadingButton>
        <Button type="button" variant="ghost" onClick={reset} disabled={running}>
          清空结果
        </Button>
      </div>
    </form>
  )
  const outcome = response?.has_evidence
    ? '已找到证据'
    : response?.abstain_triggered
      ? '证据不足，已拒答'
      : '未找到证据'
  return (
    <OperationalWorkspace
      title="证据调试"
      icon="rag-visualization"
      mode="canvas"
      context={context}
      actions={
        <>
          <Button variant="outline" aria-label="导出结果" onClick={exportPack} disabled={!result || running}>
            <Download className="size-4" />
            <span className="hidden sm:inline">导出结果</span>
          </Button>
          {tools ? (
            <Button variant="ghost" onClick={() => setToolsOpen(true)}>
              高级工具
            </Button>
          ) : null}
        </>
      }
    >
      <DirectoryWorkspace
        directory={queryForm}
        pane={pane}
        onPaneChange={setPane}
        directoryLabel="问题与范围"
        detailLabel="引用证据"
      >
        {error ? (
          <WorkspaceNotice
            retry={() => {
              void run()
            }}
            retryLabel="重新检索"
            pending={running}
          >
            {error}
          </WorkspaceNotice>
        ) : null}
        {running && result === null ? (
          <section role="status" aria-label="正在检索当前问题的证据" className="space-y-5 py-4">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-4 w-3/4" />
            <div className="grid grid-cols-3 gap-4 border-y border-border py-4">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-20 w-full" />
          </section>
        ) : result ? (
          <div aria-busy={running}>
            {running ? (
              <span role="status" className="sr-only">
                正在刷新检索证据
              </span>
            ) : null}
            <div className="border-b border-border py-4">
              <h2
                className={cn(
                  'text-lg font-semibold',
                  result.response.abstain_triggered && !result.response.has_evidence ? ws.warning : 'text-foreground',
                )}
              >
                {outcome}
              </h2>
              <p className="mt-2 break-words text-sm leading-6 text-muted-foreground">
                {result.response.query_for_retrieval.length === 0
                  ? '检索问题为空'
                  : result.response.query_for_retrieval}
              </p>
              {result.response.abstain_reason ? (
                <p className="mt-2 text-sm leading-6">{result.response.abstain_reason}</p>
              ) : null}
            </div>
            <WorkspaceMetrics
              items={[
                { label: '返回引用', value: citations.length },
                { label: '最高相关分', value: topRel },
                { label: '检索耗时（秒）', value: elapsed },
              ]}
            />
            <section key={result.request.id} aria-label="引用证据列表">
              {citations.map((citation, index) => {
                const title = titleForCitation(citation, t('results.citations.fallbackTitle'))
                const image =
                  citation.has_image && citation.img_url ? resolveSafeCitationImageUrl(citation.img_url) : null
                return (
                  <article key={index} className="border-b border-border py-5">
                    <header className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="break-words text-[15px] font-semibold leading-6">{title}</h3>
                        {citation.header_path ? (
                          <p className="mt-1 break-words text-[13px] text-muted-foreground">{citation.header_path}</p>
                        ) : null}
                      </div>
                      <span className="whitespace-nowrap text-[13px] text-muted-foreground">
                        相关分{' '}
                        <b className="font-medium tabular-nums text-foreground">{formatEvidenceScore(citation)}</b>
                      </span>
                    </header>
                    {image ? <AuthImageLink src={image} alt="引用图片" title="查看引用图片" className="mt-4" /> : null}
                    {citation.chunk_content !== undefined && citation.chunk_content !== null ? (
                      <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-7">
                        {citation.chunk_content.length === 0 ? '原文为空' : citation.chunk_content}
                      </p>
                    ) : (
                      <p className="mt-4 text-[13px] text-muted-foreground">当前引用未返回正文</p>
                    )}
                  </article>
                )
              })}
              {!citations.length ? (
                <div className={ws.empty}>
                  <h2>{result.response.abstain_triggered ? '当前问题没有足够的引用证据' : '当前结果未返回引用'}</h2>
                  <p>可调整问题表达或数据集范围后重新检索。</p>
                </div>
              ) : null}
            </section>
            <details className="py-5 text-[13px]">
              <summary className="cursor-pointer font-medium">原始检索结果</summary>
              <pre tabIndex={0} className="mt-4 max-h-96 overflow-auto bg-muted/30 p-4 text-xs leading-6">
                {JSON.stringify(result.response, null, 2)}
              </pre>
            </details>
          </div>
        ) : !error ? (
          <div className={ws.empty}>
            <h2>输入问题，查看检索证据</h2>
            <p>选择范围与检索预设后运行；这里展示引用，不生成回答。</p>
          </div>
        ) : null}
      </DirectoryWorkspace>
      <Dialog open={toolsOpen} onOpenChange={setToolsOpen}>
        <DialogContent className={cn(ws.dialog, ws.wideDialog)} aria-describedby={undefined}>
          <DialogHeader className={ws.dialogHeader}>
            <DialogTitle>证据高级工具</DialogTitle>
          </DialogHeader>
          <div className={ws.dialogBody}>{toolsOpen ? tools : null}</div>
          <DialogFooter className={ws.dialogFooter}>
            <Button variant="outline" onClick={() => setToolsOpen(false)}>
              完成
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </OperationalWorkspace>
  )
}
