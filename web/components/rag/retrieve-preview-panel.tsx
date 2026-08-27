'use client'

import { useCallback, useMemo, useRef, useState } from 'react'
import Image from 'next/image'
import {
  ArrowRight,
  ChevronRight,
  Copy,
  Database,
  ExternalLink,
  Loader2,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Zap,
} from 'lucide-react'
import type { Citation, EvidenceRetrieveRequest, EvidenceRetrieveResponse } from '@/types'
import { toast } from 'sonner'

import { AuthImage } from '@/components/auth-image'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ragApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { resolveSafeCitationImageUrl } from '@/lib/citation-images'
import { getDocumentPreviewAnchorFromCitation } from '@/lib/document-preview-anchor'
import { prefetchDocumentView } from '@/lib/document-view-prefetch'
import { cn, detachPromise } from '@/lib/utils'
import { useDocumentView } from '@/store/document-view'

type RetrievePreviewPanelProps = {
  selectedDatasetId: string | null | undefined
  availableDatasetIds?: readonly string[]
  className?: string
}

type JsonRecord = Record<string, unknown>

type RetrievePreviewCitation = Partial<
  Omit<Citation, 'matched_terms' | 'policy_clause_number' | 'policy_path_str'>
> & {
  document_id?: string
  document_name?: string
  chunk_id?: string
  chunk_content?: string
  matched_terms?: unknown
  retrieval_role?: string | null
  family_hit?: boolean | null
  family_collapse_key?: string | null
  hierarchy_family_key?: string | null
  has_image?: boolean | null
  img_url?: string | null
  file_url?: string | null
  score?: number | null
  text_range?: {
    start?: number
    end?: number
  } | null
  policy_clause_number?: string | null
  policy_path_str?: string | null
}

type RecentQueryItem = {
  query: string
  timestampLabel: string
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function buildRetrieveDatasetScope(
  selectedDatasetId: string | null | undefined,
  availableDatasetIds: readonly string[]
): Pick<EvidenceRetrieveRequest, 'dataset_id' | 'dataset_ids'> {
  const selected = String(selectedDatasetId || '').trim()
  if (selected) return { dataset_id: selected }

  const datasetIds = Array.from(
    new Set(availableDatasetIds.map((id) => String(id || '').trim()).filter(Boolean))
  )
  return datasetIds.length ? { dataset_ids: datasetIds } : {}
}

function normalizeCitations(response: EvidenceRetrieveResponse): RetrievePreviewCitation[] {
  return Array.isArray(response.citations)
    ? response.citations.filter(isRecord).map((citation) => citation as RetrievePreviewCitation)
    : []
}

function formatRelativeNow(): string {
  return '刚刚'
}

function formatScore(value: unknown, digits = 3): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
}

function getHitScore(hit: RetrievePreviewCitation): number | null {
  const score = hit.score ?? hit.relevance_score ?? hit.retrieval_score
  return typeof score === 'number' && Number.isFinite(score) ? score : null
}

function toHitKey(hit: Pick<RetrievePreviewCitation, 'document_id' | 'chunk_id' | 'retrieval_role'>): string {
  return [
    String(hit.document_id || '').trim(),
    String(hit.chunk_id || '').trim(),
    String(hit.retrieval_role || '').trim(),
  ].join(':')
}

function previewChunkContent(value: string | undefined, maxLen = 360): string {
  const text = String(value || '').trim().replaceAll(/\s+/g, ' ')
  if (!text) return '该命中未返回可预览的 chunk 内容。'
  if (text.length <= maxLen) return text
  return `${text.slice(0, maxLen).trimEnd()}…`
}

function getMatchedTerms(hit: RetrievePreviewCitation): string[] {
  const terms = Array.isArray(hit.matched_terms) ? hit.matched_terms : []
  return terms.filter(Boolean).slice(0, 24).map(String)
}

const noResultActionTips = ['缩短问题', '切换数据集', '改用原文关键词', '补充条款编号'] as const
const noResultDiagnosticTips = [
  { title: '问题过长或太泛', description: '先压缩成一个核心问题，减少背景描述和泛化措辞。' },
  { title: '检索范围过窄', description: '切到更大的数据集范围，确认文档已完成解析和入库。' },
  { title: '表达不贴近原文', description: '优先使用条款编号、章节名、专有名词和原句关键词。' },
] as const

const recommendedQuestions = [
  '该产品的主要功能和优势有哪些？',
  '如何进行数据权限配置与管理？',
  '系统支持哪些数据源和接入方式？',
  '异常处理流程的关键步骤是什么？',
] as const

