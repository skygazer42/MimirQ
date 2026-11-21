'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { CheckCircle2, ChevronRight, FileText, Info, MessageSquare, Sparkles, X } from '@/components/icons'
import { DatasetSelectField } from '@/components/ops/dataset-select-field'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { LoadingButton } from '@/components/ui/loading-button'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { Switch } from '@/components/ui/switch'
import { evaluationApi, documentApi, chatApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import {
  QUESTION_TYPE_OPTIONS,
  conversationQuestionRequestSchema,
  documentQuestionRequestSchema,
  questionDocumentPageSchema,
  type QuestionType,
} from '@/lib/question-generation-schema'
import { cn, detachPromise } from '@/lib/utils'
import type {
  TestGenFromDocsRequest,
  TestGenFromConversationsRequest,
  TestGenResponse,
  DocumentList,
  ConversationListResponse,
} from '@/types'

type SourceType = 'documents' | 'conversations'
type Step = 'select_source' | 'configure' | 'preview'
type GenerationRequest =
  | { sourceType: 'documents'; params: TestGenFromDocsRequest }
  | { sourceType: 'conversations'; params: TestGenFromConversationsRequest }
type GenerationResult = {
  autoSave: boolean
  response: Extract<TestGenResponse, { status: 'completed' }>
}
type SourceOption = { id: string; label: string; description: string }
type DocumentSourceView = Readonly<{ data: DocumentList; datasetId: string; search: string; page: number }>
type ConversationSourceView = Readonly<{ data: ConversationListResponse; search: string; offsets: readonly number[] }>

type TestGenerationDialogProps = {
  open: boolean
  onClose: () => void
  onCasesSaved?: (caseIds: readonly string[]) => void
  initialSourceType?: SourceType
  initialDatasetId?: string
  initialDocumentIds?: string[]
}

const SOURCE_PAGE_SIZE = 50

export function TestGenerationDialog({ open, onClose, onCasesSaved, ...initial }: Readonly<TestGenerationDialogProps>) {
  const queryClient = useQueryClient()
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  const requests = useRef(new Map<string, Promise<TestGenResponse>>())
  const [pendingSessions, setPendingSessions] = useState<ReadonlySet<string>>(new Set())
  const ownerRef = useRef<{ active: boolean } | null>(null)
  useLayoutEffect(() => {
    const owner = { active: true }
    ownerRef.current = owner
    return () => {
      owner.active = false
    }
  }, [])

  async function submit(request: GenerationRequest): Promise<TestGenResponse> {
    if (getAuthSessionKey() !== sessionKey) throw new Error('会话已变化，请重新打开生成窗口')
    if (requests.current.has(sessionKey)) throw new Error('上一轮问题生成尚未结束')
    const owner = ownerRef.current!
    const promise =
      request.sourceType === 'documents'
        ? evaluationApi.generateFromDocuments(request.params)
        : evaluationApi.generateFromConversations(request.params)
    requests.current.set(sessionKey, promise)
    setPendingSessions(new Set(requests.current.keys()))
    try {
      return await promise
    } finally {
      requests.current.delete(sessionKey)
      if (owner.active) setPendingSessions(new Set(requests.current.keys()))
      if (getAuthSessionKey() === sessionKey && request.params.auto_save_as_cases !== false) {
        detachPromise(queryClient.invalidateQueries({ queryKey: queryKeys.evaluations.regressionCaseLists() }))
      }
    }
  }

  const editorKey = JSON.stringify([
    sessionKey,
    initial.initialSourceType,
    initial.initialDatasetId,
    initial.initialDocumentIds,
  ])
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose()
      }}
    >
      {open ? (
        <GenerationContent
          key={editorKey}
          {...initial}
          onClose={onClose}
          onCasesSaved={onCasesSaved}
          sessionKey={sessionKey}
          pending={pendingSessions.has(sessionKey)}
          submit={submit}
        />
      ) : null}
    </Dialog>
  )
}