const seedRecentQueries: RecentQueryItem[] = [
  { query: '如何配置权限策略？', timestampLabel: '刚刚' },
  { query: '产品核心功能有哪些？', timestampLabel: '2 分钟前' },
  { query: '数据同步失败原因排查', timestampLabel: '15 分钟前' },
] as const
const RETRIEVAL_ADVANCED_PANEL_ID = 'retrieval-advanced-params'
const RETRIEVAL_HISTORY_PANEL_ID = 'retrieval-query-history'
const RETRIEVAL_RANGE_INPUT_CLASS =
  'relative z-10 h-5 w-full cursor-pointer appearance-none bg-transparent [&::-webkit-slider-runnable-track]:h-5 [&::-webkit-slider-runnable-track]:bg-transparent [&::-webkit-slider-thumb]:mt-0 [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-info/40 [&::-webkit-slider-thumb]:bg-background dark:[&::-webkit-slider-thumb]:border-foreground/10 dark:[&::-webkit-slider-thumb]:bg-background [&::-moz-range-track]:h-5 [&::-moz-range-track]:bg-transparent [&::-moz-range-progress]:h-5 [&::-moz-range-progress]:bg-transparent [&::-moz-range-thumb]:size-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-info/40 [&::-moz-range-thumb]:bg-background'
const RETRIEVAL_PANEL_SURFACE_CLASS =
  'border-foreground/10 bg-background shadow-none backdrop-blur-none dark:border-foreground/10 dark:bg-background'
const RETRIEVAL_CONTROL_SURFACE_CLASS =
  'border-foreground/10 bg-background shadow-none dark:border-foreground/10 dark:bg-background'

function SemanticRetrievalMark() {
  return (
    <div
      data-semantic-retrieval-mark="true"
      className="flex size-14 items-center justify-center rounded-xl border border-foreground/10 bg-background/70 shadow-none dark:border-foreground/10 dark:bg-background/70"
    >
      <Image
        src="/brand/mimirq-retrieval-mark.png"
        alt="MimirQ 语义检索标记"
        width={164}
        height={150}
        loading="eager"
        className="size-12 scale-110 object-contain"
      />
    </div>
  )
}

const EMPTY_DATASET_IDS: readonly string[] = []

export function RetrievePreviewPanel({
  selectedDatasetId,
  availableDatasetIds = EMPTY_DATASET_IDS,
  className,
}: Readonly<RetrievePreviewPanelProps>) {
  const { openDocument } = useDocumentView()
  const [searchQuery, setSearchQuery] = useState('')
  const [searchQueryForRetrieval, setSearchQueryForRetrieval] = useState('')
  const [searchResults, setSearchResults] = useState<RetrievePreviewCitation[]>([])
  const [activeHit, setActiveHit] = useState<RetrievePreviewCitation | null>(null)
  const [hasSearched, setHasSearched] = useState(false)
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [topK, setTopK] = useState('5')
  const [scoreThreshold, setScoreThreshold] = useState(0.7)
  const [advancedParamsOpen, setAdvancedParamsOpen] = useState(false)
  const [fullHistoryOpen, setFullHistoryOpen] = useState(false)
  const [retrievalMode, setRetrievalMode] = useState('hybrid')
  const [maxTokens, setMaxTokens] = useState('2000')
  const [alpha, setAlpha] = useState(0.6)
  const [enableWeightRerank, setEnableWeightRerank] = useState(true)
  const [recentQueries, setRecentQueries] = useState<RecentQueryItem[]>([...seedRecentQueries])
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const searchInputRef = useRef<HTMLTextAreaElement | null>(null)
  const prefetchedHitTargetsRef = useRef<Set<string>>(new Set())

  const activeResult = activeHit ?? searchResults[0] ?? null
  const visibleRecentQueries = useMemo(() => recentQueries.slice(0, 3), [recentQueries])
  const scoreThresholdPercent = Math.round(scoreThreshold * 100)
  const alphaPercent = Math.round(alpha * 100)
  const retrievalScope = useMemo(
    () => buildRetrieveDatasetScope(selectedDatasetId, availableDatasetIds),
    [availableDatasetIds, selectedDatasetId]
  )
  const hasRetrievalScope = Boolean(
    retrievalScope.dataset_id || retrievalScope.dataset_ids?.length
  )

  const handlePrefetchHitDocument = useCallback((hit: RetrievePreviewCitation) => {
    const documentId = String(hit.document_id || '').trim()
    if (!documentId) return

    prefetchDocumentView({
      documentId,
      chunkId: String(hit.chunk_id || '').trim() || null,
      rawFileUrl: typeof hit.file_url === 'string' ? hit.file_url : null,
    })
  }, [])

  const handleOpenHitInDocumentViewer = useCallback(
    (hit: RetrievePreviewCitation) => {
      const documentId = String(hit.document_id || '').trim()
      if (!documentId) return

      const chunkId = String(hit.chunk_id || '').trim() || undefined
      const rawRange = hit.text_range
      const range =
        rawRange && typeof rawRange.start === 'number' && typeof rawRange.end === 'number'
          ? { start: rawRange.start, end: rawRange.end }
          : undefined

      openDocument(documentId, chunkId, range, {
        previewAnchor: getDocumentPreviewAnchorFromCitation(hit),
      })
    },
    [openDocument]
  )

  const handleSearch = useCallback(async () => {
    const query = searchQuery.trim()
    if (!query || isSearching) return

    if (!hasRetrievalScope) {
      setSearchError('暂无可检索数据集，请先创建或选择数据集。')
      setHasSearched(true)
      setSearchResults([])
      setActiveHit(null)
      return
    }

    setIsSearching(true)
    setSearchError(null)
    try {
      const ragConfig: NonNullable<EvidenceRetrieveRequest['rag_config']> = {
        top_k: Number(topK),
        score_threshold: scoreThreshold,
        max_tokens: Number(maxTokens),
        retrieval_mode: retrievalMode,
        alpha,
        enable_weight_rerank: enableWeightRerank,
        vector_weight: Number(alpha.toFixed(2)),
        keyword_weight: Number((1 - alpha).toFixed(2)),
        use_graph: false,
        visible_evidence_only: false,
        answer_mode: 'llm',
      }

      const response = await ragApi.retrieveEvidence({
        query,
        ...retrievalScope,
        rag_config: ragConfig,
      })
      const citations = normalizeCitations(response)
      setSearchResults(citations)
      setSearchQueryForRetrieval(String(response.query_for_retrieval || query))
      setActiveHit(citations[0] ?? null)
      setHasSearched(true)
      setRecentQueries((prev) => [
        { query, timestampLabel: formatRelativeNow() },
        ...prev.filter((item) => item.query !== query),
      ].slice(0, 12))
    } catch (error) {
      setSearchError(formatApiError(error, '检索失败'))
      setHasSearched(true)
      setSearchResults([])
      setActiveHit(null)
    } finally {
      setIsSearching(false)
    }
  }, [
    alpha,
    enableWeightRerank,
    hasRetrievalScope,
    isSearching,
    maxTokens,
    retrievalMode,
    scoreThreshold,
    searchQuery,
    retrievalScope,
    topK,
  ])

  const handleApplySuggestedQuery = useCallback((query: string) => {
    setSearchQuery(query)
  }, [])

  const handleClearRecentQueries = useCallback(() => {
    setRecentQueries([])
    setFullHistoryOpen(false)
    toast.success('已清空当前会话检索历史')
  }, [])

  const handleReset = useCallback(() => {
    setSearchQuery('')
    setSearchQueryForRetrieval('')
    setSearchResults([])
    setActiveHit(null)
    setHasSearched(false)
    setSearchError(null)
  }, [])

  const resultStats = useMemo(() => {
    const total = searchResults.length
    const familyHits = searchResults.filter((hit) => Boolean(hit.family_hit)).length
    const hierarchyHits = searchResults.filter((hit) => {
      const role = String(hit.retrieval_role || '')
      return role.startsWith('hierarchy_')
    }).length
    return { total, familyHits, hierarchyHits }
  }, [searchResults])

  const renderComposer = (compact = false) => (
    <div
      className={cn(
        'rounded-xl border',
        RETRIEVAL_PANEL_SURFACE_CLASS,
        compact ? 'sticky top-0 z-20 rounded-xl' : ''
      )}
    >
      <div className={cn('flex flex-col gap-3.5', compact ? 'p-3.5' : 'p-4')}>
        {compact ? (
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-muted-foreground/68">
                Retrieval Workbench
              </div>
              <div className="mt-1 text-[15px] font-semibold tracking-[-0.03em] text-foreground">
                语义检索测试
              </div>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 rounded-md border border-foreground/10 bg-background/70 px-3 text-[12px] font-medium hover:bg-muted/20 dark:border-foreground/10 dark:bg-background/70"
              onClick={handleReset}
            >
              <RotateCcw className="mr-2 size-3.5" />
              重新检索
            </Button>
          </div>
        ) : (
          <div className="flex flex-col items-center text-center">
            <SemanticRetrievalMark />
            <div className="mt-2.5 text-[24px] font-semibold tracking-[-0.045em] text-foreground">
              语义检索测试
            </div>
            <p className="mt-1.5 max-w-2xl text-[12px] leading-5 text-muted-foreground/74">
              输入复杂问题或长 Prompt，验证 RAG 的召回质量和测试指标。
            </p>
          </div>
        )}

        <div className={cn('rounded-lg border', RETRIEVAL_CONTROL_SURFACE_CLASS)}>
          <div className="flex gap-3 px-4 pt-4">
            <Search className="mt-1 size-[18px] shrink-0 text-muted-foreground/42" />
            <textarea
              ref={searchInputRef}
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  detachPromise(handleSearch())
                }
              }}
              placeholder="例如：请按第十二条说明例外条件，并指出适用范围与例外条款"
              className={cn(
                'w-full resize-none border-0 bg-transparent p-0 text-[13px] leading-6 text-foreground outline-none placeholder:text-muted-foreground/35',
                compact ? 'min-h-[56px]' : 'min-h-[72px]'
              )}
            />
          </div>

          <div className="mt-2 flex flex-col gap-2.5 border-t border-foreground/10 px-4 py-3 lg:flex-row lg:items-center lg:justify-between dark:border-foreground/10">
            <div className="flex flex-wrap items-center gap-3 text-[12px] text-muted-foreground/72">
              <span className="inline-flex h-8 items-center rounded-md border border-foreground/10 bg-background/70 px-3 dark:border-foreground/10 dark:bg-background/70">
                <Database className="mr-2 size-3.5 text-primary" />
                {selectedDatasetId ||
                  (availableDatasetIds.length
                    ? `全部数据集 · ${availableDatasetIds.length} 库`
                    : '暂无可用数据集')}
              </span>
              <span className="font-mono text-[11px] opacity-70">Enter 发送</span>
              <span className="font-mono text-[11px] opacity-70">Shift + Enter 换行</span>
            </div>

            <Button
              type="button"
              className="h-9 rounded-lg bg-primary px-[18px] text-[13px] font-medium text-primary-foreground shadow-none"
              disabled={!searchQuery.trim() || isSearching || !hasRetrievalScope}
              onClick={() => detachPromise(handleSearch())}
            >
              {isSearching ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Zap className="mr-2 size-4" />}
              开始检索
            </Button>
          </div>
        </div>
      </div>
    </div>
  )

  const renderInitialWorkbench = () => (
    <div className="grid min-h-0 gap-3.5">
      {renderComposer(false)}

      <div className="grid gap-3.5 xl:grid-cols-[1.1fr_0.88fr_1fr]">
        <Panel padding="none" className={cn('rounded-xl border', RETRIEVAL_PANEL_SURFACE_CLASS)}>
          <div className="p-[18px]">
            <div className="flex items-center justify-between">
              <div className="text-[15px] font-semibold tracking-[-0.03em] text-foreground">推荐测试问题</div>
            </div>
            <div className="mt-3.5 space-y-2">
              {recommendedQuestions.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => {
                    handleApplySuggestedQuery(question)
                    searchInputRef.current?.focus()
                  }}
                  className="flex w-full items-center justify-between rounded-lg border border-foreground/10 bg-background/70 px-3 py-2.5 text-left transition-colors hover:border-foreground/15 hover:bg-muted/20 dark:border-foreground/10 dark:bg-background/70"
                >
                  <span className="pr-4 text-[12px] leading-5 text-foreground/86">{question}</span>
                  <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/55" />
                </button>
              ))}
            </div>
          </div>
        </Panel>

        <Panel padding="none" className={cn('rounded-xl border', RETRIEVAL_PANEL_SURFACE_CLASS)}>
          <div className="p-[18px]">
            <div className="flex items-center gap-2 text-[15px] font-semibold tracking-[-0.03em] text-foreground">
              <SlidersHorizontal className="size-3.5 text-primary" />
              参数设置
            </div>
            <div className="mt-3.5 space-y-3.5">
              <div className="space-y-2">
                <div className="text-[12px] text-muted-foreground/74">Top K（返回结果数）</div>
                <Select value={topK} onValueChange={setTopK}>
                  <SelectTrigger className="h-9 rounded-lg border-foreground/10 bg-background/70 text-[12px] font-medium dark:border-foreground/10 dark:bg-background/70">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="3">3</SelectItem>
                    <SelectItem value="5">5</SelectItem>
                    <SelectItem value="8">8</SelectItem>
                    <SelectItem value="10">10</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-[12px] text-muted-foreground/74">相似度阈值</div>
                  <div className="rounded-md border border-foreground/10 bg-background/70 px-2 py-1 font-mono text-[12px] text-foreground dark:border-foreground/10 dark:bg-background/70">
                    {scoreThreshold.toFixed(2)}
                  </div>
                </div>
                <div className="relative h-5">
                  <div className="pointer-events-none absolute inset-x-0 top-1/2 h-1 rounded-full bg-info/10 -translate-y-1/2 dark:bg-muted-foreground/20" />
                  <div
                    className="pointer-events-none absolute left-0 top-1/2 h-1 rounded-full bg-info/80 -translate-y-1/2 dark:bg-info"
                    style={{ width: `${scoreThresholdPercent}%` }}
                  />
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    value={scoreThreshold}
                    onChange={(event) => setScoreThreshold(Number(event.target.value))}
                    className={RETRIEVAL_RANGE_INPUT_CLASS}
                  />
                </div>
                <button
                  type="button"
                  aria-expanded={advancedParamsOpen}
                  aria-controls={RETRIEVAL_ADVANCED_PANEL_ID}
                  onClick={() => setAdvancedParamsOpen((open) => !open)}
                  className="inline-flex items-center text-[12px] font-medium text-primary transition-colors hover:text-primary"
                >
                  {advancedParamsOpen ? '收起高级参数' : '更多高级参数'}
                  <ChevronRight
                    className={cn(
                      'ml-1 size-3 text-primary/90 transition-transform',
                      advancedParamsOpen && 'rotate-90'
                    )}
                  />
                </button>
                {advancedParamsOpen ? (
                  <div
                    id={RETRIEVAL_ADVANCED_PANEL_ID}
                    className="space-y-3 rounded-lg border border-foreground/10 bg-background/70 p-3 dark:border-foreground/10 dark:bg-background/70"
                  >
                    <div className="space-y-1.5">
                      <div className="text-[11px] text-muted-foreground/70">检索模式</div>
                      <Select value={retrievalMode} onValueChange={setRetrievalMode}>
                        <SelectTrigger className="h-8 rounded-md border-foreground/10 bg-background/70 text-[12px] font-medium dark:border-foreground/10 dark:bg-background/70">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="hybrid">Hybrid 混合检索</SelectItem>
                          <SelectItem value="vector">Vector 向量直达</SelectItem>
                          <SelectItem value="keyword">Keyword 关键词</SelectItem>
                          <SelectItem value="mmr">MMR 多样性</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-[11px] text-muted-foreground/70">
                        <span>向量权重 Alpha</span>
                        <span className="font-mono text-foreground">{alpha.toFixed(2)}</span>
                      </div>
                      <div className="relative h-5">
                        <div className="pointer-events-none absolute inset-x-0 top-1/2 h-1 rounded-full bg-info/10 -translate-y-1/2 dark:bg-muted-foreground/20" />
                        <div
                          className="pointer-events-none absolute left-0 top-1/2 h-1 rounded-full bg-info/80 -translate-y-1/2 dark:bg-info"
                          style={{ width: `${alphaPercent}%` }}
                        />
                        <input
                          type="range"
                          min="0"
                          max="1"
                          step="0.05"
                          value={alpha}
                          onChange={(event) => setAlpha(Number(event.target.value))}
                          className={RETRIEVAL_RANGE_INPUT_CLASS}
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="space-y-1.5">
                        <div className="text-[11px] text-muted-foreground/70">上下文预算</div>
                        <Select value={maxTokens} onValueChange={setMaxTokens}>
                          <SelectTrigger className="h-8 rounded-md border-foreground/10 bg-background/70 text-[12px] font-medium dark:border-foreground/10 dark:bg-background/70">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="1000">1000 tokens</SelectItem>
                            <SelectItem value="2000">2000 tokens</SelectItem>
                            <SelectItem value="4000">4000 tokens</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <button
                        type="button"
                        onClick={() => setEnableWeightRerank((enabled) => !enabled)}
                        className={cn(
                          'mt-5 h-8 rounded-[12px] border px-3 text-[11px] font-medium transition-colors',
                          enableWeightRerank
                            ? 'border-success/25 bg-success/10 text-success'
                            : 'border-foreground/10 bg-background/70 text-muted-foreground dark:border-foreground/10 dark:bg-background/70'
                        )}
                      >
                        权重重排 {enableWeightRerank ? '开启' : '关闭'}
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </Panel>

        <Panel padding="none" className={cn('rounded-xl border', RETRIEVAL_PANEL_SURFACE_CLASS)}>
          <div className="p-[18px]">
            <div className="flex items-center justify-between">
              <div className="text-[15px] font-semibold tracking-[-0.03em] text-foreground">最近检索</div>
              <button
                type="button"
                className="text-[12px] text-muted-foreground/66 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35"
                onClick={handleClearRecentQueries}
                disabled={recentQueries.length === 0}
              >
                清空
              </button>
            </div>
            <div className="mt-3.5 space-y-2.5">
              {visibleRecentQueries.map((item) => (
                <button
                  key={`${item.query}-${item.timestampLabel}`}
                  type="button"
                  onClick={() => {
                    handleApplySuggestedQuery(item.query)
                    searchInputRef.current?.focus()
                  }}
                  className="flex w-full items-start justify-between gap-4 text-left"
                >
                  <div className="min-w-0">
                    <div className="line-clamp-2 text-[12px] leading-5 text-foreground/88">{item.query}</div>
                    <div className="mt-1 text-[11px] text-muted-foreground/62">{item.timestampLabel}</div>
                  </div>
                  <ArrowRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground/45" />
                </button>
              ))}
              {visibleRecentQueries.length === 0 ? (
                <div className="rounded-lg border border-dashed border-foreground/10 bg-background/70 px-3 py-3 text-[12px] text-muted-foreground/70 dark:border-foreground/10 dark:bg-background/70">
                  暂无检索历史
                </div>
              ) : null}
            </div>
            <div className="mt-4 flex justify-start">
              <button
                type="button"
                aria-expanded={fullHistoryOpen}
                aria-controls={RETRIEVAL_HISTORY_PANEL_ID}
                onClick={() => setFullHistoryOpen((open) => !open)}
                className="inline-flex items-center text-[12px] font-medium text-primary transition-colors hover:text-primary"
              >
                {fullHistoryOpen ? '收起全部历史' : '查看全部历史'}
                <ChevronRight
                  className={cn(
                    'ml-1 size-3 text-primary/90 transition-transform',
                    fullHistoryOpen && 'rotate-90'
                  )}
                />
              </button>
            </div>
            {fullHistoryOpen ? (
              <div
                id={RETRIEVAL_HISTORY_PANEL_ID}
                className="mt-3 rounded-lg border border-foreground/10 bg-background/70 p-3 dark:border-foreground/10 dark:bg-background/70"
              >
                <div className="text-[11px] font-medium text-foreground">当前会话历史</div>
                <div className="mt-2 space-y-2">
                  {recentQueries.length > 0 ? (
                    recentQueries.map((item) => (
                      <button
                        key={`history-${item.query}-${item.timestampLabel}`}
                        type="button"
                        onClick={() => {
                          handleApplySuggestedQuery(item.query)
                          searchInputRef.current?.focus()
                        }}
                        className="flex w-full items-center justify-between gap-3 rounded-md border border-foreground/10 bg-background/70 px-3 py-2 text-left transition-colors hover:border-foreground/15 hover:bg-muted/20 dark:border-foreground/10 dark:bg-background/70"
                      >
                        <span className="line-clamp-1 text-[12px] text-foreground/86">{item.query}</span>
                        <span className="shrink-0 text-[10px] text-muted-foreground/60">{item.timestampLabel}</span>
                      </button>
                    ))
                  ) : (
                    <div className="rounded-md border border-dashed border-foreground/10 px-3 py-2 text-[12px] text-muted-foreground/70">
                      暂无检索历史
                    </div>
                  )}
                </div>
              </div>
            ) : null}
          </div>
        </Panel>
      </div>
    </div>
  )

  const renderNoResults = () => (
    <Panel padding="none" className={cn('rounded-xl border', RETRIEVAL_PANEL_SURFACE_CLASS)}>
      <div className="p-6">
        <div className="text-[20px] font-semibold tracking-[-0.03em] text-foreground">Top-K 排序为空</div>
        <div className="mt-3 text-[14px] leading-6 text-muted-foreground/76">
          当前检索词为 <span className="font-medium text-foreground">{searchQueryForRetrieval || searchQuery.trim()}</span>，没有返回可用候选。
        </div>

        <div className="mt-6">
          <div className="text-[13px] font-medium text-foreground">建议动作</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {noResultActionTips.map((label) => (
              <button
                key={label}
                type="button"
                onClick={() => {
                  handleApplySuggestedQuery(label)
                  searchInputRef.current?.focus()
                }}
                className="rounded-full border border-foreground/10 bg-background/70 px-3 py-1.5 text-[12px] text-foreground/80 transition-colors hover:border-foreground/15 hover:bg-muted/20 dark:border-foreground/10 dark:bg-background/70"
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-7">
          <div className="text-[13px] font-medium text-foreground">排查方向</div>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {noResultDiagnosticTips.map((item) => (
              <div key={item.title} className="rounded-lg border border-foreground/10 bg-background/70 px-4 py-4 dark:border-foreground/10 dark:bg-background/70">
                <div className="text-[13px] font-medium text-foreground">{item.title}</div>
                <div className="mt-2 text-[12px] leading-5 text-muted-foreground/72">{item.description}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Panel>
  )

  const renderHitSummary = (hit: RetrievePreviewCitation) => {
    const role = String(hit.retrieval_role || '')
    const chunkId = String(hit.chunk_id || '')
    const clause = String(hit.policy_clause_number || '')
    const pathStr = String(hit.policy_path_str || '')
    const familyHit = Boolean(hit.family_hit)
    const imageUrl = resolveSafeCitationImageUrl(hit.img_url)
    const hasImage = Boolean(hit.has_image) || Boolean(hit.img_url) || Boolean(imageUrl)
    const terms = getMatchedTerms(hit)
    const score = formatScore(getHitScore(hit))

    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <div className="text-[18px] font-semibold tracking-[-0.03em] text-foreground">
            {String(hit.document_name || hit.document_id || '未命名文档')}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">Score {score}</Badge>
            {familyHit ? (
              <span className="rounded-full bg-warning/10 text-warning border border-warning/20 px-2.5 py-1 text-[11px] font-medium">
                Family Hit
              </span>
            ) : null}
            {role.startsWith('hierarchy_') ? (
              <span className="rounded-full border border-info/20 bg-card/88 px-2.5 py-1 text-[11px] text-muted-foreground dark:border-border/70 dark:bg-background/58">
                {role}
              </span>
            ) : null}
          </div>
        </div>

        {hasImage ? (
          <div className="overflow-hidden rounded-xl border border-foreground/10 bg-background/70 dark:border-foreground/10 dark:bg-background/70">
            {imageUrl ? (
              <AuthImage src={imageUrl} alt="命中图像缩略图" className="h-44 w-full object-cover" />
            ) : (
              <div className="flex h-44 items-center justify-center text-[13px] text-muted-foreground/62">
                图像命中（无可用缩略图）
              </div>
            )}
          </div>
        ) : null}

        <div className="rounded-xl border border-foreground/10 bg-background/70 px-4 py-4 dark:border-foreground/10 dark:bg-background/70">
          <div className="text-[12px] leading-6 text-foreground/86">{previewChunkContent(hit.chunk_content)}</div>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-foreground/10 bg-background/70 px-4 py-4 dark:border-foreground/10 dark:bg-background/70">
            <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/62">Chunk ID</div>
            <div className="mt-2 break-all font-mono text-[12px] text-foreground/84">{chunkId || '—'}</div>
          </div>
          <div className="rounded-lg border border-foreground/10 bg-background/70 px-4 py-4 dark:border-foreground/10 dark:bg-background/70">
            <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/62">Clause</div>
            <div className="mt-2 text-[12px] text-foreground/84">{clause || '—'}</div>
          </div>
        </div>

        <div className="rounded-lg border border-foreground/10 bg-background/70 px-4 py-4 dark:border-foreground/10 dark:bg-background/70">
          <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/62">Path</div>
          <div className="mt-2 break-all text-[12px] text-foreground/84">{pathStr || '—'}</div>
        </div>

        {terms.length ? (
          <div className="rounded-lg border border-foreground/10 bg-background/70 px-4 py-4 dark:border-foreground/10 dark:bg-background/70">
            <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground/62">Matched Terms</div>
            <div className="mt-3 flex flex-wrap gap-2">
              {terms.map((term) => (
                <span key={term} className="rounded-full border border-foreground/10 bg-background/70 px-2.5 py-1 text-[11px] text-foreground/82 dark:border-foreground/10 dark:bg-background/70">
                  {term}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            className="h-10 rounded-[14px] bg-primary px-4 text-[13px] font-medium text-primary-foreground"
            onClick={() => handleOpenHitInDocumentViewer(hit)}
          >
            <ExternalLink className="mr-2 size-3.5" />
            在文档查看器中打开
          </Button>
          <Button
            type="button"
            variant="outline"
            className="h-10 rounded-[14px] px-4 text-[13px]"
            onClick={() => {
              detachPromise(navigator.clipboard.writeText(previewChunkContent(hit.chunk_content)))
              toast.success('已复制命中内容')
            }}
          >
            <Copy className="mr-2 size-3.5" />
            复制内容
          </Button>
        </div>
      </div>
    )
  }

  const renderResultsWorkbench = () => (
    <div className="flex min-h-0 flex-1 flex-col gap-5">
      {renderComposer(true)}

      {searchError ? (
        <Panel padding="none" className="rounded-xl border border-destructive/20 bg-destructive/[0.04]">
          <div className="p-5 text-[14px] text-destructive">{searchError}</div>
        </Panel>
      ) : null}

      {!isSearching && searchResults.length === 0 ? renderNoResults() : null}

      {searchResults.length > 0 ? (
        <div className="grid min-h-0 gap-5 2xl:grid-cols-[minmax(0,1fr)_21rem]">
          <div className={cn('min-h-0 rounded-xl border', RETRIEVAL_PANEL_SURFACE_CLASS)}>
            <div className="border-b border-foreground/15 px-5 py-4 dark:border-foreground/15">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground/62">检索结果</div>
                  <div className="mt-1 text-[16px] font-semibold text-foreground">
                    共返回 {resultStats.total} 条候选
                  </div>
                </div>
                <div className="flex flex-wrap gap-2 text-[12px] text-muted-foreground/72">
                  <span className="rounded-full border border-foreground/10 bg-background/70 px-3 py-1 dark:border-foreground/10 dark:bg-background/70">Family {resultStats.familyHits}</span>
                  <span className="rounded-full border border-foreground/10 bg-background/70 px-3 py-1 dark:border-foreground/10 dark:bg-background/70">Hierarchy {resultStats.hierarchyHits}</span>
                </div>
              </div>
            </div>

            <div aria-label="检索结果排名列表" className="min-h-0 divide-y divide-foreground/10 dark:divide-foreground/10">
              {searchResults.map((hit, idx) => {
                const key = toHitKey(hit)
                const expandedHit = Boolean(expanded[key])
                const staggerDelayMs = Math.min(idx, 10) * 40
                const familyHit = Boolean(hit.family_hit)
                const role = String(hit.retrieval_role || '')
                const chunkId = String(hit.chunk_id || '')
                const clause = String(hit.policy_clause_number || '')
                const pathStr = String(hit.policy_path_str || '')
                const terms = getMatchedTerms(hit)

                return (
                  <div
                    key={key || String(idx)}
                    style={{ animationDelay: `${staggerDelayMs}ms` }}
                    className={cn(
                      'animate-in fade-in-0 slide-in-from-bottom-1 duration-300 motion-reduce:animate-none flex w-full items-start gap-4 px-5 py-4 text-left transition-colors hover:bg-primary/[0.03]',
                      activeResult === hit && 'bg-primary/[0.04]'
                    )}
                  >
                    <button
                      type="button"
                      aria-pressed={activeResult === hit}
                      className="flex min-w-0 flex-1 items-start gap-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
                      onClick={() => setActiveHit(hit)}
                      onMouseEnter={() => {
                        const hitKey = toHitKey(hit)
                        if (prefetchedHitTargetsRef.current.has(hitKey)) return
                        prefetchedHitTargetsRef.current.add(hitKey)
                        handlePrefetchHitDocument(hit)
                      }}
                      onFocus={() => {
                        const hitKey = toHitKey(hit)
                        if (prefetchedHitTargetsRef.current.has(hitKey)) return
                        prefetchedHitTargetsRef.current.add(hitKey)
                        handlePrefetchHitDocument(hit)
                      }}
                    >
                      <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-foreground/10 bg-background/70 text-primary">
                        <span className="font-mono text-[12px] font-semibold">{idx + 1}</span>
                      </div>

                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="truncate text-[15px] font-medium text-foreground">
                            {String(hit.document_name || hit.document_id || '未命名文档')}
                          </div>
                          <Badge variant="outline">Score {formatScore(getHitScore(hit))}</Badge>
                          {familyHit ? (
                            <span className="rounded-full bg-warning/10 text-warning border border-warning/20 px-2.5 py-1 text-[11px] font-medium">
                              Family Hit
                            </span>
                          ) : null}
                        </div>
                        <div className="mt-2 line-clamp-2 text-[13px] leading-6 text-muted-foreground/76">
                          {previewChunkContent(hit.chunk_content, 220)}
                        </div>
                        <div className="mt-3 flex flex-wrap items-center gap-3 text-[12px] text-muted-foreground/64">
                          <span className="font-mono">{chunkId || '—'}</span>
                          <span>{clause || '—'}</span>
                          <span className="truncate">{pathStr || '—'}</span>
                          {role.startsWith('hierarchy_') ? <span>{role}</span> : null}
                        </div>
                        {expandedHit && terms.length ? (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {terms.map((term) => (
                               <span key={term} className="rounded-full border border-foreground/10 bg-background/70 px-2.5 py-1 text-[11px] text-foreground/82 dark:border-foreground/10 dark:bg-background/70">
                                {term}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </div>

                    </button>

                    <div className="flex shrink-0 items-center gap-2">
                      <IconButton
                        label="在文档查看器中打开"
                        variant="ghost"
                        className="h-8 w-8 rounded-md text-muted-foreground hover:bg-muted/20 hover:text-primary"
                        onClick={() => handleOpenHitInDocumentViewer(hit)}
                      >
                        <ExternalLink className="size-4" />
                      </IconButton>
                      <button
                        type="button"
                        className="text-[12px] text-muted-foreground/62"
                        onClick={() => {
                          setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))
                        }}
                      >
                        {expandedHit ? '收起' : '展开'}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className={cn('min-h-0 rounded-xl border', RETRIEVAL_PANEL_SURFACE_CLASS)}>
            <div className="border-b border-foreground/15 px-5 py-4 dark:border-foreground/15">
              <div className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground/62">命中细节</div>
              <div className="mt-1 text-[16px] font-semibold text-foreground">Active Hit</div>
            </div>
            <div className="p-5">
              {activeResult ? renderHitSummary(activeResult) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )

  return (
    <div className={cn(className, 'relative flex h-full min-h-0 flex-col overflow-hidden bg-background')}>
      <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4">
        {!hasSearched && !isSearching ? renderInitialWorkbench() : renderResultsWorkbench()}
      </div>
    </div>
  )
}