function GenerationContent({
  onClose,
  onCasesSaved,
  initialSourceType,
  initialDatasetId,
  initialDocumentIds,
  sessionKey,
  pending,
  submit,
}: Readonly<
  Omit<TestGenerationDialogProps, 'open'> & {
    sessionKey: string
    pending: boolean
    submit: (request: GenerationRequest) => Promise<TestGenResponse>
  }
>) {
  const formId = useId()
  const hasInitialDocuments = initialDocumentIds !== undefined && initialDocumentIds.length > 0
  const [step, setStep] = useState<Step>(hasInitialDocuments ? 'configure' : 'select_source')
  const [sourceType, setSourceType] = useState<SourceType>(
    hasInitialDocuments ? 'documents' : (initialSourceType ?? 'documents'),
  )
  const [selectedDatasetId, setSelectedDatasetId] = useState(initialDatasetId === undefined ? '' : initialDatasetId)
  const [selectedDocuments, setSelectedDocuments] = useState<ReadonlyMap<string, string>>(
    () => new Map(initialDocumentIds?.map((id) => [id, id] as const)),
  )
  const [selectedConversations, setSelectedConversations] = useState<ReadonlyMap<string, string>>(new Map())
  const [documentSearch, setDocumentSearch] = useState('')
  const [conversationSearch, setConversationSearch] = useState('')
  const [documentPage, setDocumentPage] = useState(0)
  const [conversationOffsets, setConversationOffsets] = useState<readonly number[]>([0])
  const [documentView, setDocumentView] = useState<DocumentSourceView | null>(null)
  const [conversationView, setConversationView] = useState<ConversationSourceView | null>(null)
  const [numQuestions, setNumQuestions] = useState(10)
  const [questionTypes, setQuestionTypes] = useState<ReadonlySet<QuestionType>>(
    () => new Set(['factual', 'multi_hop', 'comparison']),
  )
  const [qualityThreshold, setQualityThreshold] = useState(0.7)
  const [autoSave, setAutoSave] = useState(true)
  const [result, setResult] = useState<GenerationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const scopeRef = useRef<{ active: boolean } | null>(null)
  useLayoutEffect(() => {
    const scope = { active: true }
    scopeRef.current = scope
    return () => {
      scope.active = false
    }
  }, [])

  const documentParams = {
    limit: SOURCE_PAGE_SIZE,
    skip: documentPage * SOURCE_PAGE_SIZE,
    status: 'completed',
    dataset_id: selectedDatasetId === '' ? undefined : selectedDatasetId,
    q: documentSearch.trim(),
  }
  const documentsQuery = useQuery({
    queryKey: queryKeys.documents.list(documentParams),
    enabled: sourceType === 'documents',
    queryFn: async ({ signal }) => {
      const page = await documentApi.list(documentParams, { signal })
      questionDocumentPageSchema.parse(page)
      return page
    },
  })
  const conversationParams = {
    limit: SOURCE_PAGE_SIZE,
    skip: conversationOffsets[conversationOffsets.length - 1],
    q: conversationSearch.trim(),
  }
  const conversationsQuery = useQuery({
    queryKey: queryKeys.chat.conversations(conversationParams),
    enabled: sourceType === 'conversations',
    queryFn: ({ signal }) => chatApi.listConversations(conversationParams, { signal }),
  })

  useLayoutEffect(() => {
    if (documentsQuery.data === undefined || documentsQuery.error !== null || documentsQuery.isPlaceholderData) return
    setDocumentView({
      data: documentsQuery.data,
      datasetId: selectedDatasetId,
      search: documentSearch,
      page: documentPage,
    })
  }, [
    documentsQuery.data,
    documentsQuery.error,
    documentsQuery.isPlaceholderData,
    selectedDatasetId,
    documentSearch,
    documentPage,
  ])
  useLayoutEffect(() => {
    if (
      conversationsQuery.data === undefined ||
      conversationsQuery.error !== null ||
      conversationsQuery.isPlaceholderData
    )
      return
    setConversationView({ data: conversationsQuery.data, search: conversationSearch, offsets: conversationOffsets })
  }, [
    conversationsQuery.data,
    conversationsQuery.error,
    conversationsQuery.isPlaceholderData,
    conversationSearch,
    conversationOffsets,
  ])

  let choices: SourceOption[] = []
  let displayedScope: string | null = null
  if (sourceType === 'documents' && documentView !== null) {
    choices = documentView.data.items.map((document) => ({
      id: document.id,
      label: document.filename,
      description: document.chunk_count == null ? '切片数未提供' : `${document.chunk_count} 切片`,
    }))
    const datasetScope = documentView.datasetId === '' ? '跨数据集' : documentView.datasetId
    const searchLabel = documentView.search.trim() === '' ? '无关键词' : documentView.search
    displayedScope = `第 ${documentView.page + 1} 页 · 数据集 ${datasetScope} · 搜索 ${searchLabel}`
  } else if (sourceType === 'conversations' && conversationView !== null) {
    choices = conversationView.data.items.map((conversation) => ({
      id: conversation.id,
      label: conversation.title ?? conversation.id,
      description: `${conversation.message_count} 消息`,
    }))
    const searchLabel = conversationView.search.trim() === '' ? '无关键词' : conversationView.search
    displayedScope = `第 ${conversationView.offsets.length} 页 · 搜索 ${searchLabel}`
  }
  const sourceQuery = sourceType === 'documents' ? documentsQuery : conversationsQuery
  const hasSourceView = sourceType === 'documents' ? documentView !== null : conversationView !== null
  const sourceViewMatches =
    sourceType === 'documents'
      ? documentView !== null &&
        documentView.datasetId === selectedDatasetId &&
        documentView.search.trim() === documentSearch.trim() &&
        documentView.page === documentPage
      : conversationView !== null &&
        conversationView.search.trim() === conversationSearch.trim() &&
        conversationView.offsets[conversationView.offsets.length - 1] === conversationParams.skip
  const selection = sourceType === 'documents' ? selectedDocuments : selectedConversations
  const setSelection = sourceType === 'documents' ? setSelectedDocuments : setSelectedConversations
  const hasSource =
    sourceType === 'documents' ? selectedDocuments.size > 0 || selectedDatasetId !== '' : selectedConversations.size > 0

  function toggleSource(option: SourceOption) {
    setSelection((current) => {
      const next = new Map(current)
      if (next.has(option.id)) next.delete(option.id)
      else next.set(option.id, option.label)
      return next
    })
  }

  function restoreSourceView() {
    if (sourceType === 'documents' && documentView !== null) {
      setSelectedDatasetId(documentView.datasetId)
      setDocumentSearch(documentView.search)
      setDocumentPage(documentView.page)
    } else if (sourceType === 'conversations' && conversationView !== null) {
      setConversationSearch(conversationView.search)
      setConversationOffsets(conversationView.offsets)
    }
  }

  function nextSourcePage() {
    if (sourceType === 'documents' && documentView !== null) {
      const nextPage = documentView.page + 1
      if (
        selectedDatasetId === documentView.datasetId &&
        documentSearch.trim() === documentView.search.trim() &&
        documentPage === nextPage
      ) {
        detachPromise(documentsQuery.refetch())
        return
      }
      setSelectedDatasetId(documentView.datasetId)
      setDocumentSearch(documentView.search)
      setDocumentPage(nextPage)
    } else if (sourceType === 'conversations' && conversationView !== null) {
      const next = conversationView.data.next_skip
      if (next === null) return
      if (conversationSearch.trim() === conversationView.search.trim() && conversationParams.skip === next) {
        detachPromise(conversationsQuery.refetch())
        return
      }
      setConversationSearch(conversationView.search)
      setConversationOffsets([...conversationView.offsets, next])
    }
  }

  function previousSourcePage() {
    if (sourceType === 'documents' && documentView !== null) {
      const previousPage = documentView.page - 1
      if (
        selectedDatasetId === documentView.datasetId &&
        documentSearch.trim() === documentView.search.trim() &&
        documentPage === previousPage
      ) {
        detachPromise(documentsQuery.refetch())
        return
      }
      setSelectedDatasetId(documentView.datasetId)
      setDocumentSearch(documentView.search)
      setDocumentPage(previousPage)
    } else if (sourceType === 'conversations' && conversationView !== null) {
      const previousOffsets = conversationView.offsets.slice(0, -1)
      if (
        conversationSearch.trim() === conversationView.search.trim() &&
        conversationParams.skip === previousOffsets[previousOffsets.length - 1]
      ) {
        detachPromise(conversationsQuery.refetch())
        return
      }
      setConversationSearch(conversationView.search)
      setConversationOffsets(previousOffsets)
    }
  }

  function removeSource(id: string) {
    setSelection((current) => {
      const next = new Map(current)
      next.delete(id)
      return next
    })
  }

  function toggleQuestionType(type: QuestionType) {
    setQuestionTypes((current) => {
      const next = new Set(current)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  async function generate(): Promise<void> {
    if (pending) return
    let request: GenerationRequest
    try {
      request =
        sourceType === 'documents'
          ? {
              sourceType,
              params: documentQuestionRequestSchema.parse({
                ...(selectedDocuments.size === 0 ? { dataset_id: selectedDatasetId } : {}),
                document_ids: [...selectedDocuments.keys()],
                num_questions: numQuestions,
                question_types: [...questionTypes],
                auto_save_as_cases: autoSave,
              }),
            }
          : {
              sourceType,
              params: conversationQuestionRequestSchema.parse({
                conversation_ids: [...selectedConversations.keys()],
                num_questions: numQuestions,
                quality_threshold: qualityThreshold,
                auto_save_as_cases: autoSave,
              }),
            }
    } catch (cause) {
      setError(formatApiError(cause, '请检查生成参数'))
      return
    }
    const scope = scopeRef.current!
    setError(null)
    let response: TestGenResponse
    try {
      response = await submit(request)
    } catch (cause) {
      if (scope.active && getAuthSessionKey() === sessionKey) {
        setError(
          formatApiError(cause, '生成未取得有效结果') +
            (request.params.auto_save_as_cases === false ? '' : ' 请先读取用例列表确认保存情况，再决定是否重新生成。'),
        )
      }
      return
    }
    if (!scope.active || getAuthSessionKey() !== sessionKey) return
    if (response.status === 'failed') {
      setError(
        `服务端返回生成失败：${response.error_message}` +
          (request.params.auto_save_as_cases === false ? '' : ' 保存情况请以用例列表为准。'),
      )
      return
    }
    setResult({ autoSave: request.params.auto_save_as_cases !== false, response })
    setError(null)
    setStep('preview')
    if (response.saved_case_ids.length > 0) onCasesSaved?.(response.saved_case_ids)
  }

  return (
    <DialogContent className="flex max-h-[90dvh] w-full max-w-4xl flex-col gap-0 overflow-hidden bg-card p-0 sm:rounded-2xl">
      <div className="border-b border-border p-6 pr-12">
        <DialogTitle className="flex items-center gap-3 text-lg font-semibold text-foreground">
          <Sparkles className="size-5 text-primary" />
          AI 生成评测问题
        </DialogTitle>
        <DialogDescription className="mt-1 text-xs text-muted-foreground">
          {step === 'select_source' ? '选择生成来源' : step === 'configure' ? '配置本轮参数' : '查看真实生成与保存结果'}
        </DialogDescription>
      </div>
      {pending ? (
        <p role="status" className="border-b border-border px-6 py-3 text-sm text-muted-foreground">
          已有一轮生成尚未结束，当前不能再次提交。关闭窗口不会停止原请求，未保存的预览会随关闭丢弃。
        </p>
      ) : null}
      {error !== null ? (
        <div className="px-6 pt-4">
          <WorkspaceNotice>{error}</WorkspaceNotice>
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-6">
        <fieldset disabled={pending} className="min-w-0 space-y-6">
          <legend className="sr-only">本轮问题生成</legend>
          {step === 'select_source' ? (
            <>
              <div role="group" aria-label="生成来源类型" className="grid grid-cols-2 gap-4">
                <Button
                  type="button"
                  variant="outline"
                  aria-pressed={sourceType === 'documents'}
                  onClick={() => setSourceType('documents')}
                  className={cn(
                    'h-auto flex-col items-start whitespace-normal rounded-xl border-2 p-4 text-left',
                    sourceType === 'documents' ? 'border-info bg-info/10' : 'border-border/60',
                  )}
                >
                  <FileText className="mb-2 size-6 text-info" />
                  <span className="font-medium">从文档生成</span>
                  <span className="mt-1 text-xs text-muted-foreground">基于文档内容生成问题</span>
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  aria-pressed={sourceType === 'conversations'}
                  onClick={() => setSourceType('conversations')}
                  className={cn(
                    'h-auto flex-col items-start whitespace-normal rounded-xl border-2 p-4 text-left',
                    sourceType === 'conversations' ? 'border-info bg-info/10' : 'border-border/60',
                  )}
                >
                  <MessageSquare className="mb-2 size-6 text-accent" />
                  <span className="font-medium">从对话生成</span>
                  <span className="mt-1 text-xs text-muted-foreground">从所选对话提炼问题</span>
                </Button>
              </div>
              {sourceType === 'documents' ? (
                <>
                  <DatasetSelectField
                    value={selectedDatasetId}
                    allowAll
                    allLabel="跨数据集选择文档"
                    label="筛选文档数据集"
                    onChange={(id) => {
                      setSelectedDatasetId(id)
                      setDocumentPage(0)
                    }}
                  />
                  <p className="text-xs text-muted-foreground">
                    搜索和数据集筛选不改变已选文档。选中文档时只使用全部已选项；未选文档时从整个所选数据集取样。
                  </p>
                </>
              ) : null}
              <SourcePicker
                name={sourceType === 'documents' ? '文档' : '对话'}
                choices={choices}
                selected={selection}
                onToggle={toggleSource}
                onRemove={removeSource}
                onClear={() => setSelection(new Map())}
                search={sourceType === 'documents' ? documentSearch : conversationSearch}
                onSearchChange={(value) => {
                  if (sourceType === 'documents') {
                    setDocumentSearch(value)
                    setDocumentPage(0)
                  } else {
                    setConversationSearch(value)
                    setConversationOffsets([0])
                  }
                }}
                displayedScope={displayedScope}
                scopeChanged={hasSourceView && !sourceViewMatches}
                onRestore={restoreSourceView}
                page={
                  sourceType === 'documents'
                    ? documentView?.page
                    : conversationView === null
                      ? undefined
                      : conversationView.offsets.length - 1
                }
                canNext={
                  sourceType === 'documents'
                    ? documentView !== null && (documentView.page + 1) * SOURCE_PAGE_SIZE < documentView.data.total
                    : conversationView !== null && conversationView.data.has_more
                }
                onNext={nextSourcePage}
                onPrevious={previousSourcePage}
                total={sourceType === 'documents' ? documentView?.data.total : conversationView?.data.total}
                loading={!hasSourceView && sourceQuery.error === null}
                fetching={sourceQuery.isFetching}
                error={sourceQuery.error}
                onRetry={() => void sourceQuery.refetch()}
              />
            </>
          ) : null}
          {step === 'configure' ? (
            <>
              <p className="text-sm text-muted-foreground">
                {sourceType === 'documents'
                  ? selectedDocuments.size > 0
                    ? `本轮使用已选的 ${selectedDocuments.size} 个文档。`
                    : '本轮从整个所选数据集取样。'
                  : `本轮从已选的 ${selectedConversations.size} 个对话提炼问题。`}
              </p>
              <div className="space-y-2">
                <Label htmlFor={`${formId}-count`}>生成数量：{numQuestions}</Label>
                <Input
                  id={`${formId}-count`}
                  type="range"
                  min={1}
                  max={50}
                  step={1}
                  value={numQuestions}
                  onChange={(event) => setNumQuestions(event.currentTarget.valueAsNumber)}
                />
                <p className="text-xs text-muted-foreground">1 至 50 个；以实际生成结果为准。</p>
              </div>
              {sourceType === 'documents' ? (
                <div className="space-y-2">
                  <p className="text-sm font-medium">问题类型</p>
                  <div role="group" aria-label="问题类型" className="flex flex-wrap gap-2">
                    {QUESTION_TYPE_OPTIONS.map((type) => (
                      <Button
                        key={type.key}
                        type="button"
                        variant="outline"
                        aria-pressed={questionTypes.has(type.key)}
                        onClick={() => toggleQuestionType(type.key)}
                        className={cn(
                          'h-auto flex-col items-start whitespace-normal rounded-lg border-2 px-4 py-2',
                          questionTypes.has(type.key) ? 'border-info bg-info/10 text-info' : 'border-border/60',
                        )}
                      >
                        <span>{type.label}</span>
                        <span className="text-xs text-muted-foreground">{type.description}</span>
                      </Button>
                    ))}
                  </div>
                  {questionTypes.size === 0 ? (
                    <p role="alert" className="text-sm text-destructive">
                      请至少选择一种问题类型。
                    </p>
                  ) : null}
                </div>
              ) : (
                <div className="space-y-2">
                  <Label htmlFor={`${formId}-quality`}>质量阈值：{qualityThreshold.toFixed(1)}</Label>
                  <Input
                    id={`${formId}-quality`}
                    type="range"
                    min={0}
                    max={1}
                    step={0.1}
                    value={qualityThreshold}
                    onChange={(event) => setQualityThreshold(event.currentTarget.valueAsNumber)}
                  />
                </div>
              )}
              <div className="flex items-start justify-between gap-4 rounded-lg bg-muted/40 p-4">
                <div className="space-y-1">
                  <Label htmlFor={`${formId}-save`}>自动保存为评测用例</Label>
                  <p className="text-xs text-muted-foreground">
                    {sourceType === 'documents'
                      ? '用例保存在来源文档所属数据集，接口确认后才计入已保存。'
                      : '对话用例会保存为未绑定数据集的记录，尚不能直接运行数据集回归。'}
                    关闭后仅生成临时预览，关闭窗口会丢弃预览。
                  </p>
                </div>
                <Switch id={`${formId}-save`} checked={autoSave} onCheckedChange={setAutoSave} />
              </div>
            </>
          ) : null}
          {step === 'preview' && result !== null ? (
            <div className="space-y-4">
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                {result.response.generated_questions.length > 0 ? (
                  result.autoSave &&
                  result.response.saved_case_ids.length < result.response.generated_questions.length ? (
                    <Info className="size-4 text-warning" />
                  ) : (
                    <CheckCircle2 className="size-4 text-success" />
                  )
                ) : null}
                本轮生成 {result.response.generated_questions.length} 个问题，实际保存{' '}
                {result.response.saved_case_ids.length} 个用例。
              </p>
              {result.response.generated_questions.length === 0 ? (
                <p className="py-8 text-center text-muted-foreground">
                  本轮没有生成问题，可以调整来源或参数后重新生成。
                </p>
              ) : (
                result.response.generated_questions.map((question, index) => {
                  const type = QUESTION_TYPE_OPTIONS.find((option) => option.key === question.metadata.question_type)
                  const save = question.metadata.auto_save
                  return (
                    <article key={index} className="space-y-2 rounded-lg border border-border bg-card p-4">
                      <h3 className="break-words text-sm font-medium">
                        {index + 1}. {question.question}
                      </h3>
                      <p className="whitespace-pre-wrap break-words text-xs text-muted-foreground">
                        参考答案：{question.expected_answer === null ? '未提供' : question.expected_answer}
                      </p>
                      {type !== undefined ? <p className="text-xs text-info">{type.label}</p> : null}
                      <p className="break-all text-xs text-muted-foreground">
                        来源：{question.source_type === 'document' ? '文档' : '对话'} ·{' '}
                        {question.source_id === null ? '接口未提供逐题来源标识' : question.source_id}
                      </p>
                      {save !== undefined ? (
                        <p className={cn('break-words text-xs', save.saved ? 'text-success' : 'text-destructive')}>
                          {save.saved ? `已保存用例：${save.case_id}` : `未保存：${save.reason}`}
                        </p>
                      ) : null}
                    </article>
                  )
                })
              )}
              {result.response.saved_case_ids.length > 0 ? (
                <p className="break-all font-mono text-xs text-muted-foreground">
                  已保存身份：{result.response.saved_case_ids.join('、')}
                </p>
              ) : null}
            </div>
          ) : null}
        </fieldset>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border p-6">
        <Button type="button" variant="ghost" onClick={onClose}>
          {step === 'preview' ? '关闭结果' : '关闭'}
        </Button>
        <div className="flex flex-wrap items-center gap-2">
          {step === 'select_source' ? (
            <Button type="button" disabled={pending || !hasSource} onClick={() => setStep('configure')}>
              下一步
              <ChevronRight className="ml-1 size-4" />
            </Button>
          ) : null}
          {step === 'configure' ? (
            <>
              {result !== null ? (
                <Button type="button" variant="ghost" disabled={pending} onClick={() => setStep('preview')}>
                  查看上次结果
                </Button>
              ) : null}
              <Button type="button" variant="outline" disabled={pending} onClick={() => setStep('select_source')}>
                上一步
              </Button>
              <LoadingButton
                loading={pending}
                disabled={!hasSource || (sourceType === 'documents' && questionTypes.size === 0)}
                onClick={() => detachPromise(generate())}
              >
                <Sparkles className="mr-2 size-4" />
                开始生成
              </LoadingButton>
            </>
          ) : null}
          {step === 'preview' ? (
            <Button type="button" variant="outline" disabled={pending} onClick={() => setStep('configure')}>
              调整参数重新生成
            </Button>
          ) : null}
        </div>
      </div>
    </DialogContent>
  )
}

function SourcePicker({
  name,
  choices,
  selected,
  onToggle,
  onRemove,
  onClear,
  search,
  onSearchChange,
  page,
  canNext,
  onNext,
  onPrevious,
  displayedScope,
  scopeChanged,
  onRestore,
  total,
  loading,
  fetching,
  error,
  onRetry,
}: Readonly<{
  name: string
  choices: readonly SourceOption[]
  selected: ReadonlyMap<string, string>
  onToggle: (option: SourceOption) => void
  onRemove: (id: string) => void
  onClear: () => void
  search: string
  onSearchChange: (value: string) => void
  page: number | undefined
  canNext: boolean
  onNext: () => void
  onPrevious: () => void
  displayedScope: string | null
  scopeChanged: boolean
  onRestore: () => void
  total: number | undefined
  loading: boolean
  fetching: boolean
  error: unknown
  onRetry: () => void
}>) {
  const searchId = useId()
  const visibleSelected = choices.filter((choice) => selected.has(choice.id)).length
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor={searchId}>搜索{name}</Label>
        <Input id={searchId} value={search} onChange={(event) => onSearchChange(event.target.value)} />
      </div>
      {error !== null ? (
        <WorkspaceNotice retry={onRetry} pending={fetching}>
          {formatApiError(error, `读取${name}失败`)}
        </WorkspaceNotice>
      ) : null}
      {displayedScope !== null ? (
        <p className="break-words text-xs text-muted-foreground">当前展示：{displayedScope}</p>
      ) : null}
      {scopeChanged ? (
        <div className="space-y-1 text-xs text-muted-foreground">
          <p>新范围尚未成功读取，下方保留上次已加载的列表。</p>
          <Button type="button" size="sm" variant="ghost" onClick={onRestore}>
            回到此范围
          </Button>
        </div>
      ) : null}
      {loading || fetching ? (
        <p role="status" className="text-xs text-muted-foreground">
          {loading ? '正在读取…' : '正在刷新，保留当前页和选择…'}
        </p>
      ) : null}
      {choices.length > 0 ? (
        <fieldset className="max-h-64 min-w-0 overflow-y-auto rounded-lg border border-border/60">
          <legend className="sr-only">选择{name}</legend>
          {choices.map((choice) => (
            <label
              key={choice.id}
              className="flex cursor-pointer items-start gap-3 border-b border-border/60 p-3 last:border-0 hover:bg-muted/30"
            >
              <input
                type="checkbox"
                checked={selected.has(choice.id)}
                onChange={() => onToggle(choice)}
                className="mt-1 size-4 shrink-0"
              />
              <span className="min-w-0 flex-1 space-y-1">
                <span className="block break-words text-sm">{choice.label}</span>
                <span className="block break-all font-mono text-[11px] text-muted-foreground">{choice.id}</span>
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">{choice.description}</span>
            </label>
          ))}
        </fieldset>
      ) : !loading && !fetching && !scopeChanged && error === null ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          {search.trim().length > 0 ? `没有匹配的${name}，可以修改搜索条件。` : `当前页没有${name}。`}
        </p>
      ) : null}
      {total !== undefined && page !== undefined ? (
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>
            第 {page + 1} 页 · 共 {total} 个{name}
          </span>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" size="sm" disabled={page === 0 || fetching} onClick={onPrevious}>
              上一页
            </Button>
            <Button type="button" variant="ghost" size="sm" disabled={!canNext || fetching} onClick={onNext}>
              下一页
            </Button>
          </div>
        </div>
      ) : null}
      {selected.size > 0 ? (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            已选 {selected.size} 个{name}，当前页可见 {visibleSelected} 个；生成会使用全部已选项。
          </p>
          <Button type="button" variant="ghost" size="sm" onClick={onClear}>
            取消全部选择
          </Button>
          <ul className="max-h-40 space-y-1 overflow-y-auto">
            {Array.from(selected, ([id, label]) => (
              <li key={id} className="flex items-start justify-between gap-2 rounded-md bg-muted/40 px-2 py-1">
                <span className="min-w-0 break-words text-xs">
                  {label}
                  <span className="block break-all font-mono text-[10px] text-muted-foreground">{id}</span>
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-6 shrink-0"
                  aria-label={`取消选择${name} ${id}`}
                  onClick={() => onRemove(id)}
                >
                  <X className="size-3" />
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
